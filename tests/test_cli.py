"""Offline tests: workflow overrides, Vast parsing (with a stub vastai CLI)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from comfy_cloud import vast
from comfy_cloud.api import Comfy, ComfyError

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_workflow_is_api_format():
    wf = Comfy.load(ROOT / "workflows" / "smoke_test.json")
    assert all("class_type" in n for n in wf.values())


def test_ui_format_rejected(tmp_path):
    p = tmp_path / "ui.json"
    p.write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(ComfyError, match="Export \\(API\\)"):
        Comfy.load(p)


def test_overrides_by_id_class_and_title():
    wf = Comfy.load(ROOT / "workflows" / "smoke_test.json")
    out = Comfy.apply_overrides(wf, ["1.width=640", "LPGrade.exposure=-1.5", "Save.inputs.filename_prefix=x",
                                     "Grade.clamp=false"])
    assert out["1"]["inputs"]["width"] == 640
    assert out["2"]["inputs"]["exposure"] == -1.5
    assert out["4"]["inputs"]["filename_prefix"] == "x"
    assert out["2"]["inputs"]["clamp"] is False
    assert wf["1"]["inputs"]["width"] == 512  # original untouched
    with pytest.raises(ComfyError):
        Comfy.apply_overrides(wf, ["Missing.x=1"])


def test_offers_query():
    q = vast.offers_query("RTX 5090", 150, 13.0, 0.9, "GB,NL")
    assert "gpu_name=RTX_5090" in q and "dph<=0.9" in q and "geolocation in [GB,NL]" in q


def test_ssh_target_prefers_direct():
    info = {"public_ipaddr": "1.2.3.4 ", "ports": {"22/tcp": [{"HostPort": "40022"}]},
            "ssh_host": "ssh5.vast.ai", "ssh_port": 1234}
    assert vast.ssh_target(info) == ("1.2.3.4", 40022)
    assert vast.ssh_target({"ssh_host": "ssh5.vast.ai", "ssh_port": 1234}) == ("ssh5.vast.ai", 1234)
    assert vast.ssh_target({}) is None


@pytest.fixture
def stub_vast(tmp_path, monkeypatch):
    b = tmp_path / "vastai"
    b.write_text("""#!/usr/bin/env bash
case "$1 $2" in
  "search offers") echo '[{"id": 11, "dph_total": 0.31, "gpu_name": "RTX 4090"}, {"id": 12, "dph_total": 0.4}]' ;;
  "create instance") echo 'Started. {"success": true, "new_contract": 777}' ;;
  "show instance") echo '{"actual_status": "running", "public_ipaddr": "9.9.9.9", "ports": {"22/tcp": [{"HostPort": "2222"}]}}' ;;
  "destroy instance") echo '{"success": true}' ;;
  *) echo "bad $*" >&2; exit 1 ;;
esac
""")
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")


def test_vast_wrapper_with_stub(stub_vast):
    offers = vast.search("x", limit=1)
    assert offers == [{"id": 11, "dph_total": 0.31, "gpu_name": "RTX 4090"}]
    assert vast.create(11, "img", 100, "t") == 777  # handles text before JSON
    assert vast.ssh_target(vast.show(777)) == ("9.9.9.9", 2222)
    vast.destroy(777)
