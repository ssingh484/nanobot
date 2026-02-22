# Available Tools

This document describes the tools available to Friday.

## File Operations

### read_file
Read the contents of a file.
```
read_file(path: str) -> str
```

### write_file
Write content to a file (creates parent directories if needed).
```
write_file(path: str, content: str) -> str
```

### edit_file
Edit a file by replacing specific text.
```
edit_file(path: str, old_text: str, new_text: str) -> str
```

### list_dir
List contents of a directory.
```
list_dir(path: str) -> str
```

## Shell Execution

### exec
Execute a shell command and return output.
```
exec(command: str, working_dir: str = None) -> str
```

**Safety Notes:**
- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- Optional `restrictToWorkspace` config to limit paths

## Web Access

### web_search
Search the web using the Exa API.
```
web_search(query: str, count: int = 5) -> str
```

Returns search results with titles, URLs, and text snippets. Requires `tools.web.search.apiKey` (Exa API key) in config, or the `EXA_API_KEY` environment variable.

### web_fetch
Fetch and extract content from a URL.
```
web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str
```

**Extract modes:**
- `markdown` (default) — Lightweight HTTP fetch + readability extraction. Fast, no JavaScript rendering. Returns clean readable content.
- `text` — Full headless Chrome rendering via CDP. Returns `document.body.innerText`. Use when the page requires JavaScript.
- `html` — Full headless Chrome rendering via CDP. Returns the complete rendered DOM. Use when you need the raw HTML structure.

**Notes:**
- Output is truncated at 50,000 characters by default

### web_click
Click an element on the current webpage by CSS selector.
```
web_click(selector: str) -> str
```

Use after `web_fetch` to interact with the loaded page. Returns a JSON object with the clicked element info and current URL.

### web_type
Type text into an input field on the current webpage.
```
web_type(selector: str, text: str, submit: bool = false) -> str
```

Use after `web_fetch` to fill out forms. Optionally submits the parent form.

### web_screenshot
Capture a PNG screenshot of the current webpage.
```
web_screenshot() -> str
```

Returns page URL, title, and a base64-encoded PNG image. Use after `web_fetch` to visually inspect the page.

### web_research
Deep web research using Exa (synchronous — blocks until finished).
```
web_research(instructions: str, model: str = "exa-research-fast") -> str
```

Submits a research task and polls until the result is ready. Best for quick research queries. For longer investigations, use the async pair below.

**Models:** `exa-research-fast` (quick), `exa-research` (standard), `exa-research-pro` (most thorough)

### web_research_submit
Submit a research task to Exa without waiting (async submission).
```
web_research_submit(instructions: str, model: str = "exa-research-fast") -> str
```

Returns immediately with a `research_id`. Use `web_research_poll` to check status and retrieve results later.

### web_research_poll
Poll a previously submitted research task by ID.
```
web_research_poll(research_id: str) -> str
```

Returns the current status (`pending`, `running`, `completed`, `failed`) and, if completed, the full research output.

## Communication

### message
Send a message to the user (used internally).
```
message(content: str, channel: str = None, chat_id: str = None) -> str
```

**When to use:** After every autonomous action (heartbeat work, self-built tools/skills, A2A delegations), always message Sid to report what was done.

## A2A (Agent-to-Agent) Delegation

### a2a
Communicate with remote AI agents via the A2A protocol.
```
a2a(action: str, url: str, message: str = None, task_id: str = None, session_id: str = None) -> str
```

**Actions:** `discover`, `send`, `get`, `cancel`

### Delegation Guidelines

Prefer delegating to a specialist A2A agent over doing the work yourself when:

- A registered agent has a skill that directly matches the task
- The task falls outside your primary domains (AppSec, programming, homelabbing, travel, anime, fitness)
- The remote agent has domain-specific training or data you lack
- The task involves a domain where precision matters and a specialist exists

When delegating:

1. **Discover first** — Always `a2a(action="discover", url=...)` before first use to confirm capabilities
2. **Give clear direction** — Write self-contained instructions. The remote agent has no access to your context, memories, or conversation history
3. **Verify the output** — Review the agent's response before delivering to Sid. Check for accuracy, completeness, and relevance
4. **Report back** — Tell Sid which agent you used and why
5. **Maintain the registry** — Keep `memory/AGENTS_REGISTRY.md` up to date with agent URLs, capabilities, and reliability notes

### Agent Registry

Known agents are stored in `memory/AGENTS_REGISTRY.md`. Sid will provide new agent URLs — add them after discovery. Format:

```markdown
## agent-name
- **URL**: https://agent.example.com
- **RPC Endpoint**: https://agent.example.com/rpc (from agent card)
- **Skills**: skill1, skill2
- **Notes**: reliability, quirks, best use cases
- **Last verified**: YYYY-MM-DD
```

## Background Tasks

### spawn
Spawn a subagent to handle a task in the background.
```
spawn(task: str, label: str = None) -> str
```

Use for complex or time-consuming tasks that can run independently. The subagent will complete the task and report back when done.

## Scheduled Reminders (Cron)

Use the `exec` tool to create scheduled reminders with `nanobot cron add`:

### Set a recurring reminder
```bash
# Every day at 9am
nanobot cron add --name "morning" --message "Good morning! ☀️" --cron "0 9 * * *"

# Every 2 hours
nanobot cron add --name "water" --message "Drink water! 💧" --every 7200
```

### Set a one-time reminder
```bash
# At a specific time (ISO format)
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"
```

### Manage reminders
```bash
nanobot cron list              # List all jobs
nanobot cron remove <job_id>   # Remove a job
```

## Heartbeat Task Management

The `HEARTBEAT.md` file in the workspace is checked every **1 hour**.
Use file operations to manage periodic tasks:

### Add a heartbeat task
```python
# Append a new task
edit_file(
    path="HEARTBEAT.md",
    old_text="## Example Tasks",
    new_text="- [ ] New periodic task here\n\n## Example Tasks"
)
```

### Remove a heartbeat task
```python
# Remove a specific task
edit_file(
    path="HEARTBEAT.md",
    old_text="- [ ] Task to remove\n",
    new_text=""
)
```

### Rewrite all tasks
```python
# Replace the entire file
write_file(
    path="HEARTBEAT.md",
    content="# Heartbeat Tasks\n\n- [ ] Task 1\n- [ ] Task 2\n"
)
```

---

## Creating New Tools & Skills (Self-Improvement)

Friday can autonomously create new tools and skills to expand its own capabilities. This is a core part of the heartbeat self-improvement cycle.

### Creating a New Tool

1. Create a new Python file in `nanobot/agent/tools/` (or add to an existing one)
2. Create a class that extends `Tool`
3. Implement the required interface: `name`, `description`, `parameters`, and `execute`
4. Register it in `AgentLoop._register_default_tools()`
5. Update this file (TOOLS.md) with documentation for the new tool
6. **Message Sid** with what was built, why, and how to use it

### Creating a New Skill

Use the `skill-creator` skill for guidance. The short version:

1. Identify a recurring pattern or workflow from conversation history / memories
2. Create a skill directory under `nanobot/skills/<skill-name>/`
3. Write `SKILL.md` with YAML frontmatter (`name`, `description`) and instructions
4. Add optional `scripts/`, `references/`, `assets/` subdirectories as needed
5. Keep SKILL.md concise — the agent is already smart, only add non-obvious knowledge
6. **Message Sid** with what was built, why, and how it triggers

### When to Build vs. Delegate

- If an A2A agent already handles the task well → **delegate**
- If a reusable pattern keeps appearing in conversations → **build a skill**
- If a specific API or automation is needed repeatedly → **build a tool**
- If it's a one-off task → just do it, don't over-engineer
