from __future__ import annotations

from src.voice_scorer import MAX_VOICE_PCT, score


def test_identical_text_caps_at_80():
    text = "週五交付沒問題。明天再對一次規格。"
    s = score(text, text)
    assert s.overall_pct == MAX_VOICE_PCT
    # All sub-metrics should be at or near 100%
    assert s.length_pct == 100
    assert s.vocab_pct == 100
    assert s.structure_pct == 100


def test_empty_user_corpus_is_zero():
    s = score("anything", "")
    assert s.overall_pct == 0
    assert "no user corpus" in s.notes


def test_empty_candidate_is_zero():
    s = score("", "previous user writing here")
    assert s.overall_pct == 0
    assert "no sentences" in s.notes


def test_completely_different_text_scores_low():
    user = "週五交付。明天對規格。"
    candidate = "Lorem ipsum dolor sit amet consectetur."
    s = score(candidate, user)
    # Different language + different rhythm → low vocab, may still partial-match on length
    assert s.vocab_pct == 0
    assert s.overall_pct < 50


def test_overall_never_exceeds_max():
    """Even on perfect identity we cap at MAX_VOICE_PCT — the uncanny-valley guard."""
    s = score("hello world", "hello world")
    assert s.overall_pct <= MAX_VOICE_PCT


def test_partial_overlap_scores_in_between():
    user = "週五交付沒問題。明天對規格。"
    # Same opening phrase, different ending
    candidate = "週五交付沒問題。下週再聯絡。"
    s = score(candidate, user)
    assert 30 < s.overall_pct <= MAX_VOICE_PCT


def test_length_similarity_punishes_big_gap():
    user = "好。"  # 1 sentence, length 1
    candidate = (
        "我認為這個方案需要更多時間討論,因為涉及多個利害關係人,"
        "並且預算需要重新審視,執行時程也要重新規劃。"
    )  # 1 sentence, much longer
    s = score(candidate, user)
    # average sentence lengths should differ → length_pct small
    assert s.length_pct < 30


def test_mixed_chinese_english_tokens_count_both():
    """Mixed text should produce tokens from both pipelines."""
    user = "Ship it 週五交付"
    candidate = "Ship it 週五交付"
    s = score(candidate, user)
    # Both ASCII word "ship", "it" and CJK bigram "週五" / "五交" / "交付" should match
    assert s.vocab_pct == 100


def test_explain_renders_all_components():
    s = score("週五交付。", "週五交付。明天對規格。")
    text = s.explain()
    assert "Voice match:" in text
    assert "length sim:" in text
    assert "vocab sim:" in text
    assert "structure sim:" in text


def test_user_avg_uses_message_separators():
    """The structure metric should use blank-line-separated messages as msg count."""
    user_two_messages = "第一句。第二句。\n\n第三句。第四句。"
    # User averages 2 sentences/message. Candidate with 2 sentences should score high.
    matching = score("一句。兩句。", user_two_messages)
    mismatching = score("只有一句話。", user_two_messages)
    assert matching.structure_pct > mismatching.structure_pct
