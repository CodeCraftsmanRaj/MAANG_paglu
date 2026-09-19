"""Groq (OpenAI-compatible) client: text, JSON mode, and vision OCR for screen capture."""
import json, os

import httpx
from dotenv import load_dotenv

load_dotenv()
URL = "https://api.groq.com/openai/v1/chat/completions"


def enabled():
    return bool(os.getenv("GROQ_API_KEY"))


def chat(messages, model=None, json_mode=False, max_tokens=2000):
    body = {"model": model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(URL, json=body, headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def jchat(system, user):
    return json.loads(chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True))


def ocr(jpeg_b64):
    prompt = ("Transcribe all meaningful text on this screen (documents, code, chat messages, terminals). "
              "Plain text only, no commentary. If there is nothing meaningful, reply NOTHING.")
    content = [{"type": "text", "text": prompt},
               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + jpeg_b64}}]
    return chat([{"role": "user", "content": content}], model=os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"))
