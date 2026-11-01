"""lp_nodes - your own ComfyUI nodes. Edit locally, `comfy-cloud push` to deploy.

Starter nodes:
  LP Grade        exposure (stops), gamma, saturation - scene-referred friendly
  LP Image Stats  min/max/mean per channel as a string (handy for debugging)
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
