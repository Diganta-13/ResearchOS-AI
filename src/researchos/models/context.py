"""ResearchOS AI — Context Token Manager, Token Estimation & Sliding Window Budgeting."""

from collections.abc import Callable

from researchos.core.exceptions import ModelContextLimitError
from researchos.core.logging import get_logger
from researchos.models.types import (
    ChatMessage,
    ContextBudget,
    ContextDiagnostics,
    MessageRole,
)

logger = get_logger("models.context")


def estimate_tokens(text: str) -> int:
    """
    Conservative token estimation heuristic.

    NOTE: Token counts from this function are conservative heuristics, NOT exact BPE counts.
    Estimates conservatively high to prevent unexpected context overflows on local models.
    """
    if not text:
        return 0

    ascii_chars = 0
    punctuation_count = 0
    non_ascii_chars = 0

    for char in text:
        code = ord(char)
        if code < 128:
            ascii_chars += 1
            if char in "{}[]():;,.!?+-*/=\\<>'\"`~@#$%^&|_":
                punctuation_count += 1
        else:
            non_ascii_chars += 1

    # Standard ASCII text averages ~3.3 chars per token.
    # Code, JSON, and punctuation-heavy prose creates isolated tokens.
    ascii_tokens = max(int(ascii_chars / 3.2), punctuation_count)

    # Multilingual, CJK, and Unicode characters typically map to 1-2 tokens per character
    non_ascii_tokens = int(non_ascii_chars * 1.5)

    estimated = ascii_tokens + non_ascii_tokens
    return max(estimated, 1)


def estimate_message_tokens(
    message: ChatMessage,
    counter: Callable[[str], int] | None = None,
) -> int:
    """
    Estimates total token footprint of a ChatMessage including role envelope framing tokens.
    Framing overhead is estimated at 4 tokens per message (standard ChatML / LLaMA framing).
    """
    count_fn = counter or estimate_tokens
    # 4 framing tokens per message (<|im_start|>role\n ... <|im_end|>\n)
    tokens = 4 + count_fn(message.content)
    if message.name:
        tokens += count_fn(message.name) + 1
    return tokens


def truncate_tool_output(
    content: str,
    max_tokens: int,
    counter: Callable[[str], int] | None = None,
) -> tuple[str, bool]:
    """
    Manages oversized tool execution results.

    Never silently truncates: injects an explicit marker indicating original length,
    preserved character count, and truncation notice so agent/model is aware of omitted content.
    """
    count_fn = counter or estimate_tokens
    current_tokens = count_fn(content)
    if current_tokens <= max_tokens:
        return content, False

    # Budget characters based on conservative 3 chars/token
    target_chars = max(max_tokens * 3, 100)
    orig_chars = len(content)

    # Keep initial head output and ending tail output to preserve execution status/errors
    head_chars = int(target_chars * 0.7)
    tail_chars = int(target_chars * 0.3)

    head = content[:head_chars]
    tail = content[-tail_chars:] if tail_chars > 0 else ""

    notice = (
        f"\n\n[TOOL OUTPUT TRUNCATED: Content exceeded limit of ~{max_tokens} tokens. "
        f"Original size: {orig_chars} chars (~{current_tokens} tokens). "
        f"Preserved first {head_chars} chars and last {tail_chars} chars below.]\n\n"
    )

    truncated = f"{head}{notice}{tail}"
    return truncated, True


class ContextManager:
    """
    Context token manager enforcing conservative token budgeting,
    system prompt preservation, recent turn retention, and tool result sizing.
    """

    def __init__(
        self,
        budget: ContextBudget | None = None,
        token_counter: Callable[[str], int] | None = None,
        max_tool_output_tokens: int = 1200,
    ) -> None:
        self.budget = budget or ContextBudget()
        self.token_counter = token_counter or estimate_tokens
        self.max_tool_output_tokens = max_tool_output_tokens

    def fit_messages(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ContextDiagnostics]:
        """
        Fits conversational messages into the configured context window budget.

        Invariants:
        1. System and developer instructions (MessageRole.SYSTEM) are pinned and NEVER discarded.
        2. The active user request (latest User message + active step messages) is pinned.
        3. Oversized tool results are safely truncated with explicit notice.
        4. Older intermediate conversation turns are pruned via sliding window if budget is exceeded.
        5. If pinned instructions alone exceed max input budget, raises ModelContextLimitError.
        """
        # Validate budget configuration
        max_input_budget = self.budget.max_input_tokens

        if not messages:
            return [], ContextDiagnostics(
                total_input_messages=0,
                retained_messages=0,
                pruned_messages=0,
                estimated_input_tokens=0,
                max_input_budget=max_input_budget,
                context_window=self.budget.context_window,
                max_output_tokens=self.budget.max_output_tokens,
                has_pruned=False,
                truncated_tool_messages=0,
            )

        # 1. First pass: Handle tool output sizing without silent data loss
        processed_messages: list[ChatMessage] = []
        truncated_tools_count = 0

        for msg in messages:
            if msg.role == MessageRole.TOOL:
                truncated_content, was_truncated = truncate_tool_output(
                    msg.content,
                    max_tokens=self.max_tool_output_tokens,
                    counter=self.token_counter,
                )
                if was_truncated:
                    truncated_tools_count += 1
                    processed_messages.append(msg.model_copy(update={"content": truncated_content}))
                else:
                    processed_messages.append(msg)
            else:
                processed_messages.append(msg)

        # 2. Partition messages into System instructions, Historical turns, and Current active turn
        system_messages: list[ChatMessage] = []
        conversation_turns: list[ChatMessage] = []

        for msg in processed_messages:
            if msg.role == MessageRole.SYSTEM:
                system_messages.append(msg)
            else:
                conversation_turns.append(msg)

        # Find boundary of the current active turn (from latest User message to end)
        last_user_index = -1
        for i in range(len(conversation_turns) - 1, -1, -1):
            if conversation_turns[i].role == MessageRole.USER:
                last_user_index = i
                break

        if last_user_index != -1:
            historical_turns = conversation_turns[:last_user_index]
            current_turn = conversation_turns[last_user_index:]
        else:
            # No user message (e.g. only assistant or tool messages)
            historical_turns = conversation_turns[:-1] if conversation_turns else []
            current_turn = conversation_turns[-1:] if conversation_turns else []

        # 3. Calculate mandatory pinned tokens (System instructions + Current turn)
        system_tokens = sum(estimate_message_tokens(m, self.token_counter) for m in system_messages)
        current_turn_tokens = sum(
            estimate_message_tokens(m, self.token_counter) for m in current_turn
        )
        pinned_tokens = system_tokens + current_turn_tokens

        # Check if pinned content alone exceeds the entire input budget
        if pinned_tokens > max_input_budget:
            raise ModelContextLimitError(
                f"Context budget exceeded: Mandatory instructions and current turn require "
                f"~{pinned_tokens} estimated tokens, exceeding maximum input budget of "
                f"{max_input_budget} tokens (context_window={self.budget.context_window}, "
                f"reserved_output={self.budget.max_output_tokens}, safety_margin={self.budget.safety_margin_tokens}). "
                "Reduce prompt size, clear history, or select a model with a larger context window."
            )

        # 4. Sliding window: fit historical messages backwards from newest to oldest
        remaining_budget = max_input_budget - pinned_tokens
        retained_history: list[ChatMessage] = []
        historical_tokens = 0

        for msg in reversed(historical_turns):
            cost = estimate_message_tokens(msg, self.token_counter)
            if historical_tokens + cost <= remaining_budget:
                retained_history.append(msg)
                historical_tokens += cost
            else:
                # Sliding window boundary reached; prune older turns
                break

        # Re-sort retained history into chronological order
        retained_history.reverse()

        # 5. Assemble final message sequence
        final_messages = system_messages + retained_history + current_turn
        total_estimated_tokens = pinned_tokens + historical_tokens
        pruned_count = len(historical_turns) - len(retained_history)

        diagnostics = ContextDiagnostics(
            total_input_messages=len(messages),
            retained_messages=len(final_messages),
            pruned_messages=pruned_count,
            estimated_input_tokens=total_estimated_tokens,
            max_input_budget=max_input_budget,
            context_window=self.budget.context_window,
            max_output_tokens=self.budget.max_output_tokens,
            has_pruned=pruned_count > 0,
            truncated_tool_messages=truncated_tools_count,
        )

        if diagnostics.has_pruned:
            logger.info(
                f"Sliding window pruned {pruned_count} historical messages. "
                f"Estimated tokens: {total_estimated_tokens}/{max_input_budget}."
            )

        return final_messages, diagnostics

    def get_diagnostics(self, messages: list[ChatMessage]) -> ContextDiagnostics:
        """Computes current context window diagnostics without modifying messages."""
        _, diagnostics = self.fit_messages(messages)
        return diagnostics
