"""ComfyUI IMAGE tensors are float32 [batch, height, width, channels], 0-1 for display images."""

import torch


class LPGrade:
    CATEGORY = "lp"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "grade"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "exposure": ("FLOAT", {"default": 0.0, "min": -10.0, "max": 10.0, "step": 0.1,
                                       "tooltip": "stops"}),
                "gamma": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 5.0, "step": 0.01}),
                "saturation": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.01}),
                "clamp": ("BOOLEAN", {"default": True}),
            }
        }

    def grade(self, image, exposure, gamma, saturation, clamp):
        rgb, alpha = image[..., :3], image[..., 3:]
        out = rgb * (2.0 ** exposure)
        if gamma != 1.0:
            out = torch.sign(out) * out.abs().pow(1.0 / gamma)
        if saturation != 1.0:
            luma = (out * torch.tensor([0.2126, 0.7152, 0.0722], device=out.device)).sum(-1, keepdim=True)
            out = luma + (out - luma) * saturation
        if clamp:
            out = out.clamp(0.0, 1.0)
        return (torch.cat([out, alpha], dim=-1) if alpha.shape[-1] else out,)


class LPImageStats:
    CATEGORY = "lp"
    RETURN_TYPES = ("STRING",)
    FUNCTION = "stats"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    def stats(self, image):
        lines = [f"shape {tuple(image.shape)}"]
        for i, name in enumerate("RGBA"[: image.shape[-1]]):
            c = image[..., i]
            lines.append(f"{name}: min {c.min():.4f} max {c.max():.4f} mean {c.mean():.4f}")
        text = "\n".join(lines)
        return {"ui": {"text": [text]}, "result": (text,)}


NODE_CLASS_MAPPINGS = {"LPGrade": LPGrade, "LPImageStats": LPImageStats}
NODE_DISPLAY_NAME_MAPPINGS = {"LPGrade": "LP Grade", "LPImageStats": "LP Image Stats"}
