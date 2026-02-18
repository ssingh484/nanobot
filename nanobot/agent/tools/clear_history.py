"""Tool for clearing conversation history."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.session.manager import Session


class ClearHistoryTool(Tool):
    """Allows the agent to clear the current session's message history."""

    def __init__(self) -> None:
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        """Bind the tool to the active session."""
        self._session = session

    @property
    def name(self) -> str:
        return "clear_history"

    @property
    def description(self) -> str:
        return (
            "Clear the conversation history for the current session. "
            "Use this after writing a summary to memory so the context "
            "window stays small. The system prompt is not affected."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to confirm clearing history.",
                }
            },
            "required": ["confirm"],
        }

    async def execute(self, confirm: bool = False, **kwargs: Any) -> str:
        if not confirm:
            return "Aborted: confirm must be true to clear history."
        if self._session is None:
            return "Error: no active session."
        count = len(self._session.messages)
        self._session.clear()
        return f"Session history cleared ({count} messages removed)."
