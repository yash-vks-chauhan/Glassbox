"""Phase F — tenant-admin user management.

Powers the "Users" card on the admin tab in the frontend. Strictly
tenant-scoped: an admin/owner can list, role-change, or revoke users only
in their own tenant. Owners cannot be demoted by themselves (single-owner
guard), but admins can be demoted as long as one owner remains.

Surface:

- ``GET    /admin/users``            — list everyone in the tenant
- ``PATCH  /admin/users/{user_id}``  — change role
- ``DELETE /admin/users/{user_id}``  — soft-revoke (we delete refresh
  tokens and overwrite password_hash with a value that can never validate;
  decisions remain attributable). Hard-delete would break the audit chain.
- ``POST   /admin/users/{user_id}/sessions/revoke`` — log this user out of
  every device.
- ``GET    /admin/users/invitations`` — list pending invites in the tenant.
- ``DELETE /admin/users/invitations/{invite_id}`` — cancel an unaccepted
  invite (e.g. wrong email).

All endpoints are admin/owner only. Role changes that would leave the
tenant without an owner return 400.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.auth.deps import require_role
from app.core.auth.service import VALID_ROLES
from app.core.security.logging import log_security_event
from app.db import get_db
from app.models_db import RefreshToken, User, UserInvitation, utcnow


router = APIRouter(prefix="/admin/users", tags=["admin"])

_ADMIN_ROLES = ("admin", "owner")


class AdminUserOut(BaseModel):
    id: str
    email: str
    role: str
    display_name: str | None
    mfa_enrolled: bool
    email_verified: bool
    last_login_at: str | None
    created_at: str
    locked: bool


class RoleChangeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    role: str = Field(pattern="^(owner|admin|compliance|advisor)$")


class InvitationOut(BaseModel):
    id: str
    email: str
    role: str
    invited_by_user_id: str | None
    expires_at: str
    created_at: str


def _serialize_user(row: User) -> AdminUserOut:
    locked_until = row.locked_until
    locked = bool(
        locked_until
        and (
            locked_until.replace(tzinfo=timezone.utc)
            if locked_until.tzinfo is None
            else locked_until
        )
        > datetime.now(timezone.utc)
    )
    return AdminUserOut(
        id=row.id,
        email=row.email,
        role=row.role,
        display_name=row.display_name,
        mfa_enrolled=row.mfa_enrolled,
        email_verified=row.email_verified,
        last_login_at=row.last_login_at.isoformat() if row.last_login_at else None,
        created_at=row.created_at.isoformat(),
        locked=locked,
    )


def _count_owners(db: Session, *, tenant_id: str, exclude_user_id: str | None = None) -> int:
    stmt = select(User).where(User.tenant_id == tenant_id, User.role == "owner")
    if exclude_user_id:
        stmt = stmt.where(User.id != exclude_user_id)
    return len(db.scalars(stmt).all())


@router.get("", response_model=list[AdminUserOut])
def list_tenant_users(
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(*_ADMIN_ROLES)),
) -> list[AdminUserOut]:
    rows = db.scalars(
        select(User)
        .where(User.tenant_id == actor.tenant_id)
        .order_by(User.role.asc(), User.email.asc())
    ).all()
    return [_serialize_user(r) for r in rows]


@router.patch("/{user_id}", response_model=AdminUserOut)
def change_user_role(
    user_id: str,
    payload: RoleChangeRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(*_ADMIN_ROLES)),
) -> AdminUserOut:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {payload.role}")
    target = db.get(User, user_id)
    if target is None or target.tenant_id != actor.tenant_id:
        # 404 — never 403 — for cross-tenant lookups.
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == actor.id and payload.role != actor.role:
        # Don't let an admin/owner self-demote — they'd lose the ability to
        # undo the change on the next request.
        raise HTTPException(
            status_code=400,
            detail="You cannot change your own role from this screen.",
        )
    if target.role == "owner" and payload.role != "owner":
        if _count_owners(db, tenant_id=actor.tenant_id, exclude_user_id=target.id) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one owner is required.",
            )
    target.role = payload.role
    log_security_event(
        db,
        kind="user_role_changed",
        tenant_id=actor.tenant_id,
        user_id=actor.id,
        metadata={"target_user_id": target.id, "new_role": payload.role},
    )
    db.commit()
    db.refresh(target)
    return _serialize_user(target)


@router.post("/{user_id}/sessions/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(*_ADMIN_ROLES)),
):
    target = db.get(User, user_id)
    if target is None or target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    log_security_event(
        db,
        kind="user_sessions_revoked",
        tenant_id=actor.tenant_id,
        user_id=actor.id,
        metadata={"target_user_id": target.id},
    )
    db.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user(
    user_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(*_ADMIN_ROLES)),
):
    """Soft-revoke: clear sessions and overwrite the password hash with a
    sentinel that can never validate. The user row stays so audit decisions
    remain attributable; restoring access means re-inviting."""
    target = db.get(User, user_id)
    if target is None or target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot revoke yourself.")
    if target.role == "owner":
        if _count_owners(db, tenant_id=actor.tenant_id, exclude_user_id=target.id) == 0:
            raise HTTPException(
                status_code=400, detail="At least one owner is required."
            )
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    # Sentinel hash: starts with a valid argon2 prefix shape but contains a
    # NUL so argon2 verification always fails.
    target.password_hash = "$argon2id$revoked$\x00"
    target.locked_until = datetime.now(timezone.utc).replace(year=9999)
    log_security_event(
        db,
        kind="user_revoked",
        tenant_id=actor.tenant_id,
        user_id=actor.id,
        metadata={"target_user_id": target.id, "target_email": target.email},
    )
    db.commit()


@router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(*_ADMIN_ROLES)),
) -> list[InvitationOut]:
    rows = db.scalars(
        select(UserInvitation)
        .where(
            UserInvitation.tenant_id == actor.tenant_id,
            UserInvitation.accepted_at.is_(None),
        )
        .order_by(UserInvitation.created_at.desc())
    ).all()
    return [
        InvitationOut(
            id=r.id,
            email=r.email,
            role=r.role,
            invited_by_user_id=r.invited_by_user_id,
            expires_at=r.expires_at.isoformat(),
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.delete("/invitations/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invitation(
    invite_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(*_ADMIN_ROLES)),
):
    row = db.get(UserInvitation, invite_id)
    if row is None or row.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if row.accepted_at is not None:
        # Already accepted — cancel is a no-op; return 404 so we don't leak
        # whether the row exists in some accepted state in another tenant.
        raise HTTPException(status_code=404, detail="Invitation not found")
    db.delete(row)
    log_security_event(
        db,
        kind="invitation_cancelled",
        tenant_id=actor.tenant_id,
        user_id=actor.id,
        metadata={"invitation_id": invite_id, "email": row.email},
    )
    db.commit()


class ChangePasswordRequest(BaseModel):
    model_config = {"extra": "forbid"}
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=12)


# Self-service password change lives here rather than auth.py because the
# admin-tab "Users" card is the natural place to learn about it from. The
# endpoint is *not* admin-only; it's user-self.
self_router = APIRouter(prefix="/users/me", tags=["users"])


@self_router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user_arg=Depends(require_role("advisor", "compliance", "admin", "owner")),
):
    # Imported lazily — verify_password lives near hash_password, and pulling
    # it at module load would cycle with auth.service.
    from app.core.auth.passwords import hash_password, verify_password

    user = user_arg
    if not verify_password(payload.current_password, user.password_hash):
        log_security_event(
            db,
            kind="change_password_wrong_current",
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    log_security_event(
        db,
        kind="change_password_success",
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    db.commit()


class SessionOut(BaseModel):
    id: str
    created_at: str
    expires_at: str
    revoked_at: str | None
    user_agent: str | None
    ip: str | None
    is_current: bool


@self_router.get("/sessions", response_model=list[SessionOut])
def list_own_sessions(
    db: Session = Depends(get_db),
    user_arg=Depends(require_role("advisor", "compliance", "admin", "owner")),
) -> list[SessionOut]:
    rows = db.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_arg.id)
        .order_by(RefreshToken.created_at.desc())
    ).all()
    # We can't tell from the access token which refresh token rotated it;
    # mark "is_current" false uniformly. The UI surfaces this honestly.
    return [
        SessionOut(
            id=r.id,
            created_at=r.created_at.isoformat(),
            expires_at=r.expires_at.isoformat(),
            revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
            user_agent=r.user_agent,
            ip=r.ip,
            is_current=False,
        )
        for r in rows
    ]


@self_router.post("/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
def revoke_all_own_sessions(
    db: Session = Depends(get_db),
    user_arg=Depends(require_role("advisor", "compliance", "admin", "owner")),
):
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_arg.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    log_security_event(
        db,
        kind="logout_everywhere",
        tenant_id=user_arg.tenant_id,
        user_id=user_arg.id,
    )
    db.commit()
