"""Structure Strategy Pattern Implementations for all 8 Modes.
Defines explicit extract, store, retrieve, and format lifecycles for:
- graph
- allowlist
- denylist
- keyword
- keyvalue
- ruleset
- versioned
- rag
"""
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import networkx as nx

from .auth import is_visible


class BaseStructureStrategy(ABC):
    """Abstract base class defining the 4-phase lifecycle for each structure mode."""
    mode_name: str

    @abstractmethod
    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        """Extract mode-specific structured fields from raw fact."""
        ...

    @abstractmethod
    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        """Score fact against query in this mode. Return None to exclude fact from retrieval."""
        ...

    @abstractmethod
    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        """Format structured answer deterministically or via LLM."""
        ...


class GraphStrategy(BaseStructureStrategy):
    mode_name = "graph"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": raw_fact.get("action") or text.split(".")[0],
            "owner": raw_fact.get("owner"),
            "depends_on": raw_fact.get("depends_on"),
        }

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        if not live:
            return 1.0
        graph_ctx = ctx.get("graph")
        score = 0.5  # Base workflow presence score
        if graph_ctx:
            by, dist = graph_ctx
            if by and dist:
                score += max((1.0 / (1.0 + dist[n]) for n in by.get(fact["id"], ()) if n in dist), default=0.0) * 0.6
        q_toks = set(re.findall(r"[a-z0-9]+", query.lower()))
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        score += float(len(q_toks & t_toks)) * 0.3
        return round(score, 3)

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "No procedural steps found for query."

        # 1. Step dependency graph & cycle detection
        G = nx.DiGraph()
        step_by_action = {}
        step_by_id = {}
        all_actions = set()
        dangling_deps = []
        unowned_steps = []

        for f in facts:
            fid = f["id"]
            act = (f.get("action") or f["text"][:30]).strip()
            step_by_id[fid] = f
            step_by_action[act.lower()] = f
            all_actions.add(act.lower())
            G.add_node(fid, action=act, fact=f)
            if not f.get("owner"):
                unowned_steps.append(act)

        for f in facts:
            dep = (f.get("depends_on") or "").strip()
            if dep:
                dep_lower = dep.lower()
                if dep_lower in step_by_action:
                    parent_id = step_by_action[dep_lower]["id"]
                    G.add_edge(parent_id, f["id"])
                else:
                    dangling_deps.append(f"'{f.get('action', f['text'][:20])}' depends on missing '{dep}'")

        # 2. Cycle detection
        cycles = list(nx.simple_cycles(G))
        if cycles:
            ordered_facts = facts
            cycle_warning = f"⚠️ Warning: Circular dependency detected in workflow: {cycles}"
        else:
            cycle_warning = None
            try:
                ordered_ids = list(nx.topological_sort(G))
                ordered_facts = [step_by_id[i] for i in ordered_ids if i in step_by_id]
            except Exception:
                ordered_facts = facts

        lines = ["Execution Runbook Checklist:"]
        if cycle_warning:
            lines.append(cycle_warning)
        if dangling_deps:
            lines.append(f"⚠️ Dangling dependencies: {'; '.join(dangling_deps)}")
        if unowned_steps:
            lines.append(f"⚠️ Unassigned steps: {', '.join(unowned_steps)}")

        for idx, f in enumerate(ordered_facts, 1):
            owner_str = f" [Owner: {f['owner']}]" if f.get("owner") else ""
            dep_str = f" (Depends on: {f['depends_on']})" if f.get("depends_on") else ""
            lines.append(f"Step {idx}: {f['text']}{owner_str}{dep_str} [{idx}]")

        return "\n".join(lines)


class AllowlistStrategy(BaseStructureStrategy):
    mode_name = "allowlist"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        return {}

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        # Exact deterministic keyword match: zero fuzzy vector match
        if not live:
            return 1.0
        q_toks = set(re.findall(r"[a-z0-9]+", query.lower()))
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        if not (q_toks & t_toks):
            return None  # Strict not-found
        return 1.0

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "Not found in your permitted scope."
        items = []
        for idx, f in enumerate(facts, 1):
            src = f.get("source", {})
            items.append(f"[{idx}] {f['text']} (Source: {src.get('title', 'Permitted Record')})")
        return "Permitted Scope Records:\n" + "\n".join(items)


class DenylistStrategy(BaseStructureStrategy):
    mode_name = "denylist"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "rejected",
            "outcome": raw_fact.get("outcome") or raw_fact.get("reason") or "Anti-pattern / prohibited approach",
        }

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        if not live:
            return 1.0
        q_toks = set(re.findall(r"[a-z0-9]+", query.lower()))
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        overlap = len(q_toks & t_toks)
        return round(float(overlap), 3) if overlap > 0 else 0.0

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "No matching guardrails or rejected patterns found."
        lines = ["⚠️ Architecture Guardrails & Prohibited Patterns:"]
        for idx, f in enumerate(facts, 1):
            reason = f.get("outcome") or "Prohibited approach"
            lines.append(f"[{idx}] REJECTED: {f['text']} — Reason: {reason}")
        return "\n".join(lines)


class KeywordStrategy(BaseStructureStrategy):
    mode_name = "keyword"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        return {}

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        if not live:
            return 1.0
        q_toks = set(re.findall(r"[a-z0-9]+", query.lower()))
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        overlap = len(q_toks & t_toks)
        if overlap == 0:
            return None
        return round(float(overlap), 3)

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return f"No exact keyword matches found for '{query}'."
        lines = [f"Keyword Search Matches for '{query}':"]
        for idx, f in enumerate(facts, 1):
            lines.append(f"[{idx}] {f['text']}")
        return "\n".join(lines)


class KeyvalueStrategy(BaseStructureStrategy):
    mode_name = "keyvalue"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        key = raw_fact.get("key")
        if not key:
            m = re.match(r"^([A-Z0-9_\-\.]+)\s*[:=]\s*(.*)$", text.strip(), re.IGNORECASE)
            if m:
                key = m.group(1).strip()
        return {"key": key}

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        k = (fact.get("key") or "").lower()
        q = query.lower().strip()
        if live and k:
            if k == q or k in q or q in k:
                return 10.0
        q_toks = set(re.findall(r"[a-z0-9]+", q))
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        overlap = len(q_toks & t_toks)
        return float(overlap) if overlap > 0 else (0.0 if not live else None)

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "Key not found in project configuration."
        f = facts[0]
        val = f["text"]
        if f.get("key") and (":" in val or "=" in val):
            val = re.sub(r"^[^:=]+[:=]\s*", "", val).strip()
        return f"{f.get('key', query)}: {val} [1]"


class RulesetStrategy(BaseStructureStrategy):
    mode_name = "ruleset"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        cond = raw_fact.get("condition")
        out = raw_fact.get("outcome")
        prio = raw_fact.get("priority", 0)
        if not cond or not out:
            m = re.search(r"if\s+(.*?)\s+then\s+(.*)", text, re.IGNORECASE)
            if m:
                cond = cond or m.group(1).strip()
                out = out or m.group(2).strip()
        return {
            "condition": cond,
            "outcome": out,
            "priority": int(prio),
        }

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        cond = (fact.get("condition") or "").lower()
        q_toks = set(re.findall(r"[a-z0-9]+", query.lower()))
        cond_toks = set(re.findall(r"[a-z0-9]+", cond)) if cond else set()
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        overlap = len(q_toks & (cond_toks | t_toks))
        priority_bonus = float(fact.get("priority", 0)) * 0.1
        return round(float(overlap) + priority_bonus, 3)

    def evaluate_rule_deterministic(self, fact: dict[str, Any], input_vars: dict[str, Any]) -> dict[str, Any]:
        """Deterministic evaluation of structured rule conditions without LLM.
        Supports operators: ==, !=, >, <, >=, <=, in, contains.
        """
        cond = fact.get("condition") or ""
        m = re.match(r"^(\w+)\s*(==|!=|>=|<=|>|<|contains|in)\s*(.+)$", cond.strip(), re.IGNORECASE)
        if not m:
            words = [w for w in re.findall(r"\b[a-zA-Z_]\w*\b", cond) if w.lower() not in {"if", "then", "and", "or", "is", "the", "a", "an"}]
            req_var = words[0] if words else "input"
            if req_var not in input_vars:
                return {"status": "missing_var", "variable": req_var}
            val = input_vars[req_var]
            matched = str(val).lower() in cond.lower()
            return {"status": "matched" if matched else "unmatched", "outcome": fact.get("outcome")}

        var_name, op, expected = m.group(1).strip(), m.group(2).strip().lower(), m.group(3).strip().strip("'\"")
        if var_name not in input_vars:
            return {"status": "missing_var", "variable": var_name}

        actual = input_vars[var_name]
        matched = False
        try:
            if expected.replace(".", "", 1).isdigit() and isinstance(actual, (int, float, str)) and str(actual).replace(".", "", 1).isdigit():
                num_actual = float(actual)
                num_expected = float(expected)
                if op in ("==", "="): matched = (num_actual == num_expected)
                elif op == "!=": matched = (num_actual != num_expected)
                elif op == ">": matched = (num_actual > num_expected)
                elif op == "<": matched = (num_actual < num_expected)
                elif op == ">=": matched = (num_actual >= num_expected)
                elif op == "<=": matched = (num_actual <= num_expected)
            else:
                str_act = str(actual).lower()
                str_exp = str(expected).lower()
                if op in ("==", "="): matched = (str_act == str_exp)
                elif op == "!=": matched = (str_act != str_exp)
                elif op == "contains": matched = (str_exp in str_act)
                elif op == "in": matched = (str_act in str_exp)
        except Exception:
            matched = False

        return {"status": "matched" if matched else "unmatched", "outcome": fact.get("outcome"), "variable": var_name}

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "No applicable rules found for context."

        input_vars = {}
        for pair in re.findall(r"(\w+)\s*[:=]\s*([^\s,]+)", query):
            input_vars[pair[0]] = pair[1]

        sorted_facts = sorted(facts, key=lambda f: f.get("priority", 0), reverse=True)

        conflicts = []
        seen_conds = {}
        for f in sorted_facts:
            c = (f.get("condition") or "").lower().strip()
            if c:
                if c in seen_conds and seen_conds[c]["outcome"] != f.get("outcome"):
                    conflicts.append(f"Rule #{f['id']} conflicts with Rule #{seen_conds[c]['id']} on condition '{c}'")
                seen_conds[c] = f

        missing_vars = set()
        matched_branches = []

        for idx, f in enumerate(sorted_facts, 1):
            eval_res = self.evaluate_rule_deterministic(f, input_vars)
            if eval_res["status"] == "missing_var":
                missing_vars.add(eval_res["variable"])
            elif eval_res["status"] == "matched":
                matched_branches.append((idx, f, eval_res["outcome"]))

        lines = ["Evaluated Decision Branches:"]
        if conflicts:
            lines.append(f"⚠️ Conflict Warning: {'; '.join(conflicts)}")

        if matched_branches:
            for idx, f, out in matched_branches:
                lines.append(f"Branch {idx}: IF {f.get('condition')} THEN {out} (Priority: {f.get('priority', 0)}) [{idx}]")
            return "\n".join(lines)

        if missing_vars:
            return f"Missing required variable(s) for rule evaluation: {', '.join(sorted(missing_vars))}. Please provide: {', '.join(sorted(missing_vars))}."

        for idx, f in enumerate(sorted_facts, 1):
            lines.append(f"Rule {idx}: IF {f.get('condition', 'Match')} THEN {f.get('outcome', f['text'])} [{idx}]")
        return "\n".join(lines)


class VersionedStrategy(BaseStructureStrategy):
    mode_name = "versioned"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        key = raw_fact.get("key")
        if not key:
            m = re.match(r"^([A-Z0-9_\-\.]+)\s*[:=]\s*(.*)$", text.strip(), re.IGNORECASE)
            if m:
                key = m.group(1).strip()
        valid_from = raw_fact.get("valid_from") or time.time()
        valid_to = raw_fact.get("valid_to")
        return {
            "key": key,
            "valid_from": float(valid_from),
            "valid_to": float(valid_to) if valid_to else None,
        }

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        k = (fact.get("key") or "").lower()
        q = query.lower().strip()
        if live and k and (k == q or k in q or q in k):
            return 10.0
        q_toks = set(re.findall(r"[a-z0-9]+", q))
        t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
        overlap = len(q_toks & t_toks)
        return float(overlap) if overlap > 0 else (0.0 if not live else None)

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "No version history or active record found."
        active = [f for f in facts if f.get("superseded_by") is None]
        superseded = [f for f in facts if f.get("superseded_by") is not None]

        lines = ["Versioned Knowledge Lineage:"]
        if active:
            lines.append(f"CURRENT (ACTIVE): {active[0]['text']} [1]")
        for idx, s in enumerate(superseded, 2):
            lines.append(f"HISTORICAL (SUPERSEDED by #{s['superseded_by']}): {s['text']} [{idx}]")
        return "\n".join(lines)


class RagStrategy(BaseStructureStrategy):
    mode_name = "rag"

    def extract_fields(self, text: str, raw_fact: dict[str, Any]) -> dict[str, Any]:
        return {}

    def score_fact(self, query: str, fact: dict[str, Any], ctx: dict[str, Any], live: bool) -> float | None:
        if not live:
            return 0.0
        score = 0.0
        flat_ctx = ctx.get("flat")
        vec_ctx = ctx.get("vector")
        if vec_ctx and fact["id"] in vec_ctx[1]:
            q_vec, vecs = vec_ctx
            doc_vec = vecs[fact["id"]]
            if len(q_vec) == len(doc_vec):
                score += float(q_vec @ doc_vec) * 1.0
        if flat_ctx:
            q_toks = set(re.findall(r"[a-z0-9]+", query.lower()))
            t_toks = set(re.findall(r"[a-z0-9]+", fact["text"].lower()))
            score += float(len(q_toks & t_toks)) * 0.15
        return round(score, 3)

    def format_answer(self, query: str, facts: list[dict[str, Any]], llm_provider: Any = None) -> str:
        if not facts:
            return "No relevant facts found for query."
        if llm_provider and llm_provider.enabled():
            return llm_provider.answer(query, facts, is_process=False, structure_mode="rag")
        lines = ["Knowledge Synthesis:"]
        for idx, f in enumerate(facts[:5], 1):
            lines.append(f"- {f['text']} [{idx}]")
        return "\n".join(lines)


STRATEGIES: dict[str, BaseStructureStrategy] = {
    "graph": GraphStrategy(),
    "allowlist": AllowlistStrategy(),
    "denylist": DenylistStrategy(),
    "keyword": KeywordStrategy(),
    "keyvalue": KeyvalueStrategy(),
    "ruleset": RulesetStrategy(),
    "versioned": VersionedStrategy(),
    "rag": RagStrategy(),
}


def get_strategy(structure_mode: str | None) -> BaseStructureStrategy:
    """Retrieve strategy instance for the given mode, defaulting to RAG."""
    return STRATEGIES.get(structure_mode or "rag", STRATEGIES["rag"])
