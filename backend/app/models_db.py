from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid4())


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    determinism_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    grounding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    claims: Mapped[list["DecisionClaim"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )
    retrieved_chunks: Mapped[list["RetrievedChunk"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )


class DecisionClaim(Base):
    __tablename__ = "decision_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    cited_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kept: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    decision: Mapped[Decision] = relationship(back_populates="claims")


class RetrievedChunk(Base):
    __tablename__ = "retrieved_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    decision: Mapped[Decision] = relationship(back_populates="retrieved_chunks")
