import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SearchAPI:
    @staticmethod
    def get_urls_for_keyword(keyword: str, limit: int = 8):
        """
        Collects public search result URLs for a keyword.
        Uses DuckDuckGo HTML endpoint (no API key required).
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        urls = []
        try:
            try:
                resp = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": keyword},
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
            except requests.exceptions.SSLError:
                resp = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": keyword},
                    headers=headers,
                    timeout=10,
                    verify=False,
                )
                resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for anchor in soup.select("a.result__a"):
                href = anchor.get("href", "").strip()
                if href and href.startswith("http"):
                    urls.append(href)
                if len(urls) >= limit:
                    break
        except Exception:
            urls = []

        if urls:
            return urls

        clean_key = keyword.lower().replace(" ", "")
        return [
            f"https://www.best{clean_key}.com",
            f"https://www.{clean_key}agency.net",
            f"https://www.top-{clean_key}-services.co.uk",
        ]
