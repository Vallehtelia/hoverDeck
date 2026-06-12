"""VPN detection decision logic (pure — no network, no Qt)."""
from hoverdeck.core.vpn import Adapter, _evaluate, _looks_like_vpn

ETHERNET = Adapter(name="Ethernet", description="Realtek PCIe GbE",
                   iftype=6, up=True, ips=["192.168.1.5"])
WIFI = Adapter(name="Wi-Fi", description="Intel(R) Wi-Fi 6 AX201",
               iftype=71, up=True, ips=["192.168.1.7"])
# NordVPN's NordLynx adapter: stays installed, "up", AND keeps its tunnel IP
# even while DISCONNECTED. Existence/IP checks must not count it.
NORDLYNX = Adapter(name="NordLynx", description="NordLynx Tunnel",
                   iftype=53, up=True, ips=["10.5.0.2"])


def test_connected_egress_through_tunnel_is_green():
    status, detail = _evaluate([ETHERNET, NORDLYNX], ["10.5.0.2"])
    assert status is True
    assert "NordLynx" in detail


def test_disconnected_stale_tunnel_ip_is_red():
    # The always-green bug: NordLynx still holds 10.5.0.2, but traffic
    # egresses via Ethernet -> must be False.
    status, detail = _evaluate([ETHERNET, NORDLYNX], ["192.168.1.5"])
    assert status is False
    assert "Ethernet" in detail


def test_no_internet_route_is_red():
    status, _ = _evaluate([ETHERNET, NORDLYNX], [])
    assert status is False


def test_unknown_egress_owner_is_unknown():
    status, _ = _evaluate([ETHERNET], ["172.99.0.1"])
    assert status is None


def test_iftype_classifies_oddly_named_tunnels():
    # A provider with no recognizable name still classifies via Wintun IfType 53.
    odd = Adapter(name="Local Area Connection 3", description="Acme Adapter",
                  iftype=53, up=True, ips=["10.8.0.4"])
    assert _looks_like_vpn(odd) is True
    status, _ = _evaluate([ETHERNET, odd], ["10.8.0.4"])
    assert status is True


def test_user_hint_broadens_matching():
    exotic = Adapter(name="AcmeSecureLink", description="Acme Networks",
                     iftype=6, up=True, ips=["10.9.0.2"])
    assert _looks_like_vpn(exotic) is False
    assert _looks_like_vpn(exotic, hint="acme") is True
    status, _ = _evaluate([ETHERNET, exotic], ["10.9.0.2"], hint="acme")
    assert status is True


def test_pseudo_tunnels_are_excluded():
    isatap = Adapter(name="isatap.{ABC}", description="Microsoft ISATAP Adapter",
                     iftype=131, up=True, ips=["169.254.2.2"])
    assert _looks_like_vpn(isatap) is False
    teredo = Adapter(name="Teredo Tunneling Pseudo-Interface",
                     description="Teredo", iftype=131, up=True, ips=[])
    assert _looks_like_vpn(teredo) is False


def test_wifi_egress_is_red_even_with_tap_present():
    tap = Adapter(name="Ethernet 2", description="TAP-NordVPN Windows Adapter V9",
                  iftype=6, up=True, ips=[])
    status, _ = _evaluate([WIFI, NORDLYNX, tap], ["192.168.1.7"])
    assert status is False


def test_ipv6_scope_normalization():
    tunnel = Adapter(name="wg0", description="", iftype=53, up=True,
                     ips=["fd00::2%5"])
    status, _ = _evaluate([ETHERNET, tunnel], ["fd00::2"])
    assert status is True
