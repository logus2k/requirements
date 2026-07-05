"""Build the self-contained frontend/preview.html for the Artifact.

index.html itself is the MULTI-document container entry (app.js fetches
data/index.json). The Artifact must be self-contained (its CSP blocks fetch),
so here we inline echarts + app.js AND inject one document's data as an inline
`window.SCORECARD` — which flips app.js into single-document mode and hides the
picker. Pure local string substitution — no network, no model. Run:

    python scripts/build_preview.py [data/scorecard.js]
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
FE = os.path.join(HERE, "..", "frontend")

# The scorecard to bake into the Artifact. `data/scorecard.js` already assigns
# `window.SCORECARD = {...}`; override on the command line if desired.
DATA_JS = sys.argv[1] if len(sys.argv) > 1 else "data/scorecard.js"


def _read(rel: str) -> str:
    with open(os.path.join(FE, rel), encoding="utf-8") as f:
        return f.read()


def _inline(html: str, body: str, tag: str) -> str:
    if tag not in html:
        raise SystemExit(f"tag not found in index.html: {tag}")
    # split guard: an inlined script must not contain a literal </script>
    return html.replace(tag, f"<script>\n{body.replace('</script>', '<\\/script>')}\n</script>")


def main() -> None:
    html = _read("index.html")
    html = _inline(html, _read("vendor/echarts.min.js"), '<script src="vendor/echarts.min.js"></script>')
    # Inject the data inline immediately before app.js (so window.SCORECARD is
    # defined when app.js boots), then inline app.js in place.
    app_tag = '<script src="js/app.js"></script>'
    if app_tag not in html:
        raise SystemExit(f"tag not found in index.html: {app_tag}")
    data_then_app = (
        f"<script>\n{_read(DATA_JS).replace('</script>', '<\\/script>')}\n</script>\n"
        f"<script>\n{_read('js/app.js').replace('</script>', '<\\/script>')}\n</script>"
    )
    html = html.replace(app_tag, data_then_app)
    # preview.html is the Artifact SOURCE: the publish step wraps it in its own
    # <html>/<head>/<body>, so we emit body-content only (from <style> onward,
    # with the document-wrapper tags stripped) — never a full standalone doc, or
    # it would double-wrap. This matches the original preview.html shape.
    html = html[html.index("<style>"):]
    for tok in ("</head>", "<body>", "</body>", "</html>"):
        html = html.replace(tok + "\n", "").replace(tok, "")
    out = os.path.join(FE, "preview.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out} ({os.path.getsize(out):,} bytes)")


if __name__ == "__main__":
    main()
