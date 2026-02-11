---
name: a2a
description: "Interact with remote AI agents using the A2A (Agent-to-Agent) protocol. Use when the user wants to discover, communicate with, delegate tasks to, or check status of tasks on external agents accessible via HTTP/HTTPS URLs."
metadata: {"nanobot":{"emoji":"🤝"}}
---

# A2A (Agent-to-Agent) Client

Use the `a2a` tool to communicate with remote AI agents that implement the [A2A protocol](https://google.github.io/A2A/).

## Actions

### Discover a remote agent

Fetch the agent card to learn what the remote agent can do:

```
a2a(action="discover", url="https://agent.example.com")
```

The agent card contains `name`, `description`, `skills`, and `url` (the RPC endpoint). Use the `url` from the card for subsequent `send`/`get`/`cancel` calls — it may differ from the discovery base URL.

### Send a task

Send a message to the remote agent and receive its response:

```
a2a(action="send", url="https://agent.example.com", message="Summarize the latest AI news")
```

The response contains a `task_id` and the agent's result. Save the `task_id` to check status or cancel later.

For multi-turn conversations, pass a `session_id` to maintain context:

```
a2a(action="send", url="https://agent.example.com", message="Tell me more about the first item", session_id="previous-session-id")
```

### Get task status

Check the current status or retrieve the result of a previously sent task:

```
a2a(action="get", url="https://agent.example.com", task_id="abc-123")
```

Task states: `submitted`, `working`, `input-required`, `completed`, `failed`, `canceled`.

### Cancel a task

Cancel a running task:

```
a2a(action="cancel", url="https://agent.example.com", task_id="abc-123")
```

## Typical Workflow

1. **Discover** the remote agent to learn its capabilities and get its RPC endpoint URL.
2. **Send** a task with a clear, specific message.
3. If the task is long-running, **get** its status periodically.
4. If the result has `status: input-required`, send a follow-up using the same `session_id`.

## Tips

- Always `discover` first to verify the agent is reachable and understand its skills.
- Use the `url` field from the agent card as the endpoint for `send`/`get`/`cancel` — it is the actual JSON-RPC endpoint.
- Keep messages self-contained; remote agents don't share your context.
- For multi-step tasks, use `session_id` to maintain conversation continuity, and pass the same `session_id` from the send response.
