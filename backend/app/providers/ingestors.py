"""Ingestor implementations for normalizing raw sources."""
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ..interfaces import Ingestor, NormalizedDocument


def _clean_text(raw: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", raw.strip())).strip()


class TextIngestor(Ingestor):
    """Normalizes pasted raw text without extraction logic."""

    def normalize(self, raw_input: Any, **kwargs: Any) -> NormalizedDocument:
        if isinstance(raw_input, dict):
            text = raw_input.get("text") or ""
            title = raw_input.get("title") or "Pasted text"
            uri = raw_input.get("uri")
            metadata = raw_input.get("metadata") or {}
        elif isinstance(raw_input, str):
            text = raw_input
            title = kwargs.get("title") or "Pasted text"
            uri = kwargs.get("uri")
            metadata = kwargs.get("metadata") or {}
        else:
            raise ValueError(f"Unsupported raw_input type for TextIngestor: {type(raw_input)}")

        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text is empty")

        return NormalizedDocument(
            text=_clean_text(clean_text),
            title=title,
            source_kind="text",
            source_uri=uri,
            metadata=metadata,
        )


class URLIngestor(Ingestor):
    """Fetches and normalizes HTML web pages into NormalizedDocument."""

    def normalize(self, raw_input: Any, **kwargs: Any) -> NormalizedDocument:
        if isinstance(raw_input, dict):
            url = raw_input.get("url") or ""
            custom_title = raw_input.get("title")
            metadata = raw_input.get("metadata") or {}
            html_content = raw_input.get("html")  # Optional pre-fetched HTML for tests/caching
        elif isinstance(raw_input, str):
            url = raw_input
            custom_title = kwargs.get("title")
            metadata = kwargs.get("metadata") or {}
            html_content = kwargs.get("html")
        else:
            raise ValueError(f"Unsupported raw_input type for URLIngestor: {type(raw_input)}")

        if not url and not html_content:
            raise ValueError("url is required")

        if html_content:
            html = html_content
        else:
            r = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": "ContextForge"})
            r.raise_for_status()
            html = r.text

        soup = BeautifulSoup(html, "html.parser")
        for tag_elem in soup(["script", "style", "nav", "footer", "header"]):
            tag_elem.decompose()

        page_title = custom_title or (soup.title.string.strip() if soup.title and soup.title.string else url)
        page_text = _clean_text(soup.get_text("\n"))

        if not page_text:
            raise ValueError(f"No meaningful text content extracted from URL: {url}")

        return NormalizedDocument(
            text=page_text,
            title=page_title,
            source_kind="url",
            source_uri=url,
            metadata=metadata,
        )
