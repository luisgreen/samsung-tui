"""Discover Samsung TVs on the local network.

Two independent methods, unioned and validated:

1. SSDP ``ssdp:all`` on 239.255.255.250:1900 -- fast, but some firmware
   suppresses the advertisement.
2. A bounded TCP sweep of port 8001 across the /24 -- slower, but catches TVs
   that ignore SSDP.

Every candidate is confirmed by ``GET /api/v2/`` and must report
``device.type == "Samsung SmartTV"``, so unrelated hosts never appear.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

REST_PORT = 8001
SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_TIMEOUT = 3.0
PROBE_TIMEOUT = 0.45

M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n\r\n"
)


@dataclass(frozen=True)
class TVFound:
    ip: str
    name: str = ""
    model: str = ""
    power: str = ""
    source: str = ""

    @property
    def label(self) -> str:
        parts = [self.ip]
        if self.name:
            parts.append(self.name)
        if self.model:
            parts.append(self.model)
        return "  ".join(parts)


def local_ip() -> str:
    """Best-effort LAN address of this machine (no packets are sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
        except OSError:
            return "192.168.0.1"


def subnet_for(ip: str) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(f"{ip}/24", strict=False)


def _ssdp_responders(timeout: float = SSDP_TIMEOUT) -> set[str]:
    found: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.3)
        try:
            sock.sendto(M_SEARCH.encode(), SSDP_ADDR)
        except OSError:
            return found

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                _data, addr = sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                break
            found.add(addr[0])
    return found


def _port_open(ip: str, port: int, timeout: float = PROBE_TIMEOUT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((ip, port)) == 0


def probe(ip: str) -> TVFound | None:
    """Confirm a host is a Samsung TV by asking its REST API."""
    if not _port_open(ip, REST_PORT):
        return None
    try:
        with urllib.request.urlopen(
            f"http://{ip}:{REST_PORT}/api/v2/", timeout=1.5
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - any failure means "not a TV"
        return None

    device = payload.get("device") or {}
    if device.get("type") != "Samsung SmartTV":
        return None
    return TVFound(
        ip=ip,
        name=str(device.get("name") or ""),
        model=str(device.get("modelName") or ""),
        power=str(device.get("PowerState") or ""),
        source="http",
    )


def discover(
    base_ip: str | None = None,
    subnet: str | None = None,
    timeout: float = SSDP_TIMEOUT,
    workers: int = 64,
) -> list[TVFound]:
    """Find Samsung TVs. ``subnet`` (CIDR) overrides the /24 guess."""
    if subnet:
        network = ipaddress.ip_network(subnet, strict=False)
    else:
        network = subnet_for(base_ip or local_ip())

    candidates: set[str] = {
        str(host) for host in network.hosts() if str(host) != local_ip()
    }
    candidates |= _ssdp_responders(timeout)

    results: list[TVFound] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for found in pool.map(probe, sorted(candidates)):
            if found is not None:
                results.append(found)

    results.sort(key=lambda tv: tuple(int(part) for part in tv.ip.split(".")))
    return results
