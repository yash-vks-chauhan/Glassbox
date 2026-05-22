from __future__ import annotations

import json
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from app.config import BACKEND_DIR
from app.core.trust_metrics import numeric_match, token_overlap_ratio
from app.core.embeddings import embed_texts


DATA_PATH = BACKEND_DIR / "data" / "training" / "grounding.jsonl"
ARTIFACT = BACKEND_DIR / "app" / "ml" / "artifacts" / "grounding_scorer.joblib"


def load_rows() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def features(claim: str, source: str) -> list[float]:
    vectors = embed_texts([claim, source])
    cosine = float(vectors[0] @ vectors[1])
    return [cosine, token_overlap_ratio(claim, source), numeric_match(claim, source)]


def main() -> None:
    rows = load_rows()
    x = [features(str(row["claim"]), str(row["source"])) for row in rows]
    y = [int(row["label"]) for row in rows]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=42, stratify=y
    )
    model = LogisticRegression(max_iter=500)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    print(f"accuracy={accuracy_score(y_test, predictions):.3f}")
    print(f"f1={f1_score(y_test, predictions):.3f}")
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACT)
    print(f"saved={ARTIFACT}")


if __name__ == "__main__":
    main()
