"""comfy-cloud - ComfyUI on a rented Vast.ai GPU, driven from your Mac.

    comfy-cloud offers                    cheapest matching GPUs right now
    comfy-cloud up                        rent, set up, start ComfyUI, tunnel, open browser
    comfy-cloud up --gpu RTX_5090 --models ltx23
    comfy-cloud status                    instance, uptime, cost so far
    comfy-cloud run workflows/x.json      queue an API-format workflow, fetch outputs
    comfy-cloud push                      sync custom_nodes/ + workflows/ up, restart ComfyUI
    comfy-cloud logs                      tail the ComfyUI log
    comfy-cloud ssh                       shell on the box
    comfy-cloud pull                      copy outputs down to ./outputs
    comfy-cloud down                      pull outputs, then destroy the instance (stops billing)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import vast
from .api import Comfy, ComfyError

console = Console()
ROOT = Path(os.environ.get("COMFY_CLOUD_ROOT", Path(__file__).resolve().parents[2]))
STATE = Path(os.environ.get("COMFY_CLOUD_STATE",
                            Path.home() / ".config" / "comfy-cloud" / "state.json"))
REMOTE = "/workspace/comfy-cloud"
LOCAL_PORT = int(os.environ.get("COMFY_LOCAL_PORT", 8188))
DEFAULTS = {
    "gpu": os.environ.get("COMFY_GPU", "RTX_4090"),
    "max_price": float(os.environ.get("COMFY_MAX_PRICE", "0.80")),
    "disk": int(os.environ.get("COMFY_DISK", "150")),
    "image": os.environ.get("COMFY_IMAGE", "pytorch/pytorch:2.14.1-cuda13.0-cudnn9-devel"),
    "min_cuda": float(os.environ.get("COMFY_MIN_CUDA", "13.0")),
    "models": os.environ.get("COMFY_MODELS", "smoke"),
}
# secrets forwarded to the box (never stored in Vast's instance metadata)
FORWARD_ENV = ["HF_TOKEN", "CIVITAI_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
               "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]


# ---------------------------------------------------------------- helpers ---
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def die(msg: str, code: int = 1):
    console.print(f"[bold red]error:[/] {msg}")
    sys.exit(code)


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def need_instance() -> dict:
    s = state()
    if not s.get("id"):
        die("no instance - run `comfy-cloud up`")
    return s


def ssh_base(s: dict) -> list[str]:
    return ["ssh", "-p", str(s["port"]), "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30", "-o", "LogLevel=ERROR", f"root@{s['host']}"]


def ssh(s: dict, cmd: str, check: bool = True, capture: bool = False, tty: bool = False):
    args = ssh_base(s)
    if tty:
        args.insert(1, "-t")
    res = subprocess.run(args + [cmd], text=True, capture_output=capture)
    if check and res.returncode != 0:
        die(f"remote command failed ({res.returncode}): {cmd}\n{res.stderr or ''}")
    return res


def rsync(s: dict, src: str, dst: str, delete: bool = False, excludes=()):
    e = f"ssh -p {s['port']} -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR"
    cmd = ["rsync", "-az", "--info=stats0" if sys.platform != "darwin" else "-q", "-e", e]
    if delete:
        cmd.append("--delete")
    for x in excludes:
        cmd += ["--exclude", x]
    cmd += [src, dst]
    if subprocess.run(cmd).returncode != 0:
        die(f"rsync failed: {src} -> {dst}")


def remote_env_file(s: dict):
    """Write forwarded secrets to the box (0600), sourced by the remote scripts."""
    lines = [f"export {k}={shlex.quote(os.environ[k])}" for k in FORWARD_ENV if os.environ.get(k)]
    payload = "\n".join(lines) + "\n"
    args = ssh_base(s) + [f"mkdir -p {REMOTE} && umask 077 && cat > {REMOTE}/.env"]
    subprocess.run(args, input=payload, text=True, check=True)


def push_files(s: dict):
    ssh(s, f"mkdir -p {REMOTE}")
    for item in ("remote/", "custom_nodes/", "workflows/"):
        if (ROOT / item).exists():
            rsync(s, str(ROOT / item), f"root@{s['host']}:{REMOTE}/{item}", delete=True,
                  excludes=("__pycache__", ".DS_Store"))
    for f in ("models.yaml", "nodes.txt"):
        rsync(s, str(ROOT / f), f"root@{s['host']}:{REMOTE}/{f}")


def tunnel_alive(s: dict) -> bool:
    pid = s.get("tunnel_pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_tunnel(s: dict) -> dict:
    if tunnel_alive(s):
        return s
    args = ssh_base(s)[:1] + ["-N", "-L", f"{LOCAL_PORT}:127.0.0.1:8188"] + ssh_base(s)[1:]
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    s["tunnel_pid"] = proc.pid
    save_state(s)
    return s


def stop_tunnel(s: dict):
    if tunnel_alive(s):
        try:
            os.kill(s["tunnel_pid"], 15)
        except OSError:
            pass
    s.pop("tunnel_pid", None)


def cost_line(s: dict) -> str:
    hrs = (time.time() - s.get("started", time.time())) / 3600
    return f"{hrs:.2f} h x ${s.get('dph', 0):.3f}/h = ~${hrs * s.get('dph', 0):.2f}"


def comfy() -> Comfy:
    return Comfy(f"http://127.0.0.1:{LOCAL_PORT}")


# --------------------------------------------------------------- commands ---
def cmd_offers(a):
    q = vast.offers_query(a.gpu, a.disk, a.min_cuda, a.max_price, a.regions)
    offers = vast.search(q, limit=a.limit)
    if not offers:
        die(f"no offers for: {q}\nTry --max-price higher, another --gpu, or --min-cuda 12.8")
    t = Table(header_style="bold")
    for c in ("offer", "gpu", "vram", "$/h", "reliab", "down Mb/s", "disk GB", "cuda", "where"):
        t.add_column(c)
    for o in offers:
        t.add_row(str(o["id"]), o.get("gpu_name", ""), f"{o.get('gpu_ram', 0) / 1024:.0f}",
                  f"{o.get('dph_total', o.get('dph', 0)):.3f}", f"{o.get('reliability', 0):.3f}",
                  f"{o.get('inet_down', 0):.0f}", f"{o.get('disk_space', 0):.0f}",
                  str(o.get("cuda_max_good", "")), o.get("geolocation", "") or "")
    console.print(t)
    return offers


def cmd_up(a):
    s = state()
    if s.get("id"):
        info = vast.show(s["id"])
        if info and info.get("actual_status") not in (None, "exited", "offline"):
            console.print(f"[yellow]instance {s['id']} already up[/] - reconnecting")
            return finish_up(s, a, fresh=False)
        console.print("[dim]stale state, starting fresh[/]")
        s = {}

    offers = cmd_offers(a)
    offer = offers[0] if not a.offer else next((o for o in offers if o["id"] == a.offer), None)
    if not offer:
        die(f"offer {a.offer} not in results")
    dph = offer.get("dph_total", offer.get("dph", 0))
    console.print(f"renting [bold]{offer.get('gpu_name')}[/] offer {offer['id']} at ${dph:.3f}/h "
                  f"({offer.get('geolocation', '?')})")
    if not a.yes and input("go? [Y/n] ").strip().lower().startswith("n"):
        return
    iid = vast.create(offer["id"], a.image, a.disk, label="comfy-cloud")
    s = {"id": iid, "dph": dph, "gpu": offer.get("gpu_name"), "started": time.time()}
    save_state(s)
    console.print(f"instance [bold]{iid}[/] created - billing has started")

    with console.status("waiting for the machine to boot (pulling image can take a few minutes)"):
        deadline = time.time() + 1200
        while time.time() < deadline:
            info = vast.show(iid)
            target = vast.ssh_target(info)
            if info.get("actual_status") == "running" and target:
                s["host"], s["port"] = target
                save_state(s)
                probe = ssh_base(s)[:1] + ["-o", "ConnectTimeout=8", "-o", "BatchMode=yes"] + ssh_base(s)[1:]
                if subprocess.run(probe + ["test -f /workspace/.vast-ready"],
                                  capture_output=True).returncode == 0:
                    break
            time.sleep(8)
        else:
            die(f"instance {iid} not reachable after 20 min - check `vastai logs {iid}`, "
                "then `comfy-cloud down`")
    return finish_up(s, a, fresh=True)


def finish_up(s: dict, a, fresh: bool):
    push_files(s)
    remote_env_file(s)
    models = a.models or DEFAULTS["models"]
    console.print(f"[bold]setting up ComfyUI[/] (models: {models}) - first run takes a while")
    ssh(s, f"cd {REMOTE} && bash remote/setup.sh {shlex.quote(models)}", tty=True)
    ssh(s, f"cd {REMOTE} && bash remote/start.sh")
    start_tunnel(s)
    with console.status("waiting for ComfyUI"):
        for _ in range(90):
            if comfy().alive():
                break
            time.sleep(2)
        else:
            die("ComfyUI didn't come up - `comfy-cloud logs`")
    stats = comfy().system_stats()
    dev = (stats.get("devices") or [{}])[0]
    console.print(f"[green]ComfyUI ready[/] at http://localhost:{LOCAL_PORT}  "
                  f"({dev.get('name', '?')}, {dev.get('vram_total', 0) / 2**30:.0f} GB)")
    console.print(f"[dim]{cost_line(s)} so far. `comfy-cloud down` when finished.[/]")
    if not a.no_browser:
        webbrowser.open(f"http://localhost:{LOCAL_PORT}")


def cmd_status(a):
    s = state()
    if not s.get("id"):
        console.print("no instance running (nothing is billing from comfy-cloud)")
        others = [i for i in vast.instances() if i.get("actual_status") == "running"]
        if others:
            console.print(f"[yellow]but {len(others)} other Vast instance(s) are running:[/] "
                          + ", ".join(str(i["id"]) for i in others))
        return
    info = vast.show(s["id"])
    console.print(f"instance {s['id']}  {s.get('gpu')}  status: {info.get('actual_status', '?')}")
    console.print(f"ssh: root@{s.get('host')} -p {s.get('port')}")
    console.print(f"tunnel: {'up' if tunnel_alive(s) else 'down'} -> http://localhost:{LOCAL_PORT}")
    console.print(f"ComfyUI: {'responding' if comfy().alive() else 'not reachable'}")
    console.print(f"cost: {cost_line(s)}")


def cmd_tunnel(a):
    s = need_instance()
    stop_tunnel(s) if a.restart else None
    start_tunnel(s)
    time.sleep(1.5)
    console.print(f"tunnel up -> http://localhost:{LOCAL_PORT}")
    if a.open:
        webbrowser.open(f"http://localhost:{LOCAL_PORT}")


def cmd_ssh(a):
    s = need_instance()
    os.execvp("ssh", ssh_base(s)[:1] + ["-t"] + ssh_base(s)[1:] + (a.cmd or []))


def cmd_logs(a):
    s = need_instance()
    follow = "-f " if a.follow else ""
    ssh(s, f"tail {follow}-n {a.lines} /workspace/comfyui.log", check=False)


def cmd_push(a):
    s = need_instance()
    push_files(s)
    if a.install:
        ssh(s, f"cd {REMOTE} && bash remote/setup.sh --nodes-only")
    ssh(s, f"cd {REMOTE} && bash remote/start.sh --restart")
    with console.status("restarting ComfyUI"):
        time.sleep(3)
        for _ in range(60):
            if comfy().alive():
                break
            time.sleep(2)
    console.print("[green]pushed and restarted[/]")


def cmd_models(a):
    s = need_instance()
    ssh(s, f"cd {REMOTE} && bash remote/setup.sh --models-only {shlex.quote(a.sets)}", tty=True)


def cmd_pull(a):
    s = need_instance()
    dest = Path(a.dest) / datetime.now().strftime("%Y-%m-%d")
    dest.mkdir(parents=True, exist_ok=True)
    rsync(s, f"root@{s['host']}:/workspace/ComfyUI/output/", str(dest) + "/")
    console.print(f"[green]outputs ->[/] {dest}")


def cmd_run(a):
    load_env()
    c = comfy()
    if not c.alive():
        die(f"ComfyUI not reachable on localhost:{LOCAL_PORT} - `comfy-cloud tunnel` or `up`")
    wf = Comfy.load(a.workflow)
    for img in a.image or []:
        node, _, path = img.partition("=")
        name = c.upload_image(path)
        a.set = (a.set or []) + [f"{node}.image={name}"]
    wf = Comfy.apply_overrides(wf, a.set or [])
    with console.status("running") as st:
        res = c.run(wf, a.out, timeout=a.timeout,
                    on_tick=lambda t: st.update(f"running {t:.0f}s"))
    if a.json:
        print(json.dumps(res))
    else:
        console.print(f"[green]done[/] in {res['seconds']}s")
        for f in res["outputs"]:
            console.print(f"  {f}")


def cmd_down(a):
    s = state()
    if not s.get("id"):
        console.print("nothing to tear down")
        return
    if not a.no_pull and s.get("host"):
        try:
            cmd_pull(argparse.Namespace(dest=a.dest))
        except SystemExit:
            console.print("[yellow]couldn't pull outputs[/]")
            if not a.yes and input("destroy anyway? [y/N] ").strip().lower() != "y":
                return
    stop_tunnel(s)
    vast.destroy(s["id"])
    console.print(f"[green]destroyed[/] instance {s['id']} - {cost_line(s)}")
    STATE.unlink(missing_ok=True)


# ------------------------------------------------------------------ main ---
def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="comfy-cloud", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def rent_args(p):
        p.add_argument("--gpu", default=DEFAULTS["gpu"], help="e.g. RTX_4090, RTX_5090, L40S, H100_SXM")
        p.add_argument("--max-price", type=float, default=DEFAULTS["max_price"], help="$/hour cap")
        p.add_argument("--disk", type=int, default=DEFAULTS["disk"], help="GB of disk")
        p.add_argument("--min-cuda", type=float, default=DEFAULTS["min_cuda"])
        p.add_argument("--regions", help="country codes, e.g. GB,NL,DE,FR,SE")
        p.add_argument("--limit", type=int, default=8)

    p = sub.add_parser("offers", help="list matching GPU offers")
    rent_args(p)
    p.set_defaults(fn=cmd_offers)

    p = sub.add_parser("up", help="rent + set up + start + tunnel")
    rent_args(p)
    p.add_argument("--models", help="model sets from models.yaml, comma-separated")
    p.add_argument("--offer", type=int, help="rent this offer id instead of the cheapest")
    p.add_argument("--image", default=DEFAULTS["image"])
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_up)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    p = sub.add_parser("tunnel", help="(re)open the SSH tunnel to ComfyUI")
    p.add_argument("--restart", action="store_true")
    p.add_argument("--open", action="store_true")
    p.set_defaults(fn=cmd_tunnel)

    p = sub.add_parser("ssh")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_ssh)

    p = sub.add_parser("logs")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("-n", "--lines", type=int, default=80)
    p.set_defaults(fn=cmd_logs)

    p = sub.add_parser("push", help="sync custom_nodes/workflows and restart ComfyUI")
    p.add_argument("--install", action="store_true", help="also reinstall nodes.txt / requirements")
    p.set_defaults(fn=cmd_push)

    p = sub.add_parser("models", help="download extra model sets on the running box")
    p.add_argument("sets")
    p.set_defaults(fn=cmd_models)

    p = sub.add_parser("pull", help="copy ComfyUI outputs to ./outputs/<date>")
    p.add_argument("--dest", default="outputs")
    p.set_defaults(fn=cmd_pull)

    p = sub.add_parser("run", help="run an API-format workflow and download outputs")
    p.add_argument("workflow")
    p.add_argument("--set", action="append", metavar="NODE.INPUT=VALUE",
                   help="override an input; NODE is id, class_type or title")
    p.add_argument("--image", action="append", metavar="NODE=PATH",
                   help="upload a local image and feed it to a LoadImage node")
    p.add_argument("--out", default="outputs/runs")
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--json", action="store_true", help="machine-readable result")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("down", help="pull outputs and destroy the instance")
    p.add_argument("--no-pull", action="store_true")
    p.add_argument("--dest", default="outputs")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(fn=cmd_down)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (vast.VastError, ComfyError) as e:
        die(str(e))
    except KeyboardInterrupt:
        s = state()
        if s.get("id"):
            console.print(f"\n[yellow]interrupted - instance {s['id']} is still billing. "
                          "`comfy-cloud down` to stop it.[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()
