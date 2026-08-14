"""Remotion motion-template overlay: the render entry for a CLOSED set of two.

Draws one of two motion-graphic templates over an existing clip:

  hook-title    an animated title over the opening seconds
  cta-endcard   one call to action over the closing seconds, brand free

Both live in ``remotion-composer/src/MotionTemplates.tsx`` and are registered
in ``Root.tsx`` as ``MotionHookTitle`` and ``MotionCtaEndcard``. This tool is
the render entry for them and nothing else: it takes a template NAME from the
fixed set above plus the text to show, and it renders. It does not choose a
template, write copy, or accept a composition id from the caller, so no run
can invent a third motion look.

## Runtime scope

Remotion only, and deliberately with NO FFmpeg fallback. Word captions have
one (``remotion_caption_burn``) because a static subtitle burn is a fair
substitute for an animated one. A motion template has no substitute: an
FFmpeg drawtext with no motion is a different deliverable, and silently
producing it would be exactly the still-image-for-motion swap the agent guide
forbids. When Remotion is unavailable this tool fails and says so, and the
caller decides what to do.

The wiring mirrors ``remotion_caption_burn``: probe the clip with ffprobe,
copy it into ``public/`` so the composition can read it, write a props file
into ``public/demo-props/``, then run ``npx remotion render`` with the clip's
own width, height, fps and frame range. That is what keeps the output at the
resolution of the input rather than at the composition's default.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolCommandError,
    ToolResult,
    ToolStability,
    ToolTier,
)

# The closed set. Template name -> registered composition id. A name that is
# not a key here is refused; there is no pass-through for a composition id.
TEMPLATES: dict[str, str] = {
    "hook-title": "MotionHookTitle",
    "cta-endcard": "MotionCtaEndcard",
}
# Where each template sits on the timeline. Held here, next to the render, so
# the caller cannot place a hook title at the end by passing a window.
PLACEMENT: dict[str, str] = {
    "hook-title": "start",
    "cta-endcard": "end",
}
DEFAULT_SECONDS: dict[str, float] = {
    "hook-title": 2.5,
    "cta-endcard": 3.0,
}
FPS = 30
DEFAULT_ACCENT = "#22D3EE"


class RemotionMotionOverlay(BaseTool):
    name = "remotion_motion_overlay"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "motion_graphics"
    provider = "remotion"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    # Remotion is required, not preferred: there is no fallback path here.
    dependencies = ["cmd:npx", "cmd:ffprobe"]
    install_instructions = (
        "Node.js plus npm install in remotion-composer/, then "
        "npx remotion browser ensure"
    )
    agent_skills = ["remotion-best-practices"]

    capabilities = ["render_motion_template_overlay"]

    input_schema = {
        "type": "object",
        "required": ["input_path", "output_path", "template", "text"],
        "properties": {
            "input_path": {
                "type": "string",
                "description": "Path to the clip the overlay is drawn on.",
            },
            "output_path": {
                "type": "string",
                "description": "Path for the output video with the overlay.",
            },
            "template": {
                "type": "string",
                "enum": sorted(TEMPLATES),
                "description": (
                    "Which motion template to draw. The set is fixed: "
                    + ", ".join(sorted(TEMPLATES))
                ),
            },
            "text": {
                "type": "string",
                "description": "The one line of text the template shows.",
            },
            "duration_seconds": {
                "type": "number",
                "description": (
                    "How long the overlay holds. Defaults per template: "
                    "hook-title 2.5, cta-endcard 3.0."
                ),
            },
            "accent_color": {
                "type": "string",
                "default": DEFAULT_ACCENT,
                "description": "Accent color for the rule (hex).",
            },
        },
    }

    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=2048, vram_mb=0, disk_mb=500)
    idempotency_key_fields = ["input_path", "template", "text", "duration_seconds"]
    side_effects = ["writes the overlaid video to output_path"]
    user_visible_verification = [
        "Play the output and verify the text animates in the intended window",
        "Verify the frame size matches the source clip",
        "Verify the text sits inside the safe area on a phone screen",
    ]

    # ------------------------------------------------------------------ #
    #  Remotion detection
    # ------------------------------------------------------------------ #

    def _find_remotion_root(self) -> Path | None:
        """Find the remotion-composer directory relative to the repo."""
        candidates = [
            Path.cwd() / "remotion-composer",
            Path(__file__).resolve().parent.parent.parent / "remotion-composer",
        ]
        for p in candidates:
            if (
                p.is_dir()
                and (p / "package.json").exists()
                and (p / "node_modules").is_dir()
            ):
                return p
        return None

    # ------------------------------------------------------------------ #
    #  Probing
    # ------------------------------------------------------------------ #

    def _probe(self, input_path: str) -> tuple[float, int, int]:
        """Duration in seconds plus the source width and height."""
        dur = self.run_command([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            input_path,
        ])
        duration_s = float(dur.stdout.strip().split("\n")[0])

        dim = self.run_command([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            input_path,
        ])
        parts = dim.stdout.strip().split("x")
        return duration_s, int(parts[0]), int(parts[1])

    @staticmethod
    def _window(
        template: str, duration_s: float, hold_s: float
    ) -> tuple[float, float]:
        """The overlay window, from the template's own placement rule."""
        hold = max(0.1, min(float(hold_s), duration_s))
        if PLACEMENT[template] == "end":
            return round(max(0.0, duration_s - hold), 3), round(duration_s, 3)
        return 0.0, round(hold, 3)

    # ------------------------------------------------------------------ #
    #  Main execute
    # ------------------------------------------------------------------ #

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        input_path = inputs["input_path"]
        output_path = inputs["output_path"]
        template = str(inputs.get("template") or "").strip().lower()
        text = str(inputs.get("text") or "").strip()

        if template not in TEMPLATES:
            return ToolResult(
                success=False,
                error=(
                    f"unknown motion template {template!r}. The set is fixed: "
                    + ", ".join(sorted(TEMPLATES))
                ),
            )
        if not text:
            return ToolResult(
                success=False, error=f"template {template} needs text to show"
            )
        if not Path(input_path).exists():
            return ToolResult(success=False, error=f"Input video not found: {input_path}")

        root = self._find_remotion_root()
        if root is None or shutil.which("npx") is None:
            missing = "npx (Node.js)" if root is not None else "remotion-composer/node_modules"
            return ToolResult(
                success=False,
                error=(
                    f"Remotion is not available on this machine ({missing} not "
                    "found), and motion templates render only through Remotion. "
                    "There is no FFmpeg fallback for motion, so nothing was "
                    "rendered."
                ),
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        duration_s, width, height = self._probe(input_path)
        total_frames = math.ceil(duration_s * FPS)
        hold_s = inputs.get("duration_seconds")
        if hold_s is None:
            hold_s = DEFAULT_SECONDS[template]
        in_seconds, out_seconds = self._window(template, duration_s, float(hold_s))

        # The composition reads the clip out of public/, the same way the
        # caption burn does. Relative props paths are resolved against public/.
        pub_dir = root / "public" / "motion"
        pub_dir.mkdir(parents=True, exist_ok=True)
        dest_video = pub_dir / Path(input_path).name
        shutil.copy2(input_path, dest_video)

        props = {
            "videoSrc": f"motion/{dest_video.name}",
            "text": text,
            "inSeconds": in_seconds,
            "outSeconds": out_seconds,
            "accentColor": inputs.get("accent_color") or DEFAULT_ACCENT,
        }
        props_dir = root / "public" / "demo-props"
        props_dir.mkdir(parents=True, exist_ok=True)
        props_file = props_dir / f"motion-{template}-{Path(input_path).stem}.json"
        props_file.write_text(json.dumps(props, indent=2), encoding="utf-8")

        npx_bin = "npx.cmd" if sys.platform == "win32" else "npx"
        render_cmd = [
            npx_bin, "remotion", "render",
            TEMPLATES[template],
            f"--props={props_file.relative_to(root)}",
            f"--width={width}", f"--height={height}", f"--fps={FPS}",
            f"--frames=0-{max(0, total_frames - 1)}",
            "--codec=h264", "--crf=18",
            f"--output={str(Path(output_path).resolve())}",
        ]
        try:
            self.run_command(render_cmd, cwd=str(root))
        except ToolCommandError as exc:
            # Returned rather than raised so the caller gets the exit code and
            # the render's own words instead of a traceback. A blocked Remotion
            # compositor shows up here as exit 3236495362 (0xC0000142).
            return ToolResult(
                success=False,
                error=(
                    f"the Remotion render of {template} failed (exit "
                    f"{exc.returncode}): {(exc.detail or str(exc)).strip()[-600:]}. "
                    "Motion templates have no FFmpeg fallback, so nothing was "
                    "rendered."
                ),
                duration_seconds=round(time.time() - started, 2),
            )
        finally:
            # The copy in public/ is scratch. A cleanup failure must never
            # replace the result, good or bad, with a file-permission error.
            try:
                dest_video.unlink()
            except OSError:
                pass

        if not Path(output_path).exists():
            return ToolResult(
                success=False,
                error=f"the Remotion render of {template} produced no output",
                duration_seconds=round(time.time() - started, 2),
            )

        return ToolResult(
            success=True,
            data={
                "method": "remotion",
                "template": template,
                "composition": TEMPLATES[template],
                "output": output_path,
                "width": width,
                "height": height,
                "fps": FPS,
                "total_frames": total_frames,
                "duration_seconds": round(duration_s, 2),
                "in_seconds": in_seconds,
                "out_seconds": out_seconds,
            },
            artifacts=[output_path],
            duration_seconds=round(time.time() - started, 2),
        )
