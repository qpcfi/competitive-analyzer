"""去噪 → 分块 → Embedding 检索 → excerpt 组装"""

import math
import re
from typing import Any, TypedDict


class Chunk(TypedDict):
    text: str
    index: int


# ── Noise cleaning ──────────────────────────────────────────────────────────

# Line-level: entire lines matching these patterns are removed
NOISE_PATTERNS = [
    # English boilerplate
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
    # Chinese — copyright / legal
    r"(版权所有|保留所有权利|侵权必究|本网站所有)",
    r"(免责声明|免责条款|用户协议|服务条款|隐私政策|隐私声明)",
    r"(未经.*许可.*转载|转载.*请联系)",
    # Chinese — subscription / registration
    r"(免费订阅|邮件订阅|订阅我们|订阅\s*(周刊|邮件|资讯))",
    r"(免费注册|立即注册|注册\s*(即|账号|会员|帐号))",
    # Chinese — comments
    r"(发表评论|提交评论|查看全部评论)",
    # Chinese — navigation / chrome
    r"(网站导航|站点导航|主导航|面包屑)",
    r"(关于我们|联系我们|商务合作|加入我们|诚聘英才)",
    r"(友情链接|合作伙伴|相关推荐|猜你喜欢|为您推荐)",
    r"(热门文章|推荐文章|最新文章|相关文章)",
    r"(下一页|上一页|返回顶部|加载更多|更多\s*(文章|资讯))",
    r"(分享到|一键分享|转发到|分享至)",
    r"(意见反馈|投诉建议|帮助中心|常见问题)",
    # Chinese — follow / QR code
    r"(扫码\s*(关注|阅读)|长按\s*(识别|扫码)|关注\s*(我们|公众号))",
    # Chinese — ads
    r"(广告投放|广告合作|招商)",
    # Markdown artifact lines
    r"^\|[\s:-]+\|[\s:-]+.*$",         # table separator |---|---|
    r"^\[\d+\]:\s+https?://",           # reference link [1]: url
]

# Inline: patterns applied to the text of surviving lines
INLINE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # markdown image ![alt](url) → remove entirely (must come before link pattern)
    (re.compile(r"!\[([^\]]*)\]\(https?://[^)]+\)"), ""),
    # autolink <https://...>
    (re.compile(r"<https?://[^>]+>"), ""),
    # markdown link [text](url) → keep text only
    (re.compile(r"\[([^\]]*)\]\(https?://[^)]+\)"), r"\1"),
    # bare URL (with Chinese punctuation as additional boundaries)
    (re.compile(r"https?://[^\s\)\]\"'>，。、；：]+"), ""),
    # heading markers
    (re.compile(r"^#{1,6}\s+"), ""),
]


def clean_noise(text: str, min_line_length: int = 15) -> str:
    """Remove navigation, copyright, ads, URLs, and other noisy content.

    Preserves paragraph boundaries (``\\n\\n``) so downstream ``chunk_text``
    can still split on meaningful section breaks.
    """
    if not text:
        return ""

    lines = text.split("\n")
    cleaned: list[str] = []
    gap = False  # whether we just passed a removed/empty line
    for line in lines:
        raw = line.strip()

        # Track gaps (blank lines, short lines, noise) without consuming them
        if not raw:
            gap = True
            continue

        if len(raw) < min_line_length:
            gap = True
            continue

        if any(re.search(p, raw, re.IGNORECASE) for p in NOISE_PATTERNS):
            gap = True
            continue

        # Clean inline noise (URLs, markdown syntax)
        for pattern, repl in INLINE_PATTERNS:
            raw = pattern.sub(repl, raw)

        raw = raw.strip()
        if not raw or len(raw) < min_line_length:
            gap = True
            continue

        # Insert paragraph separator when a gap preceded this content
        if gap and cleaned:
            cleaned.append("")  # becomes \n\n when joined
        cleaned.append(raw)
        gap = False

    # Strip trailing empty lines
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
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


# ── CJK-aware tokenization ──────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Tokenize text with CJK character-bigram support.

    Chinese text lacks word boundaries, so plain ``.split()`` treats an entire
    sentence as a single token — useless for BM25 term matching.
    This function detects CJK-dominant words and splits them into overlapping
    character bigrams, giving meaningful term overlap without an external
    Chinese segmenter.
    """
    tokens: list[str] = []
    for word in text.lower().split():
        cjk_count = sum(1 for c in word if "一" <= c <= "鿿")
        if cjk_count > len(word) * 0.5 and len(word) > 1:
            for i in range(len(word) - 1):
                tokens.append(word[i : i + 2])
        elif word:
            tokens.append(word)
    return tokens


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
        query_terms = _tokenize(query)
        if not query_terms:
            return chunks[:top_k]

        chunk_terms = [_tokenize(c["text"]) for c in chunks]
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


def process_page(text: str, query: str, max_chars: int = 4000) -> str:
    """Full pipeline: clean → chunk → retrieve → build excerpt.

    Noise cleaning always runs. Short pages skip chunk+retrieval.
    """
    cleaned = clean_noise(text)
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    chunks = chunk_text(cleaned)
    retrieval = get_retrieval()
    ranked = retrieval.rank_chunks(chunks, query)
    return build_excerpt(ranked, max_chars)
