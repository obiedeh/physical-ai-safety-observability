"""Create a self-signed certificate for the LAN HTTPS front door.

    python -m api.local_cert 192.0.2.10 thor.local

writes ``cert.pem`` and ``key.pem`` (mode 0600) to
``~/.config/physical-ai-safety/tls/`` with every name and address given as a Subject
Alternative Name, plus ``localhost`` and ``127.0.0.1``. Browsers will warn
about a self-signed certificate until it is trusted: import ``cert.pem`` on
the phone or laptop that will open the console, or use ``mkcert`` instead,
which installs a local CA that your own devices trust:

    mkcert -install
    mkcert -cert-file cert.pem -key-file key.pem 192.0.2.10 thor.local

Either pair works with ``api.tls_proxy``. Certificates and keys live outside
the repository and are ignored by git.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import socket
import stat
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

DEFAULT_DIR = Path.home() / ".config" / "physical-ai-safety" / "tls"
DEFAULT_DAYS = 825


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def generate_self_signed(
    names: list[str], out_dir: Path, *, days: int = DEFAULT_DAYS
) -> tuple[Path, Path]:
    """Write ``cert.pem`` and ``key.pem`` for ``names`` into ``out_dir``; return both paths."""
    subjects = []
    for name in [*names, "localhost", "127.0.0.1"]:
        clean = name.strip()
        if clean and clean not in subjects:
            subjects.append(clean)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, subjects[0]),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Physical AI Safety local console"),
    ])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([_san(n) for n in subjects]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / "cert.pem"
    key_path = out_dir / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key_bytes)
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    return cert_path, key_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "names", nargs="*", help="hostnames and IP addresses the console is reached at"
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_DIR), help=f"output directory (default {DEFAULT_DIR})"
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args(argv)
    names = args.names or [socket.gethostname()]
    cert_path, key_path = generate_self_signed(names, Path(args.out).expanduser(), days=args.days)
    print(f"certificate: {cert_path}")
    print(f"private key: {key_path}")
    print("names:", ", ".join([*names, "localhost", "127.0.0.1"]))
    print("Trust cert.pem on each device that opens the console, or use mkcert (see module doc).")


if __name__ == "__main__":  # pragma: no cover
    main()
