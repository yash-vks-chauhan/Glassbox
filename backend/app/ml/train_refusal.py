from __future__ import annotations

import json

import joblib
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from app.config import BACKEND_DIR


DATA_PATH = BACKEND_DIR / "data" / "training" / "refusal.jsonl"
ARTIFACT = BACKEND_DIR / "app" / "ml" / "artifacts" / "refusal_router.joblib"


def main() -> None:
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    questions = [str(row["question"]) for row in rows]
    vectorizer = CountVectorizer(ngram_range=(1, 2), min_df=1)
    text_features = vectorizer.fit_transform(questions).toarray()
    numeric_features = np.asarray(
        [[float(row["top_score"]), len(str(row["question"]))] for row in rows],
        dtype=float,
    )
    x = np.hstack([text_features, numeric_features])
    y = [str(row["label"]) for row in rows]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=42, stratify=y
    )
    model = LogisticRegression(max_iter=500)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    print(f"accuracy={accuracy_score(y_test, predictions):.3f}")
    print(f"f1={f1_score(y_test, predictions, pos_label='escalate'):.3f}")
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "model": model}, ARTIFACT)
    print(f"saved={ARTIFACT}")


if __name__ == "__main__":
    main()
