"""Register (or update) the requirements-project agent presets in agent_server.

Idempotent: creates the preset, or updates it if it already exists. Uses the
admin API (no restart). Run from the host:

    python scripts/register_agents.py
"""

from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from reqqa.segment.prompts import (
    IDENTIFIER_AGENT_NAME,
    IDENTIFIER_SYSTEM_PROMPT,
    JUDGE_AGENT_NAME,
    JUDGE_SYSTEM_PROMPT,
    REFINER_AGENT_NAME,
    REFINER_SYSTEM_PROMPT,
)

AGENT_SERVER = os.environ.get("AGENT_SERVER_URL", "http://localhost:7701")

# 64K is TOTAL context (input + output). A chunk is ~1-2K tokens of input + a
# small system prompt, so nearly the whole window is free for output. max_tokens
# is only a ceiling (the model stops when the JSON is done), so we set it
# generously — truncation, not budget, is the real risk. 1200 was the bug that
# cut dense chunks mid-string.
_COMMON_PARAMS = {
    "max_tokens": 8192,
    "temperature": 0.1,
    "top_p": 0.9,
    "chat_template_kwargs": {"enable_thinking": False},
}

PRESETS = [
    {
        "name": IDENTIFIER_AGENT_NAME,
        "system_prompt": IDENTIFIER_SYSTEM_PROMPT,
        "params_override": dict(_COMMON_PARAMS),
        "memory_policy": "none",
    },
    {
        "name": JUDGE_AGENT_NAME,
        "system_prompt": JUDGE_SYSTEM_PROMPT,
        "params_override": dict(_COMMON_PARAMS),
        "memory_policy": "none",
    },
    {
        "name": REFINER_AGENT_NAME,
        "system_prompt": REFINER_SYSTEM_PROMPT,
        "params_override": dict(_COMMON_PARAMS),
        "memory_policy": "none",
    },
]


def register(preset: dict) -> None:
    name = preset["name"]
    r = httpx.post(f"{AGENT_SERVER}/admin/api/agents", json=preset, timeout=30)
    if r.status_code == 409:
        r = httpx.put(f"{AGENT_SERVER}/admin/api/agents/{name}", json=preset, timeout=30)
        print(f"[{name}] updated: HTTP {r.status_code} {r.text[:120]}")
    else:
        print(f"[{name}] created: HTTP {r.status_code} {r.text[:120]}")
    r.raise_for_status()


if __name__ == "__main__":
    for p in PRESETS:
        register(p)
