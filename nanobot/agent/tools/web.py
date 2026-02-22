"""Web tools: search, fetch, and browser interaction via Exa and Chrome DevTools Protocol (pycdp)."""

import asyncio
import html as html_mod
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html_mod.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _html_to_markdown(raw_html: str) -> str:
    """Best-effort HTML to markdown conversion."""
    text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                  lambda m: f'[{_strip_tags(m[2])}]({m[1]})', raw_html, flags=re.I)
    text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                  lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
    text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
    text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
    text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
    return _normalize(_strip_tags(text))


def _validate_url(url: str) -> tuple[bool, str]:
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


# ---------------------------------------------------------------------------
# Web Search — Exa
# ---------------------------------------------------------------------------


class WebSearchTool(Tool):
    """Search the web using the Exa API."""

    name = "web_search"
    description = "Search the web using Exa. Returns titles, URLs, and text snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {
                "type": "integer",
                "description": "Number of results (1-10)",
                "minimum": 1,
                "maximum": 10,
            },
            "apiKey": {
                "type": "string",
                "description": "Optional Exa API key (overrides configured default)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self.api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self.max_results = max_results
        self._client = None

    def _get_client(self, api_key: str | None = None):
        key = api_key or self.api_key
        if api_key and api_key != self.api_key:
            from exa_py import Exa
            return Exa(api_key=key)
        if self._client is None:
            from exa_py import Exa
            self._client = Exa(api_key=key)
        return self._client

    async def execute(self, query: str, count: int | None = None, apiKey: str | None = None, **kwargs: Any) -> str:
        key = apiKey or self.api_key
        if not key:
            return "Error: EXA_API_KEY not configured. Pass apiKey parameter or set EXA_API_KEY env var."

        try:
            n = min(max(count or self.max_results, 1), 10)
            client = self._get_client(apiKey)

            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                None,
                lambda: client.search_and_contents(query, num_results=n, text=True),
            )

            if not results.results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, r in enumerate(results.results, 1):
                lines.append(f"{i}. {r.title or 'Untitled'}\n   {r.url}")
                if r.text:
                    snippet = r.text[:300].replace("\n", " ")
                    lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


# ---------------------------------------------------------------------------
# Web Fetch — CDP (pycdp)
# ---------------------------------------------------------------------------


class WebFetchTool(Tool):
    """Fetch and extract webpage content via readability (lightweight) or headless Chrome (full rendering)."""

    name = "web_fetch"
    description = (
        "Fetch a URL and extract its content. "
        "Use 'markdown' (default) for a clean readable extraction via readability, "
        "'text' or 'html' for full browser rendering via headless Chrome (CDP)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {
                "type": "string",
                "enum": ["markdown", "text", "html"],
                "default": "markdown",
                "description": (
                    "markdown: lightweight fetch + readability extraction (fast, no JS). "
                    "text: headless Chrome innerText (renders JS). "
                    "html: headless Chrome full DOM (renders JS)."
                ),
            },
            "maxChars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars

    async def execute(
        self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any
    ) -> str:
        max_chars = maxChars or self.max_chars

        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url})

        if extractMode == "markdown":
            return await self._fetch_readability(url, max_chars)
        return await self._fetch_cdp(url, extractMode, max_chars)

    async def _fetch_readability(self, url: str, max_chars: int) -> str:
        """Lightweight HTTP fetch + readability extraction."""
        from readability import Document

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, max_redirects=MAX_REDIRECTS, timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2), "json"
                title = ""
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = _html_to_markdown(doc.summary())
                title = doc.title() or ""
                text = f"# {title}\n\n{content}" if title else content
                extractor = "readability"
            else:
                text, extractor, title = r.text, "raw", ""

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps({
                "url": url,
                "finalUrl": str(r.url),
                "title": title,
                "status": r.status_code,
                "extractor": extractor,
                "truncated": truncated,
                "length": len(text),
                "text": text,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})

    async def _fetch_cdp(self, url: str, mode: str, max_chars: int) -> str:
        """Full browser rendering via headless Chrome CDP."""
        from nanobot.agent.tools.cdp_browser import CDPSession

        try:
            session = await CDPSession.get_or_create()
            await session.navigate(url)

            title = await session.get_title()
            final_url = await session.get_url()

            if mode == "html":
                text = await session.get_html()
            else:
                text = await session.get_text()

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps({
                "url": url,
                "finalUrl": final_url,
                "title": title,
                "extractor": "cdp",
                "truncated": truncated,
                "length": len(text),
                "text": text,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})


# ---------------------------------------------------------------------------
# Web Click — CDP
# ---------------------------------------------------------------------------


class WebClickTool(Tool):
    """Click an element on the current page using Chrome DevTools Protocol."""

    name = "web_click"
    description = (
        "Click an element on the current webpage by CSS selector. "
        "Use after web_fetch to interact with the loaded page."
    )
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the element to click (e.g. 'button.submit', '#login', 'a[href=\"/about\"]')",
            },
        },
        "required": ["selector"],
    }

    async def execute(self, selector: str, **kwargs: Any) -> str:
        from nanobot.agent.tools.cdp_browser import CDPSession

        try:
            session = await CDPSession.get_or_create()
            js = """
                (() => {
                    const el = document.querySelector(SEL);
                    if (!el) return JSON.stringify({success: false, error: 'Element not found: ' + SEL});
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    const desc = el.textContent ? el.textContent.trim().substring(0, 100) : el.tagName;
                    return JSON.stringify({success: true, clicked: desc, tag: el.tagName, url: window.location.href});
                })()
            """.replace("SEL", json.dumps(selector))
            value = await session.js_eval(js)
            return value if isinstance(value, str) else json.dumps({"error": "No result from click"})
        except Exception as e:
            return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Web Type — CDP
# ---------------------------------------------------------------------------


class WebTypeTool(Tool):
    """Type text into an input element on the current page via CDP."""

    name = "web_type"
    description = (
        "Type text into an input field on the current webpage by CSS selector. "
        "Use after web_fetch to fill out forms."
    )
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the input element (e.g. 'input[name=\"q\"]', '#email')",
            },
            "text": {"type": "string", "description": "Text to type into the element"},
            "submit": {
                "type": "boolean",
                "description": "Submit the parent form after typing",
                "default": False,
            },
        },
        "required": ["selector", "text"],
    }

    async def execute(self, selector: str, text: str, submit: bool = False, **kwargs: Any) -> str:
        from nanobot.agent.tools.cdp_browser import CDPSession

        try:
            session = await CDPSession.get_or_create()
            submit_flag = "true" if submit else "false"
            js = """
                (() => {
                    const el = document.querySelector(SEL);
                    if (!el) return JSON.stringify({success: false, error: 'Element not found: ' + SEL});
                    el.focus();
                    el.value = TEXT;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    const desc = el.name || el.id || el.tagName;
                    if (SUBMIT) {
                        const form = el.closest('form');
                        if (form) {
                            form.submit();
                            return JSON.stringify({success: true, typed: desc, submitted: true, url: window.location.href});
                        }
                        return JSON.stringify({success: true, typed: desc, submitted: false, error: 'No parent form found'});
                    }
                    return JSON.stringify({success: true, typed: desc, submitted: false, url: window.location.href});
                })()
            """.replace("SEL", json.dumps(selector)).replace("TEXT", json.dumps(text)).replace("SUBMIT", submit_flag)
            value = await session.js_eval(js)
            return value if isinstance(value, str) else json.dumps({"error": "No result"})
        except Exception as e:
            return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Web Screenshot — CDP
# ---------------------------------------------------------------------------


class WebScreenshotTool(Tool):
    """Take a screenshot of the current page via CDP."""

    name = "web_screenshot"
    description = (
        "Capture a PNG screenshot of the current webpage. "
        "Returns page metadata and a base64-encoded image. "
        "Use after web_fetch to visually inspect the page."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> str:
        from nanobot.agent.tools.cdp_browser import CDPSession

        try:
            session = await CDPSession.get_or_create()
            title = await session.get_title()
            url = await session.get_url()
            data = await session.screenshot_base64()
            return json.dumps({
                "url": url,
                "title": title,
                "format": "png",
                "base64_length": len(data),
                "data": data,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Web Research — Exa (synchronous: polls until done)
# ---------------------------------------------------------------------------


def _format_research_result(result) -> str:
    """Format an Exa ResearchDto into a JSON string."""
    info: dict[str, Any] = {
        "research_id": result.research_id,
        "status": result.status,
        "model": result.model,
        "instructions": result.instructions,
    }
    if result.status == "completed":
        info["output"] = result.output.content
        info["cost"] = {
            "total": result.cost_dollars.total,
            "pages": result.cost_dollars.num_pages,
            "searches": result.cost_dollars.num_searches,
        }
    elif result.status == "failed":
        info["error"] = result.error
    return json.dumps(info)


class WebResearchTool(Tool):
    """Run deep web research using the Exa Research API (synchronous — blocks until finished)."""

    name = "web_research"
    description = (
        "Perform deep web research on a topic using Exa. "
        "Submits a research task and waits for the result (may take minutes). "
        "For long research, prefer web_research_submit + web_research_poll."
    )
    parameters = {
        "type": "object",
        "properties": {
            "instructions": {
                "type": "string",
                "description": "Detailed research instructions describing what to investigate",
            },
            "model": {
                "type": "string",
                "enum": ["exa-research-fast", "exa-research", "exa-research-pro"],
                "default": "exa-research-fast",
                "description": "Research model: fast (quick), standard, or pro (most thorough)",
            },
            "apiKey": {
                "type": "string",
                "description": "Optional Exa API key (overrides configured default)",
            },
        },
        "required": ["instructions"],
    }

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self._client = None

    def _get_client(self, api_key: str | None = None):
        key = api_key or self.api_key
        if api_key and api_key != self.api_key:
            from exa_py import Exa
            return Exa(api_key=key)
        if self._client is None:
            from exa_py import Exa
            self._client = Exa(api_key=key)
        return self._client

    async def execute(
        self, instructions: str, model: str = "exa-research-fast", apiKey: str | None = None, **kwargs: Any
    ) -> str:
        key = apiKey or self.api_key
        if not key:
            return "Error: EXA_API_KEY not configured. Pass apiKey parameter or set EXA_API_KEY env var."

        try:
            client = self._get_client(apiKey)
            loop = asyncio.get_running_loop()

            # Create the task
            task = await loop.run_in_executor(
                None,
                lambda: client.research.create(instructions=instructions, model=model),
            )

            # Poll until finished (default timeout 10 min)
            result = await loop.run_in_executor(
                None,
                lambda: client.research.poll_until_finished(
                    task.research_id, poll_interval=2000, timeout_ms=600000
                ),
            )

            return _format_research_result(result)
        except Exception as e:
            return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Web Research Submit — Exa (async: just submits)
# ---------------------------------------------------------------------------


class WebResearchSubmitTool(Tool):
    """Submit a deep web research task to Exa without waiting for completion."""

    name = "web_research_submit"
    description = (
        "Submit a research task to Exa and return immediately with a research_id. "
        "Use web_research_poll with the returned research_id to check status and retrieve results."
    )
    parameters = {
        "type": "object",
        "properties": {
            "instructions": {
                "type": "string",
                "description": "Detailed research instructions describing what to investigate",
            },
            "model": {
                "type": "string",
                "enum": ["exa-research-fast", "exa-research", "exa-research-pro"],
                "default": "exa-research-fast",
                "description": "Research model: fast (quick), standard, or pro (most thorough)",
            },
            "apiKey": {
                "type": "string",
                "description": "Optional Exa API key (overrides configured default)",
            },
        },
        "required": ["instructions"],
    }

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self._client = None

    def _get_client(self, api_key: str | None = None):
        key = api_key or self.api_key
        if api_key and api_key != self.api_key:
            from exa_py import Exa
            return Exa(api_key=key)
        if self._client is None:
            from exa_py import Exa
            self._client = Exa(api_key=key)
        return self._client

    async def execute(
        self, instructions: str, model: str = "exa-research-fast", apiKey: str | None = None, **kwargs: Any
    ) -> str:
        key = apiKey or self.api_key
        if not key:
            return "Error: EXA_API_KEY not configured. Pass apiKey parameter or set EXA_API_KEY env var."

        try:
            client = self._get_client(apiKey)
            loop = asyncio.get_running_loop()

            task = await loop.run_in_executor(
                None,
                lambda: client.research.create(instructions=instructions, model=model),
            )

            return json.dumps({
                "research_id": task.research_id,
                "status": task.status,
                "model": task.model,
                "instructions": task.instructions,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Web Research Poll — Exa (async: check status / get results)
# ---------------------------------------------------------------------------


class WebResearchPollTool(Tool):
    """Poll an Exa research task by ID to check status and retrieve results."""

    name = "web_research_poll"
    description = (
        "Check the status of a previously submitted Exa research task. "
        "Returns the current status (pending/running/completed/failed) and, "
        "if completed, the research output."
    )
    parameters = {
        "type": "object",
        "properties": {
            "research_id": {
                "type": "string",
                "description": "The research_id returned by web_research_submit",
            },
            "apiKey": {
                "type": "string",
                "description": "Optional Exa API key (overrides configured default)",
            },
        },
        "required": ["research_id"],
    }

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self._client = None

    def _get_client(self, api_key: str | None = None):
        key = api_key or self.api_key
        if api_key and api_key != self.api_key:
            from exa_py import Exa
            return Exa(api_key=key)
        if self._client is None:
            from exa_py import Exa
            self._client = Exa(api_key=key)
        return self._client

    async def execute(self, research_id: str, apiKey: str | None = None, **kwargs: Any) -> str:
        key = apiKey or self.api_key
        if not key:
            return "Error: EXA_API_KEY not configured. Pass apiKey parameter or set EXA_API_KEY env var."

        try:
            client = self._get_client(apiKey)
            loop = asyncio.get_running_loop()

            result = await loop.run_in_executor(
                None,
                lambda: client.research.get(research_id),
            )

            return _format_research_result(result)
        except Exception as e:
            return json.dumps({"error": str(e)})
