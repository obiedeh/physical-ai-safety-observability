"""Local certificate generation and the HTTPS front door relaying to plain HTTP."""
from __future__ import annotations

import asyncio
import contextlib
import ssl
import stat

import pytest
from cryptography import x509

from api.local_cert import generate_self_signed
from api.tls_proxy import Endpoint, relay, serve


def test_generate_self_signed_cert(tmp_path) -> None:
    cert_path, key_path = generate_self_signed(["192.0.2.10", "thor.local"], tmp_path / "tls")
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["thor.local", "localhost"]
    ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
    assert ips == ["192.0.2.10", "127.0.0.1"]
    assert cert.subject.rfc4514_string().startswith("O=Physical AI Safety local console,CN=192.0.2.10")


def test_endpoint_parse() -> None:
    assert Endpoint.parse("0.0.0.0:8443") == Endpoint("0.0.0.0", 8443)
    assert Endpoint.parse("[::1]:8080") == Endpoint("::1", 8080)
    with pytest.raises(ValueError):
        Endpoint.parse("nope")


async def _http_backend() -> tuple[asyncio.Server, int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        body = b"hello from http " + request.split(b" ")[1]
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n" + body
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def test_proxy_terminates_tls_and_relays_http(tmp_path) -> None:
    asyncio.run(_proxy_round_trip(tmp_path))


async def _proxy_round_trip(tmp_path) -> None:
    cert_path, key_path = generate_self_signed(["localhost"], tmp_path / "tls")
    backend, backend_port = await _http_backend()
    proxy = await serve(
        Endpoint("127.0.0.1", 0), Endpoint("127.0.0.1", backend_port),
        str(cert_path), str(key_path),
    )
    proxy_port = proxy.sockets[0].getsockname()[1]
    client_ctx = ssl.create_default_context(cafile=str(cert_path))
    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", proxy_port, ssl=client_ctx, server_hostname="localhost"
        )
        writer.write(b"GET /cameras HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        # The backend answers with Connection: close; the proxy must close the TLS
        # side too, so reading to EOF returns the whole response.
        response = await asyncio.wait_for(reader.read(), timeout=5)
        writer.close()
        assert response.startswith(b"HTTP/1.1 200 OK")
        assert response.endswith(b"hello from http /cameras")
    finally:
        proxy.close()
        backend.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(backend.wait_closed(), 2)


def test_relay_closes_client_when_target_is_down() -> None:
    class Writer:
        closed = False

        def close(self) -> None:
            self.closed = True

    async def run() -> Writer:
        writer = Writer()
        await relay(asyncio.StreamReader(), writer, Endpoint("127.0.0.1", 1))  # type: ignore[arg-type]
        return writer

    assert asyncio.run(run()).closed
