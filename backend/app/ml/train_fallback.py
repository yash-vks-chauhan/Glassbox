from __future__ import annotations

import json

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from app.config import BACKEND_DIR


DATA_PATH = BACKEND_DIR / "data" / "training" / "fallback.jsonl"
ARTIFACT = BACKEND_DIR / "app" / "ml" / "artifacts" / "fallback_classifier.joblib"


def main() -> None:
    rows = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    texts = [f'{row["question"]} rule:{row["client_rule_hit"]}' for row in rows]
    vectorizer = CountVectorizer(ngram_range=(1, 2), min_df=1)
    x = vectorizer.fit_transform(texts).toarray()
    y = [str(row["verdict"]) for row in rows]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=42, stratify=y
    )
    model = RandomForestClassifier(n_estimators=80, random_state=42)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    print(f"accuracy={accuracy_score(y_test, predictions):.3f}")
    print(f"f1_macro={f1_score(y_test, predictions, average='macro'):.3f}")
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "model": model}, ARTIFACT)
    print(f"saved={ARTIFACT}")


if __name__ == "__main__":
    main()
