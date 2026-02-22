---
name: web
description: "Search, fetch, interact with, and research web content. Use when the agent needs to: (1) search the web for information, (2) fetch/read a webpage, (3) click elements or fill forms on a page, (4) take screenshots of pages, (5) run deep research on a topic. Covers all web_search, web_fetch, web_click, web_type, web_screenshot, web_research, web_research_submit, and web_research_poll tools."
metadata: {"nanobot":{"emoji":"🌐"}}
---

# Web Tools

Eight tools for web search, content extraction, browser interaction, and deep research.

## Search

```
web_search(query="...", count=5)
```

Uses the Exa API. Returns titles, URLs, and text snippets (up to 10 results). Requires `EXA_API_KEY` in config or pass `apiKey` directly.

All Exa-powered tools accept an optional `apiKey` parameter to override the default key at call time.

## Fetch & Read

```
web_fetch(url="https://example.com", extractMode="markdown")
```

Three extract modes:

| Mode | Engine | JS? | Best for |
|------|--------|-----|----------|
| `markdown` | HTTP + readability | No | Articles, docs, blogs — fast |
| `text` | Headless Chrome (CDP) | Yes | SPAs, JS-rendered pages |
| `html` | Headless Chrome (CDP) | Yes | Raw DOM inspection |

Default is `markdown`. Output truncated at `maxChars` (default 50,000).

## Browser Interaction

After a `web_fetch` with `text` or `html` mode loads a page in Chrome, use these to interact:

### Click
```
web_click(selector="button.submit")
```
CSS selector → scrolls into view → clicks. Returns clicked element info + current URL.

### Type
```
web_type(selector="input[name='q']", text="search query", submit=false)
```
Focus → set value → dispatch input/change events. Set `submit=true` to submit the parent form.

### Screenshot
```
web_screenshot()
```
Returns base64-encoded PNG of the current page. Use to visually verify page state.

## Deep Research

Three tools for Exa's research API:

### Synchronous (blocks until done)
```
web_research(instructions="Research the latest...", model="exa-research-fast")
```
Submits and polls automatically. Good for quick queries. May block for several minutes.

### Asynchronous (submit + poll separately)
```
web_research_submit(instructions="...", model="exa-research-fast")
# → returns { research_id: "..." }

web_research_poll(research_id="...")
# → returns status + results when complete
```
Use for long-running research where you want to do other work while waiting.

**Models:** `exa-research-fast` (quick) · `exa-research` (standard) · `exa-research-pro` (most thorough)

## Common Patterns

**Quick fact lookup:**
```
web_search(query="population of Tokyo 2025")
```

**Read an article:**
```
web_fetch(url="https://example.com/article", extractMode="markdown")
```

**Interact with a JS-heavy site:**
```
web_fetch(url="https://app.example.com", extractMode="text")
web_type(selector="#search", text="query", submit=true)
web_screenshot()
```

**Deep research with followup:**
```
id = web_research_submit(instructions="Comprehensive analysis of...")
# ... do other work ...
web_research_poll(research_id=id)
```

## API Key

Exa tools use the key from config (`tools.web.search.apiKey` or `EXA_API_KEY` env var) by default. To override at call time, pass `apiKey="sk-..."` to any Exa tool (`web_search`, `web_research`, `web_research_submit`, `web_research_poll`).
