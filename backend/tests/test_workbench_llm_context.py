from types import SimpleNamespace

from backend.services.workbench_llm import (
    CONTEXT_CHARACTER_BUDGET,
    _build_context_window,
    _context_characters,
    _context_usage,
    _merge_usage,
)


def test_context_window_summarizes_old_messages_and_respects_budget():
    messages = [
        SimpleNamespace(role="user" if index % 2 == 0 else "assistant", content=f"消息-{index}: " + "x" * 2_000)
        for index in range(14)
    ]

    summary, recent_messages, updated = _build_context_window("", messages, "当前问题" * 400)

    assert updated is True
    assert "消息-0" in summary
    assert len(recent_messages) < 12
    assert _context_characters(summary, recent_messages, "当前问题" * 400) <= CONTEXT_CHARACTER_BUDGET


def test_context_window_keeps_history_when_under_budget():
    messages = [SimpleNamespace(role="user", content="简短消息")]

    summary, recent_messages, updated = _build_context_window("已有摘要", messages, "当前问题")

    assert updated is False
    assert summary == "已有摘要"
    assert recent_messages == messages


def test_usage_merges_context_estimate_with_provider_tokens():
    usage = _merge_usage(_context_usage(101), {"prompt_tokens": 28, "completion_tokens": 12, "total_tokens": 40})

    assert usage == {
        "context_characters": 101,
        "context_budget": CONTEXT_CHARACTER_BUDGET,
        "context_estimated_tokens": 26,
        "prompt_tokens": 28,
        "completion_tokens": 12,
        "total_tokens": 40,
    }
