from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import Count
from .models import Lead
from .serializers import UserSerializer, LeadSerializer
from .utils import (
    search_keyword_urls,
    scrape_leads,
    send_bulk_smtp,
    generate_site_audit,
    compute_lead_score,
    get_smtp_config,
)

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
    new_lead_ids = []
    extracted_preview = []
    
    for url in urls:
        res = scrape_leads(url)
        leads_payload = res.get("leads", [])
        if not leads_payload:
            leads_payload = [{
                "source": url,
                "contact_name": "",
                "email": "not_found",
                "phone": "not_found",
            }]

        for l in leads_payload:
            has_email = l.get('email') and l['email'] != "not_found"
            has_phone = l.get('phone') and l['phone'] != "not_found" and l['phone'] != ""

            exists = False
            if has_email:
                exists = Lead.objects.filter(email=l['email'], owner=request.user).exists()
            elif has_phone:
                exists = Lead.objects.filter(phone=l['phone'], owner=request.user).exists()
            else:
                exists = Lead.objects.filter(
                    source_url=l['source'],
                    email="not_found",
                    owner=request.user
                ).exists()

            if not exists:
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
                        
    serialized_new_leads = LeadSerializer(
        Lead.objects.filter(id__in=new_lead_ids, owner=request.user).order_by('-lead_score', '-id'),
        many=True
    ).data
    return Response({
        "status": "success",
        "keyword": keyword,
        "new_leads_found": len(new_lead_ids),
        "searched_urls": urls,
        "extracted_preview": extracted_preview[:10],
        "new_leads": serialized_new_leads[:10],
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def single_url_scrape_view(request):
    url = request.data.get('url', '')
    if not url:
        return Response({"detail": "URL required."}, status=status.HTTP_400_BAD_REQUEST)

    res = scrape_leads(url)
    
    if res.get("status") != "success":
        error_msg = res.get("message", "")
        if "403" in error_msg:
            return Response({"detail": "Aa website ma Anti-Bot Cloudflare Security chhe. Scraper ne block kari didhu."}, status=status.HTTP_403_FORBIDDEN)
        return Response({"detail": f"Scraping failed: {error_msg}"}, status=status.HTTP_400_BAD_REQUEST)

    all_leads = []
    
    for l in res["leads"]:
        has_email = l['email'] and l['email'] != "not_found"
        has_phone = l['phone'] and l['phone'] != "not_found" and l['phone'] != ""
        
        # Always try to save it for direct URL scraper even if no email/phone just so user gets data
        exists = False
        if has_email:
            exists = Lead.objects.filter(email=l['email'], owner=request.user).exists()
        elif has_phone:
            exists = Lead.objects.filter(phone=l['phone'], owner=request.user).exists()
        else:
            exists = Lead.objects.filter(source_url=l['source'], email="not_found", owner=request.user).exists()
            
        if not exists:
            score, intent_type = compute_lead_score(
                l.get("email", ""), l.get("phone", ""), l["source"], "Direct URL"
            )
            Lead.objects.create(
                keyword="Direct URL", source_url=l['source'],
                contact_name=l['contact_name'], email=l['email'],
                phone=l['phone'], owner=request.user,
                lead_score=score, intent_type=intent_type
            )
            all_leads.append(l)
                    
    return Response({"status": "success", "new_leads_found": len(all_leads)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_audit_view(request):
    url = request.data.get('url', '')
    if not url:
        return Response({"detail": "URL required."}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"status": "success", "audit": generate_site_audit(url)})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_leads_view(request):
    leads = Lead.objects.filter(owner=request.user).order_by('-lead_score', '-id')
    serializer = LeadSerializer(leads, many=True)
    return Response(serializer.data)


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
