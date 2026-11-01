# comfy-cloud

ComfyUI on a rented NVIDIA GPU (Vast.ai), used from the Mac as if it were
local: one command rents a box, installs ComfyUI and your nodes, downloads the
models, and opens `http://localhost:8188` through an SSH tunnel. One command
tears it down. Pay only for GPU hours.

```bash
git clone https://github.com/LPvfx/comfy-cloud ~/dev/comfy-cloud && cd ~/dev/comfy-cloud
./bootstrap.sh            # installs the CLI, sets up your Vast API key + SSH key
comfy-cloud offers        # what's cheap right now
comfy-cloud up            # rent the cheapest RTX 4090 under $0.80/h, smoke models only
comfy-cloud up --gpu RTX_5090 --models ltx25
comfy-cloud down          # copies outputs to ./outputs, destroys the box
```

## Commands

| command | does |
|---|---|
| `offers` | Cheapest matching offers (`--gpu`, `--max-price`, `--disk`, `--regions GB,NL,DE`). |
| `up` | Rent → wait for boot → sync this repo → `remote/setup.sh` (ComfyUI, `nodes.txt`, your `custom_nodes/`, model sets) → start ComfyUI on the box's localhost → SSH tunnel → open browser. Re-running `up` reconnects to the existing box. |
| `status` | Instance, tunnel, ComfyUI health and **cost so far**. Also warns about other running Vast instances. |
| `run WF.json` | Queue an API-format workflow, wait, download outputs to `outputs/runs/`. `--set Node.input=value` (node id, class or title), `--image Node=photo.jpg` uploads inputs, `--json` for scripts/agents. |
| `push` | Sync `custom_nodes/` + `workflows/` up and restart ComfyUI (`--install` to reinstall requirements). The node-dev loop. |
| `models SETS` | Download more model sets on a live box. |
| `logs [-f]` | ComfyUI log. |
| `ssh [cmd]` | Shell on the box. |
| `pull` | Outputs → `./outputs/<date>/`. |
| `down` | `pull`, close tunnel, destroy instance (billing stops). |

## Files

```
models.yaml          model sets -> Hugging Face files -> ComfyUI models/ folders
nodes.txt            third-party node packs (git URLs, pin with @commit)
custom_nodes/        YOUR nodes - synced and symlinked into ComfyUI
  lp_nodes/          starter pack: LP Grade, LP Image Stats
workflows/           API-format workflows for `run` (also appear in ComfyUI's browser)
remote/setup.sh      runs on the box; idempotent
remote/start.sh      start/restart ComfyUI bound to 127.0.0.1
remote/r2.sh         optional Cloudflare R2 sync for your LoRAs/inputs/outputs
.claude/skills/      comfy-loop: lets Claude build/test nodes and workflows end to end
```

## Storage strategy (cheap by default)

Nothing persistent is rented. Public weights come from Hugging Face on each
`up` (datacenter boxes pull tens of GB in minutes). Your code is in git, and
anything you make that must survive between sessions (trained LoRAs, inputs)
can go in a Cloudflare R2 bucket - the free tier covers 10GB:

```bash
comfy-cloud ssh bash /workspace/comfy-cloud/remote/r2.sh pull   # at start
comfy-cloud ssh bash /workspace/comfy-cloud/remote/r2.sh push   # before down
```

If start-up time starts to annoy you, that's when a persistent volume
(Vast local volume, or RunPod network volume) earns its monthly fee.

## Notes

- **Workflows for `run` must be API format**: in ComfyUI, Workflow → Export (API).
  For LTX, load the built-in LTX-2.5 template from ComfyUI's template browser,
  tweak it, then export.
- **Gated models**: accept the licence on the Hugging Face model page once and
  put `HF_TOKEN` in `.env`. Secrets are copied to the box over SSH (mode 600),
  not stored in Vast's instance config.
- **Licences**: LTX-2.x is a community licence (free under $10M ARR); several
  research models are non-commercial; Tencent's licence excludes the UK.
  Check before using anything for work.
- ComfyUI only listens on the box's localhost; access is only through your SSH tunnel.
- **Forgetting to `down` costs money.** `comfy-cloud status` shows the running
  total; Ctrl-C during `up` reminds you the box is still billing.
- Defaults (GPU, price cap, disk, image, model sets) can be set in `.env`.
