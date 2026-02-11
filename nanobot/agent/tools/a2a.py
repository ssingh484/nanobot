"""A2A (Agent-to-Agent) client tool for interacting with remote agents via the A2A protocol."""

import json
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Limit redirects to prevent abuse
MAX_REDIRECTS = 5
REQUEST_TIMEOUT = 60.0
USER_AGENT = "nanobot-a2a-client/0.1"


def _validate_a2a_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


def _agent_card_url(base_url: str) -> str:
    """Derive the agent card URL from a base URL."""
    base = base_url.rstrip("/")
    return f"{base}/.well-known/agent.json"


def _jsonrpc_request(method: str, params: dict[str, Any], req_id: str | None = None) -> dict:
    """Build a JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "id": req_id or str(uuid.uuid4()),
        "method": method,
        "params": params,
    }


class A2ATool(Tool):
    """
    Tool for communicating with remote agents via the A2A protocol.

    Supports discovering agents, sending tasks, checking status, and cancelling.
    """

    name = "a2a"
    description = (
        "Communicate with remote AI agents using the A2A (Agent-to-Agent) protocol. "
        "Actions: discover (get agent card), send (send a task message), "
        "get (check task status/result), cancel (cancel a task)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["discover", "send", "get", "cancel"],
                "description": "Action to perform",
            },
            "url": {
                "type": "string",
                "description": "Base URL of the remote agent (e.g. https://agent.example.com)",
            },
            "message": {
                "type": "string",
                "description": "Message/task to send to the remote agent (for 'send')",
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (for 'get' or 'cancel')",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session ID for multi-turn conversations",
            },
        },
        "required": ["action", "url"],
    }

    async def execute(
        self,
        action: str,
        url: str,
        message: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        is_valid, error_msg = _validate_a2a_url(url)
        if not is_valid:
            return json.dumps({"error": f"Invalid URL: {error_msg}"})

        if action == "discover":
            return await self._discover(url)
        elif action == "send":
            if not message:
                return json.dumps({"error": "Parameter 'message' is required for 'send' action"})
            return await self._send_task(url, message, session_id)
        elif action == "get":
            if not task_id:
                return json.dumps({"error": "Parameter 'task_id' is required for 'get' action"})
            return await self._get_task(url, task_id)
        elif action == "cancel":
            if not task_id:
                return json.dumps({"error": "Parameter 'task_id' is required for 'cancel' action"})
            return await self._cancel_task(url, task_id)
        else:
            return json.dumps({"error": f"Unknown action: {action}"})

    async def _discover(self, base_url: str) -> str:
        """Fetch the agent card from /.well-known/agent.json."""
        card_url = _agent_card_url(base_url)
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=REQUEST_TIMEOUT,
            ) as client:
                r = await client.get(
                    card_url,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                r.raise_for_status()

            card = r.json()
            return json.dumps({
                "status": "ok",
                "agent_card": card,
            }, indent=2)
        except httpx.HTTPStatusError as e:
            return json.dumps({"error": f"HTTP {e.response.status_code}", "url": card_url})
        except Exception as e:
            return json.dumps({"error": str(e), "url": card_url})

    async def _send_task(self, base_url: str, message: str, session_id: str | None) -> str:
        """Send a task to a remote agent using tasks/send."""
        task_id = str(uuid.uuid4())
        sid = session_id or str(uuid.uuid4())

        payload = _jsonrpc_request("tasks/send", {
            "id": task_id,
            "sessionId": sid,
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": message}],
            },
        })

        return await self._rpc_call(base_url, payload)

    async def _get_task(self, base_url: str, task_id: str) -> str:
        """Get task status/result using tasks/get."""
        payload = _jsonrpc_request("tasks/get", {"id": task_id})
        return await self._rpc_call(base_url, payload)

    async def _cancel_task(self, base_url: str, task_id: str) -> str:
        """Cancel a task using tasks/cancel."""
        payload = _jsonrpc_request("tasks/cancel", {"id": task_id})
        return await self._rpc_call(base_url, payload)

    async def _rpc_call(self, base_url: str, payload: dict) -> str:
        """Make a JSON-RPC call to the remote agent."""
        rpc_url = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=REQUEST_TIMEOUT,
            ) as client:
                r = await client.post(
                    rpc_url,
                    json=payload,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                r.raise_for_status()

            result = r.json()

            # Check for JSON-RPC error
            if "error" in result:
                return json.dumps({
                    "error": result["error"],
                    "task_id": payload["params"].get("id"),
                })

            response = result.get("result", result)
            return json.dumps({
                "status": "ok",
                "task_id": payload["params"].get("id"),
                "result": response,
            }, indent=2)
        except httpx.HTTPStatusError as e:
            return json.dumps({
                "error": f"HTTP {e.response.status_code}",
                "url": rpc_url,
                "task_id": payload["params"].get("id"),
            })
        except Exception as e:
            return json.dumps({
                "error": str(e),
                "url": rpc_url,
                "task_id": payload["params"].get("id"),
            })
