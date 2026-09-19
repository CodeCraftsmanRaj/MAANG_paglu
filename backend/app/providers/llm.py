"""LLM Provider implementations: Groq provider and AWS Bedrock provider."""
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from ..interfaces import Fact, LLMProvider

load_dotenv(".env.local")
load_dotenv(".env")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

TAXONOMY_TAGS = ["backend", "frontend", "database", "deploy", "api", "process"]
STRUCTURE_MODES = ["graph", "allowlist", "denylist", "keyword", "keyvalue", "ruleset", "versioned", "rag"]


def heuristic_classify_structure_mode(project_name: str, sample_text: str = "") -> dict[str, str]:
    """Heuristic rule-based structure mode classification when LLM is not configured or fails."""
    combined = f"{project_name} {sample_text}".lower()

    if any(k in combined for k in ["denylist", "rejected", "forbidden", "anti-pattern", "do not use", "deprecated", "guardrail", "ruled out", "prohibited", "avoid"]):
        return {
            "mode": "denylist",
            "reason": "Contains rejected approaches, forbidden actions, or anti-pattern guardrails."
        }
    if any(k in combined for k in ["rule", "ruleset", "policy", "refund", "threshold", "eligibility", "condition", "if/then", "branching", "escalation"]):
        return {
            "mode": "ruleset",
            "reason": "Contains conditional branching logic, policy rules, or decision thresholds."
        }
    if any(k in combined for k in ["version", "versioned", "pricing", "changelog", "superseded", "temporal", "history", "deprecated in v", "migration"]):
        return {
            "mode": "versioned",
            "reason": "Contains temporal versioning, pricing changes, or evolving specifications."
        }
    if any(k in combined for k in ["key-value", "keyvalue", "config", "env", "environment variable", "port", "endpoint", "parameter", "constant", "settings"]):
        return {
            "mode": "keyvalue",
            "reason": "Contains configuration parameters, environment variables, or key-value pairs."
        }
    if any(k in combined for k in ["allowlist", "secret", "token", "credential", "permission-sensitive", "strictly scoped", "restricted"]):
        return {
            "mode": "allowlist",
            "reason": "Requires strict explicit permission boundaries with zero fuzzy matching."
        }
    if any(k in combined for k in ["error code", "error", "traceback", "literal", "path", "regex", "status code", "keyword"]):
        return {
            "mode": "keyword",
            "reason": "Contains exact technical strings, error codes, or literal identifiers."
        }
    if any(k in combined for k in ["workflow", "pipeline", "process", "sequence", "dependency", "step", "runbook", "checklist", "handoff", "graph"]):
        return {
            "mode": "graph",
            "reason": "Contains multi-step sequence, relational dependencies, or workflow ownership."
        }
    return {
        "mode": "rag",
        "reason": "General narrative knowledge base optimal for hybrid retrieval and LLM synthesis."
    }


def heuristic_extract_facts(text: str, is_process: bool = False, structure_mode: str = "rag") -> list[Fact]:
    """Rule-based fact extraction fallback when LLM is unavailable."""
    import re
    lines = [line.strip() for line in text.split("\n") if line.strip() and not line.strip().startswith("#")]
    facts: list[Fact] = []

    for line in lines:
        lower = line.lower()
        tags = [t for t in TAXONOMY_TAGS if t in lower]
        if not tags:
            tags = ["general"]

        if structure_mode == "keyvalue" or "keyvalue" in structure_mode:
            # Match KEY=VALUE or KEY: VALUE
            m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*[:=]\s*(.+)$", line)
            if m:
                k = m.group(1).strip()
                v = m.group(2).strip()
                facts.append(Fact(text=f"{k}: {v}", key=k, tags=tags))
                continue

        if structure_mode == "ruleset":
            # Match If ... then ... or condition -> outcome
            if "if " in lower and "then" in lower:
                parts = re.split(r"\bthen\b", line, flags=re.IGNORECASE)
                cond = parts[0].replace("if ", "").replace("IF ", "").strip()
                outc = parts[1].strip() if len(parts) > 1 else ""
                facts.append(Fact(text=line, condition=cond, outcome=outc, tags=tags))
                continue
            elif "->" in line:
                parts = line.split("->")
                facts.append(Fact(text=line, condition=parts[0].strip(), outcome=parts[1].strip(), tags=tags))
                continue

        if structure_mode == "denylist":
            # Extract rejection reason
            reason = "Rejected approach / anti-pattern"
            if "because" in lower:
                reason = line.split("because", 1)[1].strip()
            elif "due to" in lower:
                reason = line.split("due to", 1)[1].strip()
            facts.append(Fact(text=line, outcome=reason, tags=tags))
            continue

        if structure_mode == "versioned":
            # Extract key if present
            m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*[:=]\s*(.+)$", line)
            if m:
                k = m.group(1).strip()
                facts.append(Fact(text=line, key=k, tags=tags))
                continue

        if is_process or structure_mode == "graph":
            action = line
            owner = None
            depends_on = None
            if "@" in line:
                owner = line.split("@")[1].split()[0]
            if "after " in lower:
                depends_on = lower.split("after ")[1].split(".")[0]
            facts.append(Fact(text=line, tags=tags, action=action, owner=owner, depends_on=depends_on))
            continue

        facts.append(Fact(text=line, tags=tags))

    return facts


def _src_title(f: dict[str, Any]) -> str:
    src = f.get("source")
    if isinstance(src, dict):
        return src.get("title") or "Knowledge"
    return str(f.get("source_title") or src or "Knowledge")


class GroqLLMProvider(LLMProvider):
    """Groq API provider for fast text, JSON extraction, vision OCR, and RAG Q&A."""

    def __init__(self, api_key: str | None = None, model: str | None = None, vision_model: str | None = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
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

    def classify_structure_mode(self, project_name: str, sample_text: str = "") -> dict[str, str]:
        if not self.enabled():
            return heuristic_classify_structure_mode(project_name, sample_text)
        try:
            system = (
                "You are an AI database architect. Classify the given project name and sample content into exactly one of the 8 retrieval paradigms:\n"
                "1. 'graph': Relationships, dependencies, sequence, ownership, workflows, pipelines.\n"
                "2. 'allowlist': Permission-sensitive, strictly scoped facts, credentials, zero fuzzy match.\n"
                "3. 'denylist': Rejected approaches, forbidden actions, anti-patterns, guardrails against recurrence.\n"
                "4. 'keyword': Literal technical strings, configs, error codes, file paths, log codes.\n"
                "5. 'keyvalue': Key-value lookup, environment variables, service endpoints, port configs, constants.\n"
                "6. 'ruleset': Conditional/branching logic, if/then policies, eligibility criteria, escalation thresholds.\n"
                "7. 'versioned': Temporal knowledge tracking, pricing tiers, API version histories, changelogs, superseded records.\n"
                "8. 'rag': Open-ended narrative docs, general architecture, troubleshooting guides.\n\n"
                "Respond with strictly valid JSON only: {\"mode\": \"graph\"|\"allowlist\"|\"denylist\"|\"keyword\"|\"keyvalue\"|\"ruleset\"|\"versioned\"|\"rag\", \"reason\": \"<concise explanation under 20 words>\"}"
            )
            user_content = f"Project Name: {project_name}\nSample Content:\n{sample_text[:4000]}"
            res = self._jchat(system, user_content)
            mode = str(res.get("mode", "rag")).lower().strip()
            if mode not in STRUCTURE_MODES:
                mode = "rag"
            reason = str(res.get("reason", "Classified via LLM analysis of project scope."))
            return {"mode": mode, "reason": reason}
        except Exception:
            return heuristic_classify_structure_mode(project_name, sample_text)

    def extract_facts(self, text: str, is_process: bool = False, structure_mode: str = "rag") -> list[Fact]:
        if not self.enabled():
            return heuristic_extract_facts(text, is_process=is_process, structure_mode=structure_mode)

        if structure_mode == "keyvalue":
            prompt = (
                "Extract atomic key-value configuration facts from the text. For each item, populate 'key' (the canonical setting/env identifier), "
                "'value' (the value or description), and 'tags'. "
                'Return JSON {"facts":[{"key":str,"value":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "ruleset":
            prompt = (
                "Extract conditional decision rules, policy branches, and escalation thresholds. "
                "For each rule, populate 'condition' (the trigger/if clause), 'outcome' (the result/decision), and 'tags'. "
                'Return JSON {"facts":[{"condition":str,"outcome":str,"text":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "denylist":
            prompt = (
                "Extract rejected approaches, forbidden actions, ruled-out designs, or anti-patterns. "
                "For each item, populate 'text' (the rejected approach/tool/action), 'reason' (why it was rejected or forbidden), and 'tags'. "
                'Return JSON {"facts":[{"text":str,"reason":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "versioned":
            prompt = (
                "Extract temporal/versioned facts (e.g. pricing tiers, API specifications, versioned features). "
                "For each fact, populate 'key' (the topic/feature identifier) and 'text' (the fact description including version/time context if present). "
                'Return JSON {"facts":[{"key":str|null,"text":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif is_process or structure_mode == "graph":
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
            try:
                res = self._jchat(prompt, text[i:i + 6000])
                for f in res.get("facts", []):
                    tags = [t for t in f.get("tags", []) if t in TAXONOMY_TAGS or t == "general"]
                    rels = [[str(x).lower() for x in r] for r in f.get("rels", []) if isinstance(r, list) and len(r) == 3]
                    action = f.get("action")
                    owner = f.get("owner")
                    depends_on = f.get("depends_on")
                    key = f.get("key")
                    condition = f.get("condition")
                    outcome = f.get("outcome") or f.get("reason")
                    raw_text = str(f.get("text", ""))

                    if structure_mode == "keyvalue" and key:
                        val = f.get("value", "")
                        raw_text = f"{key}: {val}" if val else (raw_text or key)

                    if structure_mode == "ruleset" and condition and outcome and not raw_text:
                        raw_text = f"If {condition}, then {outcome}"

                    out.append(
                        Fact(
                            text=raw_text,
                            tags=tags,
                            rels=rels,
                            action=str(action) if action else None,
                            owner=str(owner) if owner else None,
                            depends_on=str(depends_on) if depends_on else None,
                            key=str(key).strip() if key else None,
                            condition=str(condition).strip() if condition else None,
                            outcome=str(outcome).strip() if outcome else None,
                        )
                    )
            except Exception:
                out.extend(heuristic_extract_facts(text[i:i + 6000], is_process=is_process, structure_mode=structure_mode))
        return out

    def infer_needs(self, query: str) -> dict[str, str]:
        if not self.enabled():
            return {}
        try:
            system = (
                "A teammate asks a question. Return JSON {\"needs\":[{\"tag\":str,\"why\":str}]}: the context areas from "
                + ", ".join(TAXONOMY_TAGS) + " needed to answer well, including ones they did not mention "
                "(a deploy question also needs database config). Max 5. Keep 'why' under 12 words."
            )
            res = self._jchat(system, query)
            return {n["tag"]: n.get("why", "") for n in res.get("needs", []) if n.get("tag") in TAXONOMY_TAGS}
        except Exception:
            return {}

    def answer(self, query: str, context: list[dict[str, Any]], is_process: bool = False, structure_mode: str = "rag") -> str:
        if not context:
            if structure_mode == "allowlist":
                return "Not found in your permitted scope."
            if structure_mode == "keyvalue":
                return "Key not found in project configuration."
            if structure_mode == "denylist":
                return "No guardrail violations found for this approach."
            return "I don't have enough context to answer that question."

        # Mode-specific direct answers when LLM is offline or for deterministic modes
        if structure_mode == "keyvalue":
            for f in context:
                if f.get("key") and f.get("key").lower() in query.lower():
                    return f"The value is: {f['text']} [1]"
            first = context[0]
            return f"The value is: {first.get('text', '')} [1]"

        if not self.enabled():
            # Heuristic answer synthesis
            if structure_mode == "ruleset":
                branches = []
                for i, f in enumerate(context):
                    if f.get("condition") and f.get("outcome"):
                        branches.append(f"- Because **{f['condition']}**, the outcome is **{f['outcome']}** [{i + 1}]")
                    else:
                        branches.append(f"- Rule [{i + 1}]: {f['text']}")
                return "Evaluated Decision Branches:\n" + "\n".join(branches)
            if structure_mode == "denylist":
                rejections = []
                for i, f in enumerate(context):
                    rejections.append(f"⚠️ Guardrail Alert: {f['text']} (Reason: {f.get('outcome') or 'Forbidden approach'}) [{i + 1}]")
                return "\n".join(rejections)
            if structure_mode == "versioned":
                active = context[0]
                hist_str = f" (Note: {len(context) - 1} prior versions found)" if len(context) > 1 else ""
                return f"Current active version: {active['text']} [1]{hist_str}"
            if structure_mode == "allowlist":
                return f"Permitted facts in scope:\n" + "\n".join(f"- {f['text']} [{i + 1}]" for i, f in enumerate(context))
            if structure_mode == "keyword":
                return f"Literal search matches:\n" + "\n".join(f"[{i + 1}] {f['text']} (source: {f.get('source', {}).get('title', 'Unknown')})" for i, f in enumerate(context))
            if is_process or structure_mode == "graph":
                steps = [f"Step {i + 1}: {f['text']} [{i + 1}]" for i, f in enumerate(context)]
                return "Execution Checklist:\n" + "\n".join(steps)
            return "\n".join(f"[{i + 1}] {f['text']} (source: {f.get('source', {}).get('title', 'Unknown')})" for i, f in enumerate(context))

        # Full LLM mode-specific answering
        if structure_mode == "ruleset":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (Condition: {f.get('condition') or 'N/A'}, Outcome: {f.get('outcome') or 'N/A'})" for i, f in enumerate(context))
            system = (
                "You are a policy and business rules engine. For the given question/scenario, evaluate the applicable conditional rules from the context "
                "and determine the outcome. Format response with clear decision branches: 'Because [condition], the outcome is [outcome] [citation]'. "
                "Cite every rule with [1], [2], etc."
            )
        elif structure_mode == "denylist":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (Reason: {f.get('outcome') or f.get('reason') or 'Prohibited'})" for i, f in enumerate(context))
            system = (
                "You are an architectural guardrail engine. If the user's query or proposed approach relates to any rejected/forbidden facts in the context, "
                "output: '⚠️ Guardrail Alert: [explanation of why this approach was rejected and what was ruled out] [citation]'. "
                "If no rejected pattern is violated, state: 'No guardrail violations found for this approach.'"
            )
        elif structure_mode == "versioned":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (superseded_by: {f.get('superseded_by')})" for i, f in enumerate(context))
            system = (
                "You are a versioned knowledge engine. Provide the current active version/value for the queried item cited with [1]. "
                "If superseded or historical versions are present in the context, add a note: '(Note: Prior version was [prior] superseded)'."
            )
        elif structure_mode == "allowlist":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']}" for i, f in enumerate(context))
            system = (
                "You are an exact allowlist verification engine. Answer using strictly only the exact permitted facts in the context. "
                "Do not extrapolate or infer anything outside the permitted items. Cite like [1]."
            )
        elif structure_mode == "keyword":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {_src_title(f)})" for i, f in enumerate(context))
            system = "Provide the exact literal technical information from the context. Cite every statement like [1]."
        elif is_process or structure_mode == "graph":
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
                ctx_lines.append(f"[{i + 1}] {f['text']}{extra_str} (source: {_src_title(f)})")
            ctx_str = "\n".join(ctx_lines)
            system = (
                "You are an operational process execution engine. Answer the question by formatting the response "
                "as an ordered execution checklist / runbook rather than generic prose. "
                "For each step, specify:\n"
                "- **Step [N]: [Action]** · Owner: [Role/Owner] · Prerequisite: [Prerequisites/None] [citation]\n"
                "  Description: [Brief procedural detail]\n"
                "Use ONLY the numbered context provided and cite every statement with [1], [2], etc."
            )
        else:
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {_src_title(f)})" for i, f in enumerate(context))
            system = "Answer using ONLY the numbered context and cite like [1]. If it is missing, say so."

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{ctx_str}\n\nQuestion: {query}"},
        ]
        return self._chat(messages)

    def ocr(self, jpeg_b64: str) -> str:
        if not self.enabled():
            return "NOTHING"
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

    def classify_structure_mode(self, project_name: str, sample_text: str = "") -> dict[str, str]:
        if not self.enabled():
            return heuristic_classify_structure_mode(project_name, sample_text)
        try:
            system = (
                "You are an AI database architect. Classify the given project name and sample content into exactly one of the 8 retrieval paradigms:\n"
                "1. 'graph': Relationships, dependencies, sequence, ownership, workflows, pipelines.\n"
                "2. 'allowlist': Permission-sensitive, strictly scoped facts, credentials, zero fuzzy match.\n"
                "3. 'denylist': Rejected approaches, forbidden actions, anti-patterns, guardrails against recurrence.\n"
                "4. 'keyword': Literal technical strings, configs, error codes, file paths, log codes.\n"
                "5. 'keyvalue': Key-value lookup, environment variables, service endpoints, port configs, constants.\n"
                "6. 'ruleset': Conditional/branching logic, if/then policies, eligibility criteria, escalation thresholds.\n"
                "7. 'versioned': Temporal knowledge tracking, pricing tiers, API version histories, changelogs, superseded records.\n"
                "8. 'rag': Open-ended narrative docs, general architecture, troubleshooting guides.\n\n"
                "Respond with strictly valid JSON only: {\"mode\": \"graph\"|\"allowlist\"|\"denylist\"|\"keyword\"|\"keyvalue\"|\"ruleset\"|\"versioned\"|\"rag\", \"reason\": \"<concise explanation under 20 words>\"}"
            )
            raw_ans = self._invoke(
                messages=[{"role": "user", "content": f"Project Name: {project_name}\nSample Content:\n{sample_text[:4000]}"}],
                system=system,
            )
            data = self._parse_json_response(raw_ans)
            mode = str(data.get("mode", "rag")).lower().strip()
            if mode not in STRUCTURE_MODES:
                mode = "rag"
            reason = str(data.get("reason", "Classified via Bedrock LLM analysis of project scope."))
            return {"mode": mode, "reason": reason}
        except Exception:
            return heuristic_classify_structure_mode(project_name, sample_text)

    def extract_facts(self, text: str, is_process: bool = False, structure_mode: str = "rag") -> list[Fact]:
        if not self.enabled():
            return heuristic_extract_facts(text, is_process=is_process, structure_mode=structure_mode)

        if structure_mode == "keyvalue":
            system = (
                "You are a configuration extraction engine. Extract atomic key-value configuration facts from the text. "
                "For each item, populate 'key' (the canonical setting/env identifier), 'value' (the value or description), and 'tags'. "
                "Respond with strictly valid JSON only: "
                '{"facts":[{"key":str,"value":str,"tags":[str]}]}. '
                f"Allowed tags: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "ruleset":
            system = (
                "You are a policy extraction engine. Extract conditional decision rules, policy branches, and escalation thresholds. "
                "For each rule, populate 'condition' (the trigger/if clause), 'outcome' (the result/decision), and 'tags'. "
                "Respond with strictly valid JSON only: "
                '{"facts":[{"condition":str,"outcome":str,"text":str,"tags":[str]}]}. '
                f"Allowed tags: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "denylist":
            system = (
                "You are an anti-pattern guardrail extraction engine. Extract rejected approaches, forbidden actions, or anti-patterns. "
                "For each item, populate 'text' (the rejected approach/tool/action), 'reason' (why it was rejected or forbidden), and 'tags'. "
                "Respond with strictly valid JSON only: "
                '{"facts":[{"text":str,"reason":str,"tags":[str]}]}. '
                f"Allowed tags: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "versioned":
            system = (
                "You are a temporal extraction engine. Extract versioned facts (e.g. pricing tiers, API specifications, versioned features). "
                "For each fact, populate 'key' (the topic/feature identifier) and 'text' (the fact description including version/time context if present). "
                "Respond with strictly valid JSON only: "
                '{"facts":[{"key":str|null,"text":str,"tags":[str]}]}. '
                f"Allowed tags: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif is_process or structure_mode == "graph":
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
            try:
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
                    key = f.get("key")
                    condition = f.get("condition")
                    outcome = f.get("outcome") or f.get("reason")
                    raw_text = str(f.get("text", ""))

                    if structure_mode == "keyvalue" and key:
                        val = f.get("value", "")
                        raw_text = f"{key}: {val}" if val else (raw_text or key)

                    if structure_mode == "ruleset" and condition and outcome and not raw_text:
                        raw_text = f"If {condition}, then {outcome}"

                    out.append(
                        Fact(
                            text=raw_text,
                            tags=tags,
                            rels=rels,
                            action=str(action) if action else None,
                            owner=str(owner) if owner else None,
                            depends_on=str(depends_on) if depends_on else None,
                            key=str(key).strip() if key else None,
                            condition=str(condition).strip() if condition else None,
                            outcome=str(outcome).strip() if outcome else None,
                        )
                    )
            except Exception:
                out.extend(heuristic_extract_facts(chunk_text, is_process=is_process, structure_mode=structure_mode))
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

    def answer(self, query: str, context: list[dict[str, Any]], is_process: bool = False, structure_mode: str = "rag") -> str:
        if not context:
            if structure_mode == "allowlist":
                return "Not found in your permitted scope."
            if structure_mode == "keyvalue":
                return "Key not found in project configuration."
            if structure_mode == "denylist":
                return "No guardrail violations found for this approach."
            return "I don't have enough context to answer that question."

        # Mode-specific direct answers when LLM is offline or for deterministic modes
        if structure_mode == "keyvalue":
            for f in context:
                if f.get("key") and f.get("key").lower() in query.lower():
                    return f"The value is: {f['text']} [1]"
            first = context[0]
            return f"The value is: {first.get('text', '')} [1]"

        if not self.enabled():
            # Heuristic answer synthesis
            if structure_mode == "ruleset":
                branches = []
                for i, f in enumerate(context):
                    if f.get("condition") and f.get("outcome"):
                        branches.append(f"- Because **{f['condition']}**, the outcome is **{f['outcome']}** [{i + 1}]")
                    else:
                        branches.append(f"- Rule [{i + 1}]: {f['text']}")
                return "Evaluated Decision Branches:\n" + "\n".join(branches)
            if structure_mode == "denylist":
                rejections = []
                for i, f in enumerate(context):
                    rejections.append(f"⚠️ Guardrail Alert: {f['text']} (Reason: {f.get('outcome') or 'Forbidden approach'}) [{i + 1}]")
                return "\n".join(rejections)
            if structure_mode == "versioned":
                active = context[0]
                hist_str = f" (Note: {len(context) - 1} prior versions found)" if len(context) > 1 else ""
                return f"Current active version: {active['text']} [1]{hist_str}"
            if structure_mode == "allowlist":
                return f"Permitted facts in scope:\n" + "\n".join(f"- {f['text']} [{i + 1}]" for i, f in enumerate(context))
            if structure_mode == "keyword":
                return f"Literal search matches:\n" + "\n".join(f"[{i + 1}] {f['text']} (source: {f.get('source', {}).get('title', 'Unknown')})" for i, f in enumerate(context))
            if is_process or structure_mode == "graph":
                steps = [f"Step {i + 1}: {f['text']} [{i + 1}]" for i, f in enumerate(context)]
                return "Execution Checklist:\n" + "\n".join(steps)
            return "\n".join(f"[{i + 1}] {f['text']} (source: {f.get('source', {}).get('title', 'Unknown')})" for i, f in enumerate(context))

        # Full Bedrock LLM mode-specific answering
        if structure_mode == "ruleset":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (Condition: {f.get('condition') or 'N/A'}, Outcome: {f.get('outcome') or 'N/A'})" for i, f in enumerate(context))
            system = (
                "You are a policy and business rules engine. For the given question/scenario, evaluate the applicable conditional rules from the context "
                "and determine the outcome. Format response with clear decision branches: 'Because [condition], the outcome is [outcome] [citation]'. "
                "Cite every rule with [1], [2], etc."
            )
        elif structure_mode == "denylist":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (Reason: {f.get('outcome') or f.get('reason') or 'Prohibited'})" for i, f in enumerate(context))
            system = (
                "You are an architectural guardrail engine. If the user's query or proposed approach relates to any rejected/forbidden facts in the context, "
                "output: '⚠️ Guardrail Alert: [explanation of why this approach was rejected and what was ruled out] [citation]'. "
                "If no rejected pattern is violated, state: 'No guardrail violations found for this approach.'"
            )
        elif structure_mode == "versioned":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (superseded_by: {f.get('superseded_by')})" for i, f in enumerate(context))
            system = (
                "You are a versioned knowledge engine. Provide the current active version/value for the queried item cited with [1]. "
                "If superseded or historical versions are present in the context, add a note: '(Note: Prior version was [prior] superseded)'."
            )
        elif structure_mode == "allowlist":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']}" for i, f in enumerate(context))
            system = (
                "You are an exact allowlist verification engine. Answer using strictly only the exact permitted facts in the context. "
                "Do not extrapolate or infer anything outside the permitted items. Cite like [1]."
            )
        elif structure_mode == "keyword":
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {_src_title(f)})" for i, f in enumerate(context))
            system = "Provide the exact literal technical information from the context. Cite every statement like [1]."
        elif is_process or structure_mode == "graph":
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
                ctx_lines.append(f"[{i + 1}] {f['text']}{extra_str} (source: {_src_title(f)})")
            ctx_str = "\n".join(ctx_lines)
            system = (
                "You are an operational process execution engine. Answer the question by formatting the response "
                "as an ordered execution checklist / runbook rather than generic prose. "
                "For each step, specify:\n"
                "- **Step [N]: [Action]** · Owner: [Role/Owner] · Prerequisite: [Prerequisites/None] [citation]\n"
                "  Description: [Brief procedural detail]\n"
                "Use ONLY the numbered context provided and cite every statement with [1], [2], etc."
            )
        else:
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {_src_title(f)})" for i, f in enumerate(context))
            system = "Answer using ONLY the numbered context and cite like [1]. If it is missing, say so."

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


class GeminiLLMProvider(LLMProvider):
    """Google Gemini Flash API provider for text generation, JSON extraction, vision OCR, and RAG Q&A."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        raw_model = model or os.getenv("GEMINI_LLM_MODEL", "gemini-2.5-flash")
        self.model = raw_model.removeprefix("models/")

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _generate(
        self,
        contents: list[dict[str, Any]],
        system_instruction: str | None = None,
        json_mode: bool = False,
    ) -> str:
        if not self.enabled():
            raise RuntimeError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        r = httpx.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"GeminiLLMProvider error: HTTP {r.status_code} - {r.text}")
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"GeminiLLMProvider error: unexpected response format: {data}") from e

    def _jgenerate(self, system: str, user: str) -> dict[str, Any]:
        contents = [{"role": "user", "parts": [{"text": user}]}]
        content = self._generate(contents, system_instruction=system, json_mode=True)
        return json.loads(content)

    def classify_structure_mode(self, project_name: str, sample_text: str = "") -> dict[str, str]:
        if not self.enabled():
            return heuristic_classify_structure_mode(project_name, sample_text)
        try:
            system = (
                "You are an AI database architect. Classify the given project name and sample content into exactly one of the 8 retrieval paradigms:\n"
                "1. 'graph': Relationships, dependencies, sequence, ownership, workflows, pipelines.\n"
                "2. 'allowlist': Permission-sensitive, strictly scoped facts, credentials, zero fuzzy match.\n"
                "3. 'denylist': Rejected approaches, forbidden actions, anti-patterns, guardrails against recurrence.\n"
                "4. 'keyword': Literal technical strings, configs, error codes, file paths, log codes.\n"
                "5. 'keyvalue': Key-value lookup, environment variables, service endpoints, port configs, constants.\n"
                "6. 'ruleset': Conditional/branching logic, if/then policies, eligibility criteria, escalation thresholds.\n"
                "7. 'versioned': Temporal knowledge tracking, pricing tiers, API version histories, changelogs, superseded records.\n"
                "8. 'rag': Open-ended narrative docs, general architecture, troubleshooting guides.\n\n"
                "Respond with strictly valid JSON only: {\"mode\": \"graph\"|\"allowlist\"|\"denylist\"|\"keyword\"|\"keyvalue\"|\"ruleset\"|\"versioned\"|\"rag\", \"reason\": \"<concise explanation under 20 words>\"}"
            )
            user_content = f"Project Name: {project_name}\nSample Content:\n{sample_text[:4000]}"
            res = self._jgenerate(system, user_content)
            mode = str(res.get("mode", "rag")).lower().strip()
            if mode not in STRUCTURE_MODES:
                mode = "rag"
            reason = str(res.get("reason", "Classified via Gemini analysis of project scope."))
            return {"mode": mode, "reason": reason}
        except Exception:
            return heuristic_classify_structure_mode(project_name, sample_text)

    def extract_facts(self, text: str, is_process: bool = False, structure_mode: str = "rag") -> list[Fact]:
        if not self.enabled():
            return heuristic_extract_facts(text, is_process=is_process, structure_mode=structure_mode)

        if structure_mode == "keyvalue":
            prompt = (
                "Extract atomic key-value configuration facts from the text. For each item, populate 'key' (the canonical setting/env identifier), "
                "'value' (the value or description), and 'tags'. "
                'Return JSON {"facts":[{"key":str,"value":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "ruleset":
            prompt = (
                "Extract conditional decision rules, policy branches, and escalation thresholds. "
                "For each rule, populate 'condition' (the trigger/if clause), 'outcome' (the result/decision), and 'tags'. "
                'Return JSON {"facts":[{"condition":str,"outcome":str,"text":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "denylist":
            prompt = (
                "Extract rejected approaches, forbidden actions, ruled-out designs, or anti-patterns. "
                "For each item, populate 'text' (the rejected approach/tool/action), 'reason' (why it was rejected or forbidden), and 'tags'. "
                'Return JSON {"facts":[{"text":str,"reason":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif structure_mode == "versioned":
            prompt = (
                "Extract temporal/versioned facts (e.g. pricing tiers, API specifications, versioned features). "
                "For each fact, populate 'key' (the topic/feature identifier) and 'text' (the fact description including version/time context if present). "
                'Return JSON {"facts":[{"key":str,"text":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        elif is_process or structure_mode == "graph":
            prompt = (
                "Extract atomic procedural actions and relational dependencies from the text. "
                "For each step/fact, populate 'action' (what is done), 'owner' (role/person responsible), and 'depends_on' (prerequisite step/action). "
                'Return JSON {"facts":[{"action":str,"owner":str|null,"depends_on":str|null,"text":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )
        else:
            prompt = (
                "Extract atomic facts from the text. Each fact must be self-contained and verifiable. "
                'Return JSON {"facts":[{"text":str,"tags":[str]}]}. '
                f"Tags come from: {', '.join(TAXONOMY_TAGS)}, general. Max 25 facts."
            )

        try:
            res = self._jgenerate(prompt, text[:8000])
            items = res.get("facts", [])
            facts = []
            for f in items:
                txt = f.get("text") or (f"{f.get('key')}: {f.get('value')}" if f.get("key") else f.get("action", ""))
                if not txt:
                    continue
                facts.append(
                    Fact(
                        text=txt,
                        tags=f.get("tags") or ["general"],
                        action=f.get("action"),
                        owner=f.get("owner"),
                        depends_on=f.get("depends_on"),
                        key=f.get("key"),
                        condition=f.get("condition"),
                        outcome=f.get("outcome") or f.get("reason"),
                    )
                )
            return facts or heuristic_extract_facts(text, is_process=is_process, structure_mode=structure_mode)
        except Exception:
            return heuristic_extract_facts(text, is_process=is_process, structure_mode=structure_mode)

    def infer_needs(self, query: str) -> dict[str, str]:
        if not self.enabled():
            return heuristic_infer_needs(query)
        try:
            system = (
                f"Given a question, infer which knowledge tags from: {TAXONOMY_TAGS} are relevant. "
                'Return JSON object {"inferred": {tag_name: "one sentence explanation"}}. Only include relevant tags.'
            )
            res = self._jgenerate(system, query)
            return res.get("inferred", {})
        except Exception:
            return heuristic_infer_needs(query)

    def answer(
        self,
        query: str,
        context: list[dict[str, Any]],
        is_process: bool = False,
        structure_mode: str = "rag",
    ) -> str:
        if not self.enabled():
            return "LLM integration disabled. GEMINI_API_KEY not configured."

        if structure_mode == "ruleset":
            ctx_lines = [f"[{i + 1}] Condition: {f.get('condition')} -> Outcome: {f.get('outcome')} (source: {_src_title(f)})" for i, f in enumerate(context)]
            ctx_str = "\n".join(ctx_lines)
            system = "You are a policy and rules engine. Evaluate conditional policy thresholds. Cite statements like [1]."
        elif structure_mode == "denylist":
            ctx_lines = [f"[{i + 1}] REJECTED/FORBIDDEN: {f['text']} | Reason: {f.get('outcome', 'Forbidden')} (source: {_src_title(f)})" for i, f in enumerate(context)]
            ctx_str = "\n".join(ctx_lines)
            system = "You are an architectural guardrail monitor. Identify if the query involves a rejected or forbidden approach. Cite statements like [1]."
        elif is_process or structure_mode == "graph":
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
                ctx_lines.append(f"[{i + 1}] {f['text']}{extra_str} (source: {_src_title(f)})")
            ctx_str = "\n".join(ctx_lines)
            system = (
                "You are an operational process execution engine. Answer by formatting the response as an ordered execution checklist / runbook. "
                "Use ONLY the numbered context provided and cite every statement with [1], [2], etc."
            )
        else:
            ctx_str = "\n".join(f"[{i + 1}] {f['text']} (source: {_src_title(f)})" for i, f in enumerate(context))
            system = "Answer using ONLY the numbered context and cite like [1]. If it is missing, say so."

        contents = [{"role": "user", "parts": [{"text": f"Context:\n{ctx_str}\n\nQuestion: {query}"}]}]
        return self._generate(contents, system_instruction=system)

    def ocr(self, jpeg_b64: str) -> str:
        prompt = (
            "Transcribe all meaningful text on this screen (documents, code, chat messages, terminals). "
            "Plain text only, no commentary. If there is nothing meaningful, reply NOTHING."
        )
        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": jpeg_b64,
                        }
                    },
                    {"text": prompt},
                ],
            }
        ]
        return self._generate(contents)


