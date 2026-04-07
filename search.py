import re
import requests
from ddgs import DDGS

def fetch_page_content(url: str, max_chars: int = 2000) -> str:
    try:
        r = requests.get(url, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; dapoAI/1.0)"})
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""

def web_search(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            simplified = " ".join(query.split()[:5])
            with DDGS() as ddgs:
                results = list(ddgs.text(simplified, max_results=max_results))
        if not results:
            return "Tidak ada hasil ditemukan."

        lines = []
        for i, r in enumerate(results, 1):
            entry = f"[{i}] {r['title']}\nSnippet: {r['body']}"
            if i <= 2:
                content = fetch_page_content(r["href"])
                if content:
                    entry += f"\nIsi halaman: {content}"
            entry += f"\nURL: {r['href']}"
            lines.append(entry)
        return "\n\n---\n\n".join(lines)
    except Exception as e:
        return f"Web search error: {e}"
