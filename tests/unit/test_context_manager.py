"""Unit tests for Context Token Manager, Token Estimation & Sliding Window Budgeting."""

import pytest

from researchos.core.exceptions import ConfigurationError, ModelContextLimitError
from researchos.models.context import (
    ContextManager,
    estimate_message_tokens,
    estimate_tokens,
    truncate_tool_output,
)
from researchos.models.types import (
    ChatMessage,
    ContextBudget,
    MessageRole,
)


def test_empty_conversations():
    mgr = ContextManager(budget=ContextBudget(context_window=4096, max_output_tokens=1024))
    messages, diag = mgr.fit_messages([])
    assert messages == []
    assert diag.total_input_messages == 0
    assert diag.retained_messages == 0
    assert diag.pruned_messages == 0
    assert diag.has_pruned is False
    assert diag.estimated_input_tokens == 0


def test_normal_conversations():
    mgr = ContextManager(budget=ContextBudget(context_window=4096, max_output_tokens=1024))
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="You are a helpful research assistant."),
        ChatMessage(role=MessageRole.USER, content="Hello!"),
        ChatMessage(
            role=MessageRole.ASSISTANT, content="Hello! How can I assist your research today?"
        ),
        ChatMessage(role=MessageRole.USER, content="Explain transformers."),
    ]
    fitted, diag = mgr.fit_messages(msgs)
    assert len(fitted) == 4
    assert diag.pruned_messages == 0
    assert diag.has_pruned is False
    assert diag.estimated_input_tokens > 0
    assert diag.estimated_input_tokens < diag.max_input_budget
    assert [m.content for m in fitted] == [m.content for m in msgs]


def test_context_overflow_sliding_window():
    # Set a tight input budget: window=300, output=100, safety=50 -> input=150
    mgr = ContextManager(
        budget=ContextBudget(context_window=300, max_output_tokens=100, safety_margin_tokens=50)
    )
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="System Prompt."),  # ~8 tokens
        ChatMessage(role=MessageRole.USER, content="Old Turn 1: " + ("data " * 30)),  # ~45 tokens
        ChatMessage(
            role=MessageRole.ASSISTANT, content="Old Ans 1: " + ("text " * 30)
        ),  # ~45 tokens
        ChatMessage(role=MessageRole.USER, content="Old Turn 2: " + ("data " * 30)),  # ~45 tokens
        ChatMessage(
            role=MessageRole.ASSISTANT, content="Old Ans 2: " + ("text " * 30)
        ),  # ~45 tokens
        ChatMessage(role=MessageRole.USER, content="Current user request."),  # ~8 tokens
    ]

    fitted, diag = mgr.fit_messages(msgs)

    # Invariants: System Prompt is preserved; Current request is preserved
    assert fitted[0].role == MessageRole.SYSTEM
    assert fitted[0].content == "System Prompt."
    assert fitted[-1].role == MessageRole.USER
    assert fitted[-1].content == "Current user request."

    # Older turns were pruned to fit within 150 tokens
    assert diag.has_pruned is True
    assert diag.pruned_messages > 0
    assert diag.retained_messages < diag.total_input_messages
    assert diag.estimated_input_tokens <= diag.max_input_budget


def test_multiple_model_context_limits():
    # Router tier: 2048 window
    router_budget = ContextBudget(
        context_window=2048, max_output_tokens=512, safety_margin_tokens=50
    )
    assert router_budget.max_input_tokens == 1486

    # Chat tier: 4096 window
    chat_budget = ContextBudget(
        context_window=4096, max_output_tokens=1024, safety_margin_tokens=50
    )
    assert chat_budget.max_input_tokens == 3022

    # Reasoning tier: 8192 window
    reasoning_budget = ContextBudget(
        context_window=8192, max_output_tokens=2048, safety_margin_tokens=100
    )
    assert reasoning_budget.max_input_tokens == 6044


def test_system_instruction_preservation():
    # Multiple system/developer instructions and security rules
    mgr = ContextManager(
        budget=ContextBudget(context_window=400, max_output_tokens=100, safety_margin_tokens=50)
    )
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="Instruction 1: Persona specification."),
        ChatMessage(
            role=MessageRole.SYSTEM, content="Instruction 2: Security & Approval constraints."
        ),
        ChatMessage(
            role=MessageRole.USER, content="Ancient historical query " + ("long text " * 50)
        ),
        ChatMessage(role=MessageRole.ASSISTANT, content="Ancient answer " + ("word text " * 50)),
        ChatMessage(role=MessageRole.USER, content="Latest active query."),
    ]

    fitted, diag = mgr.fit_messages(msgs)

    # Both system instructions MUST be preserved at the beginning
    assert fitted[0].role == MessageRole.SYSTEM
    assert "Persona" in fitted[0].content
    assert fitted[1].role == MessageRole.SYSTEM
    assert "Security" in fitted[1].content
    assert fitted[-1].content == "Latest active query."
    assert diag.has_pruned is True


def test_recent_message_preservation():
    mgr = ContextManager(
        budget=ContextBudget(context_window=350, max_output_tokens=100, safety_margin_tokens=50)
    )
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="System prompt."),
        ChatMessage(role=MessageRole.USER, content="Turn 1: " + ("xyz " * 20)),
        ChatMessage(role=MessageRole.ASSISTANT, content="Ans 1: " + ("abc " * 20)),
        ChatMessage(role=MessageRole.USER, content="Turn 2: " + ("def " * 10)),
        ChatMessage(role=MessageRole.ASSISTANT, content="Ans 2: " + ("ghi " * 10)),
        ChatMessage(role=MessageRole.USER, content="Recent critical request."),
        ChatMessage(role=MessageRole.TOOL, content="Tool output status=ok"),
    ]

    fitted, _ = mgr.fit_messages(msgs)

    # Recent turn (User request + active tool step) must be preserved
    retained_contents = [m.content for m in fitted]
    assert "Recent critical request." in retained_contents
    assert "Tool output status=ok" in retained_contents


def test_large_tool_outputs():
    # Large tool output of 10,000 characters
    raw_tool_output = (
        "Log line start\n"
        + ("Intermediate debug entry data...\n" * 250)
        + "Final status: SUCCESS exit=0"
    )
    truncated, was_truncated = truncate_tool_output(raw_tool_output, max_tokens=100)

    assert was_truncated is True
    assert "[TOOL OUTPUT TRUNCATED" in truncated
    assert "Original size:" in truncated
    assert "Log line start" in truncated  # Preserves head
    assert "SUCCESS exit=0" in truncated  # Preserves tail

    # In ContextManager
    mgr = ContextManager(
        budget=ContextBudget(context_window=2000, max_output_tokens=500),
        max_tool_output_tokens=100,
    )
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="System."),
        ChatMessage(role=MessageRole.USER, content="Run diagnostics"),
        ChatMessage(role=MessageRole.TOOL, content=raw_tool_output),
    ]

    fitted, diag = mgr.fit_messages(msgs)
    assert diag.truncated_tool_messages == 1
    assert "[TOOL OUTPUT TRUNCATED" in fitted[2].content


def test_unicode_and_multilingual_messages():
    # Chinese, Japanese, German, Emoji
    multilingual = "这是一个测试。こんにちは。Überprüfung mit ÄÖÜ. 🚀✨"
    tokens = estimate_tokens(multilingual)
    # Conservative heuristic counts non-ASCII chars higher
    assert tokens > 15

    msg = ChatMessage(role=MessageRole.USER, content=multilingual)
    msg_tokens = estimate_message_tokens(msg)
    assert msg_tokens >= tokens + 4  # Includes framing tokens


def test_invalid_model_configuration():
    # Output + safety margin exceeds context window
    bad_budget = ContextBudget(context_window=1000, max_output_tokens=1000, safety_margin_tokens=50)
    with pytest.raises(ConfigurationError) as exc_info:
        _ = bad_budget.max_input_tokens
    assert "Invalid context budget" in str(exc_info.value)


def test_oversized_individual_messages():
    # Single user message exceeding entire input budget
    mgr = ContextManager(
        budget=ContextBudget(context_window=500, max_output_tokens=100, safety_margin_tokens=50)
    )
    # Available input budget = 350 tokens. Send ~1000 tokens in one message:
    giant_text = "Massive user prompt block. " * 150
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="System prompt."),
        ChatMessage(role=MessageRole.USER, content=giant_text),
    ]

    with pytest.raises(ModelContextLimitError) as exc_info:
        mgr.fit_messages(msgs)
    assert "Context budget exceeded" in str(exc_info.value)
    assert "exceeding maximum input budget" in str(exc_info.value)


def test_provider_token_counter_extension_point():
    # Mock exact tokenizer
    def mock_exact_counter(text: str) -> int:
        return len(text.split())

    mgr = ContextManager(
        budget=ContextBudget(context_window=1000, max_output_tokens=200),
        token_counter=mock_exact_counter,
    )
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="One two three"),
        ChatMessage(role=MessageRole.USER, content="Four five six seven"),
    ]
    _, diag = mgr.fit_messages(msgs)
    # (4 + 3) + (4 + 4) = 15 tokens
    assert diag.estimated_input_tokens == 15
