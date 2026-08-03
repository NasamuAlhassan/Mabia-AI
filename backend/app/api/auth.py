"""Sign in. Phone plus a four-digit PIN -- what a CHO can use one-handed."""
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import create_token, current_user, hash_pin, verify_pin
from .. import phones

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Hashed once at import, never matches anything. Its only job is to make an
# unregistered number cost the same as a registered one.
_DECOY_HASH = hash_pin("0000")

# A four-digit PIN is 10,000 guesses, which is nothing without a limit -- the
# audit that prompted this landed an account in four requests. Held in process
# memory on purpose: this runs as a single web service, and a Redis dependency
# for a rate limiter on one endpoint is a worse trade than a counter that
# resets on deploy. If this ever runs on more than one instance, the limit
# becomes per-instance and needs moving.
_ATTEMPTS: Dict[str, list] = {}
_WINDOW_SECONDS = 15 * 60
_MAX_ATTEMPTS = 10


def _too_many(key: str) -> Optional[int]:
    """Seconds to wait, or None if this caller may try."""
    now = time.time()
    recent = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_SECONDS]
    _ATTEMPTS[key] = recent
    if len(recent) < _MAX_ATTEMPTS:
        return None
    return int(_WINDOW_SECONDS - (now - recent[0])) + 1


def _record_failure(key: str) -> None:
    _ATTEMPTS.setdefault(key, []).append(time.time())
    # Never let the table grow without bound on a long-running process.
    if len(_ATTEMPTS) > 5000:
        cutoff = time.time() - _WINDOW_SECONDS
        for k in [k for k, v in _ATTEMPTS.items() if not v or v[-1] < cutoff]:
            _ATTEMPTS.pop(k, None)


class LoginIn(BaseModel):
    phone: str
    pin: str


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    # Keyed on the number being attacked rather than the source address: a CHO
    # on a shared mast and an attacker can look identical by IP, and it is the
    # account that needs protecting.
    key = phones.normalise(body.phone) or (body.phone or "").strip()[:32]
    wait = _too_many(key)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts on this number. Try again in {} minutes."
            .format(max(1, wait // 60)),
            headers={"Retry-After": str(wait)})
    # Accept the number however it was typed. A worker signing in at 2am
    # should not have to remember which of four spellings she enrolled with,
    # and a row the startup migration could not rewrite -- because doing so
    # would have collided with another -- keeps its original spelling forever.
    #
    # Every match is checked, not the first. Two rows can legitimately answer
    # to one handset, which is precisely the collision this exists for, and
    # taking .first() meant the second worker's PIN was tested against the
    # first worker's hash and failed: the same permanent lockout, one layer
    # down. This does not weaken anything. A caller still needs the PIN of the
    # account she reaches, and she still only ever reaches her own.
    candidates = (db.query(User)
                    .filter(User.phone.in_(phones.variants(body.phone)))
                    .all())
    matched = [u for u in candidates if verify_pin(body.pin, u.pin_hash)]

    # Always the same work, whether or not the number is registered. The loop
    # ran once per candidate and not at all for an unknown number, so a 401
    # came back in 5 ms for a stranger and 118 ms per matching row -- an
    # unauthenticated oracle that told you which numbers belong to staff and
    # how many accounts each handset carries, which is exactly the list worth
    # attacking.
    if not candidates:
        verify_pin(body.pin, _DECOY_HASH)

    if len(matched) > 1:
        _record_failure(key)
        # Two accounts on one handset with the same PIN. Whichever row the
        # database happened to return first was being signed in -- so a nurse
        # typing her own number and her own PIN could land in an administrator
        # account, with every action then attributed to the wrong worker. Four
        # digits on a shared facility handset makes that collision likely, not
        # exotic. There is no safe way to guess which of them meant to sign in,
        # so neither does.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Two accounts share this number and PIN, so we cannot tell which "
            "is yours. Ask your supervisor to change one of the PINs.")

    user = matched[0] if matched else None
    if user is None:
        _record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "That phone number and PIN do not match.")

    # A success clears the slate, so a worker who mistypes twice and then gets
    # it right is not carrying those attempts around for a quarter of an hour.
    _ATTEMPTS.pop(key, None)
    return {"token": create_token(user.id, user.role), "user": _me(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _me(user)


def _me(user: User):
    return {"id": user.id, "name": user.name, "phone": user.phone,
            "role": user.role, "community": user.community,
            "facility_id": user.facility_id}
