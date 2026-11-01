# comfy-cloud

CLI (`src/comfy_cloud/`) that rents a Vast.ai GPU, sets up ComfyUI on it
(`remote/*.sh`, run on the box over SSH), and tunnels it to localhost:8188.

## Rules
- Renting costs real money. Never run `comfy-cloud up` or rent anything unless
  the user asked in this conversation. Always finish a session you started
  with `comfy-cloud down` unless told to keep it running; report the cost
  line it prints.
- `remote/` scripts run on Ubuntu inside a pytorch CUDA image as root. Keep
  them idempotent; never reinstall torch (the image's CUDA build must stay).
- ComfyUI must bind to 127.0.0.1 only.
- Model files: add to `models.yaml` with the exact repo path, verified against
  the Hugging Face API (`https://huggingface.co/api/models/<repo>`), never guessed.
- Secrets only in `.env` (git-ignored).

## Developing nodes and workflows
Use the `comfy-loop` skill. Nodes live in `custom_nodes/<pack>/`; workflows for
`comfy-cloud run` must be API format JSON in `workflows/`.

## Testing without a GPU
ComfyUI runs on CPU for logic tests: clone ComfyUI, `pip install` its
requirements, run `remote/setup.sh smoke` with `PYTHON=<venv python> SKIP_APT=1`,
start with `COMFY_ARGS=--cpu bash remote/start.sh`, then
`comfy-cloud run workflows/smoke_test.json --json`.
