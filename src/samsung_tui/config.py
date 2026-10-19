"""Persistent configuration for samsung-tui.

Stored as JSON under ``~/.config/samsung-tui/config.json`` (override with
``SAMSUNG_TUI_CONFIG_DIR``).

The file models several TVs. Each is keyed by the name the TV reports from
``/api/v2/`` (for example ``Living Room TV``) and keeps its own address and
pairing token. ``active`` remembers the TV selected last.

There is no built-in default address: an empty config is valid, and the app
scans the LAN to populate it the first time.

Schema (v3)::

    {
      "active": "Living Room TV",
      "tvs": {
        "Living Room TV": {"host": "192.168.1.50", "token": "…"},
        "Bedroom TV": {"host": "192.168.1.60", "token": "…"}
      }
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "samsung-tui"


def config_dir() -> Path:
    override = os.environ.get("SAMSUNG_TUI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class TVRecord:
    """One known TV: where it lives and how to authenticate to it."""

    host: str
    token: str | None = None


@dataclass
class Config:
    active: str | None = None
    tvs: dict[str, TVRecord] = field(default_factory=dict)

    # -- selection ---------------------------------------------------

    def current(self) -> TVRecord | None:
        if self.active:
            return self.tvs.get(self.active)
        return None

    def select(self, name: str, host: str) -> TVRecord:
        """Mark a TV active, creating or updating its record."""
        record = self.tvs.get(name)
        if record is None:
            record = TVRecord(host=host)
            self.tvs[name] = record
        else:
            record.host = host
        self.active = name
        return record

    def remember(self, name: str, host: str) -> bool:
        """Learn a TV's name for a host, adopting a legacy host-keyed record.

        Returns True when the persisted shape changed.
        """
        changed = False
        record = self.tvs.get(name)

        if record is None and host in self.tvs:
            record = self.tvs.pop(host)
            self.tvs[name] = record
            changed = True

        if record is None:
            record = TVRecord(host=host)
            self.tvs[name] = record
            changed = True

        if record.host != host:
            record.host = host
            changed = True
        if self.active != name:
            self.active = name
            changed = True
        return changed

    # -- tokens ------------------------------------------------------

    def token_for(self, name: str | None = None) -> str | None:
        record = self.tvs.get(name) if name else self.current()
        return record.token if record else None

    def set_token(self, name: str, token: str | None) -> None:
        record = self.tvs.get(name)
        if record is not None:
            record.token = token

    # -- persistence -------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        p = path or config_path()
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()

        tvs: dict[str, TVRecord] = {}

        raw_tvs = raw.get("tvs")
        if isinstance(raw_tvs, dict) and raw_tvs:
            for name, rec in raw_tvs.items():
                if not isinstance(rec, dict):
                    continue
                tvs[str(name)] = TVRecord(
                    host=str(rec.get("host") or ""),
                    token=rec.get("token") or None,
                )
            active = raw.get("active")
            if active not in tvs:
                active = next(iter(tvs), None)
        else:
            # Migrate v1 ({"host","token"}) and v2 ({"host","tokens"}).
            host = str(raw.get("host") or "")
            tokens = raw.get("tokens")
            if isinstance(tokens, dict):
                for key, value in tokens.items():
                    if isinstance(value, str) and value:
                        tvs[str(key)] = TVRecord(host=host, token=value)
            legacy = raw.get("token")
            if isinstance(legacy, str) and legacy and host:
                tvs.setdefault(host, TVRecord(host=host)).token = legacy
            if not tvs and host:
                tvs[host] = TVRecord(host=host)
            active = next(iter(tvs), None)

        # Drop records that lost their address in a bad edit.
        tvs = {name: rec for name, rec in tvs.items() if rec.host}
        if active not in tvs:
            active = next(iter(tvs), None)

        return cls(active=active, tvs=tvs)

    def save(self, path: Path | None = None) -> None:
        p = path or config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        payload = {
            "active": self.active,
            "tvs": {
                name: {"host": record.host, "token": record.token}
                for name, record in self.tvs.items()
            },
        }
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(p)
