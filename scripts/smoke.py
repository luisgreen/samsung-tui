"""Headless smoke test: mount the UI without touching the TV."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from samsung_tui import keys
from samsung_tui.app import ConfirmScreen, DiscoveryScreen, SamsungTUI
from samsung_tui.apps import APPS, by_name, search
from samsung_tui.config import Config
from samsung_tui.discovery import TVFound


async def main() -> None:
    app = SamsungTUI(Config(), connect=False)
    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.pause()
        for selector in (
            "#dpad",
            "#log",
            "#statusbar",
            "#app-grid",
            "#app-scroll",
            "#app-search",
            "#device-detail",
            "#service-menu",
            "#sequence",
        ):
            assert app.query_one(selector) is not None, selector

        # App catalog: embedded in code, not in the TV config.
        assert len(APPS) >= 140, len(APPS)
        assert by_name("Netflix") is not None
        assert by_name("Netflix").app_id == "3201907018807"
        assert by_name("Internet").app_id == "3202010022079"
        assert any(a.name == "YouTube" for a in search("youtube"))
        assert any(a.name == "Netflix" for a in search("3201907018807"))

        # Buttons, ordered by name, one per catalog entry.
        names = [button.label.plain for button in app.query(".app-btn")]
        assert len(names) == len(APPS), (len(names), len(APPS))
        assert names == sorted(names, key=str.casefold), "apps must be name-ordered"

        app._filter_apps("netflix")
        await pilot.pause()
        assert [entry.name for entry in app._visible_apps()] == ["Netflix"]
        app._filter_apps("")

        assert keys.resolve_sequence("MUTE 1 8 2 POWER") == keys.SERVICE_MENU
        assert keys.resolve_sequence("home, KEY_VOLUP") == ["KEY_HOME", "KEY_VOLUP"]
        try:
            keys.resolve_sequence("NOPE")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown key should raise")

        with TemporaryDirectory() as tmp:
            empty = Config.load(Path(tmp) / "missing.json")
            assert empty.current() is None
            assert empty.tvs == {}

            path = Path(tmp) / "config.json"
            config = Config()
            config.select("Living Room", "192.168.1.50")
            config.set_token("Living Room", "token-a")
            config.select("Bedroom", "192.168.1.60")
            config.set_token("Bedroom", "token-b")
            config.save(path)

            loaded = Config.load(path)
            assert loaded.active == "Bedroom"
            assert loaded.current().host == "192.168.1.60"
            assert loaded.token_for("Living Room") == "token-a"
            assert loaded.token_for("Bedroom") == "token-b"

            # Switching back restores that TV's host and token, and is remembered.
            loaded.select("Living Room", "192.168.1.50")
            loaded.save(path)
            again = Config.load(path)
            assert again.active == "Living Room"
            assert again.current().host == "192.168.1.50"
            assert again.current().token == "token-a"

            # v1 schema migrates, then adopts the reported TV name.
            legacy = Path(tmp) / "legacy.json"
            legacy.write_text('{"host": "10.0.0.7", "token": "old"}')
            migrated = Config.load(legacy)
            assert migrated.current().token == "old"
            assert migrated.remember("Kitchen TV", "10.0.0.7") is True
            assert migrated.active == "Kitchen TV"
            assert migrated.token_for("Kitchen TV") == "old"

        app.push_screen(ConfirmScreen("gate", "SERVICE"))
        await pilot.pause()
        assert app.screen.query_one("#confirm-input") is not None

        app.push_screen(
            DiscoveryScreen(
                [TVFound(ip="192.168.1.50", name="Living Room TV", model="Sample TV")]
            )
        )
        await pilot.pause()
        assert app.screen.query_one("#discovery-list") is not None
        print("smoke OK: widgets mounted, sequence parsing valid, no connection")


if __name__ == "__main__":
    asyncio.run(main())
