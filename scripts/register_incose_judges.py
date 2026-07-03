"""Register the INCOSE characteristic-judge presets in agent_server.

Each judge is a COMPLETE static system prompt in incose/judges/<name>.md — no
runtime assembly. The preset name is `incose_<filename>` (e.g. c5_singular ->
incose_c5_singular). Idempotent (create or update). Run:

    python scripts/register_incose_judges.py
"""

from __future__ import annotations

import glob
import os

import httpx

AGENT_SERVER = os.environ.get("AGENT_SERVER_URL", "http://localhost:7701")
JUDGES_DIR = os.path.join(os.path.dirname(__file__), "..", "incose", "judges")

PARAMS = {
    "max_tokens": 4096,          # batch of assessments; must not truncate
    "temperature": 0.1,
    "top_p": 0.9,
    "chat_template_kwargs": {"enable_thinking": False},
}


def register(name: str, system_prompt: str) -> None:
    preset = {
        "name": name,
        "system_prompt": system_prompt,
        "params_override": dict(PARAMS),
        "memory_policy": "none",
    }
    r = httpx.post(f"{AGENT_SERVER}/admin/api/agents", json=preset, timeout=30)
    if r.status_code == 409:
        r = httpx.put(f"{AGENT_SERVER}/admin/api/agents/{name}", json=preset, timeout=30)
    print(f"[{name}] HTTP {r.status_code} {r.text[:80]}")
    r.raise_for_status()


def main() -> None:
    files = sorted(glob.glob(os.path.join(JUDGES_DIR, "*.md")))
    if not files:
        print("no judge prompt files found in", JUDGES_DIR)
        return
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        name = f"incose_{stem}"
        with open(path, encoding="utf-8") as f:
            register(name, f.read())


if __name__ == "__main__":
    main()
