import logging
import csv
import io

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count
from django.utils import timezone
from .models import Lead, LeadTask, EmailLog
from .serializers import UserSerializer, LeadSerializer
from .utils import (
    search_keyword_urls,
    scrape_leads,
    send_bulk_smtp,
    generate_site_audit,
    generate_mock_audit,
    compute_lead_score,
    get_smtp_config,
    evaluate_website_quality_from_audit,
    _normalize_website_url,
    discover_public_site,
    truncate_url,
)

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(_request):
    """Fast check that this Django project is up (used to debug Vite proxy / 502)."""
    return Response({"ok": True, "service": "salesbooster-django"})


@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request):
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({"message": "User registered successfully"}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_search_view(request):
    keyword = request.data.get('keyword', '')
    if not keyword:
        return Response({"detail": "Keyword required."}, status=status.HTTP_400_BAD_REQUEST)

    urls = search_keyword_urls(keyword)
    if not urls:
        return Response({
            "status": "success",
            "keyword": keyword,
            "new_leads_found": 0,
            "existing_leads_found": 0,
            "attempted_rows": 0,
            "duplicate_rows": 0,
            "create_failed_rows": 0,
            "scrape_failed_urls_count": 0,
            "scrape_failed_urls": [],
            "searched_urls": [],
            "extracted_preview": [],
            "new_leads": [],
            "existing_leads": [],
            "detail": "Could not fetch search engine results right now. Try again in a moment or configure SERPAPI_KEY on the server.",
        })
    new_lead_ids = []
    existing_lead_ids = set()
    extracted_preview = []
    scrape_failed_urls = []
    create_failed_count = 0
    duplicate_count = 0
    attempted_rows = 0

    for url in urls:
        if not url:
            continue
        safe_source = truncate_url(url)
        try:
            res = scrape_leads(url)
        except Exception:
            logger.exception("scrape_leads raised for keyword pipeline url=%s", url)
            res = {"status": "error", "message": "scrape error"}
        if res.get("status") != "success":
            scrape_failed_urls.append(safe_source)

        leads_payload = res.get("leads", []) if res.get("status") == "success" else []
        if not leads_payload:
            leads_payload = [{
                "source": safe_source,
                "contact_name": "",
                "email": "not_found",
                "phone": "not_found",
            }]

        for l in leads_payload:
            attempted_rows += 1
            src = truncate_url(l.get("source") or safe_source)
            l = {**l, "source": src}
            has_email = l.get('email') and l['email'] != "not_found"
            has_phone = l.get('phone') and l['phone'] != "not_found" and l['phone'] != ""

            exists = False
            if has_email:
                existing = Lead.objects.filter(email=l['email'], owner=request.user).only("id").first()
                exists = bool(existing)
                if existing:
                    existing_lead_ids.add(existing.id)
            elif has_phone:
                existing = Lead.objects.filter(phone=l['phone'], owner=request.user).only("id").first()
                exists = bool(existing)
                if existing:
                    existing_lead_ids.add(existing.id)
            else:
                existing = Lead.objects.filter(
                    source_url=l['source'],
                    email="not_found",
                    owner=request.user
                ).only("id").first()
                exists = bool(existing)
                if existing:
                    existing_lead_ids.add(existing.id)

            if not exists:
                try:
                    score, intent_type = compute_lead_score(
                        l.get("email", ""), l.get("phone", ""), l["source"], keyword
                    )
                    lead = Lead.objects.create(
                        keyword=keyword,
                        source_url=l['source'],
                        contact_name=l.get('contact_name', ''),
                        email=l.get('email', 'not_found'),
                        phone=l.get('phone', 'not_found'),
                        owner=request.user,
                        lead_score=score,
                        intent_type=intent_type
                    )
                    new_lead_ids.append(lead.id)
                    extracted_preview.append({
                        "source_url": l["source"],
                        "contact_name": l.get("contact_name", ""),
                        "email": l.get("email", "not_found"),
                        "phone": l.get("phone", "not_found"),
                        "lead_score": score,
                        "intent_type": intent_type,
                    })
                except Exception:
                    create_failed_count += 1
                    logger.exception("Lead.objects.create failed keyword=%s url=%s", keyword, l.get("source"))
            else:
                duplicate_count += 1
                        
    serialized_new_leads = LeadSerializer(
        Lead.objects.filter(id__in=new_lead_ids, owner=request.user).order_by('-lead_score', '-id'),
        many=True
    ).data
    serialized_existing_leads = LeadSerializer(
        Lead.objects.filter(id__in=existing_lead_ids, owner=request.user).order_by('-lead_score', '-id'),
        many=True
    ).data
    return Response({
        "status": "success",
        "keyword": keyword,
        "new_leads_found": len(new_lead_ids),
        "existing_leads_found": len(existing_lead_ids),
        "attempted_rows": attempted_rows,
        "duplicate_rows": duplicate_count,
        "create_failed_rows": create_failed_count,
        "scrape_failed_urls_count": len(scrape_failed_urls),
        "scrape_failed_urls": scrape_failed_urls[:10],
        "searched_urls": urls,
        "extracted_preview": extracted_preview[:10],
        "new_leads": serialized_new_leads[:10],
        "existing_leads": serialized_existing_leads[:10],
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def single_url_scrape_view(request):
    url = request.data.get('url', '')
    if not url:
        return Response({"detail": "URL required."}, status=status.HTTP_400_BAD_REQUEST)

    normalized = truncate_url(_normalize_website_url(url) or url.strip())
    discovery = discover_public_site(url)

    res = scrape_leads(url)

    if res.get("status") != "success":
        error_msg = res.get("message", "")
        stub_saved = 0
        if not Lead.objects.filter(
            source_url=normalized, email="not_found", owner=request.user, keyword="Direct URL"
        ).exists():
            try:
                score, intent_type = compute_lead_score("", "", normalized, "Direct URL")
                Lead.objects.create(
                    keyword="Direct URL",
                    source_url=normalized,
                    contact_name="",
                    email="not_found",
                    phone="not_found",
                    owner=request.user,
                    lead_score=score,
                    intent_type=intent_type,
                )
                stub_saved = 1
            except Exception:
                logger.exception("stub lead create failed for direct url")

        warn = (
            "Page could not be scraped (blocked, timeout, or non-200). "
            "A placeholder lead was saved so you can still track this domain in Lead Manager."
            if stub_saved
            else "Page could not be scraped and no placeholder was saved (duplicate or invalid URL)."
        )
        if "403" in error_msg:
            warn = (
                "Site returned 403 / anti-bot protection. Placeholder lead saved when possible—"
                "use Keyword Search or a simpler marketing site for live contact extraction."
                if stub_saved
                else warn
            )
        return Response(
            {
                "status": "partial",
                "new_leads_found": stub_saved,
                "discovery": discovery,
                "detail": warn,
                "scrape_error": error_msg[:500] if error_msg else None,
            },
            status=status.HTTP_200_OK,
        )

    all_leads = []

    for l in res["leads"]:
        src = truncate_url(l.get("source") or normalized)
        l = {**l, "source": src}
        has_email = l['email'] and l['email'] != "not_found"
        has_phone = l['phone'] and l['phone'] != "not_found" and l['phone'] != ""

        exists = False
        if has_email:
            exists = Lead.objects.filter(email=l['email'], owner=request.user).exists()
        elif has_phone:
            exists = Lead.objects.filter(phone=l['phone'], owner=request.user).exists()
        else:
            exists = Lead.objects.filter(source_url=l['source'], email="not_found", owner=request.user).exists()

        if not exists:
            try:
                score, intent_type = compute_lead_score(
                    l.get("email", ""), l.get("phone", ""), l["source"], "Direct URL"
                )
                Lead.objects.create(
                    keyword="Direct URL",
                    source_url=l['source'],
                    contact_name=l.get('contact_name', ''),
                    email=l['email'],
                    phone=l['phone'],
                    owner=request.user,
                    lead_score=score,
                    intent_type=intent_type,
                )
                all_leads.append(l)
            except Exception:
                logger.exception("direct url lead save failed")

    return Response(
        {
            "status": "success",
            "new_leads_found": len(all_leads),
            "discovery": discovery,
        }
    )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_audit_view(request):
    url = request.data.get('url', '')
    if not url:
        return Response({"detail": "URL required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        audit = generate_site_audit(url)
        quality = evaluate_website_quality_from_audit(audit)
        audit["website_quality"] = quality
        return Response({"status": "success", "audit": audit})
    except Exception:
        logger.exception("generate_site_audit failed")
        try:
            normalized = _normalize_website_url(url) or url.strip()
            audit = generate_mock_audit(normalized)
            audit["disclaimer"] = (
                "The live audit pipeline hit an unexpected error. This is a safe demo-style summary "
                "you can still use in a conversation—always verify claims before sending to a client."
            )
            audit["is_mock"] = True
            audit["status"] = "Review Required"
            quality = evaluate_website_quality_from_audit(audit)
            audit["website_quality"] = quality
            return Response(
                {
                    "status": "degraded",
                    "audit": audit,
                    "detail": "Recovered with a demo-style audit after an internal error.",
                },
                status=status.HTTP_200_OK,
            )
        except Exception:
            return Response(
                {"detail": "Could not generate an audit. Try again or use a smaller marketing site URL."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_leads_view(request):
    leads = Lead.objects.filter(owner=request.user).order_by('-lead_score', '-id')
    serializer = LeadSerializer(leads, many=True)
    return Response(serializer.data)


def _first_non_empty(row, keys, default=""):
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return default


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def import_leads_csv_view(request):
    csv_file = request.FILES.get("file")
    if not csv_file:
        return Response({"detail": "CSV file is required under 'file' field."}, status=status.HTTP_400_BAD_REQUEST)
    if not csv_file.name.lower().endswith(".csv"):
        return Response({"detail": "Only .csv files are supported."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        raw = csv_file.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return Response({"detail": "Could not read uploaded file."}, status=status.HTTP_400_BAD_REQUEST)

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return Response({"detail": "CSV header row is missing."}, status=status.HTTP_400_BAD_REQUEST)

    created = 0
    skipped = 0
    errors = []
    preview = []

    for idx, original_row in enumerate(reader, start=2):
        row = {str(k).strip().lower(): (v or "") for k, v in (original_row or {}).items()}
        source_url = truncate_url(
            _first_non_empty(row, ["source_url", "website", "url", "source", "domain"])
        )
        if not source_url:
            skipped += 1
            if len(errors) < 10:
                errors.append(f"Line {idx}: Missing source URL (source_url/website/url).")
            continue
        if not source_url.startswith(("http://", "https://")):
            source_url = "https://" + source_url

        contact_name = _first_non_empty(row, ["contact_name", "name", "company"], "")
        email = _first_non_empty(row, ["email", "extracted_email"], "not_found")
        phone = _first_non_empty(row, ["phone", "mobile", "contact"], "not_found")
        keyword = _first_non_empty(row, ["keyword", "source_keyword"], "CSV Import")
        lead_status = _first_non_empty(row, ["status"], "new")

        has_email = email != "not_found"
        has_phone = phone not in {"", "not_found"}
        if lead_status not in {choice[0] for choice in Lead.STATUS_CHOICES}:
            lead_status = Lead.STATUS_NEW

        exists = False
        if has_email:
            exists = Lead.objects.filter(email=email, owner=request.user).exists()
        elif has_phone:
            exists = Lead.objects.filter(phone=phone, owner=request.user).exists()
        else:
            exists = Lead.objects.filter(source_url=source_url, email="not_found", owner=request.user).exists()
        if exists:
            skipped += 1
            continue

        try:
            score, intent_type = compute_lead_score(email, phone, source_url, keyword)
            lead = Lead.objects.create(
                keyword=keyword,
                source_url=source_url,
                contact_name=contact_name,
                email=email,
                phone=phone,
                owner=request.user,
                lead_score=score,
                intent_type=intent_type,
                status=lead_status,
            )
            created += 1
            if len(preview) < 5:
                preview.append({"id": lead.id, "name": lead.contact_name, "email": lead.email, "source_url": lead.source_url})
        except Exception:
            skipped += 1
            if len(errors) < 10:
                errors.append(f"Line {idx}: Could not create lead row.")

    return Response(
        {
            "status": "success",
            "created": created,
            "skipped": skipped,
            "errors": errors,
            "preview": preview,
        }
    )


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_lead_status_view(request, lead_id):
    new_status = request.data.get("status")
    allowed = {choice[0] for choice in Lead.STATUS_CHOICES}
    if new_status not in allowed:
        return Response({"detail": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        lead = Lead.objects.get(id=lead_id, owner=request.user)
    except Lead.DoesNotExist:
        return Response({"detail": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)

    lead.status = new_status
    lead.save(update_fields=["status"])
    return Response({"status": "updated", "lead_id": lead.id, "new_status": lead.status})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def campaign_analytics_view(request):
    user_leads = Lead.objects.filter(owner=request.user)
    total_leads = user_leads.count()
    status_counts = {
        item["status"]: item["count"]
        for item in user_leads.values("status").annotate(count=Count("id"))
    }
    avg_score = (
        round(sum(user_leads.values_list("lead_score", flat=True)) / total_leads, 2)
        if total_leads
        else 0
    )
    return Response({
        "total_leads": total_leads,
        "avg_lead_score": avg_score,
        "status_breakdown": {
            "new": status_counts.get("new", 0),
            "contacted": status_counts.get("contacted", 0),
            "replied": status_counts.get("replied", 0),
            "meeting": status_counts.get("meeting", 0),
            "won": status_counts.get("won", 0),
            "lost": status_counts.get("lost", 0),
        },
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_bulk_view(request):
    data = request.data
    lead_ids = data.get('lead_ids', [])
    emails = list(Lead.objects.filter(id__in=lead_ids, owner=request.user).values_list('email', flat=True))
    
    if not emails:
        return Response({"detail": "No valid leads found."}, status=status.HTTP_400_BAD_REQUEST)

    success, error_message = send_bulk_smtp(
        emails, data.get('subject', ''), data.get('body', ''), request.user
    )
    
    if success:
        return Response({"status": "Emails queued and logged successfully."})
    return Response({"detail": error_message or "Failed to connect to SMTP server."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_scheduled_followups_view(request):
    """
    Simple manual cron-like endpoint:
    - finds queued EmailLog with scheduled_at <= now
    - sends them and marks status success/failed
    """
    config = get_smtp_config()
    if not config["configured"]:
        return Response({"detail": "SMTP is not configured on the server."}, status=status.HTTP_400_BAD_REQUEST)

    now = timezone.now()
    due_logs = EmailLog.objects.filter(
        owner=request.user,
        status="queued",
        scheduled_at__isnull=False,
        scheduled_at__lte=now,
    )[:100]

    if not due_logs:
        return Response({"status": "no_followups_due", "sent": 0})

    try:
        server = smtplib.SMTP(config["host"], config["port"])
        if config["use_tls"]:
            server.starttls()
        server.login(config["user"], settings.SMTP_PASS)
    except Exception as e:
        return Response({"detail": f"SMTP connect failed: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    sent = 0
    for log in due_logs:
        try:
            msg = EmailMessage()
            msg.set_content(request.data.get("body", "").replace("{email}", log.target_email) or log.subject)
            msg["Subject"] = log.subject
            msg["From"] = config["user"]
            msg["To"] = log.target_email
            server.send_message(msg)
            log.status = "success"
            log.error_msg = ""
            log.save(update_fields=["status", "error_msg"])
            sent += 1
        except Exception as e:
            log.status = "failed"
            log.error_msg = str(e)
            log.save(update_fields=["status", "error_msg"])

    server.quit()
    return Response({"status": "followups_sent", "sent": sent})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_tasks_for_nonresponders_view(request):
    """
    Multi-channel: create WhatsApp/Call tasks for leads that were emailed but not replied.
    Light implementation: any lead with failed emails becomes a task.
    """
    task_type = request.data.get("task_type", LeadTask.TYPE_CALL)
    if task_type not in {choice[0] for choice in LeadTask.TYPE_CHOICES}:
        return Response({"detail": "Invalid task type."}, status=status.HTTP_400_BAD_REQUEST)

    failed_emails = EmailLog.objects.filter(
        owner=request.user,
        status="failed",
    ).values_list("target_email", flat=True)

    leads = Lead.objects.filter(owner=request.user, email__in=failed_emails)
    created = 0
    for lead in leads:
        if not lead.phone:
            continue
        exists = lead.tasks.filter(task_type=task_type, status=LeadTask.STATUS_PENDING).exists()
        if exists:
            continue
        LeadTask.objects.create(
            lead=lead,
            task_type=task_type,
            notes=f"Auto-created because {lead.email} outreach failed.",
        )
        created += 1

    return Response({"status": "tasks_created", "count": created})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_tasks_view(request):
    tasks = LeadTask.objects.filter(lead__owner=request.user, status=LeadTask.STATUS_PENDING).select_related("lead")
    payload = []
    for t in tasks:
        payload.append({
            "id": t.id,
            "lead_id": t.lead.id,
            "lead_email": t.lead.email,
            "lead_phone": t.lead.phone,
            "task_type": t.task_type,
            "status": t.status,
            "notes": t.notes or "",
            "created_at": t.created_at,
        })
    return Response(payload)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_task_view(request, task_id):
    try:
        task = LeadTask.objects.select_related("lead").get(
            id=task_id,
            lead__owner=request.user,
        )
    except LeadTask.DoesNotExist:
        return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

    task.status = LeadTask.STATUS_DONE
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at"])
    return Response({"status": "completed", "task_id": task.id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def smtp_status_view(request):
    config = get_smtp_config()
    masked_user = ""
    if config["user"]:
        name, _, domain = config["user"].partition("@")
        masked_user = f"{name[:2]}***@{domain}" if domain else "***"
    return Response({
        "configured": config["configured"],
        "host": config["host"],
        "port": config["port"],
        "sender": masked_user,
    })
