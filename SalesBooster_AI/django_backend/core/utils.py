import requests
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, parse_qs, unquote
import smtplib
from email.message import EmailMessage
import random
import os
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from django.conf import settings

def fetch_html_with_fallback(url: str, timeout: int = 15):
    """
    Prefer curl_cffi (better anti-bot behavior) and fallback to requests
    when TLS/certificate validation fails on some local environments.
    """
    try:
        return curl_requests.get(url, impersonate="chrome110", timeout=timeout)
    except Exception:
        return requests.get(
            url,
            timeout=timeout,
            verify=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )

def search_keyword_urls(keyword: str):
    serpapi_key = os.getenv("SERPAPI_KEY")
    if serpapi_key:
        try:
            response = requests.get(
                "https://serpapi.com/search.json",
                params={"q": keyword, "engine": "google", "api_key": serpapi_key},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            urls = [
                item.get("link")
                for item in data.get("organic_results", [])
                if item.get("link")
            ]
            if urls:
                return urls[:10]
        except Exception:
            # fallback to mock if external API fails
            pass

    def _decode_duckduckgo_redirect(href: str) -> str:
        raw = (href or "").strip()
        if not raw:
            return ""
        if raw.startswith("//duckduckgo.com/l/"):
            parsed = urlparse("https:" + raw)
            uddg = parse_qs(parsed.query).get("uddg", [])
            return unquote(uddg[0]) if uddg else ""
        if raw.startswith("/l/"):
            parsed = urlparse("https://duckduckgo.com" + raw)
            uddg = parse_qs(parsed.query).get("uddg", [])
            return unquote(uddg[0]) if uddg else ""
        return raw

    def _looks_like_real_http_url(href: str) -> bool:
        if not href.startswith(("http://", "https://")):
            return False
        parsed = urlparse(href)
        host = (parsed.netloc or "").lower()
        if not host:
            return False
        blocked_hosts = {
            "duckduckgo.com",
            "www.duckduckgo.com",
            "google.com",
            "www.google.com",
            "bing.com",
            "www.bing.com",
        }
        return host not in blocked_hosts

    def _extract_urls_from_html(html: str):
        soup = BeautifulSoup(html or "", "html.parser")
        urls = []
        seen = set()

        selectors = [
            "a.result__a",
            "a.result-link",
            "a[data-testid='result-title-a']",
            "article h2 a",
            "h2 a",
            ".results_links a",
        ]

        candidate_anchors = []
        for selector in selectors:
            candidate_anchors.extend(soup.select(selector))
        if not candidate_anchors:
            candidate_anchors = soup.find_all("a", href=True)

        for anchor in candidate_anchors:
            href = _decode_duckduckgo_redirect(anchor.get("href", ""))
            if not _looks_like_real_http_url(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            urls.append(href)
            if len(urls) >= 10:
                break
        return urls

    search_endpoints = [
        ("https://html.duckduckgo.com/html/", {"q": keyword}),
        ("https://lite.duckduckgo.com/lite/", {"q": keyword}),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    for endpoint, params in search_endpoints:
        try:
            response = requests.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=15,
                verify=False,
            )
            response.raise_for_status()
            urls = _extract_urls_from_html(response.text)
            if urls:
                return urls
        except Exception:
            continue

    # Never return fake domains. If real search fails, return empty list
    # so the API can report this transparently to the UI.
    return []


def detect_intent_type(keyword: str):
    key = keyword.lower()
    high_intent_markers = ["near me", "hire", "agency", "services", "developer", "company"]
    mid_intent_markers = ["best", "top", "compare", "pricing", "cost"]

    if any(marker in key for marker in high_intent_markers):
        return "high_intent"
    if any(marker in key for marker in mid_intent_markers):
        return "mid_intent"
    return "awareness"


def compute_lead_score(email: str, phone: str, source_url: str, keyword: str):
    score = 0
    domain = email.split("@")[-1] if "@" in email else ""
    generic_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com"}

    if email and email != "not_found":
        score += 35
    if phone:
        score += 25
    if domain and domain not in generic_domains:
        score += 20
    if source_url.startswith("https://"):
        score += 10

    intent = detect_intent_type(keyword)
    if intent == "high_intent":
        score += 10
    elif intent == "mid_intent":
        score += 5

    return min(score, 100), intent


def evaluate_website_quality_from_audit(audit: dict):
    """
    Map audit performance/status into a simple quality label for leads.
    """
    status = (audit or {}).get("status", "") or ""
    perf = (audit or {}).get("performance_score", "0/100")
    try:
        perf_num = int(str(perf).split("/")[0])
    except Exception:
        perf_num = 0

    if status == "Review Required" or str(perf).upper().startswith("N"):
        return "average"
    if status in {"Excellent", "Good"} or perf_num >= 80:
        return "good"
    if status in {"Needs Improvement"} or 55 <= perf_num < 80:
        return "average"
    return "poor"

def extract_name_heuristic(soup, url):
    try:
        domain = urlparse(url).netloc.replace('www.', '').split('.')[0].capitalize()
        return f"{domain} Rep"
    except:
        return "Unknown Rep"


def truncate_url(url: str, max_len: int = 500) -> str:
    u = (url or "").strip()
    if len(u) <= max_len:
        return u
    return u[: max_len - 3] + "..."


def discover_public_site(url: str) -> dict:
    """
    Lightweight robots.txt + sitemap sniffing for the Direct URL UI (no JS required).
    """
    out = {
        "robots_found": False,
        "scanned_pages": [],
        "sitemaps": [],
        "disallow_rules": [],
        "sitemap_pages_found": [],
    }
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url.strip()
        parsed = urlparse(url)
        if not parsed.netloc:
            return out
        base = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base}/robots.txt"
        r = fetch_html_with_fallback(robots_url, timeout=10)
        out["scanned_pages"] = [robots_url]
        if r.status_code != 200:
            return out
        out["robots_found"] = True
        text = r.text or ""
        sitemaps = []
        disallows = []
        for raw in text.splitlines():
            line = raw.strip()
            low = line.lower()
            if low.startswith("sitemap:"):
                part = line.split(":", 1)[1].strip()
                if part.startswith("http"):
                    sitemaps.append(part)
            elif low.startswith("disallow:"):
                disallows.append(line.split(":", 1)[1].strip() or "/")
        out["sitemaps"] = sitemaps[:5]
        out["disallow_rules"] = disallows[:20]
        for sm in sitemaps[:2]:
            try:
                sr = fetch_html_with_fallback(sm, timeout=12)
                if sr.status_code != 200:
                    continue
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sr.text or "", flags=re.I)
                out["sitemap_pages_found"].extend(locs[:25])
            except Exception:
                continue
        out["sitemap_pages_found"] = out["sitemap_pages_found"][:30]
    except Exception:
        pass
    return out


def scrape_leads(url: str):
    try:
        if not url.startswith('http'):
            url = 'https://' + url
            
        response = fetch_html_with_fallback(url, timeout=15)
        if response.status_code != 200:
            raise Exception(f"HTTP Error: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator=' ')
        def extract_from_soup_and_text(s, t):
            raw_em = list(set(re.findall(r"[a-zA-Z0-9.\-+_]+@[a-zA-Z0-9.\-+_]+\.[a-zA-Z]+", t)))
            em = [e for e in raw_em if not e.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
            ph = list(set(re.findall(r"[\+\(]?[1-9][0-9 .\-\(\)]{8,14}[0-9]", t)))
            cl_ph = [p.strip() for p in ph if len(p.strip()) > 7 and not p.strip().startswith('202')]
            
            if s:
                for a in s.find_all('a', href=True):
                    href = a.get('href', '').strip()
                    if href.startswith('mailto:'):
                        ext_email = href.replace('mailto:', '').split('?')[0].strip()
                        if ext_email and ext_email not in em:
                            em.append(ext_email)
                    elif href.startswith('tel:'):
                        ext_phone = href.replace('tel:', '').strip()
                        if len(ext_phone) > 7 and ext_phone not in cl_ph:
                            cl_ph.append(ext_phone)
            return em, cl_ph

        emails, clean_phones = extract_from_soup_and_text(soup, text)
        
        # Deep Scan: If no leads found, find and crawl contact/about pages
        if not emails and not clean_phones:
            try:
                base_domain = '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(url))
                crawled_urls = {url.strip('/')}
                to_crawl = []
                
                # Find promising links
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '').strip().lower()
                    txt = a.get_text().lower()
                    
                    if any(kw in href for kw in ['contact', 'about', 'team', 'support', 'reach']) or \
                       any(kw in txt for kw in ['contact', 'about', 'team', 'support', 'reach']):
                        
                        if href.startswith('http'):
                            full_url = href
                        elif href.startswith('/'):
                            full_url = base_domain + href
                        else:
                            full_url = base_domain + '/' + href
                            
                        # Ensure it's on the same domain and not already queued
                        if base_domain in full_url and full_url not in crawled_urls:
                            if not any(ext in full_url for ext in ['.pdf', '.jpg', '.png', '.css', '.js']):
                                to_crawl.append(full_url)
                                crawled_urls.add(full_url)
                                if len(to_crawl) >= 3: # Max 3 subpages to keep it fast
                                    break
                                    
                # Ensure we at least try standard /contact if none found
                if not to_crawl:
                    to_crawl.append(base_domain + '/contact')
                    
                # Crawl the queued subpages
                for sub_url in to_crawl:
                    if emails or clean_phones:
                        break # Stop early if we struck gold
                    try:
                        c_res = fetch_html_with_fallback(sub_url, timeout=10)
                        if c_res.status_code == 200:
                            c_soup = BeautifulSoup(c_res.text, 'html.parser')
                            c_text = c_soup.get_text(separator=' ')
                            new_em, new_ph = extract_from_soup_and_text(c_soup, c_text)
                            for ne in new_em:
                                if ne not in emails: emails.append(ne)
                            for np in new_ph:
                                if np not in clean_phones: clean_phones.append(np)
                    except:
                        continue
            except:
                pass
        
        phone_str = clean_phones[0] if clean_phones else ""
        contact_name = extract_name_heuristic(soup, url)
        
        results = []
        if not emails and not clean_phones:
            results.append({"source": url, "contact_name": contact_name, "email": "not_found", "phone": "not_found"})
        elif not emails and clean_phones:
            results.append({"source": url, "contact_name": contact_name, "email": "not_found", "phone": phone_str})
        else:
            for email in emails:
                results.append({"source": url, "contact_name": contact_name, "email": email, "phone": phone_str})
        return {"status": "success", "leads": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_smtp_config():
    smtp_user = settings.SMTP_USER
    return {
        "configured": bool(settings.SMTP_HOST and settings.SMTP_PORT and smtp_user and settings.SMTP_PASS),
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": smtp_user,
        "use_tls": settings.SMTP_USE_TLS,
    }


def send_bulk_smtp(emails, subject, body, user, schedule_followups: bool = True):
    from .models import EmailLog
    config = get_smtp_config()
    if not config["configured"]:
        return False, "SMTP is not configured on the server."

    try:
        server = smtplib.SMTP(config["host"], config["port"])
        if config["use_tls"]:
            server.starttls()
        server.login(config["user"], settings.SMTP_PASS)
        
        for email in emails:
            try:
                msg = EmailMessage()
                msg.set_content(body.replace("{email}", email))
                msg['Subject'] = subject
                msg['From'] = config["user"]
                msg['To'] = email
                server.send_message(msg)
                EmailLog.objects.create(
                    target_email=email,
                    subject=subject,
                    status="success",
                    campaign_name="bulk_campaign",
                    sequence_step=1,
                    owner=user
                )
            except Exception as e:
                EmailLog.objects.create(
                    target_email=email,
                    subject=subject,
                    status="failed",
                    campaign_name="bulk_campaign",
                    sequence_step=1,
                    error_msg=str(e),
                    owner=user
                )
        # schedule follow-up steps as queued logs
        if schedule_followups:
            now = datetime.utcnow()
            for email in emails:
                for step, days in ((2, 3), (3, 7)):
                    try:
                        EmailLog.objects.create(
                            target_email=email,
                            subject=subject,
                            status="queued",
                            campaign_name="bulk_campaign",
                            sequence_step=step,
                            scheduled_at=now + timedelta(days=days),
                            owner=user,
                        )
                    except Exception:
                        continue

        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)

def generate_mock_audit(url: str):
    score = random.randint(45, 80)
    issues = [
        "Images are not optimized (WebP recommended).",
        "No caching headers detected.",
        "Mobile responsiveness fails.",
        "Missing meta descriptions.",
        "Slow server response time."
    ]
    selected_issues = random.sample(issues, 3)
    base = {
        "url": url,
        "is_mock": True,
        "performance_score": f"{score}/100",
        "status": "Poor" if score < 60 else "Needs Improvement",
        "critical_issues_found": selected_issues,
        "technical_observations": [],
        "pages_audited": 1,
        "audited_pages": [],
        "disclaimer": "Demo audit only. Results are simulated and not generated from a live Lighthouse scan.",
        "recommendation": "We recommend a full code refactor and UI update. Our tech team can fix this rapidly.",
        "estimated_cost_to_fix": f"${random.randint(5, 15) * 100}",
    }
    insights = _build_sales_insights(
        base["critical_issues_found"], base["estimated_cost_to_fix"], base["status"], url
    )
    base.update(insights)
    return base


def _normalize_website_url(url: str):
    clean = (url or "").strip()
    if not clean:
        return ""
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean


def _status_from_score(score: int):
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs Improvement"
    return "Poor"


def _coerce_int(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _find_meta_content(soup, names):
    for name in names:
        tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        if tag and (tag.get("content") or "").strip():
            return tag.get("content").strip()
    return ""


def _find_meta_property_content(soup, properties):
    for prop in properties:
        tag = soup.find("meta", attrs={"property": re.compile(f"^{re.escape(prop)}$", re.I)})
        if tag and (tag.get("content") or "").strip():
            return tag.get("content").strip()
    return ""


def _looks_like_bot_block_page(html: str, final_url: str):
    haystack = f"{(html or '').lower()} {str(final_url).lower()}"
    markers = [
        "captcha",
        "robot check",
        "verify you are human",
        "access denied",
        "request blocked",
        "automated access",
        "cloudflare",
        "/errors/validatecaptcha",
        "security challenge",
    ]
    return any(marker in haystack for marker in markers)


def _run_browser_audit(url: str):
    frontend_dir = Path(settings.BASE_DIR).parent / "frontend"
    script_path = frontend_dir / "scripts" / "browserAudit.mjs"
    if not script_path.exists():
        return None

    try:
        completed = subprocess.run(
            ["node", str(script_path), url],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception:
        return None

    if completed.returncode != 0 or not completed.stdout.strip():
        return None

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _build_sales_insights(issues, estimated_cost, status, url):
    parsed = urlparse(url)
    brand = parsed.netloc.replace("www.", "") or "this website"
    has_real_issues = bool(issues) and "No high-confidence" not in issues[0]
    review_required = status == "Review Required"

    if review_required:
        return {
            "what_we_can_improve": [
                "We can run a deeper manual browser audit and verify the real user journey page by page.",
                "We can test homepage, landing pages, and contact flow in a logged-in browser session.",
                "We can convert the audit into a safe client presentation with only verified findings.",
            ],
            "competitor_benchmark": [
                "Stronger competitors usually review conversion flow, speed, and messaging on real browsers, not raw HTML only.",
                "Winning brands often use audited landing pages and cleaner offer presentation to improve lead conversion.",
                "Competitor advantage normally comes from better UX clarity and funnel design, not just technical tags.",
            ],
            "delivery_plan": [
                "Run a verified browser audit with screenshots and confidence notes.",
                "Prepare a shortlist of real issues with business impact and priority.",
                "Deliver a polished improvement roadmap the client can understand quickly.",
            ],
            "outreach_summary": (
                f"We reviewed {brand} and noticed that an automated scan needs manual verification before making technical claims. "
                "Our team can run a deeper browser-based audit and convert the findings into a practical growth roadmap."
            ),
        }

    if not has_real_issues:
        return {
            "what_we_can_improve": [
                "We can improve conversion rate with stronger CTAs, better landing page messaging, and form-flow optimization.",
                "We can improve trust with clearer proof points, testimonials, and offer positioning.",
                "We can improve lead capture by refining page hierarchy, mobile UX, and follow-up flows.",
            ],
            "competitor_benchmark": [
                "Top competitors usually win with sharper messaging and better funnel design, even when the website is technically healthy.",
                "Competitors often use dedicated landing pages for campaigns instead of sending traffic to generic pages.",
                "Better-performing brands usually combine speed, trust signals, and clearer conversion intent on each page.",
            ],
            "delivery_plan": [
                "Audit key conversion pages and identify drop-off points.",
                "Redesign sections that affect trust, clarity, and conversions.",
                "Launch CRO improvements and measure lead quality impact.",
            ],
            "outreach_summary": (
                f"{brand} already looks technically solid, so the growth opportunity is more around conversion optimization, "
                "landing-page positioning, and better lead capture strategy than urgent bug fixing."
            ),
        }

    themes = []
    joined = " ".join(issues).lower()
    if "load" in joined or "slow" in joined or "heavy payload" in joined:
        themes.append(("performance", "Improve page speed, asset loading, and render efficiency on key landing pages."))
    if "javascript" in joined or "stylesheet" in joined:
        themes.append(("frontend", "Reduce front-end weight by trimming unused scripts, styles, and third-party resources."))
    if "title" in joined or "seo" in joined or "crawlability" in joined:
        themes.append(("seo", "Strengthen technical SEO signals and search snippet quality across important pages."))
    if "image" in joined:
        themes.append(("media", "Optimize imagery and visual delivery for faster load and better mobile experience."))

    if not themes:
        themes.append(("ux", "Improve overall site quality through conversion-focused UX and technical cleanup."))

    improve_points = [item[1] for item in themes[:3]]
    competitor_points = []
    delivery_points = []

    for name, _ in themes[:3]:
        if name == "performance":
            competitor_points.append("Competitors that convert better usually load faster and reach the key message sooner.")
            delivery_points.append("Compress assets, reduce blocking resources, and improve page load performance.")
        elif name == "frontend":
            competitor_points.append("Better competitors often keep their pages leaner, with fewer heavy scripts and dependencies.")
            delivery_points.append("Refactor front-end assets and remove unnecessary third-party requests.")
        elif name == "seo":
            competitor_points.append("Competitors often gain more search visibility by keeping metadata and crawl signals more consistent.")
            delivery_points.append("Fix core SEO markup, landing-page structure, and indexing signals.")
        elif name == "media":
            competitor_points.append("Higher-performing sites usually deliver lighter images and cleaner mobile visuals.")
            delivery_points.append("Convert and resize media assets for faster rendering and lower page weight.")
        else:
            competitor_points.append("Competitors usually make the buying journey clearer with simpler structure and stronger trust signals.")
            delivery_points.append("Refine layout, messaging hierarchy, and conversion elements across priority pages.")

    return {
        "what_we_can_improve": improve_points,
        "competitor_benchmark": competitor_points[:3],
        "delivery_plan": delivery_points[:3],
        "outreach_summary": (
            f"We reviewed {brand} and found a few practical improvement areas. "
            f"Our team can address these issues in a focused sprint, with estimated implementation around {estimated_cost}."
        ),
    }


def _build_browser_based_audit(normalized_url: str, browser_data: dict):
    final_url = browser_data.get("finalUrl") or normalized_url
    score = 100
    issues = []
    confidence = "high"
    observations = []
    pages_audited = max(1, _coerce_int(browser_data.get("pagesAudited"), 1))
    page_summaries = browser_data.get("pageSummaries") or []

    if browser_data.get("blocked"):
        result = {
            "url": normalized_url,
            "is_mock": False,
            "performance_score": "N/A",
            "status": "Review Required",
            "critical_issues_found": [
                "Automated browser hit a bot-protection or challenge page.",
                "This domain needs a manual/browser-authenticated audit.",
                "No client-facing issues are shown to avoid false positives.",
            ],
            "technical_observations": [],
            "pages_audited": pages_audited,
            "audited_pages": page_summaries[:4],
            "disclaimer": "Confidence low: findings intentionally suppressed to avoid fake issues.",
            "recommendation": "Use a logged-in or human-reviewed browser audit before pitching this client.",
            "estimated_cost_to_fix": "$0",
        }
        result.update(_build_sales_insights(result["critical_issues_found"], result["estimated_cost_to_fix"], result["status"], normalized_url))
        return result

    http_status = browser_data.get("status")
    if isinstance(http_status, int) and http_status >= 400:
        issues.append(f"Landing page returned HTTP {http_status}.")
        score -= 35

    dom_content_loaded_ms = browser_data.get("domContentLoadedMs")
    load_event_ms = browser_data.get("loadEventMs")
    total_bytes = _coerce_int(browser_data.get("totalTransferSize"), 0)
    js_requests = _coerce_int(browser_data.get("scriptRequests"), 0)
    image_requests = _coerce_int(browser_data.get("imageRequests"), 0)
    stylesheet_requests = _coerce_int(browser_data.get("stylesheetRequests"), 0)
    total_requests = _coerce_int(browser_data.get("totalRequests"), 0)
    failed_request_count = _coerce_int(browser_data.get("failedRequestCount"), 0)
    bad_response_count = _coerce_int(browser_data.get("badResponseCount"), 0)
    console_error_count = _coerce_int(browser_data.get("consoleErrorCount"), 0)
    h1_count = _coerce_int(browser_data.get("h1Count"), 0)
    image_count = _coerce_int(browser_data.get("imageCount"), 0)
    missing_alt_count = _coerce_int(browser_data.get("missingAltCount"), 0)
    oversized_images = _coerce_int(browser_data.get("oversizedImages"), 0)
    unlabeled_inputs_count = _coerce_int(browser_data.get("unlabeledInputsCount"), 0)
    forms_count = _coerce_int(browser_data.get("formsCount"), 0)
    inputs_count = _coerce_int(browser_data.get("inputsCount"), 0)
    empty_buttons_count = _coerce_int(browser_data.get("emptyButtonsCount"), 0)
    insecure_requests = _coerce_int(browser_data.get("insecureRequests"), 0)
    third_party_domains = _coerce_int(browser_data.get("thirdPartyDomains"), 0)
    title_length = _coerce_int(browser_data.get("titleLength"), 0)
    meta_description_length = _coerce_int(browser_data.get("metaDescriptionLength"), 0)
    has_canonical = browser_data.get("hasCanonical", False)
    has_noindex = browser_data.get("hasNoindex", False)

    if isinstance(load_event_ms, (int, float)) and load_event_ms > 5000:
        issues.append(f"Page load is slow in-browser ({int(load_event_ms)}ms load event).")
        score -= 18
    elif isinstance(dom_content_loaded_ms, (int, float)) and dom_content_loaded_ms > 3000:
        issues.append(f"Initial rendering is slower than expected ({int(dom_content_loaded_ms)}ms DOM ready).")
        score -= 12

    avg_bytes = int(total_bytes / pages_audited) if pages_audited else total_bytes
    avg_requests = int(total_requests / pages_audited) if pages_audited else total_requests
    avg_scripts = int(js_requests / pages_audited) if pages_audited else js_requests
    avg_stylesheets = int(stylesheet_requests / pages_audited) if pages_audited else stylesheet_requests

    if isinstance(avg_bytes, (int, float)) and avg_bytes > 7_000_000:
        issues.append("Average page payload is very heavy across audited pages, which can hurt conversions.")
        score -= 12
    elif isinstance(avg_bytes, (int, float)) and avg_bytes > 4_500_000:
        issues.append("Average page payload is larger than ideal for a landing experience.")
        score -= 8

    if avg_requests > 120:
        issues.append("Average request count is very high across audited pages, increasing page complexity.")
        score -= 10

    if avg_scripts > 35:
        issues.append("High JavaScript request volume may be affecting interactivity and performance.")
        score -= 8

    if image_requests > 80:
        issues.append("Very high image count detected on first paint path.")
        score -= 8

    if avg_stylesheets > 12:
        issues.append("Too many stylesheet requests can slow render start.")
        score -= 6

    if failed_request_count >= max(3, pages_audited * 2):
        issues.append(f"{failed_request_count} network requests failed across audited pages.")
        score -= 12
    elif failed_request_count >= 1:
        issues.append("Some network requests failed during the audit.")
        score -= 8

    if bad_response_count >= max(3, pages_audited * 2):
        issues.append(f"{bad_response_count} page resources returned 4xx/5xx responses during the audit.")
        score -= 12

    if console_error_count >= max(3, pages_audited * 2):
        issues.append(f"Browser console reported {console_error_count} JavaScript errors across audited pages.")
        score -= 10
    elif console_error_count >= 1:
        issues.append("Browser console reported JavaScript errors during load.")
        score -= 6

    page_title = (browser_data.get("title") or "").strip()
    if not page_title:
        issues.append("Missing page title after full browser render.")
        score -= 12
    elif title_length > 70:
        observations.append("Title is longer than typical SERP-friendly length.")

    if h1_count == 0:
        issues.append("No H1 heading found on the homepage render, which can weaken content hierarchy.")
        score -= 6
    elif h1_count > 2:
        observations.append("Multiple H1 headings detected; content hierarchy may need cleanup.")

    if image_count >= 5 and missing_alt_count >= max(3, int(image_count * 0.4)):
        issues.append("Many images are missing alt text, which affects accessibility and SEO.")
        score -= 8

    if oversized_images >= 3:
        issues.append("Several oversized images may be increasing page weight unnecessarily.")
        score -= 8

    if forms_count > 0 and inputs_count > 0 and unlabeled_inputs_count >= max(1, int(inputs_count * 0.3)):
        issues.append("Some form fields appear unlabeled, which can hurt accessibility and form completion.")
        score -= 7

    if empty_buttons_count >= 1:
        issues.append("Some buttons appear to have no visible or accessible label.")
        score -= 6

    if insecure_requests >= 1:
        issues.append("Mixed-content style requests were detected over HTTP.")
        score -= 10

    if has_noindex:
        issues.append("Page includes a noindex directive, which can block search visibility.")
        score -= 14

    if third_party_domains > 12:
        issues.append("Heavy third-party dependency footprint detected during load.")
        score -= 6

    if not browser_data.get("hasViewport"):
        observations.append("Viewport meta tag was not detected in rendered markup.")
        confidence = "medium"

    if not browser_data.get("hasMetaDescription"):
        observations.append("Meta description was not detected in rendered markup.")
        confidence = "medium"

    if not has_canonical:
        observations.append("Canonical URL tag was not detected on this page.")

    if 0 < meta_description_length < 70:
        observations.append("Meta description looks shorter than ideal for search snippets.")

    if pages_audited > 1:
        observations.append(f"Audit aggregated findings from {pages_audited} important site pages for better accuracy.")

    slow_pages = [
        page.get("url")
        for page in page_summaries
        if isinstance(page.get("loadEventMs"), (int, float)) and page.get("loadEventMs") > 5000
    ]
    if slow_pages:
        observations.append(f"Slowest audited pages include {', '.join(slow_pages[:2])}.")

    if not issues:
        issues = ["No high-confidence client-facing issues found from the rendered page."]

    score = max(35, min(99, score))
    estimated_cost = max(300, (100 - score) * 15) if len(issues) and "No high-confidence" not in issues[0] else 0

    result = {
        "url": final_url,
        "is_mock": False,
        "performance_score": f"{score}/100" if estimated_cost else "95/100",
        "status": "Good" if estimated_cost == 0 else _status_from_score(score),
        "critical_issues_found": issues[:5],
        "technical_observations": observations[:5],
        "pages_audited": pages_audited,
        "audited_pages": page_summaries[:4],
        "disclaimer": f"Browser-rendered audit completed with {confidence} confidence.",
        "recommendation": (
            "Lead with real performance issues only."
            if estimated_cost
            else "This site looks healthy. Use personalization or CRO ideas instead of technical fear-based outreach."
        ),
        "estimated_cost_to_fix": f"${estimated_cost}",
    }
    result.update(_build_sales_insights(result["critical_issues_found"], result["estimated_cost_to_fix"], result["status"], final_url))
    return result


def generate_site_audit(url: str):
    normalized_url = _normalize_website_url(url)
    if not normalized_url:
        result = {
            "url": url,
            "is_mock": True,
            "performance_score": "0/100",
            "status": "Poor",
            "critical_issues_found": ["Invalid URL provided."],
            "technical_observations": [],
            "pages_audited": 0,
            "audited_pages": [],
            "disclaimer": "Audit could not run because URL was missing or invalid.",
            "recommendation": "Provide a valid website URL to generate a real audit.",
            "estimated_cost_to_fix": "$0",
        }
        result.update(_build_sales_insights(result["critical_issues_found"], result["estimated_cost_to_fix"], result["status"], url))
        return result

    browser_data = _run_browser_audit(normalized_url)
    if browser_data:
        return _build_browser_based_audit(normalized_url, browser_data)

    started = time.perf_counter()
    try:
        response = fetch_html_with_fallback(normalized_url, timeout=20)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        html = response.text or ""
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        # Keep fallback behavior available when remote websites block scanners.
        fallback = generate_mock_audit(normalized_url)
        fallback["disclaimer"] = (
            "Live audit failed (site blocked or timed out). Showing simulated findings instead."
        )
        return fallback

    issues = []
    score = 100
    headers = {k.lower(): v for k, v in response.headers.items()}
    status_code = response.status_code
    final_url = getattr(response, "url", normalized_url)
    blocked_like_page = _looks_like_bot_block_page(html, final_url)
    very_thin_html = len(html.strip()) < 900

    if blocked_like_page or very_thin_html:
        result = {
            "url": normalized_url,
            "is_mock": False,
            "performance_score": "N/A",
            "status": "Review Required",
            "critical_issues_found": [
                "Automated scanner could not access a full public page payload.",
                "Site likely served a bot-protection/challenge response.",
                "Run a browser-based Lighthouse audit for accurate findings.",
            ],
            "technical_observations": [],
            "pages_audited": 1,
            "audited_pages": [],
            "disclaimer": "Confidence low: results suppressed to avoid false positives.",
            "recommendation": "Use authenticated browser audit (Lighthouse/Puppeteer) for this domain.",
            "estimated_cost_to_fix": "$0",
        }
        result.update(_build_sales_insights(result["critical_issues_found"], result["estimated_cost_to_fix"], result["status"], normalized_url))
        return result

    if status_code >= 400:
        issues.append(f"Homepage returned HTTP {status_code}, reducing crawlability and trust.")
        score -= 30
    elif status_code >= 300:
        issues.append(f"Homepage returns HTTP {status_code} redirect; review redirect chain for speed.")
        score -= 8

    if elapsed_ms > 2500:
        issues.append(f"Slow server response detected ({elapsed_ms}ms).")
        score -= 18
    elif elapsed_ms > 1500:
        issues.append(f"Server response is high for first load ({elapsed_ms}ms).")
        score -= 10

    title_tag = soup.find("title")
    title_text = title_tag.get_text(strip=True) if title_tag else ""
    og_title = _find_meta_property_content(soup, ["og:title"])
    twitter_title = _find_meta_content(soup, ["twitter:title"])
    effective_title = title_text or og_title or twitter_title
    if not effective_title:
        issues.append("Missing page title, which harms SEO and ad-quality relevance.")
        score -= 12
    elif len(effective_title) < 15:
        issues.append("Title is too short and may underperform in search snippets.")
        score -= 6

    meta_desc = _find_meta_content(soup, ["description", "twitter:description"])
    og_desc = _find_meta_property_content(soup, ["og:description"])
    effective_desc = meta_desc or og_desc
    if not effective_desc:
        issues.append("Missing meta description tag.")
        score -= 8

    viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    if not viewport:
        issues.append("Mobile viewport tag missing; mobile responsiveness likely affected.")
        score -= 12

    html_tag = soup.find("html")
    if html_tag and not html_tag.get("lang"):
        issues.append("`<html lang>` attribute is missing, impacting accessibility and SEO.")
        score -= 5

    img_sources = [
        (img.get("src") or "").lower()
        for img in soup.find_all("img")
        if (img.get("src") or "").strip()
    ]
    legacy_images = [
        src for src in img_sources if src.endswith((".jpg", ".jpeg", ".png")) and ".svg" not in src
    ]
    if img_sources and len(legacy_images) >= max(3, int(len(img_sources) * 0.6)):
        issues.append("Most images are legacy formats (JPG/PNG); modern WebP/AVIF is recommended.")
        score -= 10

    external_scripts = [
        script for script in soup.find_all("script")
        if (script.get("src") or "").startswith(("http://", "https://"))
    ]
    if len(external_scripts) > 12:
        issues.append("High number of external scripts can degrade performance.")
        score -= 8

    parsed = urlparse(normalized_url)
    if parsed.scheme != "https":
        issues.append("Site is not served over HTTPS.")
        score -= 12

    if not issues:
        issues = ["No critical automated issues found. A manual Lighthouse pass can uncover deeper bottlenecks."]

    score = max(30, min(99, score))
    estimated_cost = max(300, (100 - score) * 15)

    result = {
        "url": normalized_url,
        "is_mock": False,
        "performance_score": f"{score}/100",
        "status": _status_from_score(score),
        "critical_issues_found": issues[:5],
        "technical_observations": [],
        "pages_audited": 1,
        "audited_pages": [],
        "disclaimer": "Automated quick audit generated from real page response and markup signals.",
        "recommendation": "Prioritize the top issues, then run a full Lighthouse + Core Web Vitals audit.",
        "estimated_cost_to_fix": f"${estimated_cost}",
    }
    result.update(_build_sales_insights(result["critical_issues_found"], result["estimated_cost_to_fix"], result["status"], normalized_url))
    return result
