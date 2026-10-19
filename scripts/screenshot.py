"""Render the UI headlessly to an SVG for layout inspection.

usage: screenshot.py OUT.svg [tab-id | confirm]
"""

import asyncio
import sys

from textual.widgets import TabbedContent

from samsung_tui.app import ConfirmScreen, DiscoveryScreen, SamsungTUI
from samsung_tui.config import Config
from samsung_tui.discovery import TVFound


async def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "screenshot.svg"
    mode = sys.argv[2] if len(sys.argv) > 2 else ""

    app = SamsungTUI(Config(), connect=False)
    async with app.run_test(size=(150, 46)) as pilot:
        await pilot.pause()
        if mode == "confirm":
            app.push_screen(
                ConfirmScreen(
                    "This sends MUTE 1 8 2 POWER.\n\n"
                    "The TV will power-cycle and every option after that is blind.\n"
                    "Type SERVICE to proceed.",
                    "SERVICE",
                )
            )
        elif mode == "discover":
            app.push_screen(
                DiscoveryScreen(
                    [
                        TVFound(
                            ip="192.168.1.50",
                            name="Living Room TV",
                            model="Sample TV",
                            source="ssdp",
                        ),
                        TVFound(
                            ip="192.168.1.60",
                            name="Bedroom TV",
                            model="Sample TV",
                            source="http",
                        ),
                    ]
                )
            )
        elif mode:
            app.query_one(TabbedContent).active = mode
        await pilot.pause()
        app.save_screenshot(out)
        print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
