"""Optional HTTPS front door for the LAN: a TLS-terminating TCP proxy.

Browsers only expose the camera (``getUserMedia``) in a secure context, so a
phone or laptop on the LAN that wants to share its camera must open the
console over HTTPS. Running the API itself on TLS would change the URL every
operator already uses, so this proxy adds HTTPS on a second port and leaves
the plain HTTP listener untouched:

    python -m api.local_cert 192.0.2.10 thor.local          # once
    python -m api.tls_proxy --listen 0.0.0.0:8444 --target 127.0.0.1:8081 \
        --cert ~/.config/physical-ai-safety/tls/cert.pem --key ~/.config/physical-ai-safety/tls/key.pem

Every byte is relayed unchanged in both directions, so MJPEG, server-sent
events and WebRTC signalling work exactly as on HTTP. The proxy is opt-in
(``deploy/physical-ai-safety-tls.service``) and has no dependencies beyond the
standard library.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import ssl
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ENV_CERT = "PHYSICAL_AI_TLS_CERT"
ENV_KEY = "PHYSICAL_AI_TLS_KEY"
ENV_LISTEN = "PHYSICAL_AI_TLS_LISTEN"
ENV_TARGET = "PHYSICAL_AI_TLS_TARGET"
DEFAULT_LISTEN = "0.0.0.0:8444"
DEFAULT_TARGET = "127.0.0.1:8081"
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int

    @classmethod
    def parse(cls, text: str) -> Endpoint:
        host, _, port = text.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"expected host:port, got '{text}'")
        return cls(host.strip("[]"), int(port))


def server_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    """TLS context for the listener; TLS 1.2+ with the system defaults."""
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return ctx


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(_CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (OSError, RuntimeError):
            pass


async def relay(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target: Endpoint,
) -> None:
    """Connect to the plain HTTP API and copy bytes both ways.

    A client that half-closes (EOF) has that EOF passed to the API, which then
    finishes its response. TLS has no half-close, so when the API side ends the
    client connection is closed outright; browsers reuse connections with
    keep-alive, so this only happens on ``Connection: close`` responses.
    """
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(target.host, target.port)
    except OSError as exc:
        logger.warning("tls proxy: cannot reach %s:%s: %s", target.host, target.port, exc)
        client_writer.close()
        return
    to_upstream = asyncio.create_task(_pump(client_reader, upstream_writer))
    try:
        await _pump(upstream_reader, client_writer)
    finally:
        to_upstream.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await to_upstream
        for w in (client_writer, upstream_writer):
            w.close()


async def serve(listen: Endpoint, target: Endpoint, certfile: str, keyfile: str) -> asyncio.Server:
    """Start the HTTPS listener and return the server (caller closes it)."""
    ctx = server_context(certfile, keyfile)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await relay(reader, writer, target)

    server = await asyncio.start_server(handle, listen.host, listen.port, ssl=ctx)
    logger.info("tls proxy: https://%s:%s -> http://%s:%s",
                listen.host, listen.port, target.host, target.port)
    return server


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HTTPS front door for the Physical AI Safety API.")
    parser.add_argument("--listen", default=os.getenv(ENV_LISTEN, DEFAULT_LISTEN),
                        help=f"host:port to accept HTTPS on (default {DEFAULT_LISTEN})")
    parser.add_argument("--target", default=os.getenv(ENV_TARGET, DEFAULT_TARGET),
                        help=f"host:port of the plain HTTP API (default {DEFAULT_TARGET})")
    parser.add_argument("--cert", default=os.getenv(ENV_CERT), help="PEM certificate chain")
    parser.add_argument("--key", default=os.getenv(ENV_KEY), help="PEM private key")
    args = parser.parse_args(argv)
    if not args.cert or not args.key:
        parser.error(f"--cert and --key are required (or set {ENV_CERT} and {ENV_KEY})")
    return args


async def _main_async(args: argparse.Namespace) -> None:
    server = await serve(
        Endpoint.parse(args.listen), Endpoint.parse(args.target),
        os.path.expanduser(args.cert), os.path.expanduser(args.key),
    )
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(_main_async(_parse_args(argv)))
    except KeyboardInterrupt:  # pragma: no cover - operator stopped it
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
