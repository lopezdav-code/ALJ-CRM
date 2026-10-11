"""HTTP helpers shared by the API routers."""

import hashlib
import json
from typing import Any

from fastapi import Request
from fastapi.responses import Response

# Member and competition data must not be kept in the browser's HTTP cache (personal data),
# so responses are never stored: the page keeps the last body in memory and sends
# If-None-Match itself, which makes an unchanged poll a cheap 304.
NO_STORE = "no-store"


def _etag_matches(header: str, etag: str) -> bool:
    candidates = [c.strip() for c in (header or "").split(",")]
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


def json_with_etag(request: Request, payload: Any) -> Response:
    """JSON response with a strong ETag (hash of the body); 304 when the client already has it."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    etag = '"' + hashlib.sha1(body).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": NO_STORE}
    if _etag_matches(request.headers.get("if-none-match", ""), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
