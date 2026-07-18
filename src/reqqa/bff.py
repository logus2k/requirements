"""reqoach BFF — the UI and nothing else.

The analysis engine now lives in the Analyst Agent (:7803). reqoach keeps the
frontend and forwards every analysis call to it, so the browser still talks to a
single origin (no CORS, no frontend changes).

  /                     static frontend (dashboard, editor, coverage, review, …)
  /projects, /jobs, /rules, /catalog, /documents   -> proxied to the Analyst
  /socket.io                                        -> proxied to the Analyst

socket.io: DEPLOYED, nginx routes `/reqoach/socket.io/` straight to the Analyst,
so the browser gets a real WebSocket. LOCALLY there is no nginx, so the polling
transport is proxied here instead — socket.io negotiates that automatically, and
the frontend needs no change in either environment.

The old single-container backend (`orchestration_api.py`) is intentionally left in
place until the decommission phase: switching back is a one-line command change.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_FRONTEND = os.path.join(_REPO, "frontend")
ANALYST_URL = os.environ.get("ANALYST_URL", "http://localhost:7803").rstrip("/")

# Paths the Analyst owns. Everything else is a static asset.
PROXIED = ("projects", "jobs", "rules", "catalog", "documents", "socket.io")
_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1) — and content-length is
# recomputed by the response we build.
_DROP = {"host", "content-length", "transfer-encoding", "connection",
         "keep-alive", "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailer"}

# `content-encoding` must ALSO be dropped from the RESPONSE: the Analyst gzips
# (GZipMiddleware) but httpx transparently decompresses, so `upstream.content` is
# already plain. Forwarding "gzip" makes the browser try to gunzip plain bytes and
# fail with ERR_CONTENT_DECODING_FAILED — which silently breaks every API call.
_DROP_RESPONSE = _DROP | {"content-encoding"}

app = FastAPI(title="reqoach-bff")
_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _client
    # Long timeout: analysis runs stream for minutes; the source-PDF fetch is large.
    _client = httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=10.0))


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client is not None:
        await _client.aclose()


@app.get("/health")
def health() -> dict:
    """The BFF's own liveness. The Analyst's health is at /analyst/health."""
    return {"status": "ok", "role": "bff", "analyst": ANALYST_URL}


@app.get("/analyst/health")
async def analyst_health() -> dict:
    try:
        r = await _client.get(f"{ANALYST_URL}/health")
        return {"reachable": True, "status": r.status_code, "analyst": r.json()}
    except Exception as e:  # noqa: BLE001 — probe, never raises
        return {"reachable": False, "error": f"{type(e).__name__}: {e}"}


async def _forward(request: Request) -> Response:
    """Forward a request to the Analyst verbatim (path, query, method, headers, body)."""
    url = f"{ANALYST_URL}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP}
    body = await request.body()
    try:
        upstream = await _client.request(request.method, url, headers=headers, content=body)
    except httpx.RequestError as e:
        return Response(content=f'{{"detail":"analyst unreachable: {type(e).__name__}"}}',
                        status_code=502, media_type="application/json")

    content = upstream.content
    # socket.io handshake: this BFF proxies only the HTTP polling transport (a
    # WebSocket upgrade needs nginx, which is how it works deployed). If we let the
    # handshake advertise `upgrades:["websocket"]`, the browser tries to upgrade
    # against us, fails, and floods the console. Advertise no upgrades locally so the
    # client simply stays on polling.
    if request.url.path.startswith("/socket.io") and b'"upgrades"' in content:
        content = content.replace(b'"upgrades":["websocket"]', b'"upgrades":[]')

    out = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE}
    return Response(content=content, status_code=upstream.status_code, headers=out)


# Explicit prefix routes, registered BEFORE the static mount so they win; the mount
# would otherwise swallow everything under "/".
for _p in PROXIED:
    app.add_api_route(f"/{_p}", _forward, methods=_METHODS, include_in_schema=False)
    app.add_api_route(f"/{_p}/{{rest:path}}", _forward, methods=_METHODS, include_in_schema=False)

# Static frontend LAST — it is the catch-all.
app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
