"""去噪 → 分块 → Embedding 检索 → excerpt 组装"""

import math
import re
from typing import Any, TypedDict


class Chunk(TypedDict):
    text: str
    index: int


# ── Noise cleaning ──────────────────────────────────────────────────────────

NOISE_PATTERNS = [
    r"(copyright|©|\(c\)|all rights reserved)",
    r"(sign\s*up|subscribe|newsletter)",
    r"(cookie|privacy\s*policy|terms\s*of\s*service)",
    r"(navigation|menu|breadcrumb|skip\s*to\s*content)",
    r"(comments?|leave\s*a\s*reply|join\s*the\s*discussion)",
    r"(share\s*this|tweet|facebook|twitter|linkedin)",
    r"(advertisement|sponsored|promoted)",
    r"(search\b.*\b(results|the\s*site))",
    r"(related\s*posts|popular\s*posts|you\s*may\s*also\s*like)",
    r"(footer|©\s*\d{4})",
]


def clean_noise(text: str, min_line_length: int = 15) -> str:
    """Remove navigation, copyright, ads, and other noisy lines."""
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or len(line) < min_line_length:
            continue
        if any(re.search(p, line, re.IGNORECASE) for p in NOISE_PATTERNS):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# ── Chunking ────────────────────────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 128) -> list[Chunk]:
    """Split text into overlapping chunks by paragraph boundaries."""
    paragraphs = text.split("\n\n")
    chunks: list[Chunk] = []
    buffer = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buffer) + len(para) > chunk_size and buffer:
            chunks.append({"text": buffer.strip(), "index": len(chunks)})
            buffer = buffer[-overlap:] + "\n\n" + para
        else:
            buffer += "\n\n" + para if buffer else para
    if buffer.strip():
        chunks.append({"text": buffer.strip(), "index": len(chunks)})
    return chunks


# ── Embedding retrieval ─────────────────────────────────────────────────────

_CONTENT_RETRIEVAL_INSTANCE: Any | None = None


class ContentRetrieval:
    """Rank chunks by relevance to query using Embedding (primary) or BM25 (fallback)."""

    def __init__(self):
        self._model = None
        self._model_loaded = False
        self._cache: dict[int, Any] = {}

    def _load_model(self):
        if self._model_loaded:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                "BAAI/bge-small-zh-v1.5",
                device="cpu",
            )
        except ImportError:
            self._model = None
        self._model_loaded = True

    def rank_chunks(self, chunks: list[Chunk], query: str, top_k: int = 5) -> list[Chunk]:
        self._load_model()
        if self._model is None:
            return self._rank_bm25(chunks, query, top_k)
        return self._rank_embedding(chunks, query, top_k)

    def _rank_embedding(self, chunks: list[Chunk], query: str, top_k: int) -> list[Chunk]:
        import numpy as np

        chunk_texts = [c["text"] for c in chunks]
        cache_key = hash("".join(chunk_texts))

        if cache_key in self._cache:
            chunk_vecs = self._cache[cache_key]
        else:
            chunk_vecs = self._model.encode(chunk_texts, normalize_embeddings=True)
            self._cache[cache_key] = chunk_vecs

        query_vec = self._model.encode(query, normalize_embeddings=True)
        scores = (chunk_vecs @ query_vec).tolist()

        scored = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
        ranked = [c for c, _ in scored[:top_k]]
        ranked.sort(key=lambda x: x["index"])
        return ranked

    def _rank_bm25(self, chunks: list[Chunk], query: str, top_k: int) -> list[Chunk]:
        k1, b = 1.5, 0.75
        query_terms = query.lower().split()
        if not query_terms:
            return chunks[:top_k]

        chunk_terms = [c["text"].lower().split() for c in chunks]
        avg_dl = sum(len(t) for t in chunk_terms) / max(len(chunk_terms), 1)
        n_chunks = len(chunks)

        df: dict[str, int] = {}
        for qt in query_terms:
            df[qt] = sum(1 for ct in chunk_terms if qt in ct)

        scored = []
        for i, ct in enumerate(chunk_terms):
            dl = len(ct)
            score = 0.0
            for qt in query_terms:
                tf = ct.count(qt)
                idf = math.log((n_chunks - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
            scored.append((chunks[i], score))

        ranked = [c for c, _ in sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]]
        ranked.sort(key=lambda x: x["index"])
        return ranked

    def clear_cache(self):
        self._cache.clear()


def get_retrieval() -> ContentRetrieval:
    global _CONTENT_RETRIEVAL_INSTANCE
    if _CONTENT_RETRIEVAL_INSTANCE is None:
        _CONTENT_RETRIEVAL_INSTANCE = ContentRetrieval()
    return _CONTENT_RETRIEVAL_INSTANCE


# ── Excerpt building ────────────────────────────────────────────────────────


def build_excerpt(ranked_chunks: list[Chunk], max_chars: int = 12000) -> str:
    """Concatenate top-ranked chunks in original order up to max_chars."""
    total = 0
    selected: list[str] = []
    for chunk in ranked_chunks:
        if total + len(chunk["text"]) > max_chars and selected:
            break
        selected.append(chunk["text"])
        total += len(chunk["text"])
    return "\n\n".join(selected)


# ── Convenience pipeline ────────────────────────────────────────────────────


def process_page(text: str, query: str, max_chars: int = 12000) -> str:
    """Full pipeline: clean → chunk → retrieve → build excerpt.

    Short pages bypass retrieval and return the full text directly.
    """
    if len(text) <= max_chars:
        return text

    cleaned = clean_noise(text)
    chunks = chunk_text(cleaned)
    retrieval = get_retrieval()
    ranked = retrieval.rank_chunks(chunks, query)
    return build_excerpt(ranked, max_chars)
