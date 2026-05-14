from __future__ import annotations

from pathlib import Path

from src import kill_switch as ks


def test_keyword_exact_match():
    assert ks.is_keyword("STOP")
    assert ks.is_keyword("緊急停止")
    assert ks.is_keyword("KILL")


def test_keyword_with_surrounding_whitespace():
    assert ks.is_keyword("  STOP  ")
    assert ks.is_keyword("\n緊急停止\n")


def test_keyword_no_partial_match():
    # "stop" inside a sentence must NOT trigger
    assert not ks.is_keyword("please stop the email")
    assert not ks.is_keyword("STOP IT NOW")  # not a standalone keyword
    assert not ks.is_keyword("kill")  # case-sensitive per docs/00


def test_flag_file(tmp_path: Path):
    flag = tmp_path / "KILL.flag"
    assert not ks.flag_present(flag)
    flag.touch()
    assert ks.flag_present(flag)


def test_triggered_combines_both_paths(tmp_path: Path):
    flag = tmp_path / "KILL.flag"
    assert not ks.triggered("hello", flag)
    assert ks.triggered("STOP", flag)
    flag.touch()
    assert ks.triggered("hello", flag)


def test_stop_reply_format():
    assert ks.stop_reply("送信給 alice@") == "✋ 已停止。最後一筆 [送信給 alice@]"
    assert ks.stop_reply() == "✋ 已停止。最後一筆 [無]"
