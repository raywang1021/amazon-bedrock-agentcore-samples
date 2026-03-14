"""Shared utility for fetching and extracting text from web pages."""

import requests


def fetch_page_text(url: str, include_links: bool = False) -> str:
    """Fetch a web page and return its text content.

    Uses trafilatura for clean text extraction if available,
    falls back to simple HTML tag stripping.

    Args:
        url: The full URL to fetch.
        include_links: Whether to preserve links in extracted text (for llms.txt).
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GEOAgent/1.0)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    try:
        import trafilatura
        text = trafilatura.extract(resp.text, include_links=include_links)
        if text:
            return text
    except ImportError:
        pass

    # Fallback: strip HTML tags
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self._skip = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self._skip = True

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript"):
                self._skip = False

        def handle_data(self, data):
            if not self._skip:
                self.parts.append(data)

    extractor = _TextExtractor()
    extractor.feed(resp.text)
    return " ".join(extractor.parts).strip()
