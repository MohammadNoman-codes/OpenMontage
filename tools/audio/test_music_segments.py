"""Detection gate test: synthetic speech-like bursts must not trigger,
a sustained chord must. Runs without demucs or ffmpeg."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demucs_music_removal import detect_music_segments


def _speech_like(sr: int, seconds: float) -> np.ndarray:
    """Noise bursts with pauses: broadband (high spectral flatness)."""
    rng = np.random.default_rng(7)
    out = np.zeros(int(sr * seconds), dtype=np.float32)
    t = 0.0
    while t < seconds - 0.6:
        start = int(t * sr)
        burst = int(0.4 * sr)
        out[start : start + burst] = rng.normal(0, 0.1, burst).astype(np.float32)
        t += 0.7
    return out


def _chord(sr: int, seconds: float) -> np.ndarray:
    """Sustained three-tone chord: tonal (very low spectral flatness)."""
    t = np.arange(int(sr * seconds)) / sr
    sig = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.2, 329.6))
    return (0.2 * sig / 3).astype(np.float32)


def test_chord_detected_speech_not():
    sr = 16000
    audio = np.concatenate(
        [_speech_like(sr, 4.0), _chord(sr, 4.0), _speech_like(sr, 2.0)]
    )
    segments = detect_music_segments(audio, sr)
    assert segments, "sustained chord must be detected"
    assert any(
        s >= 3.0 and e <= 9.0 for s, e in segments
    ), f"segment outside the chord window: {segments}"
    assert not any(
        e <= 3.5 for _, e in segments
    ), "no segment may sit fully inside the speech-only region"


def test_silence_returns_empty():
    sr = 16000
    silence = np.zeros(sr * 6, dtype=np.float32)
    assert detect_music_segments(silence, sr) == []
