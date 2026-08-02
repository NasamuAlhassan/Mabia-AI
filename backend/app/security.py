"""Authentication.

Deliberately dependency-free: PBKDF2 from the standard library and a hand-rolled
HS256 token. Fewer packages is fewer things that fail to install on a laptop in
Tamale the morning of a demo, and a four-digit PIN does not need bcrypt's cost
so much as it needs to work.
"""
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

_ITERATIONS = 120_000


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _ITERATIONS)
    return "pbkdf2${}${}${}".format(
        _ITERATIONS, base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode())


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(user_id: str, role: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    expiry = dt.datetime.utcnow() + dt.timedelta(hours=settings.jwt_ttl_hours)
    body = _b64url(json.dumps({
        "sub": user_id, "role": role, "exp": int(expiry.timestamp())}).encode())
    signing_input = "{}.{}".format(header, body).encode()
    signature = hmac.new(settings.jwt_secret.encode(), signing_input,
                         hashlib.sha256).digest()
    return "{}.{}.{}".format(header, body, _b64url(signature))


def decode_token(token: str) -> Optional[dict]:
    try:
        header, body, signature = token.split(".")
        signing_input = "{}.{}".format(header, body).encode()
        expected = hmac.new(settings.jwt_secret.encode(), signing_input,
                            hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64url(signature), expected):
            return None
        claims = json.loads(_unb64url(body))
        if claims.get("exp", 0) < dt.datetime.utcnow().timestamp():
            return None
        return claims
    except Exception:
        return None


def current_user(authorization: str = Header(default=""),
                 db: Session = Depends(get_db)) -> User:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    claims = decode_token(authorization.split(" ", 1)[1].strip())
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.get(User, claims["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user
