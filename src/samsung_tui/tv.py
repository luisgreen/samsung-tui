"""Local Samsung Tizen client: REST device info + WebSocket remote control.

Two local interfaces are used, both stock on the TV:

* ``http://<host>:8001/api/v2/``            -- device facts (read-only)
* ``wss://<host>:8002/api/v2/channels/...`` -- remote keys / text / app launch

The WebSocket channel is request-only: it carries no screen framebuffer, so
this client cannot read the UI. Pairing shows a prompt on the TV the first
time; the returned token is persisted and reused.
"""

from __future__ import annotations

import base64
import contextlib
import json
import queue
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import websocket

WS_PORT = 8002
REST_PORT = 8001
CLIENT_NAME = "samsung-tui"


@dataclass
class Event:
    """A message for the UI thread. ``kind`` is status|sent|tv|error."""

    kind: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


class TVClient:
    def __init__(
        self,
        host: str,
        token: str | None = None,
        on_token: Callable[[str | None, str | None], None] | None = None,
    ) -> None:
        self.host = host
        self.token = token
        self.on_token = on_token
        self._name: str | None = None

        self.events: queue.Queue[Event] = queue.Queue()
        self._out: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._ws: websocket.WebSocket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="samsung-tui", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._connected.clear()
        with self._lock:
            ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                ws.close()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3)

    # -- commands ----------------------------------------------------

    def send_key(self, key: str) -> bool:
        return self._enqueue({"type": "key", "key": key})

    def send_text(self, text: str) -> bool:
        return self._enqueue({"type": "text", "text": text})

    def launch_app(self, app_id: str) -> bool:
        return self._enqueue({"type": "app", "app_id": app_id})

    def send_macro(self, keys: list[str], delay: float = 0.35) -> bool:
        return self._enqueue({"type": "macro", "keys": keys, "delay": delay})

    def _enqueue(self, job: dict[str, Any]) -> bool:
        if not self.connected:
            self.events.put(Event("error", "Not connected to the TV"))
            return False
        self._out.put(job)
        return True

    # -- REST --------------------------------------------------------

    def device_info(self, timeout: float = 4.0) -> dict[str, Any]:
        url = f"http://{self.host}:{REST_PORT}/api/v2/"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        device = payload.get("device") or {}
        return {
            "name": device.get("name"),
            "model": device.get("modelName"),
            "os": device.get("OS"),
            "power": device.get("PowerState"),
            "resolution": device.get("resolution"),
            "network": device.get("networkType"),
            "firmware": device.get("firmwareVersion"),
            "developer_mode": device.get("developerMode"),
        }

    # -- worker ------------------------------------------------------

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                name = self._resolve_name()
                if not self._connect(self.token, name):
                    self._stop.wait(2.0)
                    continue
                backoff = 1.0
                self._pump()
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                if self._stop.is_set():
                    break
                self.events.put(Event("status", f"Disconnected: {exc}"))
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 15.0)
            finally:
                self._connected.clear()
                with self._lock:
                    ws, self._ws = self._ws, None
                if ws is not None:
                    with contextlib.suppress(Exception):
                        ws.close()

    def _resolve_name(self) -> str | None:
        """The TV's own name from ``/api/v2/``; cached once known."""
        if self._name:
            return self._name
        try:
            name = self.device_info(timeout=2.0).get("name")
        except Exception:  # noqa: BLE001 - TV may be off; retry next loop
            return None
        if name:
            self._name = str(name)
        return self._name

    def _connect(self, token: str | None, name: str | None) -> bool:
        name = base64.b64encode(CLIENT_NAME.encode()).decode()
        url = (
            f"wss://{self.host}:{WS_PORT}"
            f"/api/v2/channels/samsung.remote.control?name={name}"
        )
        if self.token:
            url += f"&token={token}"

        self.events.put(Event("status", "Connecting…"))
        ws = websocket.create_connection(
            url, timeout=15, sslopt={"cert_reqs": ssl.CERT_NONE}
        )
        ws.settimeout(120)  # long enough for the user to approve on the TV
        with self._lock:
            self._ws = ws  # so stop() can abort a pending approval prompt

        try:
            while not self._stop.is_set():
                raw = ws.recv()
                if not raw:
                    raise ConnectionError("closed during handshake")
                msg = json.loads(raw)
                event = msg.get("event") or msg.get("method")
                if event == "ms.channel.connect":
                    issued = (msg.get("data") or {}).get("token")
                    if issued and issued != token:
                        self.token = issued
                        if self.on_token:
                            self.on_token(name, issued)
                    self._connected.set()
                    self.events.put(Event("status", "Connected"))
                    return True
                if event == "ms.channel.unauthorized":
                    self.token = None
                    if self.on_token:
                        self.on_token(name, None)
                    self.events.put(
                        Event("error", "Pairing denied, or the saved token was rejected")
                    )
                    ws.close()
                    return False
        except websocket.WebSocketTimeoutException as exc:
            ws.close()
            raise TimeoutError(
                "no approval from the TV (accept the prompt on screen, then reconnect)"
            ) from exc
        except Exception:
            ws.close()
            raise

    def _pump(self) -> None:
        ws = self._ws
        if ws is None:
            return
        ws.settimeout(0.25)
        while not self._stop.is_set() and self.connected:
            self._flush(ws)
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                raise ConnectionError("the TV closed the connection")
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            event = msg.get("event") or msg.get("method") or "?"
            if event in ("ms.channel.clientConnect", "ms.channel.clientDisconnect"):
                continue
            self.events.put(Event("tv", str(event), {"payload": msg}))

    def _flush(self, ws: websocket.WebSocket) -> None:
        while True:
            try:
                job = self._out.get_nowait()
            except queue.Empty:
                return

            kind = job["type"]
            if kind == "key":
                payload = {
                    "method": "ms.remote.control",
                    "params": {
                        "Cmd": "Click",
                        "DataOfCmd": job["key"],
                        "Option": "false",
                        "TypeOfRemote": "SendRemoteKey",
                    },
                }
                label = job["key"]
            elif kind == "text":
                payload = {
                    "method": "ms.remote.control",
                    "params": {
                        "Cmd": "SendInputString",
                        "DataOfCmd": base64.b64encode(job["text"].encode()).decode(),
                        "TypeOfRemote": "SendInputString",
                    },
                }
                label = f'text "{job["text"]}"'
            elif kind == "app":
                if self._launch_rest(job["app_id"]):
                    self.events.put(Event("sent", f"app {job['app_id']} (REST)"))
                else:
                    ws.send(
                        json.dumps(
                            {
                                "method": "ms.channel.emit",
                                "params": {
                                    "event": "ed.apps.launch",
                                    "to": "host",
                                    "data": {"appId": job["app_id"]},
                                },
                            }
                        )
                    )
                    self.events.put(Event("sent", f"app {job['app_id']} (WS)"))
                continue
            elif kind == "macro":
                for key in job["keys"]:
                    self._send_key(ws, key)
                    time.sleep(job["delay"])
                self.events.put(Event("sent", "macro " + " > ".join(job["keys"])))
                continue
            else:
                continue

            ws.send(json.dumps(payload))
            self.events.put(Event("sent", label))

    def _launch_rest(self, app_id: str, timeout: float = 3.0) -> bool:
        """Launch via the TV REST endpoint; True when it answers ``true``."""
        url = (
            f"http://{self.host}:{REST_PORT}"
            f"/api/v2/applications/{urllib.parse.quote(app_id)}"
        )
        request = urllib.request.Request(
            url,
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read(32).decode("utf-8", "replace").strip().lower()
                return resp.status == 200 and body.startswith("true")
        except Exception:  # noqa: BLE001 - fall back to the WS event
            return False

    @staticmethod
    def _send_key(ws: websocket.WebSocket, key: str) -> None:
        ws.send(
            json.dumps(
                {
                    "method": "ms.remote.control",
                    "params": {
                        "Cmd": "Click",
                        "DataOfCmd": key,
                        "Option": "false",
                        "TypeOfRemote": "SendRemoteKey",
                    },
                }
            )
        )
