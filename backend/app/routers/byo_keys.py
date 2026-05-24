"""Phase E — encrypted BYO key store.

Previous behaviour: ``/ask`` accepted a ``byo_key`` field on every request,
the API hot-pathed it into the LLM call, and the key was kicking around in
process memory + logs. That's the wrong shape for production: the operator
has no idea who handed us what, and a single mis-redaction leaks the key.

New behaviour: a user POSTs their key once to ``/users/me/byo-keys``. We
encrypt it under ``APP_ENCRYPTION_KEY`` (AES-GCM, random nonce, AAD bound
to the user_id) and store the ciphertext + the last 4 chars of the
plaintext for display. The plaintext is never returned again. ``/ask``
loads + decrypts the active key for the caller on demand.

Endpoints:

- ``GET    /users/me/byo-keys``     — list this user's keys (metadata only).
- ``POST   /users/me/byo-keys``     — upsert a key for a given provider.
- ``DELETE /users/me/byo-keys/{provider}`` — drop a key.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.deps import current_user
from app.core.security.encryption import EncryptionError, encrypt, safe_last4
from app.db import get_db
from app.models_db import ByoKey, User


router = APIRouter(prefix="/users/me/byo-keys", tags=["byo-keys"])


class ByoKeyCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9._-]+$")
    api_key: str = Field(min_length=8, max_length=512)


class ByoKeyOut(BaseModel):
    provider: str
    last4: str | None
    kid: str
    created_at: str


def _serialize(row: ByoKey) -> ByoKeyOut:
    return ByoKeyOut(
        provider=row.provider,
        last4=row.last4,
        kid=row.key_kid,
        created_at=row.created_at.isoformat(),
    )


def _aad_for(user_id: str) -> bytes:
    return f"byo_key:{user_id}".encode("utf-8")


@router.get("", response_model=list[ByoKeyOut])
def list_byo_keys(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ByoKeyOut]:
    rows = db.scalars(
        select(ByoKey).where(ByoKey.user_id == user.id).order_by(ByoKey.provider.asc())
    ).all()
    return [_serialize(row) for row in rows]


@router.post("", response_model=ByoKeyOut, status_code=status.HTTP_201_CREATED)
def upsert_byo_key(
    payload: ByoKeyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ByoKeyOut:
    provider = payload.provider.strip().lower()
    blob = encrypt(payload.api_key, aad=_aad_for(user.id))
    row = db.scalar(
        select(ByoKey).where(ByoKey.user_id == user.id, ByoKey.provider == provider)
    )
    if row is None:
        row = ByoKey(
            user_id=user.id,
            provider=provider,
            encrypted_key=blob.ciphertext_b64,
            key_kid=blob.kid,
            last4=safe_last4(payload.api_key),
        )
        db.add(row)
    else:
        row.encrypted_key = blob.ciphertext_b64
        row.key_kid = blob.kid
        row.last4 = safe_last4(payload.api_key)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_byo_key(
    provider: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    row = db.scalar(
        select(ByoKey).where(
            ByoKey.user_id == user.id, ByoKey.provider == provider.lower()
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="BYO key not found")
    db.delete(row)
    db.commit()


def load_byo_key_for_user(
    db: Session, *, user_id: str, provider: str
) -> str | None:
    """Server-side helper: decrypt + return the active BYO key. Returns None
    when the user hasn't enrolled one. Raises EncryptionError if the row is
    corrupt (caller should refuse + log)."""
    from app.core.security.encryption import decrypt

    row = db.scalar(
        select(ByoKey).where(
            ByoKey.user_id == user_id, ByoKey.provider == provider.lower()
        )
    )
    if row is None:
        return None
    try:
        return decrypt(row.encrypted_key, aad=_aad_for(user_id))
    except EncryptionError:
        # Don't 500 the caller — let them fall through to the platform model.
        return None
