"""Export reviewer claim verdicts as grounding-scorer training data.

Usage (from backend/):
    PYTHONPATH=. python -m scripts.export_review_labels            # all tenants
    PYTHONPATH=. python -m scripts.export_review_labels --tenant <tenant-id>
    PYTHONPATH=. python -m app.ml.train_grounding                   # retrain

Writes data/training/review_labels.jsonl in the same {claim, source, label}
shape as the synthetic grounding.jsonl; train_grounding merges both. The
file holds real claim and source text, so it is git-ignored.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.config import BACKEND_DIR
from app.db import SessionLocal
from app.models_db import ClaimLabel


OUTPUT = BACKEND_DIR / "data" / "training" / "review_labels.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export reviewer claim labels.")
    parser.add_argument("--tenant", help="only export labels from this tenant id")
    args = parser.parse_args(argv)

    stmt = select(ClaimLabel).where(ClaimLabel.source_text.is_not(None))
    if args.tenant:
        stmt = stmt.where(ClaimLabel.tenant_id == args.tenant)
    with SessionLocal() as db:
        labels = db.scalars(stmt.order_by(ClaimLabel.created_at.asc())).all()
        rows = [
            {
                "claim": label.claim_text,
                "source": label.source_text,
                "label": 1 if label.supported else 0,
                "review_id": label.review_id,
            }
            for label in labels
        ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    supported = sum(row["label"] for row in rows)
    print(
        f"Exported {len(rows)} labelled claims ({supported} supported, "
        f"{len(rows) - supported} unsupported) to {OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
