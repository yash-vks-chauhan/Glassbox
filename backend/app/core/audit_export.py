"""Audit log filtering and exports (CSV and the PDF "audit binder").

The audit list endpoint and both exports share ``AuditFilters`` and
``filtered_decisions``, so the rows a reviewer sees on screen are exactly
the rows they export.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from fpdf import FPDF
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.security.audit_hash import verify_chain
from app.models_db import (
    Decision,
    DecisionCorrection,
    DecisionReview,
    Escalation,
    Tenant,
    User,
)


LOW_GROUNDING = 0.6
TENANT_WIDE_ROLES = frozenset({"compliance", "admin", "owner"})
CSV_MAX_ROWS = 10_000
PDF_MAX_DECISIONS = 500


@dataclass(frozen=True)
class AuditFilters:
    outcome: str | None = None
    client_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    low_grounding: bool = False
    q: str | None = None

    def describe(self) -> str:
        parts = []
        if self.outcome:
            parts.append(f"outcome = {self.outcome}")
        if self.client_id:
            parts.append(f"client = {self.client_id}")
        if self.since:
            parts.append(f"from {self.since.isoformat()}")
        if self.until:
            parts.append(f"until {self.until.isoformat()}")
        if self.low_grounding:
            parts.append(f"grounding < {int(LOW_GROUNDING * 100)}%")
        if self.q:
            parts.append(f'search "{self.q}"')
        return ", ".join(parts) or "none (all decisions)"


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def filtered_decisions(user: User, filters: AuditFilters) -> Select:
    """Tenant-scoped decisions matching ``filters``; advisors only see their
    own. Newest first."""
    stmt = select(Decision).where(Decision.tenant_id == user.tenant_id)
    if user.role not in TENANT_WIDE_ROLES:
        stmt = stmt.where(Decision.user_id == user.id)
    if filters.outcome:
        stmt = stmt.where(Decision.outcome == filters.outcome)
    if filters.client_id:
        stmt = stmt.where(Decision.client_id == filters.client_id)
    if filters.since:
        stmt = stmt.where(Decision.created_at >= filters.since)
    if filters.until:
        stmt = stmt.where(Decision.created_at < filters.until)
    if filters.low_grounding:
        stmt = stmt.where(Decision.grounding_score < LOW_GROUNDING)
    if filters.q:
        needle = filters.q.strip()
        stmt = stmt.where(
            or_(
                Decision.question.ilike(_like_pattern(needle), escape="\\"),
                Decision.id.startswith(needle, autoescape=True),
            )
        )
    return stmt.order_by(Decision.created_at.desc(), Decision.id.desc())


# ---------------------------------------------------------------------------
# Shared enrichment
# ---------------------------------------------------------------------------


@dataclass
class _DecisionContext:
    asked_by: dict[str, str]
    reviews: dict[str, list[DecisionReview]]
    corrections: dict[str, list[DecisionCorrection]]
    escalations: dict[str, list[Escalation]]


def _context(db: Session, decisions: list[Decision]) -> _DecisionContext:
    ids = [d.id for d in decisions]
    user_ids = {d.user_id for d in decisions if d.user_id}
    asked_by = {
        u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids)))
    } if user_ids else {}

    def grouped(model, *options):
        out: dict[str, list] = {}
        if not ids:
            return out
        stmt = select(model).where(model.decision_id.in_(ids)).order_by(model.created_at.asc())
        for option in options:
            stmt = stmt.options(option)
        for row in db.scalars(stmt):
            out.setdefault(row.decision_id, []).append(row)
        return out

    reviews = grouped(DecisionReview, selectinload(DecisionReview.claim_labels))
    reviewer_ids = {r.reviewer_user_id for rows in reviews.values() for r in rows}
    reviewer_ids -= asked_by.keys()
    if reviewer_ids:
        asked_by.update(
            {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(reviewer_ids)))}
        )
    return _DecisionContext(
        asked_by=asked_by,
        reviews=reviews,
        corrections=grouped(DecisionCorrection),
        escalations=grouped(Escalation, selectinload(Escalation.events)),
    )


def load_for_export(db: Session, stmt: Select) -> list[Decision]:
    return list(
        db.scalars(
            stmt.options(selectinload(Decision.claims), selectinload(Decision.retrieved_chunks))
        )
    )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "decision_id",
    "created_at",
    "asked_by",
    "client_id",
    "outcome",
    "question",
    "final_answer",
    "grounding_score",
    "latency_ms",
    "model_route",
    "claims_kept",
    "claims_dropped",
    "sources",
    "latest_review",
    "corrected_outcome",
    "escalation_status",
    "prev_hash",
    "row_hash",
]


def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formulas (CSV injection): a cell that starts
    with = + - @ or a control character is prefixed with an apostrophe."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def export_csv(db: Session, decisions: list[Decision]) -> str:
    ctx = _context(db, decisions)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for d in decisions:
        reviews = ctx.reviews.get(d.id, [])
        corrections = ctx.corrections.get(d.id, [])
        escalations = ctx.escalations.get(d.id, [])
        sources = sorted({chunk.source_id for chunk in d.retrieved_chunks})
        writer.writerow(
            [
                _csv_safe(value)
                for value in (
                    d.id,
                    d.created_at.isoformat(),
                    ctx.asked_by.get(d.user_id or "", ""),
                    d.client_id or "",
                    d.outcome,
                    d.question,
                    d.final_answer or "",
                    "" if d.grounding_score is None else f"{d.grounding_score:.3f}",
                    d.latency_ms,
                    d.llm_model,
                    sum(1 for c in d.claims if c.kept),
                    sum(1 for c in d.claims if not c.kept),
                    ";".join(sources),
                    reviews[-1].assessment if reviews else "",
                    corrections[-1].corrected_outcome or "" if corrections else "",
                    escalations[-1].status if escalations else "",
                    d.prev_hash or "",
                    d.row_hash or "",
                )
            ]
        )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF audit binder
# ---------------------------------------------------------------------------

# The built-in PDF fonts only cover Latin-1, so map the punctuation and
# symbols the corpus and UI use onto ASCII equivalents.
_PDF_REPLACEMENTS = {
    "—": "-", "–": "-", "·": "-", "•": "-", "…": "...", "’": "'", "‘": "'",
    "“": '"', "”": '"', "€": "EUR", "≤": "<=", "≥": ">=", "→": "->", "⇒": "=>",
    "×": "x", "≈": "~", "✓": "v", "✗": "x",
}


def _pdf_text(value: object) -> str:
    text = "" if value is None else str(value)
    for old, new in _PDF_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


class _Binder(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self._title = title
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(16, 16, 16)
        self.alias_nb_pages()

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, _pdf_text(f"{self._title} - confidential"), align="L")
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="R")
        self.set_text_color(0, 0, 0)

    def heading(self, text: str, size: int = 13) -> None:
        self.set_font("Helvetica", "B", size)
        self.multi_cell(0, 7, _pdf_text(text), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", size=9)

    def label_value(self, label: str, value: object) -> None:
        self.set_font("Helvetica", "B", 9)
        self.cell(40, 5.5, _pdf_text(label))
        self.set_font("Helvetica", size=9)
        self.multi_cell(0, 5.5, _pdf_text(value), new_x="LMARGIN", new_y="NEXT")

    def paragraph(self, text: object, size: int = 9) -> None:
        self.set_font("Helvetica", size=size)
        self.multi_cell(0, 5, _pdf_text(text), new_x="LMARGIN", new_y="NEXT")

    def rule(self) -> None:
        self.ln(2)
        y = self.get_y()
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(3)


def export_pdf(
    db: Session,
    *,
    user: User,
    decisions: list[Decision],
    filters: AuditFilters,
) -> bytes:
    ctx = _context(db, decisions)
    tenant = db.get(Tenant, user.tenant_id)
    chain = verify_chain(db, tenant_id=user.tenant_id)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf = _Binder("GlassBox audit binder")

    # Cover page -----------------------------------------------------------
    pdf.add_page()
    pdf.heading("GlassBox audit binder", size=20)
    pdf.ln(2)
    pdf.label_value("Workspace", tenant.name if tenant else user.tenant_id)
    pdf.label_value("Generated", generated)
    pdf.label_value("Generated by", user.email)
    pdf.label_value("Filters", filters.describe())
    pdf.label_value("Decisions", len(decisions))
    if decisions:
        pdf.label_value(
            "Period covered",
            f"{decisions[-1].created_at:%Y-%m-%d %H:%M} to {decisions[0].created_at:%Y-%m-%d %H:%M} UTC",
        )
    pdf.label_value(
        "Hash chain",
        (
            f"intact - {chain.verified} of {chain.total} workspace decisions verified"
            if chain.ok
            else f"BROKEN at decision {chain.first_break_decision_id}: {chain.first_break_reason}"
        ),
    )
    outcomes = Counter(d.outcome for d in decisions)
    pdf.label_value(
        "Outcomes",
        ", ".join(f"{name} {outcomes.get(name, 0)}" for name in ("answered", "flagged", "refused", "fallback")),
    )
    pdf.label_value(
        "Reviews",
        f"{sum(len(v) for v in ctx.reviews.values())} reviews, "
        f"{sum(len(v) for v in ctx.corrections.values())} corrections",
    )
    pdf.ln(4)
    pdf.paragraph(
        "Each section below reproduces one decision exactly as recorded: the question, the "
        "answer or refusal, every claim the system kept or dropped with its cited source, the "
        "evidence it retrieved, and any human review. Decisions are hash-chained; the stored "
        "hashes are printed so the chain can be re-verified independently.",
        size=9,
    )

    # One section per decision ----------------------------------------------
    for d in decisions:
        pdf.add_page()
        pdf.heading(f"Decision {d.id}", size=12)
        pdf.label_value("Recorded", f"{d.created_at:%Y-%m-%d %H:%M:%S} UTC")
        pdf.label_value("Asked by", ctx.asked_by.get(d.user_id or "", "-"))
        pdf.label_value("Client", d.client_id or "-")
        pdf.label_value("Outcome", d.outcome)
        pdf.label_value(
            "Grounding", "-" if d.grounding_score is None else f"{d.grounding_score:.0%}"
        )
        pdf.label_value("Model route", d.llm_model)
        pdf.label_value("Latency", f"{d.latency_ms} ms")
        pdf.rule()
        pdf.heading("Question", size=10)
        pdf.paragraph(d.question)
        pdf.heading("Answer / refusal", size=10)
        pdf.paragraph(d.final_answer or "(no answer text recorded)")

        pdf.heading("Claims", size=10)
        if not d.claims:
            pdf.paragraph("No claims recorded.")
        for claim in d.claims:
            state = "KEPT" if claim.kept else "DROPPED"
            verified = "verified" if claim.verified else "unverified"
            pdf.paragraph(
                f"[{state}, {verified}, source {claim.cited_source_id or 'none'}] {claim.claim_text}"
            )

        pdf.heading("Retrieved evidence", size=10)
        if not d.retrieved_chunks:
            pdf.paragraph("No evidence retrieved.")
        for chunk in d.retrieved_chunks:
            snippet = chunk.chunk_text if len(chunk.chunk_text) <= 400 else chunk.chunk_text[:400] + "..."
            pdf.paragraph(f"{chunk.source_id} ({chunk.source_type}, score {chunk.score:.3f}): {snippet}")

        reviews = ctx.reviews.get(d.id, [])
        corrections = ctx.corrections.get(d.id, [])
        escalations = ctx.escalations.get(d.id, [])
        if reviews or corrections or escalations:
            pdf.heading("Human oversight", size=10)
        for esc in escalations:
            pdf.paragraph(
                f"Escalation {esc.status} (priority {esc.priority}, reason {esc.reason}, "
                f"SLA {esc.sla_due_at:%Y-%m-%d %H:%M} UTC)"
            )
            for event in sorted(esc.events, key=lambda e: e.created_at):
                pdf.paragraph(
                    f"  {event.created_at:%Y-%m-%d %H:%M} - {event.action}"
                    + (f" -> {event.to_status}" if event.to_status else "")
                    + (f": {event.note}" if event.note else "")
                )
        for review in reviews:
            labels = review.claim_labels
            supported = sum(1 for label in labels if label.supported)
            pdf.paragraph(
                f"Review {review.created_at:%Y-%m-%d %H:%M} by "
                f"{ctx.asked_by.get(review.reviewer_user_id, review.reviewer_user_id)}: "
                f"{review.assessment} ({review.reason_code})"
                + (f"; {len(labels)} claim verdicts, {supported} supported" if labels else "")
                + (f". Notes: {review.notes}" if review.notes else "")
            )
        for correction in corrections:
            pdf.paragraph(
                f"Correction {correction.created_at:%Y-%m-%d %H:%M}"
                + (f", correct outcome {correction.corrected_outcome}" if correction.corrected_outcome else "")
                + f": {correction.note}"
            )

        pdf.rule()
        pdf.set_font("Courier", size=7)
        pdf.multi_cell(0, 4, _pdf_text(f"prev_hash {d.prev_hash or '-'}"), new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 4, _pdf_text(f"row_hash  {d.row_hash or '-'}"), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
