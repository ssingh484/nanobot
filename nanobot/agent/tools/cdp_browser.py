"""Chrome DevTools Protocol browser session management via pycdp."""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Generator

import httpx
import websockets


class CDPSession:
    """Manages a Chrome browser session via Chrome DevTools Protocol.

    Uses pycdp types for constructing CDP commands and communicates
    with Chrome over a WebSocket connection.
    """

    _instance: "CDPSession | None" = None

    def __init__(self):
        self._ws = None
        self._process: subprocess.Popen | None = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listener_task: asyncio.Task | None = None
        self._user_data_dir: str | None = None

    @classmethod
    async def get_or_create(cls) -> "CDPSession":
        """Return an existing live session or create a new one."""
        if cls._instance is not None and cls._instance._ws is not None:
            try:
                await asyncio.wait_for(cls._instance._ws.ping(), timeout=2)
                return cls._instance
            except Exception:
                try:
                    await cls._instance.close()
                except Exception:
                    pass
        session = CDPSession()
        await session._connect()
        cls._instance = session
        return session

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _connect(self):
        from pycdp import cdp  # noqa: F401 – validates availability

        port = int(os.environ.get("CDP_PORT", "9222"))
        endpoint = os.environ.get("CDP_ENDPOINT", "")
        ws_url = endpoint if endpoint else await self._resolve_ws_url(port)

        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._listener_task = asyncio.create_task(self._listen())

        # Enable essential CDP domains
        await self._raw_send("Page.enable")
        await self._raw_send("DOM.enable")
        await self._raw_send("Runtime.enable")

    async def _resolve_ws_url(self, port: int) -> str:
        try:
            return await self._fetch_ws_url(port)
        except Exception:
            await self._launch_chrome(port)
            for _ in range(10):
                await asyncio.sleep(0.5)
                try:
                    return await self._fetch_ws_url(port)
                except Exception:
                    continue
            raise RuntimeError(f"Chrome failed to start on port {port}")

    async def _fetch_ws_url(self, port: int) -> str:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://127.0.0.1:{port}/json", timeout=2.0)
            targets = r.json()
            for t in targets:
                if t.get("type") == "page":
                    return t["webSocketDebuggerUrl"]
            if targets:
                return targets[0]["webSocketDebuggerUrl"]
        raise RuntimeError("No CDP targets found")

    async def _launch_chrome(self, port: int):
        chrome = self._find_chrome()
        self._user_data_dir = tempfile.mkdtemp(prefix="nanobot_cdp_")
        self._process = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self._user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def _find_chrome() -> str:
        env = os.environ.get("CHROME_PATH", "")
        if env and os.path.isfile(env):
            return env
        for path in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]:
            if os.path.isfile(path):
                return path
        for name in ["google-chrome", "chromium", "chrome"]:
            found = shutil.which(name)
            if found:
                return found
        raise RuntimeError("Chrome not found. Set CHROME_PATH or install Chrome.")

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _raw_send(self, method: str, params: dict | None = None) -> dict:
        """Send a raw CDP command and await its response."""
        if not self._ws:
            raise RuntimeError("CDP session not connected")
        self._msg_id += 1
        msg_id = self._msg_id
        msg: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        await self._ws.send(json.dumps(msg))
        return await asyncio.wait_for(future, timeout=30)

    async def execute(self, cmd: Generator) -> Any:
        """Execute a pycdp command generator.

        pycdp commands are generators that yield a JSON dict to send
        and receive the raw CDP result dict back, then return a typed
        Python object.
        """
        cmd_dict = next(cmd)
        response = await self._raw_send(cmd_dict["method"], cmd_dict.get("params"))
        try:
            cmd.send(response)
        except StopIteration as e:
            return e.value
        return response

    async def _listen(self):
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                msg_id = data.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if "error" in data:
                        fut.set_exception(
                            RuntimeError(
                                data["error"].get("message", json.dumps(data["error"]))
                            )
                        )
                    else:
                        fut.set_result(data.get("result", {}))
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass

    # ------------------------------------------------------------------
    # High-level helpers used by tools
    # ------------------------------------------------------------------

    async def navigate(self, url: str, wait: float = 10.0) -> dict:
        """Navigate to *url* and wait for the page to finish loading."""
        from pycdp import cdp

        result = await self.execute(cdp.page.navigate(url=url))
        if wait > 0:
            try:
                await asyncio.wait_for(self._wait_for_load(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        return result

    async def _wait_for_load(self):
        for _ in range(40):
            state = await self.js_eval("document.readyState")
            if state == "complete":
                return
            await asyncio.sleep(0.25)

    async def js_eval(self, expression: str) -> Any:
        """Evaluate a JavaScript expression and return the value."""
        from pycdp import cdp

        result = await self.execute(
            cdp.runtime.evaluate(
                expression=expression,
                return_by_value=True,
                await_promise=True,
            )
        )
        # pycdp returns (RemoteObject, Optional[ExceptionDetails])
        if isinstance(result, tuple):
            remote_obj = result[0]
            exc = result[1] if len(result) > 1 else None
            if exc:
                raise RuntimeError(str(exc))
            return getattr(remote_obj, "value", None)
        if hasattr(result, "value"):
            return result.value
        # Fallback for raw dict responses
        if isinstance(result, dict):
            return result.get("result", {}).get("value")
        return None

    async def get_text(self) -> str:
        return (await self.js_eval("document.body.innerText")) or ""

    async def get_html(self) -> str:
        return (await self.js_eval("document.documentElement.outerHTML")) or ""

    async def get_title(self) -> str:
        return (await self.js_eval("document.title")) or ""

    async def get_url(self) -> str:
        return (await self.js_eval("window.location.href")) or ""

    async def screenshot_base64(self) -> str:
        """Capture a PNG screenshot and return it as a base64 string."""
        from pycdp import cdp

        result = await self.execute(cdp.page.capture_screenshot(format_="png"))
        if isinstance(result, str):
            return result
        if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
            # Typically returns just the base64 data string
            return str(next(iter(result), ""))
        return str(result) if result else ""

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        if self._user_data_dir and os.path.exists(self._user_data_dir):
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None
        CDPSession._instance = None
