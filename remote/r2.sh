#!/usr/bin/env bash
# Runs ON THE BOX. Sync your own files with a Cloudflare R2 bucket so they
# survive between rentals (free tier: 10GB). Needs R2_* vars in .env.
#
#   r2.sh pull     bucket/loras -> ComfyUI/models/loras, bucket/input -> ComfyUI/input
#   r2.sh push     ComfyUI/models/loras -> bucket/loras (your trained LoRAs)
#   r2.sh outputs  ComfyUI/output -> bucket/output/<date>
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$HERE/.env" ]] && source "$HERE/.env"
: "${R2_ACCOUNT_ID:?set R2_ACCOUNT_ID in .env}" "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}" "${R2_BUCKET:?}"
command -v rclone >/dev/null || { apt-get install -y -qq rclone >/dev/null; }

export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
  RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
C=/workspace/ComfyUI
B="r2:$R2_BUCKET"
case "${1:-}" in
  pull)    rclone copy -P "$B/loras" "$C/models/loras"; rclone copy -P "$B/input" "$C/input" ;;
  push)    rclone copy -P "$C/models/loras" "$B/loras" --exclude "ltx-*" ;;
  outputs) rclone copy -P "$C/output" "$B/output/$(date +%F)" ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
