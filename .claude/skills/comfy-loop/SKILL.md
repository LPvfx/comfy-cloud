---
name: comfy-loop
description: Build, test and iterate on ComfyUI custom nodes and workflows against the rented GPU box (or a local CPU ComfyUI), closing the loop by running workflows through the API and inspecting outputs. Use when asked to write a ComfyUI node, fix a workflow, try a model, or "get X working in Comfy".
allowed-tools: Bash(comfy-cloud status) Bash(comfy-cloud run *) Bash(comfy-cloud push*) Bash(comfy-cloud logs*) Bash(comfy-cloud pull*)
---

# ComfyUI build-test loop

## 0. Check the target
Run `comfy-cloud status`. If no instance is up, **ask before renting** (it
costs money) - suggest the GPU and model set you'd use and the rough $/h from
`comfy-cloud offers`. For pure logic (nodes that don't need a model), a local
CPU ComfyUI is enough - see CLAUDE.md "Testing without a GPU".

## 1. Know the real node interfaces
Never guess input names. Query the live server:
`curl -s localhost:8188/object_info/<ClassName> | jq` (or `/object_info` and filter).

## 2. Nodes
- Edit `custom_nodes/<pack>/`. IMAGE tensors are float32 `[B,H,W,C]`.
- Deploy with `comfy-cloud push` (add `--install` if requirements changed).
- Check `comfy-cloud logs -n 60` for import errors after every push.

## 3. Workflows
- API-format JSON in `workflows/`. Get a base by loading a template in the UI
  and exporting API format, or write it by hand from `object_info`.
- Run: `comfy-cloud run workflows/<wf>.json --json [--set Title.input=value] [--image LoadImage=path]`
- The JSON result lists output files. **Look at them** (Read the image, or
  extract a frame from video with ffmpeg) before claiming success.
- On `node errors` / `execution error`, fix the cause and rerun - don't
  paper over it with a different workflow.

## 4. Report
What changed, the command that proves it works, the output path(s), timing,
and anything you couldn't verify. If you rented the box this session, remind
the user it's still running (or `comfy-cloud down` if they said to).
