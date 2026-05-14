"""Voice match scorer — quantifies how close a draft sounds to the user.

Per docs/00 §你的人格 and CLAUDE.md §moat:
- Three pure metrics (sentence length, vocab overlap, structure)
- Hard ceiling at 80% by design ("uncanny valley is an anti-feature")
- No LLM call — this is a fingerprint algorithm, not a vibe check

The score is a fingerprint of *style*, not meaning. A 78% score means:
"this draft uses sentences of similar length, shares much of the user's
vocabulary, and follows a similar opening→body→closing shape."

Tokenization handles mixed Chinese/English text by overlaying two strategies:
- For Chinese characters (CJK Unified Ideographs): character bigrams.
- For ASCII letters: lowercased whitespace tokens.
Both sides of the comparison run through the same pipeline, so the metric
is consistent regardless of the user's language mix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Per docs/00 / CLAUDE.md: cap by design at 80%. Above this is the uncanny
# valley + creates legal/psychological risk per docs/03 §commercialization.
MAX_VOICE_PCT = 80

# Sentence terminators — Chinese full-width + ASCII
_SENTENCE_SPLIT = re.compile(r"[。!?!?\.\n]+")

_CJK_RE = re.compile(r"[一-鿿]")
_ASCII_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


@dataclass(frozen=True)
class VoiceScore:
    overall_pct: int  # 0-80 inclusive
    length_pct: int  # 0-100 — similarity of avg sentence length
    vocab_pct: int  # 0-100 — Jaccard of bigram + word tokens
    structure_pct: int  # 0-100 — similarity of sentence-count profile
    notes: str  # short human-readable summary

    def explain(self) -> str:
        return (
            f"Voice match: {self.overall_pct}% (capped at {MAX_VOICE_PCT}%)\n"
            f"  length sim:    {self.length_pct}%\n"
            f"  vocab sim:     {self.vocab_pct}%\n"
            f"  structure sim: {self.structure_pct}%\n"
            f"  {self.notes}"
        )


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _tokens(text: str) -> set[str]:
    """Mixed-language tokens: CJK bigrams + lowercased ASCII words."""
    out: set[str] = set()
    # ASCII words
    out.update(_ASCII_WORD_RE.findall(text.lower()))
    # CJK character bigrams (sliding window of 2)
    cjk_chars = "".join(_CJK_RE.findall(text))
    for i in range(len(cjk_chars) - 1):
        out.add(cjk_chars[i : i + 2])
    return out


def _avg_sentence_length(sentences: list[str]) -> float:
    if not sentences:
        return 0.0
    return sum(len(s) for s in sentences) / len(sentences)


def _similarity_from_ratio(a: float, b: float) -> float:
    """1 - |a-b| / max(a, b, 1). Returns 0..1."""
    denom = max(a, b, 1.0)
    return max(0.0, 1.0 - abs(a - b) / denom)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score(candidate: str, user_corpus: str) -> VoiceScore:
    """Compute voice match for `candidate` against the user's historical writing.

    `user_corpus` is the concatenated text of the user's prior messages (one
    long string is fine; sentence boundaries are detected internally). If the
    corpus is empty, we return 0% — there's nothing to match against.
    """
    cand_sentences = _split_sentences(candidate)
    user_sentences = _split_sentences(user_corpus)

    if not user_sentences:
        return VoiceScore(
            overall_pct=0,
            length_pct=0,
            vocab_pct=0,
            structure_pct=0,
            notes="no user corpus to compare",
        )
    if not cand_sentences:
        return VoiceScore(
            overall_pct=0,
            length_pct=0,
            vocab_pct=0,
            structure_pct=0,
            notes="candidate has no sentences",
        )

    cand_avg_len = _avg_sentence_length(cand_sentences)
    user_avg_len = _avg_sentence_length(user_sentences)
    length_sim = _similarity_from_ratio(cand_avg_len, user_avg_len)

    cand_tokens = _tokens(candidate)
    user_tokens = _tokens(user_corpus)
    vocab_sim = _jaccard(cand_tokens, user_tokens)

    # Structure: how close is the candidate's sentence count to the user's
    # average per-message count? We estimate user's average as
    # len(user_sentences) / (rough number of "messages" derived from blank
    # lines in the corpus; default 1).
    msg_separator_count = max(1, user_corpus.count("\n\n") + 1)
    user_avg_sent_per_msg = len(user_sentences) / msg_separator_count
    structure_sim = _similarity_from_ratio(len(cand_sentences), user_avg_sent_per_msg)

    # Equal-weight average, then cap
    overall = (length_sim + vocab_sim + structure_sim) / 3
    overall_pct = min(MAX_VOICE_PCT, int(round(overall * 100)))

    return VoiceScore(
        overall_pct=overall_pct,
        length_pct=int(round(length_sim * 100)),
        vocab_pct=int(round(vocab_sim * 100)),
        structure_pct=int(round(structure_sim * 100)),
        notes=(
            f"corpus={len(user_sentences)} sent, {len(user_tokens)} tokens; "
            f"candidate={len(cand_sentences)} sent, {len(cand_tokens)} tokens"
        ),
    )
