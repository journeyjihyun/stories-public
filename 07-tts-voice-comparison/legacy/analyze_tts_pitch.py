"""Measure end-of-word F0 movement for the published Typecast word clips."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import parselmouth


ROOT = Path(__file__).parent
DEFAULT_AUDIO_DIR = ROOT / "dist" / "audio"
DEFAULT_MANIFEST = ROOT / "typecast-sdk-quality-test-jinhee-eunsol-20-words-v2" / "manifest.json"


def semitones(f0: np.ndarray) -> np.ndarray:
    return 12 * np.log2(f0 / np.median(f0))


def measure(audio_path: Path | parselmouth.Sound) -> dict[str, float | int | None]:
    sound = audio_path if isinstance(audio_path, parselmouth.Sound) else parselmouth.Sound(str(audio_path))
    pitch = sound.to_pitch_ac(time_step=0.01, pitch_floor=80, pitch_ceiling=700)
    times = pitch.xs()
    f0 = pitch.selected_array["frequency"]
    valid = np.isfinite(f0) & (f0 > 0)
    times, f0 = times[valid], f0[valid]
    if len(f0) < 8:
        return {"voiced_frames": int(len(f0)), "rise_st": None, "slope_st_per_sec": None}

    # Discard the edges, where a fade-out or consonant can distort F0.
    start = np.quantile(times, 0.10)
    end = np.quantile(times, 0.93)
    tail_start = start + (end - start) * 0.45
    mask = (times >= tail_start) & (times <= end)
    tail_times, tail_f0 = times[mask], f0[mask]
    if len(tail_f0) < 6:
        return {"voiced_frames": int(len(f0)), "rise_st": None, "slope_st_per_sec": None}

    tail_st = semitones(tail_f0)
    third = max(1, len(tail_st) // 3)
    rise_st = float(np.median(tail_st[-third:]) - np.median(tail_st[:third]))
    slope = float(np.polyfit(tail_times - tail_times[0], tail_st, 1)[0])
    return {
        "voiced_frames": int(len(f0)),
        "rise_st": round(rise_st, 2),
        "slope_st_per_sec": round(slope, 2),
    }


def is_rising_issue(metrics: dict[str, float | int | None]) -> bool:
    """Flag a clearly rising word ending, calibrated against the comparison set."""
    rise = metrics["rise_st"]
    slope = metrics["slope_st_per_sec"]
    return (
        isinstance(rise, float)
        and isinstance(slope, float)
        and rise >= 2.0
        and slope >= 20.0
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = []
    for index, word in enumerate(manifest["words"], start=1):
        for voice in manifest["voices"]:
            metrics = measure(args.audio_dir / f"{index:02d}_{voice}.mp3")
            rows.append({"word": word, "voice": voice, **metrics})

    print("word\tvoice\trise_st\tslope_st_per_sec\tvoiced_frames\trising_issue")
    for row in rows:
        print(
            f"{row['word']}\t{row['voice']}\t{row['rise_st']}\t"
            f"{row['slope_st_per_sec']}\t{row['voiced_frames']}\t"
            f"{is_rising_issue(row)}"
        )


if __name__ == "__main__":
    main()
