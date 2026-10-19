"""Samsung Tizen remote key codes this app sends.

Everything here is a ``KEY_*`` press. The TV exposes no API primitive for
"write EEPROM" or "factory reset" -- those are *menu items inside service
mode*, reachable only by blind navigation. ``SERVICE_MENU`` is the documented
Samsung entry sequence (``MUTE 1 8 2 POWER``); it is model/firmware-specific and
unverified on the CU7000. It is exposed in the UI behind a typed confirmation
and nothing is automated after entry.
"""

from __future__ import annotations

NAV = {
    "UP": "KEY_UP",
    "DOWN": "KEY_DOWN",
    "LEFT": "KEY_LEFT",
    "RIGHT": "KEY_RIGHT",
    "ENTER": "KEY_ENTER",
    "RETURN": "KEY_RETURN",
    "EXIT": "KEY_EXIT",
}

SYSTEM = {
    "HOME": "KEY_HOME",
    "MENU": "KEY_MENU",
    "SOURCE": "KEY_SOURCE",
    "GUIDE": "KEY_GUIDE",
    "INFO": "KEY_INFO",
    "TOOLS": "KEY_TOOLS",
    "POWER": "KEY_POWER",
}

VOLUME = {
    "VOLUP": "KEY_VOLUP",
    "VOLDOWN": "KEY_VOLDOWN",
    "MUTE": "KEY_MUTE",
}

CHANNEL = {
    "CHUP": "KEY_CHUP",
    "CHDOWN": "KEY_CHDOWN",
}

MEDIA = {
    "PLAY": "KEY_PLAY",
    "PAUSE": "KEY_PAUSE",
    "STOP": "KEY_STOP",
    "REWIND": "KEY_REWIND",
    "FF": "KEY_FF",
}

COLOR = {
    "RED": "KEY_RED",
    "GREEN": "KEY_GREEN",
    "YELLOW": "KEY_YELLOW",
    "BLUE": "KEY_BLUE",
}

ALL: dict[str, str] = {**NAV, **SYSTEM, **VOLUME, **CHANNEL, **MEDIA, **COLOR}

# Home -> Settings (verified on a 2023 CU7000).
OPEN_SETTINGS = ["KEY_HOME", "KEY_DOWN", "KEY_ENTER"]

# Documented Samsung service-menu entry. Unverified on this model: if the
# sequence does not match the firmware, the TV simply power-cycles.
SERVICE_MENU = ["KEY_MUTE", "KEY_1", "KEY_8", "KEY_2", "KEY_POWER"]

MAX_SEQUENCE = 40


def resolve_sequence(text: str) -> list[str]:
    """Turn user input into KEY_* codes.

    Accepts bare names (``MUTE``), ``KEY_*`` codes verbatim, digits, and
    comma- or space-separated tokens. Raises ``ValueError`` on unknown tokens
    so the UI can report them instead of guessing.
    """
    resolved: list[str] = []
    for raw in text.replace(",", " ").split():
        token = raw.strip().upper()
        if not token:
            continue
        if token in ALL:
            resolved.append(ALL[token])
        elif token.startswith("KEY_"):
            resolved.append(token)
        elif token.isdigit():
            resolved.extend(f"KEY_{digit}" for digit in token)
        else:
            raise ValueError(f"unknown key: {raw!r}")
    if len(resolved) > MAX_SEQUENCE:
        raise ValueError(f"sequence too long (max {MAX_SEQUENCE} keys)")
    return resolved

