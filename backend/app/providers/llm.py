"""LLM Provider implementations: Groq provider and AWS Bedrock provider."""
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from ..interfaces import Fact, LLMProvider

load_dotenv()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

TAXONOMY_TAGS = ["backend", "frontend", "database", "deploy", "api", "process"]


class GroqLLMProvider(LLMProvider):
    """Groq API provider for fast text, JSON extraction, vision OCR, and RAG Q&A."""

    def __init__(self, api_key: str | None = None, model: str | None = None, vision_model: str | None = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.vision_model = vision_model or os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _chat(self, messages: list[dict[str, Any]], model: str | None = None, json_mode: bool = False, max_tokens: int = 2000) -> str:
        if not self.enabled():
            raise RuntimeError("GROQ_API_KEY is not configured")
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = httpx.post(
            GROQ_API_URL,
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _jchat(self, system: str, user: str) -> dict[str, Any]:
        content = self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True)
        return json.loads(content)

    def extract_facts(self, text: str, is_process: bool = False) -> list[Fact]:
        if is_process:
            prompt = (
                "Extract atomic, self-contained facts from the text. Look specifically for procedural language "
                "(who does what, in what order). For each fact, populate: 'action' (the specific task/step executed), "
                "'owner' (role or person responsible), and 'depends_on' (prerequisite step, approval, or condition required first) "
                "when present in the text, otherwise null. "
                'Return JSON {"facts":[{"text":str,"tags":[str],"rels":[[subject,relation,object]],"action":str|null,"owner":str|null,"depends_on":str|null}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Entities in rels are short lowercase names. Max 25 facts."
            )
        else:
            prompt = (
                "Extract atomic, self-contained facts a new teammate or an AI coding assistant would need from the text. "
                'Return JSON {"facts":[{"text":str,"tags":[str],"rels":[[subject,relation,object]]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Entities in rels are short lowercase names. Max 25 facts."
            )
        out: list[Fact] = []
        for i in range(0, min(len(text), 24000), 6000):
            res = self._jchat(prompt, text[i:i + 6000])
            for f in res.get("facts", []):
                tags = [t for t in f.get("tags", []) if t in TAXONOMY_TAGS or t == "general"]
                rels = [[str(x).lower() for x in r] for r in f.get("rels", []) if isinstance(r, list) and len(r) == 3]
                action = f.get("action")
                owner = f.get("owner")
                depends_on = f.get("depends_on")
                out.append(
                    Fact(
                        text=str(f.get("text", "")),
                        tags=tags,
                        rels=rels,
                        action=str(action) if action else None,
                        owner=str(owner) if owner else None,
                        depends_on=str(depends_on) if depends_on else None,
                    )
                )
        return out

    def infer_needs(self, query: str) -> dict[str, str]:
        system = (
            "A teammate asks a question. Return JSON {\"needs\":[{\"tag\":str,\"why\":str}]}: the context areas from "
            + ", ".join(TAXONOMY_TAGS) + " needed to answer well, including ones they did not mention "
            "(a deploy question also needs database config). Max 5. Keep 'why' under 12 words."
        )
        res = self._jchat(system, query)
        return {n["tag"]: n.get("why", "") for n in res.get("needs", []) if n.get("tag") in TAXONOMY_TAGS}

    def answer(self, query: str, context: list[dict[str, Any]], is_process: bool = False) -> str:
        has_process_fields = any(f.get("action") or f.get("owner") or f.get("depends_on") for f in context)
        if is_process or has_process_fields:
            ctx_lines = []
            for i, f in enumerate(context):
                extra = []
                if f.get("action"):
                    extra.append(f"Action: {f['action']}")
                if f.get("owner"):
                    extra.append(f"Owner: {f['owner']}")
                if f.get("depends_on"):
                    extra.append(f"Requires first: {f['depends_on']}")
                extra_str = f" | ({', '.join(extra)})" if extra else ""
                ctx_lines.append(f"[{i + 1}] {f['text']}{extra_str} (source: {f['source']['title']})")
            ctx_str = "\n".join(ctx_lines)
            system = (
                "You are an operational process execution engine. Answer the question by formatting the response "
                "as an ordered execution checklist / runbook rather than generic prose. "
                "For each step, specify:\n"
                "- **Step [N]: [Action]** · Owner: [Role/Owner] · Prerequisite: [Prerequisites/None] [citation]\n"
                "  Description: [Brief procedural detail]\n"
                "Use ONLY the numbered context provided and cite every statement with [1], [2], etc. If information is missing, state it clearly."
            )
        else:
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {f['source']['title']})" for i, f in enumerate(context))
            system = "Answer using ONLY the numbered context and cite like [1]. If it is missing, say so."

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{ctx_str}\n\nQuestion: {query}"},
        ]
        return self._chat(messages)

    def ocr(self, jpeg_b64: str) -> str:
        prompt = (
            "Transcribe all meaningful text on this screen (documents, code, chat messages, terminals). "
            "Plain text only, no commentary. If there is nothing meaningful, reply NOTHING."
        )
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + jpeg_b64}},
        ]
        return self._chat([{"role": "user", "content": content}], model=self.vision_model)


class BedrockLLMProvider(LLMProvider):
    """AWS Bedrock runtime provider for Claude models (extract facts, dynamic intent, RAG, vision)."""

    def __init__(
        self,
        region_name: str | None = None,
        model_id: str | None = None,
    ):
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.model_id = model_id or os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region_name)
        return self._client

    def enabled(self) -> bool:
        try:
            import boto3
            session = boto3.Session(region_name=self.region_name)
            credentials = session.get_credentials()
            return credentials is not None
        except Exception:
            return False

    def _invoke(self, messages: list[dict[str, Any]], system: str | None = None, max_tokens: int = 2000) -> str:
        client = self._get_client()
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "messages": messages,
        }
        if system:
            body["system"] = system

        response = client.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        response_body = json.loads(response["body"].read().decode("utf-8"))
        return response_body["content"][0]["text"]

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        return json.loads(cleaned)

    def extract_facts(self, text: str, is_process: bool = False) -> list[Fact]:
        if is_process:
            system = (
                "You are a knowledge extraction engine. Extract atomic, self-contained facts from the text. "
                "Look specifically for procedural language (who does what, in what order). For each fact, populate: "
                "'action' (the specific task/step executed), 'owner' (role or person responsible), and "
                "'depends_on' (prerequisite step, approval, or condition required first) when present in the text, otherwise null. "
                "Respond with strictly valid JSON only: "
                '{"facts":[{"text":str,"tags":[str],"rels":[[subject,relation,object]],"action":str|null,"owner":str|null,"depends_on":str|null}]}. '
                f"Allowed tags: {', '.join(TAXONOMY_TAGS)}, general. Entities in rels are short lowercase names. Max 25 facts."
            )
        else:
            system = (
                "You are a knowledge extraction engine. Extract atomic, self-contained facts a new teammate or an AI coding "
                "assistant would need from the text. Respond with strictly valid JSON only: "
                '{"facts":[{"text":str,"tags":[str],"rels":[[subject,relation,object]]}]}. '
                f"Allowed tags: {', '.join(TAXONOMY_TAGS)}, general. Entities in rels are short lowercase names. Max 25 facts."
            )
        out: list[Fact] = []
        for i in range(0, min(len(text), 24000), 6000):
            chunk_text = text[i:i + 6000]
            raw_ans = self._invoke(
                messages=[{"role": "user", "content": chunk_text}],
                system=system,
            )
            data = self._parse_json_response(raw_ans)
            for f in data.get("facts", []):
                tags = [t for t in f.get("tags", []) if t in TAXONOMY_TAGS or t == "general"]
                rels = [[str(x).lower() for x in r] for r in f.get("rels", []) if isinstance(r, list) and len(r) == 3]
                action = f.get("action")
                owner = f.get("owner")
                depends_on = f.get("depends_on")
                out.append(
                    Fact(
                        text=str(f.get("text", "")),
                        tags=tags,
                        rels=rels,
                        action=str(action) if action else None,
                        owner=str(owner) if owner else None,
                        depends_on=str(depends_on) if depends_on else None,
                    )
                )
        return out

    def infer_needs(self, query: str) -> dict[str, str]:
        system = (
            "A teammate asks a question. Return strictly JSON {\"needs\":[{\"tag\":str,\"why\":str}]}: the context areas from "
            + ", ".join(TAXONOMY_TAGS) + " needed to answer well, including implicit ones "
            "(e.g. a deploy question also needs database config). Max 5. Keep 'why' under 12 words."
        )
        raw_ans = self._invoke(
            messages=[{"role": "user", "content": query}],
            system=system,
        )
        data = self._parse_json_response(raw_ans)
        return {n["tag"]: n.get("why", "") for n in data.get("needs", []) if n.get("tag") in TAXONOMY_TAGS}

    def answer(self, query: str, context: list[dict[str, Any]], is_process: bool = False) -> str:
        has_process_fields = any(f.get("action") or f.get("owner") or f.get("depends_on") for f in context)
        if is_process or has_process_fields:
            ctx_lines = []
            for i, f in enumerate(context):
                extra = []
                if f.get("action"):
                    extra.append(f"Action: {f['action']}")
                if f.get("owner"):
                    extra.append(f"Owner: {f['owner']}")
                if f.get("depends_on"):
                    extra.append(f"Requires first: {f['depends_on']}")
                extra_str = f" | ({', '.join(extra)})" if extra else ""
                ctx_lines.append(f"[{i + 1}] {f['text']}{extra_str} (source: {f['source']['title']})")
            ctx_str = "\n".join(ctx_lines)
            system = (
                "You are an operational process execution engine. Answer the question by formatting the response "
                "as an ordered execution checklist / runbook rather than generic prose. "
                "For each step, specify:\n"
                "- **Step [N]: [Action]** · Owner: [Role/Owner] · Prerequisite: [Prerequisites/None] [citation]\n"
                "  Description: [Brief procedural detail]\n"
                "Use ONLY the numbered context provided and cite every statement with [1], [2], etc. If information is missing, state it clearly."
            )
        else:
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {f['source']['title']})" for i, f in enumerate(context))
            system = "Answer using ONLY the numbered context and cite like [1]. If the answer is missing from the context, state that clearly."

        return self._invoke(
            messages=[{"role": "user", "content": f"Context:\n{ctx_str}\n\nQuestion: {query}"}],
            system=system,
        )

    def ocr(self, jpeg_b64: str) -> str:
        prompt = (
            "Transcribe all meaningful text on this screen (documents, code, chat messages, terminals). "
            "Plain text only, no commentary. If there is nothing meaningful, reply NOTHING."
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": jpeg_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        return self._invoke(messages=messages)

