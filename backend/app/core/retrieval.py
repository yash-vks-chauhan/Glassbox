from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.core.embeddings import cosine_similarity, embed_texts
from app.core.types import RetrievedChunk

# Phase D sentinel: chunks tagged with this tenant_id are part of the shared
# Chroma collection (regulations / public factsheets). Retrieval unions them
# with each caller's `glassbox_t_{tenant_id}` collection.
SHARED_TENANT_SENTINEL = ""

_RETRIEVAL_CACHE: dict[tuple[str, str, int, str, str], tuple[float, list[RetrievedChunk]]] = {}


def _store_paths() -> tuple[Path, Path]:
    store_dir = get_settings().resolved_chroma_dir
    return store_dir / "chunks.json", store_dir / "vectors.npy"


def ensure_index() -> None:
    chunks_path, vectors_path = _store_paths()
    if chunks_path.exists() and vectors_path.exists() and _index_schema_current(chunks_path):
        return
    from corpus.ingest import ingest

    ingest()


def _index_schema_current(chunks_path: Path) -> bool:
    try:
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    # Phase D adds the `collection` field. Force a re-ingest on older indexes
    # so we never serve chunks whose tenant assignment is stale.
    return isinstance(chunks, list) and all(
        "tenant_id" in chunk and "collection" in chunk for chunk in chunks
    )


def _load_index() -> tuple[list[dict[str, object]], np.ndarray]:
    ensure_index()
    chunks_path, vectors_path = _store_paths()
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    return chunks, vectors


def _matches_client(chunk: dict[str, object], client_id: str | None) -> bool:
    if client_id is None:
        return True
    source_type = chunk.get("source_type")
    if source_type not in {"ips", "portfolio"}:
        return True
    if chunk.get("source_id") == client_id:
        return True
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get("client_id") == client_id
    return False


def _matches_tenant(chunk: dict[str, object], tenant_id: str | None) -> bool:
    """Phase D isolation rule. Two cases:

    1. ``tenant_id`` is provided (the normal case): accept chunks tagged with
       that tenant *or* with the shared sentinel ("", the
       ``glassbox_shared`` collection). Anything else is another tenant's
       content and must never surface.
    2. ``tenant_id`` is ``None``: fall back to shared-only. We deliberately
       refuse to broaden to "all tenants" so a missing tenant context is
       safe-by-default — a leak would be far worse than an empty result.
    """
    chunk_tenant = chunk.get("tenant_id")
    if tenant_id is None:
        return chunk_tenant in (None, SHARED_TENANT_SENTINEL)
    if chunk_tenant in (None, SHARED_TENANT_SENTINEL):
        return True
    return chunk_tenant == tenant_id


def retrieve(
    question: str,
    client_id: str | None = None,
    k: int = 6,
    tenant_id: str | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    cache_key = (
        tenant_id or "",
        client_id or "",
        k,
        _normalize_question(question),
        _corpus_version(),
    )
    cached = _RETRIEVAL_CACHE.get(cache_key)
    if cached and time.time() - cached[0] <= settings.retrieval_cache_ttl_seconds:
        return [replace(chunk, cache_hit=True) for chunk in cached[1][:k]]

    chunks = _retrieve_uncached(question, client_id=client_id, k=k, tenant_id=tenant_id)
    _RETRIEVAL_CACHE[cache_key] = (time.time(), chunks)
    return chunks


def evidence_quality(chunks: list[RetrievedChunk]) -> float:
    if not chunks:
        return 0.0
    source_count = len({chunk.source_id for chunk in chunks})
    top_score = max(chunk.score for chunk in chunks)
    breadth = min(1.0, source_count / 3)
    return round(max(0.0, min(1.0, 0.75 * top_score + 0.25 * breadth)), 4)


def clear_retrieval_cache() -> None:
    _RETRIEVAL_CACHE.clear()


def _retrieve_uncached(
    question: str,
    client_id: str | None = None,
    k: int = 6,
    tenant_id: str | None = None,
) -> list[RetrievedChunk]:
    chunks, vectors = _load_index()
    allowed_indices = [
        index
        for index, chunk in enumerate(chunks)
        if _matches_tenant(chunk, tenant_id) and _matches_client(chunk, client_id)
    ]
    if not allowed_indices:
        return []

    query_vector = embed_texts([_expanded_question(question)])[0]
    allowed_vectors = vectors[allowed_indices]
    scores = cosine_similarity(query_vector, allowed_vectors)
    candidate_count = max(k * 4, 20)
    vector_ranked = sorted(
        zip(allowed_indices, scores.tolist()), key=lambda item: item[1], reverse=True
    )[:candidate_count]
    ranked = sorted(
        (
            (
                index,
                _rerank_score(
                    question=question,
                    client_id=client_id,
                    chunk=chunks[index],
                    vector_score=float(score),
                ),
            )
            for index, score in vector_ranked
        ),
        key=lambda item: item[1],
        reverse=True,
    )[:k]

    results = [
        RetrievedChunk(
            source_id=str(chunks[index]["source_id"]),
            source_type=str(chunks[index]["source_type"]),
            chunk_text=str(chunks[index]["chunk_text"]),
            score=float(max(score, 0.0)),
            file=str(chunks[index].get("file") or ""),
            chunk_index=int(chunks[index].get("chunk_index") or 0),
            source_version=_source_version(chunks[index]),
            selected_reason=_selection_reason(question, client_id, chunks[index]),
        )
        for index, score in ranked
    ]
    results = _dedupe_chunks(results)
    allowed_chunks = [chunks[index] for index in allowed_indices]
    return _ensure_required_sources(question, client_id, allowed_chunks, results, k)


def _expanded_question(question: str) -> str:
    lower = question.lower()
    additions: list[str] = []
    if "%" in question or "percent" in lower:
        additions.append("single position limit concentration allocation")
    if "suitable" in lower or "suitability" in lower:
        additions.append("risk profile suitability recommendation REG-SUITABILITY")
    if "fund" in lower:
        additions.append("factsheet risk level asset class sector region liquidity")
    if _needs_portfolio_source(question, _client_id(question)):
        additions.append("portfolio snapshot current holdings current exposure current liquid assets post trade")
    if _is_tax_guidance_question(question):
        additions.append("approved tax evidence jurisdictional tax memo Tax Desk")
    if _is_jurisdiction_question(question):
        additions.append("client IPS jurisdiction cross-border compliance review")
    if "exception" in lower or "verbally approves" in lower or re.search(r"\bwaiv\w*\b", lower):
        additions.append("mandate exception process compliance approval IPS control")
    return f"{question} {' '.join(additions)}".strip()


def _rerank_score(
    *,
    question: str,
    client_id: str | None,
    chunk: dict[str, object],
    vector_score: float,
) -> float:
    text = str(chunk.get("chunk_text") or "")
    lexical = _lexical_score(question, text)
    boost = _metadata_boost(question, client_id, chunk, text)
    return max(0.0, min(1.0, 0.72 * max(vector_score, 0.0) + 0.22 * lexical + boost))


def _lexical_score(question: str, text: str) -> float:
    question_terms = _tokens(question) - _STOPWORDS
    if not question_terms:
        return 0.0
    text_terms = _tokens(text)
    return len(question_terms & text_terms) / len(question_terms)


def _metadata_boost(
    question: str,
    client_id: str | None,
    chunk: dict[str, object],
    text: str,
) -> float:
    lower_q = question.lower()
    lower_text = text.lower()
    source_id = str(chunk.get("source_id") or "")
    source_type = str(chunk.get("source_type") or "")
    boost = 0.0
    if client_id and source_type == "ips" and source_id == client_id:
        boost += 0.08
    if client_id and source_type == "portfolio" and _portfolio_source_id(client_id) == source_id:
        boost += 0.08
        if _needs_portfolio_source(question, client_id):
            boost += 0.14
        if any(term in lower_text for term in ["current", "portfolio snapshot", "exposure", "liquid assets"]):
            boost += 0.04
    for fund_id in re.findall(r"\bF\d{3}\b", question, flags=re.I):
        if source_id == fund_id.upper():
            boost += 0.08
            if source_type == "factsheet" and (
                _is_fund_transaction(question) or _is_source_checklist_question(question)
                or any(term in lower_q for term in ["recommend", "suitable", "suitability"])
            ):
                if any(term in lower_text for term in _FACTSHEET_HINT_TERMS):
                    boost += 0.10
    if _is_tax_guidance_question(question) and source_id == "REG-TAX-GUIDANCE":
        boost += 0.16
    if _is_jurisdiction_question(question) and source_id == "REG-JURISDICTION":
        boost += 0.14
    if ("exception" in lower_q or "verbally approves" in lower_q or re.search(r"\bwaiv\w*\b", lower_q)) and source_id == "REG-EXCEPTIONS":
        boost += 0.14
    if _is_fund_transaction(question) and source_type == "ips":
        if any(term in lower_text for term in ["risk profile", "may hold", "human review", "liquid", "single position"]):
            boost += 0.08
    if _is_source_checklist_question(question) and source_type == "ips":
        if any(term in lower_text for term in ["risk profile", "single position", "liquid", "must not", "suitability constraints"]):
            boost += 0.10
    if any(term in lower_q for term in ["recommend", "suitable", "suitability"]):
        if source_id == "REG-SUITABILITY":
            boost += 0.05
    if "liquid" in lower_q and "liquid" in lower_text:
        boost += 0.04
    if any(term in lower_q for term in ["single position", "concentration", "%", "percent"]):
        if "single position" in lower_text or "portfolio value" in lower_text:
            boost += 0.05
    return boost


def _selection_reason(
    question: str,
    client_id: str | None,
    chunk: dict[str, object],
) -> str:
    source_id = str(chunk.get("source_id") or "")
    source_type = str(chunk.get("source_type") or "")
    if client_id and source_type == "ips" and source_id == client_id:
        return "matching client IPS"
    fund_ids = {fund.upper() for fund in re.findall(r"\bF\d{3}\b", question, flags=re.I)}
    if source_id in fund_ids:
        return "mentioned fund factsheet"
    if source_id == "REG-SUITABILITY":
        return "suitability guidance"
    if source_id == "REG-TAX-GUIDANCE":
        return "tax evidence handling"
    if source_id == "REG-JURISDICTION":
        return "jurisdiction review policy"
    if source_id == "REG-EXCEPTIONS":
        return "mandate exception process"
    if source_type == "portfolio":
        return "matching portfolio snapshot"
    return "semantic relevance"


def _ensure_required_sources(
    question: str,
    client_id: str | None,
    index_chunks: list[dict[str, object]],
    results: list[RetrievedChunk],
    k: int,
) -> list[RetrievedChunk]:
    required = _required_source_ids(question, client_id)
    if not required:
        return results[:k]
    existing = {chunk.source_id for chunk in results}
    augmented = list(results)
    for source_id in required:
        if source_id in existing:
            if (
                _is_source_checklist_question(question)
                or _is_suitability_or_risk_question(question)
                or _is_jurisdiction_question(question)
            ):
                for candidate in _best_required_chunks(question, source_id, index_chunks, limit=2):
                    chunk, score = candidate
                    augmented.append(
                        RetrievedChunk(
                            source_id=str(chunk["source_id"]),
                            source_type=str(chunk["source_type"]),
                            chunk_text=str(chunk["chunk_text"]),
                            score=float(max(score, 0.05)),
                            file=str(chunk.get("file") or ""),
                            chunk_index=int(chunk.get("chunk_index") or 0),
                            source_version=_source_version(chunk),
                            selected_reason=f"required source fallback: {_selection_reason(question, client_id, chunk)}",
                        )
                    )
            continue
        candidate = _best_required_chunk(question, source_id, index_chunks)
        if candidate is None:
            continue
        chunk, score = candidate
        augmented.append(
            RetrievedChunk(
                source_id=str(chunk["source_id"]),
                source_type=str(chunk["source_type"]),
                chunk_text=str(chunk["chunk_text"]),
                # Do not inflate semantic confidence just because the source
                # was required. Answerability needs the document to be present,
                # but eval should still expose when vector retrieval needed a
                # metadata fallback to complete the evidence pack.
                score=float(max(score, 0.05)),
                file=str(chunk.get("file") or ""),
                chunk_index=int(chunk.get("chunk_index") or 0),
                source_version=_source_version(chunk),
                selected_reason=f"required source fallback: {_selection_reason(question, client_id, chunk)}",
            )
        )
        existing.add(source_id)
    deduped = _dedupe_chunks(augmented)
    required_top: list[RetrievedChunk] = []
    required_rest: list[RetrievedChunk] = []
    for source_id in required:
        matches = sorted(
            [chunk for chunk in deduped if chunk.source_id == source_id],
            key=lambda item: item.score,
            reverse=True,
        )
        if matches:
            required_top.append(matches[0])
            required_rest.extend(matches[1:])
    required_set = set(required)
    other_chunks = [chunk for chunk in deduped if chunk.source_id not in required_set]
    ordered = required_top
    ordered.extend(
        sorted(required_rest + other_chunks, key=lambda item: item.score, reverse=True)
    )
    return ordered[:k]


def _required_source_ids(question: str, client_id: str | None) -> list[str]:
    lower = question.lower()
    required: list[str] = []
    mentioned_client = client_id or _client_id(question)
    mentioned_funds = _fund_ids(question)
    asks_mandate = any(
        term in lower
        for term in [
            "mandate",
            "ips",
            "single position",
            "concentration",
            "liquid",
            "liquidity",
            "risk profile",
            "exclude",
            "excluded",
            "permit",
            "exposure",
            "allocate",
            "allocation",
            "jurisdiction",
            "cross-border",
            "%",
            "percent",
        ]
    )
    asks_suitability = any(
        term in lower for term in ["suitable", "suitability", "recommend", "recommending"]
    ) or _is_fund_transaction(question)
    if mentioned_client and (asks_mandate or asks_suitability):
        required.append(mentioned_client)
    if _needs_portfolio_source(question, mentioned_client):
        required.append(_portfolio_source_id(mentioned_client))
    required.extend(mentioned_funds)
    asks_risk_guidance = (
        ("risk" in lower and "sector" in lower)
        or ("risk" in lower and "concentration" in lower)
    )
    if asks_suitability or asks_risk_guidance:
        required.append("REG-SUITABILITY")
    if _is_tax_guidance_question(question):
        required.append("REG-TAX-GUIDANCE")
    if _is_jurisdiction_question(question):
        if mentioned_client:
            required.append(mentioned_client)
        required.append("REG-JURISDICTION")
    if "exception" in lower or "verbally approves" in lower or re.search(r"\bwaiv\w*\b", lower):
        required.append("REG-EXCEPTIONS")
    return list(dict.fromkeys(required))


def _best_required_chunk(
    question: str,
    source_id: str,
    chunks: list[dict[str, object]],
) -> tuple[dict[str, object], float] | None:
    ranked = _best_required_chunks(question, source_id, chunks, limit=1)
    return ranked[0] if ranked else None


def _best_required_chunks(
    question: str,
    source_id: str,
    chunks: list[dict[str, object]],
    *,
    limit: int,
) -> list[tuple[dict[str, object], float]]:
    candidates = [chunk for chunk in chunks if str(chunk.get("source_id") or "") == source_id]
    if not candidates:
        return []
    ranked = sorted(
        (
            (
                chunk,
                max(
                    _lexical_score(question, str(chunk.get("chunk_text") or "")),
                    _required_chunk_hint_score(question, chunk),
                ),
            )
            for chunk in candidates
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:limit]


def _required_chunk_hint_score(question: str, chunk: dict[str, object]) -> float:
    lower_q = question.lower()
    lower_text = str(chunk.get("chunk_text") or "").lower()
    source_id = str(chunk.get("source_id") or "")
    score = 0.0
    if source_id == "REG-SUITABILITY":
        if any(term in lower_q for term in ["escalate", "available documents"]):
            if "human reviewer" in lower_text or "escalated" in lower_text:
                score = max(score, 0.95)
        if "liquidity" in lower_q and "liquidity requirements" in lower_text:
            score = max(score, 0.95)
        if "prohibited sector" in lower_q and "prohibited sector" in lower_text:
            score = max(score, 0.95)
        if "concentration" in lower_q and "concentration limits" in lower_text:
            score = max(score, 0.95)
        if "risk" in lower_q and "risk profile" in lower_text:
            score = max(score, 0.95)
    if source_id == "REG-TAX-GUIDANCE":
        if _is_tax_guidance_question(question) and any(
            term in lower_text for term in ["approved jurisdictional tax memo", "tax desk", "must not quote"]
        ):
            score = max(score, 0.96)
    if source_id == "REG-JURISDICTION":
        if _is_jurisdiction_question(question) and any(
            term in lower_text for term in ["client's approved ips", "cross-border", "not documented"]
        ):
            score = max(score, 0.95)
        if "undocumented" in lower_q and "not documented" in lower_text:
            score = max(score, 0.98)
    if source_id == "REG-EXCEPTIONS":
        if "exception" in lower_q or "verbally approves" in lower_q or re.search(r"\bwaiv\w*\b", lower_q):
            if any(term in lower_text for term in ["verbal approval", "compliance approval", "ips control"]):
                score = max(score, 0.95)
    if source_id.startswith("PORTFOLIO-"):
        if _needs_portfolio_source(question, None) and any(
            term in lower_text for term in ["portfolio snapshot", "current", "exposure", "liquid assets"]
        ):
            score = max(score, 0.95)
    if any(term in lower_q for term in ["single position", "concentration", "%", "percent"]):
        if "single position" in lower_text or "portfolio value" in lower_text:
            score = max(score, 0.9)
    if any(term in lower_q for term in ["liquid", "liquidity"]):
        if "liquid" in lower_text:
            score = max(score, 0.9)
    if any(term in lower_q for term in ["suitable", "suitability", "recommend"]):
        if "suitability" in lower_text or "recommendation" in lower_text:
            score = max(score, 0.9)
    if str(chunk.get("source_type") or "") == "factsheet" and (
        _is_fund_transaction(question) or _is_source_checklist_question(question)
        or any(term in lower_q for term in ["recommend", "suitable", "suitability"])
    ):
        if _is_suitability_or_risk_question(question) and "risk level" in lower_text:
            score = max(score, 0.98)
        if _is_source_checklist_question(question) and (
            "risk level" in lower_text or "invests" in lower_text
        ):
            score = max(score, 0.97)
        if _is_source_checklist_question(question) and (
            "technology" in lower_text or "concentrated exposure" in lower_text
        ):
            score = max(score, 0.975)
        if any(term in lower_text for term in _FACTSHEET_HINT_TERMS):
            score = max(score, 0.93)
    if _is_fund_transaction(question) and str(chunk.get("source_type") or "") == "ips":
        if any(term in lower_text for term in ["risk profile", "may hold", "human review"]):
            score = max(score, 0.92)
    if _is_suitability_or_risk_question(question) and str(chunk.get("source_type") or "") == "ips":
        if "risk profile" in lower_text:
            score = max(score, 0.94)
    if _is_jurisdiction_question(question) and str(chunk.get("source_type") or "") == "ips":
        if "governed by" in lower_text or "jurisdiction" in lower_text:
            score = max(score, 0.97)
    if _is_source_checklist_question(question) and str(chunk.get("source_type") or "") == "ips":
        if any(term in lower_text for term in ["risk profile", "single position", "liquid", "must not"]):
            score = max(score, 0.92)
    return score


def _dedupe_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    by_key: dict[tuple[str, str], RetrievedChunk] = {}
    for chunk in chunks:
        key = (chunk.source_id, re.sub(r"\s+", " ", chunk.chunk_text.strip().lower()))
        existing = by_key.get(key)
        if existing is None or chunk.score > existing.score:
            by_key[key] = chunk
    return list(by_key.values())


def _source_version(chunk: dict[str, object]) -> str | None:
    text = str(chunk.get("chunk_text") or "")
    match = re.search(r"\b(v\d+(?:\.\d+)*)\b", text, flags=re.I)
    return match.group(1) if match else None


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _client_id(question: str) -> str | None:
    match = re.search(r"\b(C\d{3})\b", question, flags=re.I)
    return match.group(1).upper() if match else None


def _portfolio_source_id(client_id: str | None) -> str:
    return f"PORTFOLIO-{client_id}" if client_id else ""


def _fund_ids(question: str) -> list[str]:
    return list(dict.fromkeys(match.upper() for match in re.findall(r"\bF\d{3}\b", question, flags=re.I)))


def _is_fund_transaction(question: str) -> bool:
    return bool(
        re.search(r"\b(can|may|should|would)\b", question, re.I)
        and re.search(r"\b(buy|hold|invest|put|allocate|count|use|treat)\b", question, re.I)
        and (re.search(r"\bF\d{3}\b", question, re.I) or re.search(r"\bhigh-risk equity fund\b", question, re.I))
    )


_FACTSHEET_HINT_TERMS = (
    "risk level",
    "concentrated",
    "technology",
    "equity securities",
    "government bonds",
    "government securities",
    "short-duration",
    "cash-equivalent",
    "money market",
    "daily liquidity",
    "private credit",
    "quarterly liquidity",
    "liquid within 30 days",
    "capital preservation",
)


def _is_tax_guidance_question(question: str) -> bool:
    q = question.lower()
    if re.search(r"\b(tax|tax-rate|tax rate|capital gains|vat)\b", q):
        return bool(
            re.search(
                r"\b(source|evidence|memo|approved|before|support|what should|do when|handling|cite|advisor)\b",
                q,
            )
        )
    return False


def _is_jurisdiction_question(question: str) -> bool:
    return bool(
        re.search(r"\b(jurisdiction|jurisdictions|cross-border|country|countries)\b", question, re.I)
        and re.search(r"\b(C\d{3}|client|ips|constraint|govern|review|documented)\b", question, re.I)
    )


def _is_source_checklist_question(question: str) -> bool:
    return bool(
        re.search(r"\b(which|what)\s+sources?\b|\bsource checklist\b|\bwhat evidence\b", question, re.I)
        and re.search(r"\b(cite|cited|recommend|recommending|advisor|evidence)\b", question, re.I)
    )


def _is_suitability_or_risk_question(question: str) -> bool:
    return bool(
        re.search(
            r"\b(suitable|suitability|recommend\w*|risk|risk evidence|risk profile|risk level|high risk|low risk|asset class)\b",
            question,
            re.I,
        )
        or _is_fund_transaction(question)
    )


def _needs_portfolio_source(question: str, client_id: str | None) -> bool:
    if not client_id:
        return False
    q = question.lower()
    return bool(
        re.search(
            r"\b(current|existing|portfolio|holding|holdings|post[- ]trade|after|before recommending|recommend\w*|add|breach\w*)\b",
            q,
        )
        and re.search(
            r"\b(client|C\d{3}|technology|sector|liquid|liquidity|F\d{3}|suitable|recommend\w*)\b",
            question,
            re.I,
        )
    )


def _corpus_version() -> str:
    chunks_path, vectors_path = _store_paths()
    try:
        return f"{chunks_path.stat().st_mtime_ns}:{vectors_path.stat().st_mtime_ns}"
    except OSError:
        return "missing"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9%_]+", text.lower()))


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "can",
    "client",
    "does",
    "for",
    "fund",
    "in",
    "into",
    "is",
    "may",
    "of",
    "or",
    "the",
    "to",
    "what",
    "which",
    "would",
}
