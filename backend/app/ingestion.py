"""Ingestion: source-agnostic. Each ingestor turns raw input into {title, uri, text}."""
import re
from typing import Callable

import httpx
from bs4 import BeautifulSoup

INGESTORS: dict[str, Callable[[dict], dict]] = {}


def ingestor(kind: str):
    def deco(fn):
        INGESTORS[kind] = fn
        return fn
    return deco


@ingestor("text")
def _text(p):
    if not (p.get("text") or "").strip():
        raise ValueError("text is empty")
    return {"title": p.get("title") or "Pasted text", "uri": None, "text": p["text"]}


@ingestor("url")
def _url(p):
    if not p.get("url"):
        raise ValueError("url is required")
    r = httpx.get(p["url"], follow_redirects=True, timeout=20, headers={"User-Agent": "ContextForge"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header"]):
        t.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else p["url"]
    return {"title": title, "uri": p["url"], "text": soup.get_text("\n")}


def normalize(kind: str, payload: dict) -> dict:
    doc = INGESTORS[kind](payload)
    doc["text"] = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", doc["text"])).strip()
    return doc


def watch(folder, cb, every=10):
    """Automatic ingestion: poll a folder and hand new/changed text files to cb(name, path, text)."""
    import pathlib, threading, time
    seen = {}

    def loop():
        while True:
            for p in pathlib.Path(folder).rglob("*"):
                try:
                    if p.is_file() and p.suffix.lower() in {".md", ".txt", ".json", ".py", ".log"} and seen.get(p) != p.stat().st_mtime:
                        seen[p] = p.stat().st_mtime
                        cb(p.name, str(p), p.read_text(errors="ignore"))
                except Exception as e:
                    print("watch error:", e)
            time.sleep(every)

    threading.Thread(target=loop, daemon=True).start()
