"""Demucs music removal, applied only on detected music segments.

Rule (project CLAUDE.md): never apply music removal across a whole track
by default; it can degrade speech. This tool gates the audio with an
energy plus spectral-flatness detector, runs Demucs once over the full
extracted audio to get the vocals stem, then splices the stem in ONLY
inside detected segments with short crossfades. Speech outside detected
segments stays the untouched original. force_full_track is an explicit
operator opt-in and defaults to False.

Demucs is MIT licensed. device="auto" uses the GPU when torch sees CUDA
(RTX 3060) and falls back to CPU otherwise. The detected segment list is
returned so the operator can review it at the checkpoint.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
FRAME_S = 0.5
MIN_MUSIC_S = 3.0
PAD_S = 0.25
RMS_FLOOR_DB = -45.0
FLATNESS_MAX = 0.35
SUSTAIN_FRAMES = 4
CROSSFADE_S = 0.05
DEMUCS_MODEL = "htdemucs"


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({cmd[0]}): {proc.stderr[-500:]}")


def extract_audio(video_path: str, wav_path: str) -> None:
    _run(
        [
            "ffmpeg", "-y", "-i", video_path, "-vn",
            "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", wav_path,
        ]
    )


def detect_music_segments(
    samples: np.ndarray,
    sr: int,
    frame_s: float = FRAME_S,
    min_music_s: float = MIN_MUSIC_S,
    pad_s: float = PAD_S,
    rms_floor_db: float = RMS_FLOOR_DB,
    flatness_max: float = FLATNESS_MAX,
    sustain_frames: int = SUSTAIN_FRAMES,
) -> list[tuple[float, float]]:
    """Return [(start_s, end_s)] windows that look like sustained music.

    Coarse on purpose: a frame counts as music-suspect when it has audible
    energy AND a tonal spectrum (low spectral flatness), and only runs of
    at least sustain_frames consecutive suspect frames survive. Speech
    alone is broadband and gappy, so it does not sustain. Thresholds are
    parameters; the segment list is surfaced for operator review.
    """
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    frame_len = max(1, int(frame_s * sr))
    n_frames = len(mono) // frame_len
    if n_frames == 0:
        return []
    eps = 1e-10
    flags = np.zeros(n_frames, dtype=bool)
    window = np.hanning(frame_len)
    for i in range(n_frames):
        frame = mono[i * frame_len : (i + 1) * frame_len]
        rms = float(np.sqrt(np.mean(frame**2)) + eps)
        if 20.0 * np.log10(rms) < rms_floor_db:
            continue
        mag = np.abs(np.fft.rfft(frame * window)) + eps
        flatness = float(np.exp(np.mean(np.log(mag))) / np.mean(mag))
        if flatness <= flatness_max:
            flags[i] = True

    sustained = np.zeros_like(flags)
    run_start = None
    for i, f in enumerate(np.append(flags, False)):
        if f and run_start is None:
            run_start = i
        elif not f and run_start is not None:
            if i - run_start >= sustain_frames:
                sustained[run_start:i] = True
            run_start = None

    segments: list[tuple[float, float]] = []
    start = None
    total_s = len(mono) / sr
    for i, f in enumerate(np.append(sustained, False)):
        if f and start is None:
            start = i
        elif not f and start is not None:
            s = max(0.0, start * frame_s - pad_s)
            e = min(total_s, i * frame_s + pad_s)
            if e - s >= min_music_s:
                segments.append((s, e))
            start = None
    return segments


def _resolve_device(device: str) -> str:
    """Resolve device="auto" to the device Demucs actually uses (cuda when
    torch sees the GPU, cpu otherwise), so summaries and checkpoint
    evidence report the true device, never the literal string auto."""
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def separate_vocals(wav_path: str, work_dir: str, device: str = "auto") -> str:
    """Run Demucs once over the full audio; return the vocals stem path.

    Separation is computed over the whole track for quality, but the stem
    is APPLIED only inside detected segments by splice_vocals.

    Separation runs IN PROCESS and the stem is written with soundfile on
    purpose. The `demucs.separate` CLI writes its stems through
    torchaudio.save, and torchaudio 2.9+ routes every save through
    TorchCodec, which needs FFmpeg 4 to 7 shared libraries present. This
    machine has a static FFmpeg 8 on PATH, so the CLI path fails with
    "Could not load this library: libtorchcodec_core4.dll" on any clip
    that actually contains music. soundfile writes the WAV directly and
    keeps the tool working with no extra system dependency.
    """
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio
    from demucs.pretrained import get_model

    device = _resolve_device(device)
    samples, sr = sf.read(wav_path, dtype="float32", always_2d=True)

    model = get_model(DEMUCS_MODEL)
    model.eval()

    wav = torch.from_numpy(samples.T)
    wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()
    sources = apply_model(model, wav[None], device=device, progress=False)[0]
    sources = sources * ref.std() + ref.mean()
    vocals = sources[model.sources.index("vocals")].cpu().numpy().T

    stem = Path(work_dir) / "vocals.wav"
    sf.write(str(stem), vocals, model.samplerate)
    if not stem.is_file():
        raise RuntimeError(f"demucs did not produce the vocals stem at {stem}")
    return str(stem)


def splice_vocals(
    original: np.ndarray,
    vocals: np.ndarray,
    sr: int,
    segments: list[tuple[float, float]],
    crossfade_s: float = CROSSFADE_S,
) -> np.ndarray:
    """Replace only the detected segments with the vocals stem, with a
    short linear crossfade at each boundary. Everything outside the
    segments is the untouched original."""
    out = original.copy()
    n = min(len(original), len(vocals))
    fade = max(1, int(crossfade_s * sr))
    for start_s, end_s in segments:
        a = max(0, int(start_s * sr))
        b = min(n, int(end_s * sr))
        if b <= a:
            continue
        out[a:b] = vocals[a:b]
        k = min(fade, (b - a) // 2)
        if k > 0:
            ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)
            if out.ndim == 2:
                ramp = ramp[:, None]
            out[a : a + k] = (
                original[a : a + k] * (1.0 - ramp) + vocals[a : a + k] * ramp
            )
            out[b - k : b] = (
                vocals[b - k : b] * (1.0 - ramp) + original[b - k : b] * ramp
            )
    return out


def remove_music(
    video_path: str,
    out_path: str,
    device: str = "auto",
    force_full_track: bool = False,
) -> dict:
    """Detect music segments, separate, splice, remux. Returns a summary
    dict: output path, whether anything was applied, the segment list in
    seconds, the device actually used (auto is resolved to cuda or cpu
    up front, so the summary is true), and a plain note."""
    device = _resolve_device(device)
    with tempfile.TemporaryDirectory(prefix="demucs_") as work:
        wav = str(Path(work) / "audio.wav")
        extract_audio(video_path, wav)
        samples, sr = sf.read(wav, dtype="float32", always_2d=True)
        segments = detect_music_segments(samples, sr)
        if force_full_track:
            segments = [(0.0, len(samples) / sr)]
        if not segments:
            shutil.copyfile(video_path, out_path)
            return {
                "output": out_path,
                "applied": False,
                "segments": [],
                "device": device,
                "note": "no music segments detected; audio untouched",
            }
        vocals_path = separate_vocals(wav, work, device=device)
        vocals, vsr = sf.read(vocals_path, dtype="float32", always_2d=True)
        if vsr != sr:
            raise RuntimeError(f"stem sample rate {vsr} != source {sr}")
        spliced = splice_vocals(samples, vocals, sr, segments)
        clean_wav = str(Path(work) / "clean.wav")
        sf.write(clean_wav, spliced, sr)
        _run(
            [
                "ffmpeg", "-y", "-i", video_path, "-i", clean_wav,
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", out_path,
            ]
        )
        return {
            "output": out_path,
            "applied": True,
            "segments": [[round(s, 2), round(e, 2)] for s, e in segments],
            "device": device,
            "note": (
                f"music removal applied on {len(segments)} detected "
                f"segment(s) only; speech outside segments untouched"
            ),
        }


# The registry discovers this BaseTool subclass by importing the module from
# the fork root, where `tools.base_tool` resolves. The detection unit test
# imports this module from inside tools/audio (where `tools` is not a package
# on sys.path), so the import is guarded: detect_music_segments/remove_music
# stay usable without the tool contract, and the subclass is defined only when
# imported as part of the fork's tool package.
try:
    from typing import Any

    from tools.base_tool import (
        BaseTool,
        Determinism,
        ExecutionMode,
        ResourceProfile,
        ResumeSupport,
        RetryPolicy,
        ToolResult,
        ToolStability,
        ToolTier,
    )

    class DemucsMusicRemoval(BaseTool):
        """Segment-gated music removal (never whole-track by default)."""

        name = "demucs_music_removal"
        version = "0.1.0"
        tier = ToolTier.ENHANCE
        capability = "audio_cleanup"
        provider = "local"
        stability = ToolStability.EXPERIMENTAL
        execution_mode = ExecutionMode.SYNC
        determinism = Determinism.DETERMINISTIC

        dependencies = ["python:demucs", "python:soundfile", "binary:ffmpeg"]
        install_instructions = (
            "pip install demucs soundfile  # ffmpeg must be on PATH; "
            "CUDA torch optional for the RTX 3060, CPU works"
        )
        agent_skills = ["music-removal"]
        capabilities = ["music_removal", "vocal_isolation"]

        input_schema = {
            "type": "object",
            "required": ["video_path", "output_path"],
            "properties": {
                "video_path": {"type": "string", "description": "Source video file"},
                "output_path": {"type": "string", "description": "Cleaned video output path"},
                "device": {"type": "string", "default": "auto", "description": "auto | cuda | cpu"},
                "force_full_track": {
                    "type": "boolean",
                    "default": False,
                    "description": "Explicit operator opt-in to treat the whole track as music",
                },
            },
        }
        output_schema = {
            "type": "object",
            "properties": {
                "output": {"type": "string"},
                "applied": {"type": "boolean"},
                "segments": {"type": "array"},
                "device": {"type": "string"},
                "note": {"type": "string"},
            },
        }

        resource_profile = ResourceProfile(
            cpu_cores=4, ram_mb=4096, vram_mb=0, disk_mb=1000, network_required=False
        )
        retry_policy = RetryPolicy(max_retries=1, retryable_errors=["MemoryError"])
        resume_support = ResumeSupport.FROM_START
        idempotency_key_fields = ["video_path", "output_path", "device", "force_full_track"]
        side_effects = ["writes a cleaned video to output_path"]
        fallback = None
        user_visible_verification = [
            "Confirm the detected music segments match where music actually plays",
            "Confirm speech outside the detected segments is untouched",
        ]

        def execute(self, inputs: "dict[str, Any]") -> "ToolResult":
            try:
                result = remove_music(
                    video_path=inputs["video_path"],
                    out_path=inputs["output_path"],
                    device=inputs.get("device", "auto"),
                    force_full_track=bool(inputs.get("force_full_track", False)),
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(success=False, error=f"music removal failed: {exc}")
            return ToolResult(success=True, data=result, artifacts=[result["output"]])

except ImportError:
    # tools.base_tool not importable here (running the detection unit test from
    # tools/audio). The pure functions above remain available.
    pass
