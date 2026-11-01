#!/usr/bin/env bash
# Runs ON THE BOX. Start (or --restart) ComfyUI in the background, bound to
# localhost only - you reach it through the SSH tunnel, never the open internet.
set -euo pipefail
COMFY=/workspace/ComfyUI
LOG=/workspace/comfyui.log
PIDF=/workspace/comfyui.pid
PY="${PYTHON:-python3}"

running() { [[ -f $PIDF ]] && kill -0 "$(cat $PIDF)" 2>/dev/null; }

if [[ "${1:-}" == "--restart" || "${1:-}" == "--stop" ]] && running; then
  kill "$(cat $PIDF)" || true
  for _ in $(seq 1 20); do running || break; sleep 0.5; done
  running && kill -9 "$(cat $PIDF)" || true
  rm -f $PIDF
  [[ "${1:-}" == "--stop" ]] && exit 0
fi

if running; then echo "ComfyUI already running (pid $(cat $PIDF))"; exit 0; fi

cd "$COMFY"
# shellcheck disable=SC2086
nohup $PY main.py --listen 127.0.0.1 --port 8188 ${COMFY_ARGS:-} >> "$LOG" 2>&1 &
echo $! > $PIDF
echo "ComfyUI started (pid $(cat $PIDF)), log: $LOG"
