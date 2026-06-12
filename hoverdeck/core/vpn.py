"""VPN connection detection — pure Python, no Qt, no hard deps on Windows.

``vpn_status()`` returns True (traffic is going through a VPN tunnel), False
(it isn't), or None (couldn't determine). ``last_detail()`` says why.

How it decides — the **egress interface** is the source of truth:
ask the OS routing table which local address it would route internet traffic
through (a UDP ``connect()`` — no packets are sent), find the adapter that owns
that address, and classify *that* adapter. This is robust against the classic
trap: clients like NordVPN leave their NordLynx adapter installed, "up", AND
holding its 10.x tunnel IP even while disconnected — so adapter-existence or
adapter-has-IP checks read green forever. The default route doesn't lie:
disconnected, traffic egresses via Ethernet/Wi-Fi; connected, via the tunnel.

Adapter classification (any provider, out of the box):
- **Interface type** (Windows, via ``GetAdaptersAddresses`` — no psutil, and
  locale-independent): Wintun-based tunnels (NordLynx, WireGuard, modern
  OpenVPN) register IfType 53 (IF_TYPE_PROP_VIRTUAL); built-in VPNs (IKEv2,
  SSTP, L2TP, PPTP) are PPP (23); others are TUNNEL (131).
- **Name/description keywords** for TAP-style adapters and non-Windows.
- An optional user **hint** (Settings) for exotic providers.

Known trade-off: split-tunnel VPNs egress via the LAN, so they read "not
connected" — which is the honest answer to "is my traffic protected?".
"""
from __future__ import annotations

import socket
import sys
from dataclasses import dataclass, field

# IANA ifType values that mean "virtual tunnel" on Windows.
_VPN_IFTYPES = {23, 53, 131}   # PPP, PROP_VIRTUAL (Wintun), TUNNEL

_VPN_HINTS = (
    "vpn", "wireguard", "wg", "tun", "tap", "nordlynx", "nordvpn", "openvpn",
    "proton", "mullvad", "expressvpn", "surfshark", "ppp", "utun", "zerotier",
    "tailscale", "cisco", "anyconnect", "forticlient", "globalprotect", "wintun",
)
# Windows pseudo-tunnels that aren't VPNs — never count these.
_VPN_EXCLUDE = ("isatap", "teredo", "6to4", "loopback")

_last_detail = "not checked yet"


def last_detail() -> str:
    """Human-readable reason for the last ``vpn_status()`` verdict (for logs)."""
    return _last_detail


@dataclass
class Adapter:
    """One network interface, normalized across collectors."""

    name: str
    description: str = ""
    iftype: int | None = None     # IANA ifType; None when the collector can't tell
    up: bool = True
    ips: list[str] = field(default_factory=list)


def _looks_like_vpn(adapter: Adapter, hint: str = "") -> bool:
    text = f"{adapter.name} {adapter.description}".lower()
    if any(bad in text for bad in _VPN_EXCLUDE):
        return False
    hint = hint.strip().lower()
    if hint and hint in text:
        return True
    if any(h in text for h in _VPN_HINTS):
        return True
    return adapter.iftype in _VPN_IFTYPES


def _norm_ip(address: str) -> str:
    return address.split("%", 1)[0].lower()


def _egress_ips() -> list[str]:
    """Local addresses the OS routes internet traffic through (no packets sent)."""
    out: list[str] = []
    for family, probe in (
        (socket.AF_INET, "8.8.8.8"),
        (socket.AF_INET6, "2001:4860:4860::8888"),
    ):
        sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 80))   # selects a route; nothing is transmitted
            out.append(_norm_ip(sock.getsockname()[0]))
        except OSError:
            pass
        finally:
            sock.close()
    return out


# --------------------------------------------------------------- collectors
def _adapters_windows() -> list[Adapter] | None:
    """Enumerate adapters via GetAdaptersAddresses (names, IfType, status, IPs)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class SOCKADDR(ctypes.Structure):
            _fields_ = [("sa_family", ctypes.c_ushort),
                        ("sa_data", ctypes.c_char * 26)]  # fits sockaddr_in6

        class SOCKET_ADDRESS(ctypes.Structure):
            _fields_ = [("lpSockaddr", ctypes.POINTER(SOCKADDR)),
                        ("iSockaddrLength", ctypes.c_int)]

        class UNICAST(ctypes.Structure):
            pass

        UNICAST._fields_ = [
            ("Length", ctypes.c_ulong),        # union {ULONGLONG; {Length, Flags}}
            ("Flags", wintypes.DWORD),
            ("Next", ctypes.POINTER(UNICAST)),
            ("Address", SOCKET_ADDRESS),
        ]

        class ADAPTER(ctypes.Structure):
            pass

        ADAPTER._fields_ = [
            ("Length", ctypes.c_ulong),        # union {ULONGLONG; {Length, IfIndex}}
            ("IfIndex", wintypes.DWORD),
            ("Next", ctypes.POINTER(ADAPTER)),
            ("AdapterName", ctypes.c_char_p),
            ("FirstUnicastAddress", ctypes.POINTER(UNICAST)),
            ("FirstAnycastAddress", ctypes.c_void_p),
            ("FirstMulticastAddress", ctypes.c_void_p),
            ("FirstDnsServerAddress", ctypes.c_void_p),
            ("DnsSuffix", ctypes.c_wchar_p),
            ("Description", ctypes.c_wchar_p),
            ("FriendlyName", ctypes.c_wchar_p),
            ("PhysicalAddress", ctypes.c_ubyte * 8),
            ("PhysicalAddressLength", ctypes.c_ulong),
            ("Flags", ctypes.c_ulong),
            ("Mtu", ctypes.c_ulong),
            ("IfType", wintypes.DWORD),
            ("OperStatus", ctypes.c_int),      # 1 == IfOperStatusUp
        ]

        iphlpapi = ctypes.WinDLL("Iphlpapi")
        AF_UNSPEC = 0
        SKIP = 0x2 | 0x4 | 0x8   # anycast | multicast | dns-server
        ERROR_BUFFER_OVERFLOW = 111

        size = ctypes.c_ulong(16 * 1024)
        buf = ctypes.create_string_buffer(size.value)
        for _ in range(4):
            ret = iphlpapi.GetAdaptersAddresses(
                AF_UNSPEC, SKIP, None,
                ctypes.cast(buf, ctypes.POINTER(ADAPTER)), ctypes.byref(size),
            )
            if ret == 0:
                break
            if ret != ERROR_BUFFER_OVERFLOW:
                return None
            buf = ctypes.create_string_buffer(size.value)
        else:
            return None

        out: list[Adapter] = []
        node = ctypes.cast(buf, ctypes.POINTER(ADAPTER))
        while node:
            a = node.contents
            ips: list[str] = []
            unicast = a.FirstUnicastAddress
            while unicast:
                sa = unicast.contents.Address.lpSockaddr
                if sa:
                    family = sa.contents.sa_family
                    raw = bytes(sa.contents.sa_data)
                    # sockaddr_in: port(2) addr(4); sockaddr_in6: port(2)
                    # flowinfo(4) addr(16) scope(4) — offsets within sa_data.
                    if family == socket.AF_INET:
                        ips.append(socket.inet_ntop(socket.AF_INET, raw[2:6]))
                    elif family == 23:  # AF_INET6 on Windows
                        ips.append(_norm_ip(
                            socket.inet_ntop(socket.AF_INET6, raw[6:22])
                        ))
                unicast = unicast.contents.Next
            out.append(Adapter(
                name=a.FriendlyName or "",
                description=a.Description or "",
                iftype=int(a.IfType),
                up=(a.OperStatus == 1),
                ips=ips,
            ))
            node = a.Next
        return out
    except Exception:  # noqa: BLE001 — any ctypes hiccup → try the fallback
        return None


def _adapters_psutil() -> list[Adapter] | None:
    """Fallback collector (non-Windows, or if the ctypes path failed)."""
    try:
        import psutil  # type: ignore[import-not-found]

        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
    except Exception:  # noqa: BLE001
        return None
    out: list[Adapter] = []
    for name, entries in addrs.items():
        ips = [
            _norm_ip(e.address) for e in entries
            if e.family in (socket.AF_INET, socket.AF_INET6)
        ]
        up = stats[name].isup if name in stats else True
        out.append(Adapter(name=name, up=up, ips=ips))
    return out


def _adapters() -> list[Adapter] | None:
    return _adapters_windows() or _adapters_psutil()


# ----------------------------------------------------------------- decision
def _evaluate(
    adapters: list[Adapter], egress_ips: list[str], hint: str = ""
) -> tuple[bool | None, str]:
    """Pure decision: classify the adapter that owns the egress address."""
    by_ip: dict[str, Adapter] = {}
    for adapter in adapters:
        for ip in adapter.ips:
            by_ip.setdefault(_norm_ip(ip), adapter)

    for ip in egress_ips:
        owner = by_ip.get(ip)
        if owner is None:
            continue
        if _looks_like_vpn(owner, hint):
            return True, f"traffic egresses via {owner.name!r} (VPN)"
        return False, f"traffic egresses via {owner.name!r} (not a VPN)"

    if egress_ips:
        return None, f"egress {egress_ips} not owned by any known adapter"
    return False, "no internet route — not tunnelling"


def vpn_status(hint: str = "") -> bool | None:
    """True = tunnel carries the traffic, False = it doesn't, None = unknown."""
    global _last_detail
    adapters = _adapters()
    if adapters is None:
        _last_detail = "could not enumerate network adapters"
        return None
    status, _last_detail = _evaluate(adapters, _egress_ips(), hint)
    return status
