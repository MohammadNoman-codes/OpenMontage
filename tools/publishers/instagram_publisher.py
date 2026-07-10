"""Publish a rendered video to Instagram Reels via our connector. Wraps
connectors.instagram.publish; auth and rate limits live there. Needs an
approved app with instagram_content_publish (about 200 requests/hour, 25
posts/24h).

Thin BaseTool wrapper only. All HTTP, auth, throttling, and error hygiene
live in our repo's connector. This file never accepts, forwards, prints,
or logs a token: the connector loads credentials from E:\\Video AI\\.env
itself and its PublishError messages are token-free by construction.
"""
from __future__ import annotations

# --- sys.path bridge to our repo (see phase3 plan Task 7) --------------------
# The fork lives at E:\Video AI\openmontage, so parents[3] from
# tools/publishers/<file>.py is our repo root. Append (never insert at 0):
# this runs at ToolRegistry discovery time and front-loading our root could
# shadow a same-named fork package. Appending keeps the fork's packages
# winning inside the fork's process; our connectors resolve because the fork
# owns no top-level `connectors`/`common` (confirmed in pin notes).
import os
import sys
from pathlib import Path

VA_ROOT = Path(os.environ.get("VA_ROOT", str(Path(__file__).resolve().parents[3])))
if str(VA_ROOT) not in sys.path:
    sys.path.append(str(VA_ROOT))
# ----------------------------------------------------------------------------

from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


class InstagramPublisher(BaseTool):
    name = "instagram_publisher"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "instagram_graph_api"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    # env deps gate availability: the tool is UNAVAILABLE until IG credentials
    # exist, which is correct (no live publish without an approved app).
    dependencies = [
        "env:IG_USER_TOKEN",
        "env:IG_BUSINESS_ID",
        "python:requests",
        "python:dotenv",
    ]
    install_instructions = (
        "Set IG_USER_TOKEN and IG_BUSINESS_ID in E:\\Video AI\\.env for a "
        "Business/Creator account whose app has instagram_content_publish approved."
    )

    agent_skills = []
    capabilities = ["publish_reel"]
    supports = {"local_offline": False, "free": True, "uploads": True}
    best_for = ["publishing a finished vertical render as an Instagram Reel"]
    not_good_for = [
        "reading analytics (actuals live in the Phase 0 loop, not here)",
        "publishing to any account other than the configured owned one",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path"],
        "properties": {
            "video_path": {"type": "string", "description": "Rendered video file"},
            "caption": {"type": "string", "default": "", "description": "Reel caption"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "media_id": {"type": "string"},
            "permalink": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=0, network_required=True
    )
    idempotency_key_fields = ["video_path"]
    side_effects = ["publishes a public Reel to the configured Instagram account"]
    fallback = None
    user_visible_verification = [
        "Confirm the Reel is live on the intended account and the permalink opens",
    ]

    def execute(self, inputs: "dict[str, Any]") -> "ToolResult":
        params = inputs
        # Connector imports resolve through the VA_ROOT bridge above.
        from connectors.instagram.publish import PublishError, publish_reel

        try:
            result = publish_reel(params["video_path"], params.get("caption", ""))
        except PublishError as exc:
            # The connector guarantees a token-free message; surface it as-is
            # through the pinned return-value error convention.
            return ToolResult(success=False, error=str(exc))
        return ToolResult(
            success=True,
            data={
                "media_id": result["media_id"],
                "permalink": result.get("permalink") or "",
            },
        )
