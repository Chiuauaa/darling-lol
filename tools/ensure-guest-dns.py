#!/usr/bin/env python3
"""Make the guest resolve through the same servers as the host.

Darling's root image ships private/etc/resolv.conf with hard-coded public
resolvers (8.8.8.8/8.8.4.4). The guest runs in the host's network namespace, so
the only resolver it can use is the one the host itself uses; when that is a
host-local stub (Cloudflare WARP's 127.0.2.2, systemd-resolved's 127.0.0.53) the
hard-coded file is unreachable from anywhere and the Riot Client fails with
"Could not resolve host" even though the host resolves fine.

The DPREFIX private/etc overlay wins over the read-only root image at container
start, so installing the host's file there fixes resolution without rebuilding
Darling and without editing the host's WARP-managed configuration.
"""
import os
from pathlib import Path

prefix = Path(os.environ.get("DPREFIX", str(Path.home() / ".darling")))
host = Path("/etc/resolv.conf")
dest = prefix / "private/etc/resolv.conf"

try:
    content = host.read_text()
except OSError as error:
    print(f"Leaving guest DNS untouched: cannot read {host}: {error}", flush=True)
    raise SystemExit(0)
if not any(line.split()[:1] == ["nameserver"] for line in content.splitlines()):
    print(f"Leaving guest DNS untouched: {host} names no server", flush=True)
    raise SystemExit(0)
try:
    if dest.read_text() == content:
        raise SystemExit(0)
except OSError:
    pass
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(content)
# The overlay is consumed when the container starts, so an already running guest
# keeps the previous file until it is restarted.
running = False
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        if (proc / "comm").read_text().strip() == "darlingserver":
            running = True
            break
    except OSError:
        continue
print(f"Guest DNS now follows {host}" + (" (restart Darling to apply)" if running else ""), flush=True)
