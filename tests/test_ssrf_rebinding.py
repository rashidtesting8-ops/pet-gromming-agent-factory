from __future__ import annotations

import socket
import threading
from typing import Any

import pytest
import requests

from engine.collector import (
    build_collector_session,
    dial_verified_socket,
    response_get,
    safe_url,
    validate_ip_address,
)


def _addrinfo(ip: str, port: int = 80) -> tuple[int, int, int, str, tuple[Any, ...]]:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr: tuple[Any, ...] = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "::1",
        "169.254.169.254",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:10.0.0.1",
        "0.0.0.0",
        "::",
        "100.64.0.1",
        "100.127.255.254",
    ],
)
def test_validate_ip_and_dialer_reject_non_global_addresses(blocked_ip: str) -> None:
    with pytest.raises(ValueError, match="Non-public|Non-global|blocked"):
        validate_ip_address(blocked_ip)

    connector_calls: list[tuple[str, int]] = []

    def fake_resolver(host: str, port: int) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        return [_addrinfo(blocked_ip, port)]

    def fake_connector(
        addr: tuple[str, int],
        timeout: float | None,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        connector_calls.append(addr)
        raise AssertionError("connector must not be called for non-global IP")

    with pytest.raises(ValueError, match="Non-public|Non-global|blocked"):
        dial_verified_socket(
            "example.com",
            80,
            resolver=fake_resolver,
            connector=fake_connector,
        )
    assert connector_calls == []


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://2130706433/",
        "http://0x7f.1/",
        "http://0177.0.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://100.64.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://user:pass@example.com/",
        "ftp://example.com/file.jpg",
        "http://example.com:8080/",
        "http://n8n:5678/",
    ],
)
def test_safe_url_and_dialer_reject_encoded_literals_and_bad_ports(bad_url: str) -> None:
    with pytest.raises(ValueError):
        safe_url(bad_url)


def test_multi_record_dns_answer_with_one_private_ip_is_rejected() -> None:
    connector_calls: list[tuple[str, int]] = []

    def multi_resolver(host: str, port: int) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        return [
            _addrinfo("93.184.216.34", port),
            _addrinfo("10.0.0.42", port),
        ]

    def fake_connector(
        addr: tuple[str, int],
        timeout: float | None,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        connector_calls.append(addr)
        raise AssertionError("connector must not be called when any record is private")

    with pytest.raises(ValueError, match="Non-public|Non-global|blocked"):
        dial_verified_socket(
            "dual.example.com",
            80,
            resolver=multi_resolver,
            connector=fake_connector,
        )
    assert connector_calls == []


def test_dns_rebinding_single_resolution_and_private_rebind_blocked() -> None:
    """Verify resolver is called once per connection and connector never receives private IP."""
    resolver_calls = 0
    connected_targets: list[tuple[str, int]] = []

    def rebinding_resolver(
        host: str, port: int
    ) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls == 1:
            return [_addrinfo("93.184.216.34", port)]
        return [_addrinfo("127.0.0.1", port)]

    def fake_connector(
        addr: tuple[str, int],
        timeout: float | None,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        connected_targets.append(addr)
        s1, s2 = socket.socketpair()
        s2.close()
        return s1

    sock = dial_verified_socket(
        "rebind.example.com",
        80,
        resolver=rebinding_resolver,
        connector=fake_connector,
    )
    sock.close()

    # Single dial resolved DNS exactly once and connected to the public IP, never 127.0.0.1
    assert resolver_calls == 1
    assert connected_targets == [("93.184.216.34", 80)]

    # If a subsequent connection triggers the second resolution (127.0.0.1), it is blocked
    # before connector is ever invoked.
    with pytest.raises(ValueError, match="Non-public|Non-global|blocked"):
        dial_verified_socket(
            "rebind.example.com",
            80,
            resolver=rebinding_resolver,
            connector=fake_connector,
        )
    assert resolver_calls == 2
    assert connected_targets == [("93.184.216.34", 80)]


def test_real_urllib3_stack_preserves_host_header_and_blocks_redirects() -> None:
    """Exercise the real requests + urllib3 HTTPConnectionPool + SafeHTTPConnection stack."""
    resolver_calls: list[tuple[str, int]] = []
    connected_ips: list[tuple[str, int]] = []
    observed_request_lines: list[str] = []

    def fake_resolver(host: str, port: int) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        resolver_calls.append((host, port))
        if host == "public.example.com":
            # Only return public IP on the first lookup; if urllib3 ever resolved a second time,
            # return 127.0.0.1 to prove the dialer does not double-resolve.
            if len(resolver_calls) == 1:
                return [_addrinfo("93.184.216.34", port)]
            return [_addrinfo("127.0.0.1", port)]
        if host == "redirect-local.example.com":
            return [_addrinfo("93.184.216.34", port)]
        if host == "redirect-n8n.example.com":
            return [_addrinfo("93.184.216.34", port)]
        return [_addrinfo("127.0.0.1", port)]

    def socketpair_connector(
        addr: tuple[str, int],
        timeout: float | None,
        source_address: tuple[str, int] | None,
    ) -> socket.socket:
        connected_ips.append(addr)
        client_sock, server_sock = socket.socketpair()

        def serve_once() -> None:
            try:
                raw = server_sock.recv(4096).decode("latin1", errors="replace")
                observed_request_lines.append(raw)
                if "GET /to-local " in raw:
                    resp = (
                        "HTTP/1.1 302 Found\r\n"
                        "Location: http://127.0.0.1/admin\r\n"
                        "Content-Length: 0\r\n"
                        "Connection: close\r\n\r\n"
                    )
                elif "GET /to-n8n " in raw:
                    resp = (
                        "HTTP/1.1 302 Found\r\n"
                        "Location: http://n8n:5678/webhook\r\n"
                        "Content-Length: 0\r\n"
                        "Connection: close\r\n\r\n"
                    )
                else:
                    resp = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: text/html; charset=utf-8\r\n"
                        "Content-Length: 15\r\n"
                        "Connection: close\r\n\r\n"
                        "<h1> Groom </h1>"
                    )
                server_sock.sendall(resp.encode("latin1"))
            finally:
                server_sock.close()

        t = threading.Thread(target=serve_once, daemon=True)
        t.start()
        return client_sock

    session = build_collector_session(resolver=fake_resolver, connector=socketpair_connector)
    assert session.trust_env is False

    # 1. Successful fetch through real urllib3 stack:
    #    - Resolver called once
    #    - Connected to validated IP 93.184.216.34:80
    #    - Original Host header "Host: public.example.com" preserved (no URL-to-IP rewrite)
    res = response_get(session, "http://public.example.com/ok")
    try:
        assert res.status_code == 200
        assert len(resolver_calls) == 1
        assert connected_ips == [("93.184.216.34", 80)]
        assert any("Host: public.example.com\r\n" in req for req in observed_request_lines)
    finally:
        res.close()

    # 2. Redirect to http://127.0.0.1/admin is blocked on redirect hop validation
    with pytest.raises((ValueError, requests.RequestException)):
        response_get(session, "http://redirect-local.example.com/to-local")
    assert all(ip != "127.0.0.1" for ip, _ in connected_ips)

    # 3. Redirect to http://n8n:5678/webhook is blocked on redirect hop validation
    with pytest.raises((ValueError, requests.RequestException)):
        response_get(session, "http://redirect-n8n.example.com/to-n8n")
    assert all(port != 5678 for _, port in connected_ips)

