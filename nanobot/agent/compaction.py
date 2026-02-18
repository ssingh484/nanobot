"""Message history compaction via summarization."""

import json
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider

SUMMARIZATION_PROMPT = """\
You are a conversation summarizer. Condense the following conversation into a \
concise summary that preserves all important context, decisions, facts, user \
preferences, and pending tasks. Use bullet points. Keep technical details \
(file paths, variable names, code snippets) when they are relevant to ongoing \
work. Omit small talk and routine confirmations. Write in third person \
("The user asked…", "The assistant wrote…")."""


def estimate_tokens(messages: list[dict[str, Any]], model: str) -> int:
    """Estimate the token count for a list of messages.

    Uses litellm's ``token_counter`` when available, falling back to a rough
    character-based heuristic (~4 chars per token).
    """
    try:
        from litellm import token_counter
        return token_counter(model=model, messages=messages)
    except Exception:
        total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        return total_chars // 4


async def summarize_messages(
    provider: LLMProvider,
    messages: list[dict[str, Any]],
    model: str,
) -> str:
    """Ask the LLM to produce a compact summary of *messages*."""
    # Format the conversation for the summarizer
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, list):
            # Multimodal content – extract text parts only
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        # Skip tool-result messages but keep a trace of tool calls
        if role == "tool":
            name = m.get("name", "tool")
            content = content[:300] if len(content) > 300 else content
            lines.append(f"[Tool result: {name}] {content}")
        elif role == "assistant" and m.get("tool_calls"):
            calls = ", ".join(
                tc["function"]["name"] for tc in m["tool_calls"] if "function" in tc
            )
            text = content[:200] if content else ""
            lines.append(f"Assistant (called tools: {calls}): {text}")
        else:
            lines.append(f"{role.capitalize()}: {content}")

    conversation_text = "\n".join(lines)

    summary_messages = [
        {"role": "system", "content": SUMMARIZATION_PROMPT},
        {"role": "user", "content": conversation_text},
    ]

    response = await provider.chat(
        messages=summary_messages,
        tools=None,
        model=model,
        temperature=0.3,
    )
    return response.content or "(empty summary)"


async def maybe_compact(
    messages: list[dict[str, Any]],
    provider: LLMProvider,
    model: str,
    context_window: int,
    threshold_ratio: float = 0.6,
) -> tuple[list[dict[str, Any]], bool]:
    """Check token usage and compact *messages* if necessary.

    Returns ``(messages, compacted)`` where *compacted* is ``True`` when the
    history was replaced with a summary.
    """
    token_count = estimate_tokens(messages, model)
    threshold = int(context_window * threshold_ratio)

    if token_count < threshold:
        return messages, False

    logger.info(
        f"Compaction triggered: {token_count} tokens >= {threshold} "
        f"({threshold_ratio:.0%} of {context_window})"
    )

    # Separate system message from conversation history
    system_msg: dict[str, Any] | None = None
    history = messages
    if messages and messages[0].get("role") == "system":
        system_msg = messages[0]
        history = messages[1:]

    summary = await summarize_messages(provider, history, model)

    # Rebuild messages with the summary replacing full history
    compacted: list[dict[str, Any]] = []
    if system_msg:
        compacted.append(system_msg)
    compacted.append({
        "role": "user",
        "content": (
            "[Conversation summary – earlier messages were compacted]\n\n"
            + summary
        ),
    })
    compacted.append({
        "role": "assistant",
        "content": (
            "Understood. I have the context from our previous conversation "
            "and I'm ready to continue."
        ),
    })

    new_count = estimate_tokens(compacted, model)
    logger.info(f"Compaction complete: {token_count} → {new_count} tokens")
    return compacted, True
