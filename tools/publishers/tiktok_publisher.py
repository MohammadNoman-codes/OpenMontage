"""Publish a rendered video to TikTok via our connector. Wraps
connectors.tiktok.publish; auth, silent-refresh handling, and the 6
requests/minute throttle live there. SELF_ONLY until the app passes
TikTok audit.

Thin BaseTool wrapper only. All HTTP, auth, throttling, and error hygiene
live in our repo's connector. This file never accepts, forwards, prints,
or logs a token: the connector loads credentials from E:\\Video AI\\.env
and store/tiktok_tokens.json itself, and its error messages are token-free
by construction. Graceful re-auth means the tool fails with a plain re-run
instruction, never with token internals.
"""
from __future__ import annotations

# --- sys.path bridge to our repo (see phase3 plan Task 7) --------------------
# parents[3] from tools/publishers/<file>.py is our repo root. Append (never
# insert at 0): this runs at discovery time; the fork owns no top-level
# `connectors`/`common`, so our modules resolve without shadowing the fork.
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


class TikTokPublisher(BaseTool):
    name = "tiktok_publisher"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "tiktok_content_posting_api"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = [
        "env:TIKTOK_CLIENT_KEY",
        "env:TIKTOK_CLIENT_SECRET",
        "python:requests",
        "python:dotenv",
    ]
    install_instructions = (
        "Set TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in E:\\Video AI\\.env, then "
        "run: python -m connectors.tiktok.auth login (from E:\\Video AI)."
    )

    agent_skills = []
    capabilities = ["publish_video"]
    supports = {"local_offline": False, "free": True, "uploads": True}
    best_for = ["publishing a finished vertical render to TikTok (SELF_ONLY)"]
    not_good_for = [
        "public posting before the TikTok app passes audit (SELF_ONLY only)",
        "reading analytics (TikTok has no analytics API; actuals are manual CSV)",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path"],
        "properties": {
            "video_path": {"type": "string", "description": "Rendered video file"},
            "caption": {"type": "string", "default": "", "description": "Post title"},
            "privacy_level": {
                "type": "string",
                "default": "SELF_ONLY",
                "description": "Stays SELF_ONLY until the app passes TikTok audit",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "publish_id": {"type": "string"},
            "status": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=0, network_required=True
    )
    idempotency_key_fields = ["video_path"]
    side_effects = ["uploads and publishes a video to the configured TikTok account"]
    fallback = None
    user_visible_verification = [
        "Confirm the post appears in the account (SELF_ONLY is private to you)",
    ]

    def execute(self, inputs: "dict[str, Any]") -> "ToolResult":
        params = inputs
        from connectors.tiktok.auth import ReAuthRequired
        from connectors.tiktok.publish import TikTokPublishError, publish_video

        try:
            result = publish_video(
                params["video_path"],
                params.get("caption", ""),
                privacy_level=params.get("privacy_level", "SELF_ONLY"),
            )
        except ReAuthRequired as exc:
            return ToolResult(
                success=False,
                error=(
                    f"TikTok re-auth needed: {exc}. From E:\\Video AI run: "
                    f"python -m connectors.tiktok.auth login"
                ),
            )
        except TikTokPublishError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(
            success=True,
            data={"publish_id": result["publish_id"], "status": result["status"]},
        )
