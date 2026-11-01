#!/usr/bin/env bash
# One-time setup on the Mac: CLI, Vast API key, SSH key.
set -euo pipefail
cd "$(dirname "$0")"
say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

command -v uv >/dev/null || { say "Installing uv"; curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
command -v rsync >/dev/null || { echo "rsync missing (it ships with macOS; on Linux: apt install rsync)"; exit 1; }

say "Installing comfy-cloud and the Vast CLI"
uv tool install --force --editable . --python 3.12
uv tool install --force vastai

[[ -f .env ]] || { cp .env.example .env; echo "  created .env"; }

if [[ ! -f "$HOME/.config/vastai/vast_api_key" ]]; then
  say "Vast API key"
  echo "Create one at https://cloud.vast.ai/manage-keys/ and paste it here:"
  read -r -s key
  vastai set api-key "$key"
fi

KEY="$HOME/.ssh/id_ed25519"
if [[ ! -f "$KEY" ]]; then
  say "Creating an SSH key"
  ssh-keygen -t ed25519 -N "" -f "$KEY" -C "comfy-cloud"
fi
say "Registering your SSH public key with Vast (safe to repeat)"
vastai create ssh-key "$(cat "$KEY.pub")" -y || echo "  (already registered?)"

say "Checking"
vastai show user --raw >/dev/null && echo "  Vast account OK"
cat <<'EOF'

Ready. Try:
  comfy-cloud offers
  comfy-cloud up            # then `comfy-cloud down` when finished!
Add HF_TOKEN to .env before using gated models (LTX).
EOF
