from __future__ import annotations

import json
import random
import re
from pathlib import Path

from app.config import BACKEND_DIR
from corpus.ingest import build_chunks


OUT_DIR = BACKEND_DIR / "data" / "training"
RANDOM = random.Random(42)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def grounding_rows(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    texts = [str(chunk["chunk_text"]) for chunk in chunks]
    for text in texts:
        rows.append({"claim": text, "source": text, "label": 1})
        mutated = _mutate_number(text)
        if mutated != text:
            rows.append({"claim": mutated, "source": text, "label": 0})
    while len(rows) < 320:
        claim = RANDOM.choice(texts)
        source = RANDOM.choice([text for text in texts if text != claim])
        rows.append({"claim": claim, "source": source, "label": 0})
    RANDOM.shuffle(rows)
    return rows[:320]


def refusal_rows(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    answerable = [
        "What is the single position limit for client C001?",
        "Is fund F100 high risk?",
        "Can Client C002 invest in cryptocurrency?",
        "What liquidity must Client C001 keep within 30 days?",
        "Does suitability require considering concentration limits?",
    ]
    escalate = [
        "What is the capital gains tax rate in Germany?",
        "Should the client file taxes jointly after divorce?",
        "What criminal penalty applies for insider trading?",
        "Can you draft a binding legal opinion for this client?",
        "What is tomorrow's price of F100?",
    ]
    rows: list[dict[str, object]] = []
    for _ in range(120):
        rows.append(
            {
                "question": RANDOM.choice(answerable),
                "top_score": round(RANDOM.uniform(0.2, 0.9), 3),
                "label": "answer",
            }
        )
        rows.append(
            {
                "question": RANDOM.choice(escalate),
                "top_score": round(RANDOM.uniform(0.0, 0.18), 3),
                "label": "escalate",
            }
        )
    return rows


def fallback_rows() -> list[dict[str, object]]:
    templates = [
        ("Can client C001 put 40% into fund F100?", "single_position", "violation"),
        ("Can client C003 put 20% into F100?", "single_position", "allowed"),
        ("What is the German capital gains tax rate?", "none", "escalate"),
        ("Is F200 low risk for C002?", "risk_profile", "allowed"),
        ("Can C002 buy cryptocurrency exposure?", "excluded_sector", "violation"),
    ]
    rows = []
    for _ in range(160):
        question, rule, verdict = RANDOM.choice(templates)
        rows.append({"question": question, "client_rule_hit": rule, "verdict": verdict})
    return rows


def _mutate_number(text: str) -> str:
    match = re.search(r"(\d+)", text)
    if not match:
        return text + " This unrelated sentence is unsupported."
    number = int(match.group(1))
    return text[: match.start()] + str(number + 10) + text[match.end() :]


def main() -> None:
    chunks = build_chunks()
    write_jsonl(OUT_DIR / "grounding.jsonl", grounding_rows(chunks))
    write_jsonl(OUT_DIR / "refusal.jsonl", refusal_rows(chunks))
    write_jsonl(OUT_DIR / "fallback.jsonl", fallback_rows())
    print(f"Wrote training data to {OUT_DIR}")


if __name__ == "__main__":
    main()
