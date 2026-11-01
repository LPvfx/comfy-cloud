"""Thin wrapper around the `vastai` CLI (always --raw JSON)."""

from __future__ import annotations

import json
import shutil
import subprocess


class VastError(RuntimeError):
    pass


def _bin() -> str:
    b = shutil.which("vastai")
    if not b:
        raise VastError("vastai CLI not found - run ./bootstrap.sh (uv tool install vastai)")
    return b


def call(*args: str) -> object:
    res = subprocess.run([_bin(), *args, "--raw"], capture_output=True, text=True)
    if res.returncode != 0:
        raise VastError((res.stderr or res.stdout).strip())
    out = res.stdout.strip()
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        # some commands print a line of text before the JSON
        for i, ch in enumerate(out):
            if ch in "[{":
                try:
                    return json.loads(out[i:])
                except json.JSONDecodeError:
                    continue
        return out


def offers_query(gpu: str, disk: int, min_cuda: float, max_price: float | None,
                 regions: str | None = None) -> str:
    q = [
        f"gpu_name={gpu.replace(' ', '_')}",
        "num_gpus=1",
        "reliability>0.98",
        "inet_down>=500",
        f"disk_space>={disk}",
        f"cuda_vers>={min_cuda}",
        "direct_port_count>=1",
        "rentable=true",
        "verified=true",
    ]
    if max_price:
        q.append(f"dph<={max_price}")
    if regions:
        q.append(f"geolocation in [{regions}]")
    return " ".join(q)


def search(query: str, limit: int = 10) -> list[dict]:
    res = call("search", "offers", query, "-o", "dph")
    return (res or [])[:limit] if isinstance(res, list) else []


def create(offer_id: int, image: str, disk: int, label: str) -> int:
    res = call("create", "instance", str(offer_id), "--image", image, "--disk", str(disk),
               "--ssh", "--direct", "--label", label, "--cancel-unavail",
               "--onstart-cmd", "mkdir -p /workspace && touch /workspace/.vast-ready")
    if not isinstance(res, dict) or not res.get("success"):
        raise VastError(f"create failed: {res}")
    return int(res["new_contract"])


def show(instance_id: int) -> dict:
    res = call("show", "instance", str(instance_id))
    return res if isinstance(res, dict) else {}


def instances() -> list[dict]:
    res = call("show", "instances")
    return res if isinstance(res, list) else []


def destroy(instance_id: int):
    call("destroy", "instance", str(instance_id), "-y")


def ssh_target(info: dict) -> tuple[str, int] | None:
    """(host, port) for direct SSH, falling back to Vast's SSH proxy."""
    ip = info.get("public_ipaddr")
    ports = info.get("ports") or {}
    direct = ports.get("22/tcp")
    if ip and direct:
        return ip.strip(), int(direct[0]["HostPort"])
    if info.get("ssh_host") and info.get("ssh_port"):
        return info["ssh_host"], int(info["ssh_port"])
    return None
