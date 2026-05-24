"""Phase D — tenant-owned client roster.

Replaces the frontend localStorage hack. Every endpoint here is tenant-scoped:
listing returns *only* the caller's tenant's clients; creates land under the
caller's tenant; cross-tenant fetches return 404 (never 403) to avoid leaking
existence.

Role gates:
- GET  /clients         -> advisor+ (any authenticated user in the tenant)
- GET  /clients/{code}  -> advisor+
- POST /clients         -> advisor+ (advisors add the clients they manage)
- DELETE /clients/{code}-> admin/owner (destructive)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.deps import require_role
from app.db import get_db
from app.models_db import ClientRecord, User
from app.schemas import ClientCreateRequest, ClientOut


router = APIRouter(prefix="/clients", tags=["clients"])


_READ_ROLES = ("advisor", "compliance", "admin", "owner")
_WRITE_ROLES = ("advisor", "compliance", "admin", "owner")
_DELETE_ROLES = ("admin", "owner")


def _serialize(row: ClientRecord) -> ClientOut:
    return ClientOut(
        id=row.id,
        client_code=row.client_code,
        display_name=row.display_name,
        household=row.household,
        risk_profile=row.risk_profile,
        jurisdictions=list(row.jurisdictions or []),
        max_single_position_pct=row.max_single_position_pct,
        min_liquid_within_30d_pct=row.min_liquid_within_30d_pct,
        excluded_sectors=list(row.excluded_sectors or []),
        excluded_regions=list(row.excluded_regions or []),
        ips_version=row.ips_version,
        ips_updated_at=row.ips_updated_at.isoformat() if row.ips_updated_at else None,
        aum_eur=row.aum_eur,
        advisor_name=row.advisor_name,
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=list[ClientOut])
def list_clients(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_READ_ROLES)),
) -> list[ClientOut]:
    rows = db.scalars(
        select(ClientRecord)
        .where(ClientRecord.tenant_id == user.tenant_id)
        .order_by(ClientRecord.client_code.asc())
    ).all()
    return [_serialize(row) for row in rows]


@router.get("/{code}", response_model=ClientOut)
def get_client(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_READ_ROLES)),
) -> ClientOut:
    row = db.scalar(
        select(ClientRecord).where(
            ClientRecord.tenant_id == user.tenant_id,
            ClientRecord.client_code == code.upper(),
        )
    )
    if row is None:
        # 404 — never 403 — so cross-tenant probes can't tell whether a
        # client_code exists in some other tenant.
        raise HTTPException(status_code=404, detail="Client not found")
    return _serialize(row)


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_WRITE_ROLES)),
) -> ClientOut:
    existing = db.scalar(
        select(ClientRecord).where(
            ClientRecord.tenant_id == user.tenant_id,
            ClientRecord.client_code == payload.client_code,
        )
    )
    if existing is not None:
        # Conflict, but only within *our* tenant — a different tenant may
        # legitimately use the same client_code.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Client code {payload.client_code} already exists.",
        )

    ips_updated_at = _parse_iso_date(payload.ips_updated_at)
    record = ClientRecord(
        tenant_id=user.tenant_id,
        client_code=payload.client_code,
        display_name=payload.display_name,
        household=payload.household,
        risk_profile=payload.risk_profile,
        jurisdictions=[j.strip().upper() for j in payload.jurisdictions],
        max_single_position_pct=payload.max_single_position_pct,
        min_liquid_within_30d_pct=payload.min_liquid_within_30d_pct,
        excluded_sectors=[s.strip().lower() for s in payload.excluded_sectors],
        excluded_regions=[r.strip().lower() for r in payload.excluded_regions],
        ips_version=payload.ips_version,
        ips_updated_at=ips_updated_at,
        aum_eur=payload.aum_eur,
        advisor_name=payload.advisor_name,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize(record)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_DELETE_ROLES)),
) -> None:
    row = db.scalar(
        select(ClientRecord).where(
            ClientRecord.tenant_id == user.tenant_id,
            ClientRecord.client_code == code.upper(),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(row)
    db.commit()


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Accept "YYYY-MM-DD" as well as full ISO timestamps.
        if len(value) == 10:
            return datetime.fromisoformat(value + "T00:00:00+00:00")
        return datetime.fromisoformat(value)
    except ValueError:
        # Tolerate bad input from the form: store None rather than 400ing.
        return None
