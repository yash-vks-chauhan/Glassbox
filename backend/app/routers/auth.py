"""Auth endpoints — Phase B.

Routers stay thin: parse + validate, call into app.core.auth.service, map
service-layer exceptions to HTTP status. Anything more complex (token
rotation logic, MFA verification, lockout policy) lives in the service.

Note on /auth/invite, /auth/mfa/* — these endpoints still accept the actor
identity in the body because the current_user dependency lands in Phase C.
The route guards (admin-only invite, MFA enrollment scoped to the right
user) are imposed in that phase; for now anyone with a valid tenant_id can
hit them. Tests cover Phase B behaviour; cross-tenant guards are a Phase C
deliverable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth.deps import current_user, require_role
from app.core.auth.passwords import WeakPasswordError
from app.db import get_db
from app.models_db import Tenant, User
from app.schemas import (
    AcceptInviteRequest,
    ForgotPasswordRequest,
    InviteRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MFAChallengeResponse,
    MFAEnrollResponse,
    MFAVerifyRequest,
    MFAVerifyResponse,
    RefreshResponse,
    ResetPasswordRequest,
)


router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_GENERIC_LOGIN_ERROR = "Invalid email, password, or MFA code."


def _set_refresh_cookie(response: Response, *, plaintext: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=plaintext,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/auth",  # cookie only travels with /auth/* requests
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/auth",
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Returns either a LoginResponse (200) or an MFAChallengeResponse (202).
    Routed without `response_model` because the two shapes diverge; the
    explicit return type is captured by the per-case response objects."""
    settings = get_settings()
    try:
        if payload.mfa_token:
            result = auth_service.authenticate_mfa_challenge(
                db,
                mfa_token=payload.mfa_token,
                mfa_code=payload.mfa_code or "",
                ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
        else:
            result = auth_service.authenticate(
                db,
                email=str(payload.email),
                password=payload.password or "",
                tenant_slug=payload.tenant_slug,
                mfa_code=payload.mfa_code,
                ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
    except auth_service.AccountLocked:
        db.commit()
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=_GENERIC_LOGIN_ERROR)
    except auth_service.MFARequired as exc:
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=MFAChallengeResponse(
                status="mfa_required", mfa_token=exc.mfa_token
            ).model_dump(),
        )
    except auth_service.InvalidToken:
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_LOGIN_ERROR)
    except auth_service.MFAEnrollmentRequired:
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=MFAChallengeResponse(
                status="mfa_enrollment_required",
                detail="MFA enrollment is mandatory for this role.",
            ).model_dump(),
        )
    except auth_service.InvalidCredentials:
        db.commit()  # persist failed_login_count + security_event
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_LOGIN_ERROR)

    db.commit()
    body = LoginResponse(
        access_token=result.access_token,
        expires_in=settings.access_token_ttl_seconds,
    )
    response = JSONResponse(status_code=200, content=body.model_dump())
    _set_refresh_cookie(response, plaintext=result.refresh_token)
    return response


@router.post("/refresh")
def refresh(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    presented = request.cookies.get(settings.refresh_cookie_name)
    if not presented:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token.")
    try:
        result = auth_service.refresh_session(
            db,
            presented_refresh=presented,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except auth_service.InvalidToken:
        db.commit()
        err = JSONResponse(status_code=401, content={"detail": "Refresh failed."})
        _clear_refresh_cookie(err)
        return err
    db.commit()
    body = RefreshResponse(
        access_token=result.access_token,
        expires_in=settings.access_token_ttl_seconds,
    )
    response = JSONResponse(status_code=200, content=body.model_dump())
    _set_refresh_cookie(response, plaintext=result.refresh_token)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    presented = request.cookies.get(settings.refresh_cookie_name)
    auth_service.logout(db, presented_refresh=presented)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.post("/forgot", status_code=status.HTTP_200_OK)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Always returns 200 — no email-enumeration oracle."""
    auth_service.request_password_reset(
        db,
        email=payload.email,
        tenant_slug=payload.tenant_slug,
        ip=_client_ip(request),
    )
    db.commit()
    return {"status": "ok"}


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    try:
        auth_service.complete_password_reset(
            db, token=payload.token, new_password=payload.new_password
        )
    except auth_service.InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invite", status_code=status.HTTP_201_CREATED)
def invite(
    payload: InviteRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role("admin", "owner")),
):
    """Admins/owners may invite into their own tenant only."""
    try:
        auth_service.invite_user(
            db,
            tenant_id=actor.tenant_id,
            email=payload.email,
            role=payload.role,
            invited_by_user_id=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    db.commit()
    return {"status": "invited"}


@router.post("/accept-invite", status_code=status.HTTP_201_CREATED)
def accept_invite(
    payload: AcceptInviteRequest,
    db: Session = Depends(get_db),
):
    try:
        user = auth_service.accept_invitation(
            db,
            token=payload.token,
            password=payload.password,
            display_name=payload.display_name,
        )
    except auth_service.InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token.",
        )
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    db.commit()
    return {"status": "created", "user_id": user.id}


@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
def mfa_enroll(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Enroll MFA for the *currently authenticated* user. Self-only."""
    challenge = auth_service.begin_mfa_enrollment(db, user=user)
    db.commit()
    return MFAEnrollResponse(
        secret=challenge.secret, provisioning_uri=challenge.provisioning_uri
    )


@router.post("/mfa/verify", response_model=MFAVerifyResponse)
def mfa_verify(
    payload: MFAVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        recovery = auth_service.complete_mfa_enrollment(db, user=user, code=payload.code)
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code."
        )
    db.commit()
    return MFAVerifyResponse(recovery_codes=recovery)


@router.get("/me", response_model=MeResponse)
def me(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MeResponse:
    tenant = db.get(Tenant, user.tenant_id)
    return MeResponse(
        user_id=user.id,
        tenant_id=user.tenant_id,
        tenant_slug=tenant.slug if tenant else "",
        email=user.email,
        role=user.role,
        mfa_enrolled=user.mfa_enrolled,
    )
