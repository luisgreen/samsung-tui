"""Textual UI for local control of a Samsung Tizen TV."""

from __future__ import annotations

import argparse
import queue
import sys
import time
from typing import Any, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from . import keys
from .apps import APPS, AppEntry
from .config import Config, config_path
from .discovery import TVFound, discover
from .tv import Event, TVClient


class ConfirmScreen(ModalScreen[bool]):
    """Gate for actions that cannot be undone."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, message: str, word: str = "CONFIRM") -> None:
        super().__init__()
        self.message = message
        self.word = word

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self.message, id="confirm-message")
            yield Input(
                placeholder=f"type {self.word} to proceed", id="confirm-input"
            )
            with Horizontal(id="confirm-actions"):
                yield Button("Cancel", id="confirm-cancel")
                yield Button("Proceed", id="confirm-proceed", variant="error")

    def on_mount(self) -> None:
        self.query_one("#confirm-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _submit(self) -> None:
        typed = self.query_one("#confirm-input", Input).value.strip().upper()
        self.dismiss(typed == self.word.upper())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-proceed":
            self._submit()
        else:
            self.dismiss(False)



class DiscoveryScreen(ModalScreen[TVFound | None]):
    """Pick a discovered TV; dismisses with it or None."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Close")]

    def __init__(self, found: list[TVFound]) -> None:
        super().__init__()
        self.found = found
        self._by_id = {"tv-" + tv.ip.replace(".", "-"): tv for tv in found}

    def compose(self) -> ComposeResult:
        with Vertical(id="discovery-box"):
            if self.found:
                yield Static(
                    f"Found {len(self.found)} Samsung TV(s) — pick one",
                    id="discovery-title",
                )
                with VerticalScroll(id="discovery-list"):
                    for tv in self.found:
                        yield Button(
                            tv.label,
                            id="tv-" + tv.ip.replace(".", "-"),
                            classes="tv-btn",
                        )
            else:
                yield Static(
                    "No Samsung TVs found.\n"
                    "Check that the TV is powered on and on this network.",
                    id="discovery-title",
                )
            yield Button("Cancel", id="discovery-cancel")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self._by_id.get(event.button.id or ""))


class SamsungTUI(App):
    TITLE = "samsung-tui"
    SUB_TITLE = "local remote for Samsung Tizen"
    CSS_PATH = "app.tcss"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "reconnect", "Reconnect"),
        Binding("ctrl+d", "discover", "Discover"),
        Binding("f5", "refresh_device", "Refresh"),
        Binding("ctrl+l", "clear_log", "Clear log"),
    ]

    def __init__(self, config: Config, connect: bool = True) -> None:
        super().__init__()
        self.config = config
        self.connect_on_start = connect
        self.tv: TVClient | None = None
        self._app_order: list[AppEntry] = sorted(
            APPS, key=lambda entry: entry.name.casefold()
        )
        self._device: dict[str, Any] = {}
        self._connection_text = ""

    # -- layout ------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("starting…", id="statusbar")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static("REMOTE", classes="section")
                with Grid(id="dpad"):
                    yield Static("", classes="blank")
                    yield Button("▲", id="key-UP", classes="pad")
                    yield Static("", classes="blank")
                    yield Button("◀", id="key-LEFT", classes="pad")
                    yield Button("OK", id="key-ENTER", variant="primary", classes="pad")
                    yield Button("▶", id="key-RIGHT", classes="pad")
                    yield Static("", classes="blank")
                    yield Button("▼", id="key-DOWN", classes="pad")
                    yield Static("", classes="blank")

                with Horizontal(classes="row"):
                    yield Button("Back", id="key-RETURN")
                    yield Button("Home", id="key-HOME")
                    yield Button("Exit", id="key-EXIT")
                    yield Button("⏻", id="key-POWER", variant="error")

                with Horizontal(classes="row"):
                    yield Button("Menu", id="key-MENU")
                    yield Button("Source", id="key-SOURCE")
                    yield Button("Guide", id="key-GUIDE")
                    yield Button("⚙", id="macro-settings")

                with Horizontal(classes="row"):
                    yield Static("Vol", classes="inlabel")
                    yield Button("−", id="key-VOLDOWN")
                    yield Button("Mute", id="key-MUTE")
                    yield Button("+", id="key-VOLUP")

                with Horizontal(classes="row"):
                    yield Static("Ch", classes="inlabel")
                    yield Button("−", id="key-CHDOWN")
                    yield Button("+", id="key-CHUP")

                with Horizontal(classes="row"):
                    yield Button("⏮", id="key-REWIND")
                    yield Button("⏯", id="key-PLAY")
                    yield Button("⏸", id="key-PAUSE")
                    yield Button("⏹", id="key-STOP")
                    yield Button("⏭", id="key-FF")

            with Vertical(id="right"), TabbedContent(initial="tab-apps"):
                with TabPane("Apps", id="tab-apps"):
                    yield Input(placeholder="search apps or IDs…", id="app-search")
                    with VerticalScroll(id="app-scroll"), Grid(id="app-grid"):
                        for index, entry in enumerate(self._app_order):
                            yield Button(
                                entry.name,
                                id=f"app-{index}",
                                classes="app-btn",
                                tooltip=f"{entry.name} — {entry.app_id}",
                            )
                    with Horizontal(id="custom-app"):
                        yield Input(
                            placeholder="custom ID (use for alternates)",
                            id="custom-app-id",
                        )
                        yield Button("Launch", id="launch-custom", variant="primary")

                with TabPane("Text", id="tab-text"):
                    yield Static(
                        "Sends text to the focused field on the TV "
                        "(open a search box first).",
                        classes="hint",
                    )
                    with Horizontal(id="text-row"):
                        yield Input(placeholder="text to type…", id="text-input")
                        yield Button("Send", id="send-text", variant="primary")

                with TabPane("Device", id="tab-device"):
                    yield Static("reading device info…", id="device-detail")

                with TabPane("Service", id="tab-service"):
                    yield Static(
                        "[bold red]Destructive area.[/] These are real presses on "
                        "the real TV, and this channel cannot read the screen — "
                        "navigation here is blind.",
                        classes="warn",
                    )
                    yield Static("Service menu", classes="section")
                    yield Button(
                        "Open service menu  (MUTE 1 8 2 POWER)",
                        id="service-menu",
                        variant="error",
                    )
                    yield Static(
                        "Model- and firmware-specific; unverified on the CU7000. "
                        "It power-cycles the set. Once inside, every option is "
                        "reachable with the D-pad, including factory reset and "
                        "EEPROM/ADC writes. Nothing is automated after entry: you "
                        "drive, and Back/Exit leaves without saving.",
                        classes="hint",
                    )
                    yield Static("Arbitrary key sequence", classes="section")
                    with Horizontal(id="sequence-row"):
                        yield Input(
                            placeholder="space separated, e.g. MUTE 1 8 2 POWER",
                            id="sequence",
                        )
                        yield Button(
                            "Send", id="send-sequence", variant="warning"
                        )
                    yield Static(
                        "Bare names resolve via keys.py (UP, HOME, MUTE, POWER, "
                        "INFO, digits…); KEY_* passes through verbatim. "
                        f"Max {keys.MAX_SEQUENCE} keys.",
                        classes="hint",
                    )
                    yield Static("Not automated here", classes="section")
                    yield Static(
                        "• Factory reset is Settings → General y privacidad → "
                        "Restablecer (default PIN 0000). The TV runs its own "
                        "confirmation; this TUI does not press it.\n"
                        "• EEPROM/ADC writes are service-menu items, not key "
                        "codes — there is no API primitive for them, only blind "
                        "navigation to them. That is why no button does it.",
                        classes="hint",
                    )

                with TabPane("Log", id="tab-log"):
                    yield RichLog(id="log", highlight=False, markup=True, wrap=True)
                    yield Button("Clear log", id="clear-log")
        yield Footer()

    # -- lifecycle ---------------------------------------------------

    def on_mount(self) -> None:
        self._render_status()
        if self.connect_on_start:
            if self.config.current():
                self._start_client()
            else:
                # First run (or an empty config): find TVs, then let the user pick.
                self.call_after_refresh(self.action_discover)
        self.set_interval(0.2, self._drain_events)
        self.set_interval(20.0, self.action_refresh_device)
        self.action_refresh_device()
        self._log(
            "[dim]samsung-tui ready — first connection shows a prompt on the TV[/]"
        )

    def on_unmount(self) -> None:
        if self.tv:
            self.tv.stop()

    def _start_client(self) -> None:
        if self.tv:
            self.tv.stop()
        record = self.config.current()
        if record is None:
            self._render_status()
            return
        self.tv = TVClient(record.host, record.token, on_token=self._save_token)
        self.tv.start()
        self._render_status()

    def _save_token(self, name: str | None, token: str | None) -> None:
        """Runs on the TV worker thread."""
        record = self.config.current()
        if record is None:
            return
        if name:
            self.config.select(name, record.host)
        key = name or self.config.active or record.host
        self.config.set_token(key, token)
        try:
            self.config.save()
        except OSError as exc:
            if self.tv:
                self.tv.events.put(Event("error", f"could not save token: {exc}"))

    # -- events ------------------------------------------------------

    def _drain_events(self) -> None:
        if not self.tv:
            return
        while True:
            try:
                event = self.tv.events.get_nowait()
            except queue.Empty:
                return
            self._handle_event(event)

    def _handle_event(self, event: Event) -> None:
        if event.kind == "status":
            self._connection_text = event.message
            self._render_status()
            self._log(f"[dim]{event.message}[/]")
        elif event.kind == "error":
            self._log(f"[red]{event.message}[/]")
            self.notify(event.message, severity="error")
        elif event.kind == "sent":
            self._log(f"[cyan]→[/] {event.message}")
        elif event.kind == "tv":
            self._log(f"[magenta]←[/] {event.message}")

    def _render_status(self) -> None:
        connected = bool(self.tv and self.tv.connected)
        dot = "[green]●[/]" if connected else "[red]●[/]"
        record = self.config.current()
        address = record.host if record else "no TV selected"
        parts = [f"{dot} {address}"]
        device = self._device
        for key in ("name", "model", "os"):
            if device.get(key):
                parts.append(str(device[key]))
        if device.get("power"):
            parts.append(f"power={device['power']}")
        if device.get("resolution"):
            parts.append(str(device["resolution"]))
        if not connected and self._connection_text:
            parts.append(self._connection_text)
        for bar in self.query("#statusbar"):
            bar.update("  ·  ".join(parts))

    def _log(self, message: str) -> None:
        line = f"[dim]{time.strftime('%H:%M:%S')}[/] {message}"
        for log in self.query("#log"):
            log.write(line)

    # -- actions -----------------------------------------------------

    def action_reconnect(self) -> None:
        self._log("[yellow]reconnecting…[/]")
        self._start_client()
        self.action_refresh_device()

    def action_clear_log(self) -> None:
        for log in self.query("#log"):
            log.clear()

    def action_discover(self) -> None:
        self.notify("Scanning the LAN for Samsung TVs…", timeout=4)
        self._run_discovery()

    @work(thread=True, exclusive=True, group="discover")
    def _run_discovery(self) -> None:
        try:
            record = self.config.current()
            found = discover(base_ip=record.host if record else None)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            message = f"Scan failed: {exc}"
            self.call_from_thread(lambda: self.notify(message, severity="error"))
            return
        self.call_from_thread(self._show_discovery, found)

    def _show_discovery(self, found: list[TVFound]) -> None:
        self.push_screen(DiscoveryScreen(found), self._on_host_chosen)

    def _on_host_chosen(self, tv: TVFound | None) -> None:
        if tv is None:
            return
        name = tv.name or tv.ip
        record = self.config.select(name, tv.ip)
        self.config.save()
        note = (
            "reusing its cached token"
            if record.token
            else "approve the prompt on that TV"
        )
        self._log(f"[green]switched to {name} ({tv.ip}) — {note}[/]")
        self._start_client()
        self.action_refresh_device()

    def action_refresh_device(self) -> None:
        self.refresh_device()

    @work(thread=True, exclusive=True, group="device")
    def refresh_device(self) -> None:
        tv = self.tv
        if tv is None:
            return
        try:
            info = tv.device_info()
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._log, f"[yellow]device info: {exc}[/]")
            return
        self.call_from_thread(self._apply_device, info)

    def _apply_device(self, info: dict[str, Any]) -> None:
        self._device = info
        name = info.get("name")
        record = self.config.current()
        changed = False
        if name and record is not None:
            changed = self.config.remember(str(name), record.host)
        if changed:
            try:
                self.config.save()
            except OSError:
                pass
        self._render_status()
        rows = [
            ("Name", info.get("name")),
            ("Model", info.get("model")),
            ("OS", info.get("os")),
            ("Power", info.get("power")),
            ("Resolution", info.get("resolution")),
            ("Network", info.get("network")),
            ("Firmware", info.get("firmware")),
            ("Developer mode", info.get("developer_mode")),
            ("Address", record.host if record else "—"),
        ]
        body = "\n".join(
            f"[bold]{label:<15}[/] {value if value not in (None, '') else '—'}"
            for label, value in rows
        )
        for detail in self.query("#device-detail"):
            detail.update(body)

    # -- app catalog ------------------------------------------------

    def _visible_apps(self) -> list[AppEntry]:
        return [
            entry
            for entry, button in zip(self._app_order, self.query(".app-btn"))
            if button.display
        ]

    def _filter_apps(self, query: str = "") -> None:
        term = query.strip().lower()
        for entry, button in zip(self._app_order, self.query(".app-btn")):
            button.display = (
                not term
                or term in entry.name.lower()
                or any(term in app_id for app_id in entry.ids)
            )
        for scroll in self.query("#app-scroll"):
            scroll.scroll_home(animate=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "app-search":
            self._filter_apps(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "app-search":
            event.stop()
            visible = self._visible_apps()
            if visible:
                self._launch(visible[0].app_id)

    # -- input -------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("key-"):
            name = button_id[4:]
            self._send_key(keys.ALL.get(name, name))
        elif button_id.startswith("app-"):
            index = int(button_id[4:])
            if 0 <= index < len(self._app_order):
                self._launch(self._app_order[index].app_id)
        elif button_id == "macro-settings":
            self._send_macro(keys.OPEN_SETTINGS)
        elif button_id == "service-menu":
            self._confirm(
                "This sends MUTE 1 8 2 POWER.\n\n"
                "The TV will power-cycle. The sequence is model-specific and\n"
                "unverified on this CU7000; after entry everything is blind.\n\n"
                "Type SERVICE to proceed.",
                lambda: self._send_macro(keys.SERVICE_MENU),
                word="SERVICE",
            )
        elif button_id == "send-sequence":
            self._send_custom_sequence()
        elif button_id == "launch-custom":
            value = self.query_one("#custom-app-id", Input).value.strip()
            if value:
                self._launch(value)
        elif button_id == "send-text":
            field = self.query_one("#text-input", Input)
            if field.value and self.tv:
                self.tv.send_text(field.value)
                field.value = ""
        elif button_id == "clear-log":
            self.action_clear_log()

    def _send_key(self, key: str) -> None:
        if not (self.tv and self.tv.connected):
            self.notify("Not connected to the TV", severity="warning")
            return
        self.tv.send_key(key)

    def _send_macro(self, sequence: list[str], delay: float = 0.35) -> None:
        if not (self.tv and self.tv.connected):
            self.notify("Not connected to the TV", severity="warning")
            return
        self.tv.send_macro(sequence, delay=delay)

    def _send_custom_sequence(self) -> None:
        raw = self.query_one("#sequence", Input).value
        try:
            sequence = keys.resolve_sequence(raw)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        if not sequence:
            self.notify("Nothing to send", severity="warning")
            return
        self._send_macro(sequence)

    def _confirm(self, message: str, callback: Any, word: str = "CONFIRM") -> None:
        self.push_screen(
            ConfirmScreen(message, word),
            lambda ok: callback() if ok else None,
        )

    def _launch(self, app_id: str) -> None:
        if not (self.tv and self.tv.connected):
            self.notify("Not connected to the TV", severity="warning")
            return
        self.tv.launch_app(app_id)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="samsung-tui", description="Local remote control for Samsung Tizen TVs"
    )
    parser.add_argument("--host", help="TV IP address (overrides the saved config)")
    parser.add_argument(
        "--probe", action="store_true", help="print device info and exit"
    )
    parser.add_argument(
        "--reset-token",
        action="store_true",
        help="forget the active TV's pairing token",
    )
    parser.add_argument(
        "--no-connect", action="store_true", help="start the UI without connecting"
    )
    parser.add_argument(
        "--scan", action="store_true", help="scan the LAN for Samsung TVs and exit"
    )
    parser.add_argument(
        "--subnet",
        help="CIDR to scan (default: /24 of the active TV, else this machine's LAN)",
    )
    args = parser.parse_args(argv)

    config = Config.load()
    if not config_path().exists():
        config.save()  # initialize an empty config on first run

    if args.host:
        # Keyed by address until the TV reports its name.
        config.select(args.host, args.host)
    if args.reset_token:
        record = config.current()
        if record is not None:
            config.set_token(config.active, None)
            config.save()

    if args.scan:
        record = config.current()
        found = discover(
            base_ip=record.host if record else None, subnet=args.subnet
        )
        if not found:
            print("no Samsung TVs found", file=sys.stderr)
            raise SystemExit(1)
        for tv in found:
            print(f"{tv.ip:15}  {tv.name:24}  {tv.model}")
        return

    if args.probe:
        record = config.current()
        if record is None:
            print("no TV configured; run --scan first", file=sys.stderr)
            raise SystemExit(1)
        client = TVClient(record.host, record.token)
        try:
            info = client.device_info()
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        for label, value in info.items():
            print(f"{label:16} {value}")
        return

    SamsungTUI(config, connect=not args.no_connect).run()


if __name__ == "__main__":
    main()
