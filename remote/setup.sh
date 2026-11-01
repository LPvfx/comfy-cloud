#!/usr/bin/env bash
# Runs ON THE RENTED BOX. Idempotent: safe to run again on a live instance.
#
#   setup.sh SETS            install ComfyUI + nodes, download model sets (comma-separated)
#   setup.sh --nodes-only    reinstall nodes.txt + custom_nodes requirements
#   setup.sh --models-only SETS
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"     # /workspace/comfy-cloud
WS=/workspace
COMFY="$WS/ComfyUI"
[[ -f "$HERE/.env" ]] && source "$HERE/.env"
export HF_XET_HIGH_PERFORMANCE=1 PIP_ROOT_USER_ACTION=ignore

say() { printf "\n\033[1;36m[setup] %s\033[0m\n" "$*"; }
PY="${PYTHON:-python3}"
PIP="$PY -m pip install -q"

install_base() {
  say "system packages"
  if [[ -z "${SKIP_APT:-}" ]] && command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null
    apt-get install -y -qq git ffmpeg rsync tmux rclone libgl1 libglib2.0-0 >/dev/null || true
  fi
  say "python tooling"
  $PIP -U pip uv huggingface_hub pyyaml

  if [[ ! -d "$COMFY/.git" ]]; then
    say "cloning ComfyUI"
    git clone -q --depth 1 https://github.com/comfyanonymous/ComfyUI "$COMFY"
  else
    say "updating ComfyUI"
    git -C "$COMFY" pull -q --ff-only || echo "  (couldn't fast-forward, keeping current)"
  fi
  # keep the image's CUDA torch; install everything else
  grep -viE '^(torch|torchvision|torchaudio)([<>=~ ]|$)' "$COMFY/requirements.txt" > /tmp/comfy-req.txt
  $PY -m uv pip install --python "$PY" -q -r /tmp/comfy-req.txt
}

install_nodes() {
  say "custom node packs (nodes.txt)"
  mkdir -p "$COMFY/custom_nodes"
  grep -vE '^\s*(#|$)' "$HERE/nodes.txt" | while read -r spec; do
    url="${spec%@*}"; ref=""; [[ "$spec" == *@* ]] && ref="${spec##*@}"
    name="$(basename "$url" .git)"
    dir="$COMFY/custom_nodes/$name"
    if [[ ! -d "$dir/.git" ]]; then git clone -q "$url" "$dir"; else git -C "$dir" pull -q --ff-only || true; fi
    [[ -n "$ref" ]] && git -C "$dir" checkout -q "$ref"
    [[ -f "$dir/requirements.txt" ]] && $PY -m uv pip install --python "$PY" -q -r "$dir/requirements.txt" || true
    echo "  $name"
  done

  say "your nodes (custom_nodes/)"
  for d in "$HERE"/custom_nodes/*/; do
    [[ -d "$d" ]] || continue
    name="$(basename "$d")"
    ln -sfn "$d" "$COMFY/custom_nodes/$name"
    [[ -f "$d/requirements.txt" ]] && $PY -m uv pip install --python "$PY" -q -r "$d/requirements.txt" || true
    echo "  $name -> linked"
  done
  # workflows show up in ComfyUI's workflow browser
  mkdir -p "$COMFY/user/default/workflows"
  cp -f "$HERE"/workflows/*.json "$COMFY/user/default/workflows/" 2>/dev/null || true
}

download_models() {
  local sets="$1"
  [[ -z "$sets" || "$sets" == "none" ]] && return 0
  say "models: $sets"
  SETS="$sets" COMFY="$COMFY" MANIFEST="$HERE/models.yaml" $PY - <<'EOF'
import os, sys, shutil, yaml
from pathlib import Path
from huggingface_hub import hf_hub_download
man = yaml.safe_load(open(os.environ["MANIFEST"]))["sets"]
comfy = Path(os.environ["COMFY"]) / "models"
todo = []
for s in os.environ["SETS"].split(","):
    s = s.strip()
    if s not in man:
        sys.exit(f"unknown model set {s!r}; have: {', '.join(man)}")
    todo += man[s] or []
for m in todo:
    dest = comfy / m["dir"] / Path(m["file"]).name
    if dest.exists():
        print(f"  have {dest.name}"); continue
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get  {m['repo']}/{m['file']}", flush=True)
    try:
        p = hf_hub_download(m["repo"], m["file"], token=os.environ.get("HF_TOKEN"))
    except Exception as e:
        msg = str(e).splitlines()[0]
        hint = " (gated: accept the licence on huggingface.co and set HF_TOKEN in .env)" if "401" in msg or "403" in msg or "gated" in msg.lower() else ""
        sys.exit(f"  FAILED {m['file']}: {msg}{hint}")
    # move out of the HF cache so the disk isn't used twice
    shutil.move(os.path.realpath(p), dest)
    print(f"       -> models/{m['dir']}/{dest.name}")
EOF
}

case "${1:-}" in
  --nodes-only)  install_nodes ;;
  --models-only) download_models "${2:-}" ;;
  *)             install_base; install_nodes; download_models "${1:-}" ;;
esac
say "done"
