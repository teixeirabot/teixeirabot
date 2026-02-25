import secrets
from datetime import datetime, timedelta
from threading import Lock
from fastapi import Header, HTTPException

# Simple in-memory rate limit: 30 req/min per API key
_LIMIT = 30
_WINDOW = timedelta(minutes=1)
_hits: dict[str, list[datetime]] = {}
_lock = Lock()


def issue_api_key() -> str:
    return secrets.token_urlsafe(24)


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    return x_api_key


def check_rate_limit(api_key: str) -> None:
    now = datetime.utcnow()
    cutoff = now - _WINDOW
    with _lock:
        arr = _hits.get(api_key, [])
        arr = [t for t in arr if t > cutoff]
        if len(arr) >= _LIMIT:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        arr.append(now)
        _hits[api_key] = arr
