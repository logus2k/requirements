"""Problem Framing (Coverage stage 0) — see specs/projects_mode/.

Distils a structured, provenance-graded PROBLEM STATEMENT from whatever project
material exists (from a full spec down to a one-line request), plus a soft list of
candidate archetypes and salient coverage domains that later weight the domain-judge
panel. The LLM work is the `problem_framing` preset on agent_server; this module
gathers the input (project doc text + the catalog menus) and calls it.
"""

from __future__ import annotations

import glob
import json
import os

from reqqa.jobs import _ingest
from reqqa.llm.client import AgentServerClient

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CATALOG = os.environ.get("REQQA_CATALOG", os.path.join(_REPO, "catalog"))


def archetype_menu() -> str:
    items = []
    for f in sorted(glob.glob(os.path.join(CATALOG, "project_types", "*.json"))):
        try:
            a = json.load(open(f, encoding="utf-8"))
            items.append(f"- {a['id']}: {a['name']} — {a.get('summary', '')}")
        except (OSError, ValueError, KeyError):
            continue
    return "\n".join(items)


def domain_menu() -> str:
    try:
        d = json.load(open(os.path.join(CATALOG, "domains.json"), encoding="utf-8"))
        return "\n".join(f"- {x['id']}: {x['name']}" for x in d.get("domains", []))
    except (OSError, ValueError):
        return ""


def gather_text(doc_paths: list[str], limit: int = 24000) -> str:
    """Ingest each document to plain text (markdown in-process, binary via the
    ingest service), joined and length-bounded to fit the framing context."""
    parts = []
    for p in doc_paths:
        try:
            parts.append("\n".join(it.text for it in _ingest(p)))
        except Exception:  # noqa: BLE001 — a bad doc shouldn't sink framing
            parts.append("")
    return ("\n\n---\n\n".join(x for x in parts if x))[:limit]


def frame_problem(doc_paths: list[str], user_request: str = "",
                  client: AgentServerClient | None = None) -> dict:
    """Return the structured problem statement (the raw preset output)."""
    client = client or AgentServerClient()
    body = (
        f"ARCHETYPES:\n{archetype_menu()}\n\n"
        f"COVERAGE DOMAINS:\n{domain_menu()}\n\n"
        f"INPUT DOCUMENTS:\n{gather_text(doc_paths) or '(none)'}\n\n"
        f"USER REQUEST:\n{user_request or '(none)'}"
    )
    return client.complete_json("problem_framing", body)


# ---- catalog reads (for the API / UI) ----

def load_domains() -> dict:
    return json.load(open(os.path.join(CATALOG, "domains.json"), encoding="utf-8"))


def load_archetypes() -> list[dict]:
    out = []
    for f in sorted(glob.glob(os.path.join(CATALOG, "project_types", "*.json"))):
        try:
            out.append(json.load(open(f, encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def load_standards() -> list[dict]:
    out = []
    for f in sorted(glob.glob(os.path.join(CATALOG, "standards", "*.json"))):
        try:
            out.append(json.load(open(f, encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out
