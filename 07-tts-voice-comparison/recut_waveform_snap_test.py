"""Experiment: snap the clip start to a nearby silent-to-speech boundary.

This uses saved full Typecast audio; it never makes an API request and writes
to a new folder so the existing word-only clips remain unchanged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).with_name("typecast-sdk-quality-test-jinhee-eunsol-20-words-v2")
VOICE = "jinhee"
FRAME_SECONDS = 0.005
WINDOW_SECONDS = 0.010
SEARCH_BEFORE_SECONDS = 0.180
# A timestamp is a hint, but the output must never start later than it.
# Otherwise a quiet consonant inside the target can become a false boundary.
SEARCH_AFTER_SECONDS = 0.005
DESIRED_LEAD_IN_SECONDS = 0.030
MIN_SILENCE_SECONDS = 0.020


def silent_runs(audio_path: Path) -> tuple[list[tuple[float, float]], float]:
    samples, sample_rate = sf.read(audio_path, always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    hop = max(1, round(sample_rate * FRAME_SECONDS))
    window = max(hop, round(sample_rate * WINDOW_SECONDS))
    rms = np.array(
        [
            np.sqrt(np.mean(np.square(samples[offset : offset + window])))
            for offset in range(0, max(1, len(samples) - window), hop)
        ]
    )
    db = 20 * np.log10(np.maximum(rms, 1e-8))
    # Relative threshold keeps the rule stable across normalized MP3 files.
    threshold_db = max(-50.0, float(np.percentile(db, 95) - 38.0))
    is_silent = db < threshold_db

    runs: list[tuple[float, float]] = []
    run_start: int | None = None
    for index, value in enumerate(is_silent):
        if value and run_start is None:
            run_start = index
        elif not value and run_start is not None:
            if (index - run_start) * FRAME_SECONDS >= MIN_SILENCE_SECONDS:
                runs.append((run_start * FRAME_SECONDS, index * FRAME_SECONDS))
            run_start = None
    return runs, threshold_db


def choose_start(audio_path: Path, timestamp: float) -> tuple[float, dict[str, object]]:
    runs, threshold_db = silent_runs(audio_path)
    candidates = [
        run
        for run in runs
        if timestamp - SEARCH_BEFORE_SECONDS <= run[1] <= timestamp + SEARCH_AFTER_SECONDS
    ]
    if not candidates:
        return timestamp, {"mode": "timestamp_fallback", "threshold_db": round(threshold_db, 1)}

    silence_start, silence_end = min(candidates, key=lambda run: abs(run[1] - timestamp))
    snapped_start = max(silence_start, silence_end - DESIRED_LEAD_IN_SECONDS)
    return snapped_start, {
        "mode": "waveform_snap",
        "threshold_db": round(threshold_db, 1),
        "silence_start_seconds": round(silence_start, 3),
        "silence_end_seconds": round(silence_end, 3),
    }
