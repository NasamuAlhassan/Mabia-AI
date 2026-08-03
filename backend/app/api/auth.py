"""Sign in. Phone plus a four-digit PIN -- what a CHO can use one-handed."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import create_token, current_user, verify_pin
from .. import phones

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    phone: str
    pin: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
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
    user = next((u for u in candidates if verify_pin(body.pin, u.pin_hash)),
                None)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "That phone number and PIN do not match.")
    return {"token": create_token(user.id, user.role), "user": _me(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _me(user)


def _me(user: User):
    return {"id": user.id, "name": user.name, "phone": user.phone,
            "role": user.role, "community": user.community,
            "facility_id": user.facility_id}
