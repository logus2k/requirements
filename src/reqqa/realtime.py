"""Real-time single-requirement assessor — socket.io server + editor page.

A thin interactive front-end onto `reqqa.assess`: the client emits the
requirement text (debounced) and receives a streamed assessment back —
deterministic findings immediately, then one characteristic score at a time
(fast-lane first), then an optional reviewer suggestion.

Run:
    PYTHONPATH=src uvicorn reqqa.realtime:asgi --port 7801

Then open http://localhost:7801/ .

Transport is socket.io (python-socketio ASGI). The blocking assessment runs in
a worker thread per request; a per-client generation counter cancels an
in-flight stream as soon as newer text arrives, so only the latest keystroke's
results reach the client.
"""

from __future__ import annotations

import asyncio
import os

import socketio
from fastapi import FastAPI
from fastapi.responses import FileResponse

from reqqa.assess import iter_assessment
from reqqa.llm.client import AgentServerClient

_FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
api = FastAPI(title="reqqa-realtime")

# Latest requested generation per client — bump on each new "assess" so a
# superseded stream stops emitting.
_generation: dict[str, int] = {}
_client = AgentServerClient()


@api.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_FRONTEND, "editor.html"))


@api.get("/vendor/socket.io.min.js")
def socketio_client() -> FileResponse:
    return FileResponse(os.path.join(_FRONTEND, "vendor", "socket.io.min.js"),
                        media_type="application/javascript")


@sio.event
async def connect(sid, environ):
    _generation[sid] = 0


@sio.event
async def disconnect(sid):
    _generation.pop(sid, None)


@sio.event
async def assess(sid, data):
    """Stream an assessment for the given text. `data = {"text": ...,
    "review": bool}`. Superseded as soon as a newer `assess` bumps the gen."""
    text = ((data or {}).get("text") or "").strip()
    review = bool((data or {}).get("review", True))
    gen = _generation.get(sid, 0) + 1
    _generation[sid] = gen

    if len(text) < 12:            # matches verify.MIN_TEXT_LEN — too short to judge
        await sio.emit("idle", {"reason": "too_short"}, to=sid)
        return

    await sio.emit("start", {"gen": gen}, to=sid)

    loop = asyncio.get_running_loop()
    gen_iter = iter_assessment(text, client=_client, review=review)
    _SENTINEL = object()

    def _next():
        try:
            return next(gen_iter)
        except StopIteration:
            return _SENTINEL

    while True:
        # Bail out the moment this stream is superseded by newer text.
        if _generation.get(sid) != gen:
            gen_iter.close()
            return
        event = await loop.run_in_executor(None, _next)
        if event is _SENTINEL:
            break
        if _generation.get(sid) != gen:
            return
        await sio.emit(event["type"], {**event, "gen": gen}, to=sid)


# The ASGI entrypoint: socket.io handles /socket.io/*, FastAPI serves the rest.
asgi = socketio.ASGIApp(sio, other_asgi_app=api)
