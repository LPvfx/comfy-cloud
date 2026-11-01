"""Minimal ComfyUI HTTP API client (stdlib only).

Used by `comfy-cloud run` so Claude (or you) can submit a workflow, wait for
it, and get the output files - without touching the browser.
"""

from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, url: str = "http://127.0.0.1:8188", timeout: float = 30):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    # -- http ---------------------------------------------------------------
    def _req(self, path: str, data: dict | None = None, raw: bool = False):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.url + path, data=body,
                                     headers={"Content-Type": "application/json"} if body else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise ComfyError(f"HTTP {e.code} {path}: {detail}") from None
        except urllib.error.URLError as e:
            raise ComfyError(f"ComfyUI not reachable at {self.url} ({e.reason}) - "
                             "is the tunnel up? `comfy-cloud tunnel`") from None
        return payload if raw else json.loads(payload or b"null")

    def alive(self) -> bool:
        try:
            self._req("/system_stats")
            return True
        except ComfyError:
            return False

    def system_stats(self) -> dict:
        return self._req("/system_stats")

    def object_info(self, node: str | None = None) -> dict:
        return self._req(f"/object_info/{node}" if node else "/object_info")

    # -- workflows ----------------------------------------------------------
    @staticmethod
    def load(path: str | Path) -> dict:
        wf = json.loads(Path(path).read_text())
        if "nodes" in wf and "links" in wf:
            raise ComfyError(
                f"{path} is a UI-format workflow. In ComfyUI use Workflow > Export (API) "
                "and save that instead.")
        return wf

    @staticmethod
    def apply_overrides(wf: dict, sets: list[str]) -> dict:
        """--set 3.seed=42  or  --set 3.inputs.seed=42  or  --set KSampler.steps=20"""
        wf = copy.deepcopy(wf)
        for s in sets:
            key, _, value = s.partition("=")
            if not _:
                raise ComfyError(f"bad --set {s!r}, expected node.input=value")
            node_ref, _, field = key.partition(".")
            field = field.removeprefix("inputs.")
            targets = [nid for nid, n in wf.items()
                       if nid == node_ref or n.get("class_type") == node_ref
                       or n.get("_meta", {}).get("title") == node_ref]
            if not targets:
                raise ComfyError(f"--set: no node {node_ref!r} (id, class_type or title)")
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = value
            for nid in targets:
                wf[nid].setdefault("inputs", {})[field] = parsed
        return wf

    def upload_image(self, path: str | Path) -> str:
        """Upload a local image to ComfyUI's input folder; returns its name."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + path.read_bytes() + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
            f"\r\n--{boundary}--\r\n").encode()
        req = urllib.request.Request(self.url + "/upload/image", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["name"]

    def queue(self, wf: dict) -> str:
        res = self._req("/prompt", {"prompt": wf, "client_id": self.client_id})
        if res.get("node_errors"):
            raise ComfyError("node errors: " + json.dumps(res["node_errors"], indent=2))
        return res["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 3600, poll: float = 1.0,
             on_tick=None) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            hist = self._req(f"/history/{prompt_id}")
            if hist and prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    detail = msgs[-1][1] if msgs else status
                    raise ComfyError("execution error: " + json.dumps(detail, indent=2)[:4000])
                if status.get("completed", True):
                    return entry
            if on_tick:
                on_tick(time.time() - start)
            time.sleep(poll)
        raise ComfyError(f"timed out after {timeout:.0f}s waiting for {prompt_id}")

    def download_outputs(self, entry: dict, dest: str | Path) -> list[Path]:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        saved = []
        for node_id, out in entry.get("outputs", {}).items():
            for kind in ("images", "gifs", "videos", "audio", "files"):
                for item in out.get(kind, []) or []:
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    q = urllib.parse.urlencode({
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    })
                    data = self._req(f"/view?{q}", raw=True)
                    p = dest / item["filename"]
                    p.write_bytes(data)
                    saved.append(p)
        return saved

    def run(self, wf: dict, dest: str | Path, timeout: float = 3600, on_tick=None) -> dict:
        t0 = time.time()
        pid = self.queue(wf)
        entry = self.wait(pid, timeout=timeout, on_tick=on_tick)
        files = self.download_outputs(entry, Path(dest) / pid[:8])
        return {"prompt_id": pid, "seconds": round(time.time() - t0, 1),
                "outputs": [str(f) for f in files]}
