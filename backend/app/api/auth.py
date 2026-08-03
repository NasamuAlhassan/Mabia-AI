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
    # Accept the number however it was typed; a worker signing in at 2am
    # should not have to remember which of four spellings she enrolled with.
    # Both forms. A number the migration could not normalise -- because doing
    # so would have collided with another row -- is still stored as it was
    # written, and looking only for the canonical form meant no spelling of her
    # own number reached her account. She would have been locked out
    # permanently, with the only trace a line on the server's boot log.
    user = (db.query(User)
              .filter(User.phone.in_(phones.variants(body.phone)))
              .first())
    if not user or not verify_pin(body.pin, user.pin_hash):
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
