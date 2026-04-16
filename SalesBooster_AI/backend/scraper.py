import re
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REQUEST_HEADERS = {
    "User-Agent": "SalesBoosterAI/1.0 (+public-site-discovery)"
}
MAX_PAGES_TO_SCAN = 5
CONTACT_HINTS = ("contact", "about", "team", "support", "company")


def normalize_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("URL is required")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


def fetch_text(url: str, timeout: int = 10):
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.exceptions.SSLError:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, verify=False)
        response.raise_for_status()
        return response


def is_same_domain(candidate_url: str, base_domain: str) -> bool:
    parsed = urlparse(candidate_url)
    return bool(parsed.netloc) and parsed.netloc == base_domain


def parse_robots(base_url: str) -> dict:
    robots_url = urljoin(base_url, "/robots.txt")
    result = {
        "robots_url": robots_url,
        "robots_found": False,
        "disallow_rules": [],
        "sitemaps": [],
    }
    try:
        response = fetch_text(robots_url)
    except Exception:
        return result

    result["robots_found"] = True
    for raw_line in response.text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith("disallow:"):
            rule = line.split(":", 1)[1].strip() or "/"
            result["disallow_rules"].append(rule)
        elif lower.startswith("sitemap:"):
            sitemap_url = line.split(":", 1)[1].strip()
            if sitemap_url:
                result["sitemaps"].append(sitemap_url)
    return result


def path_disallowed(url: str, disallow_rules: list[str]) -> bool:
    path = urlparse(url).path or "/"
    for rule in disallow_rules:
        if rule == "/":
            return True
        if rule and path.startswith(rule):
            return True
    return False


def collect_sitemap_urls(sitemap_urls: list[str], base_domain: str, disallow_rules: list[str]) -> list[str]:
    discovered = []
    seen = set()

    for sitemap_url in sitemap_urls[:3]:
        try:
            response = fetch_text(sitemap_url, timeout=12)
        except Exception:
            continue

        soup = BeautifulSoup(response.text, "xml")
        for loc in soup.find_all("loc"):
            candidate = (loc.text or "").strip()
            if not candidate:
                continue
            if not is_same_domain(candidate, base_domain):
                continue
            if path_disallowed(candidate, disallow_rules):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            discovered.append(candidate)
            if len(discovered) >= 20:
                return discovered
    return discovered


def collect_candidate_pages(root_url: str, soup: BeautifulSoup, base_domain: str, disallow_rules: list[str]) -> list[str]:
    candidates = [root_url]
    seen = {root_url}

    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        candidate = urljoin(root_url, href)
        lower_candidate = candidate.lower()
        if not is_same_domain(candidate, base_domain):
            continue
        if path_disallowed(candidate, disallow_rules):
            continue
        if candidate in seen:
            continue
        if any(hint in lower_candidate for hint in CONTACT_HINTS):
            seen.add(candidate)
            candidates.append(candidate)
        if len(candidates) >= MAX_PAGES_TO_SCAN:
            break
    return candidates

def extract_name_heuristic(soup, url):
    try:
        domain = urlparse(url).netloc.replace('www.', '').split('.')[0].capitalize()
        return f"{domain} Rep"
    except:
        return "Unknown Rep"


def extract_contacts_from_text(text: str, soup: BeautifulSoup) -> tuple[list[str], str]:
    raw_emails = list(set(re.findall(r"[a-zA-Z0-9.\-+_]+@[a-zA-Z0-9.\-+_]+\.[a-zA-Z]+", text)))
    for mailto in soup.select("a[href^='mailto:']"):
        href = mailto.get("href", "").replace("mailto:", "").strip()
        if href:
            raw_emails.append(href)
    emails = sorted(set(e for e in raw_emails if not e.endswith((".png", ".jpg", ".jpeg", ".gif"))))

    phones = list(set(re.findall(r"[\+\(]?[1-9][0-9 .\-\(\)]{8,14}[0-9]", text)))
    clean_phones = sorted(
        p.strip() for p in phones if len(p.strip()) > 7 and not p.strip().startswith("202")
    )
    return emails, (clean_phones[0] if clean_phones else "")

def scrape_leads(url: str):
    """
    Discovers public crawlable pages and extracts contact details from them.
    This does not bypass access controls or anti-bot protections.
    """
    try:
        normalized_url = normalize_url(url)
        parsed = urlparse(normalized_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        robots_info = parse_robots(base_url)

        if "/" in robots_info["disallow_rules"]:
            return {
                "status": "error",
                "message": "This site disallows crawling in robots.txt.",
                "leads": [],
                "discovery": robots_info,
            }

        response = fetch_text(normalized_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        contact_name = extract_name_heuristic(soup, normalized_url)

        candidate_pages = collect_candidate_pages(
            response.url,
            soup,
            urlparse(response.url).netloc,
            robots_info["disallow_rules"],
        )
        sitemap_pages = collect_sitemap_urls(
            robots_info["sitemaps"],
            urlparse(response.url).netloc,
            robots_info["disallow_rules"],
        )

        for sitemap_page in sitemap_pages:
            if sitemap_page not in candidate_pages and len(candidate_pages) < MAX_PAGES_TO_SCAN:
                candidate_pages.append(sitemap_page)

        scanned_pages = []
        emails = set()
        phone_str = ""
        for page_url in candidate_pages[:MAX_PAGES_TO_SCAN]:
            try:
                page_response = fetch_text(page_url)
            except Exception:
                continue
            page_soup = BeautifulSoup(page_response.text, "html.parser")
            page_text = page_soup.get_text(separator=" ")
            page_emails, page_phone = extract_contacts_from_text(page_text, page_soup)
            scanned_pages.append(page_response.url)
            emails.update(page_emails)
            if not phone_str and page_phone:
                phone_str = page_phone

        results = []
        if not emails:
            if phone_str:
                results.append({
                    "source": normalized_url,
                    "contact_name": contact_name,
                    "email": "not_found",
                    "phone": phone_str,
                })
        else:
            for email in sorted(emails):
                results.append({
                    "source": normalized_url,
                    "contact_name": contact_name,
                    "email": email,
                    "phone": phone_str,
                })

        return {
            "status": "success",
            "leads": results,
            "discovery": {
                **robots_info,
                "requested_url": normalized_url,
                "scanned_pages": scanned_pages,
                "sitemap_pages_found": sitemap_pages[:10],
            },
        }

    except Exception as e:
        return {"status": "error", "message": str(e), "leads": [], "discovery": {}}
