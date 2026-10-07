"""Re-cut timestamp-aligned word clips from saved full TTS audio without API calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(
    os.environ.get(
        "TYPECAST_RECUT_INPUT_DIR",
        Path(__file__).with_name("typecast-sdk-quality-test-jinhee-eunsol-20-words-v2"),
    )
)
FULL_DIR = ROOT / "full"
OUTPUT_DIR = Path(
    os.environ.get("TYPECAST_RECUT_OUTPUT_DIR", ROOT / "word-only-recut")
)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")

    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(exist_ok=True)
    for item in manifest["outputs"]:
        index = manifest["words"].index(item["word"]) + 1
        voice = item["voice"]
        target_word_count = len(item["word"].split())
        # Old manifests retain all source text in `input`; target words are at
        # the end, so use their count to span multiword entries correctly.
        segments = item.get("segments")
        if segments:
            target_segments = segments
        else:
            raise RuntimeError("This manifest predates multiword timestamp data; regenerate timestamps first")
        if len(target_segments) != target_word_count:
            raise RuntimeError(f"Unexpected timestamp count for {item['word']}")
        start = float(target_segments[0]["start"])
        end = float(target_segments[-1]["end"]) + 0.14
        duration = end - start
        input_path = FULL_DIR / f"{index:02d}_{voice}.mp3"
        output_path = OUTPUT_DIR / f"{index:02d}_{voice}.mp3"
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(input_path), "-ss", f"{start:.3f}",
                "-t", f"{duration:.3f}", "-vn", "-c:a", "libmp3lame", "-q:a", "3",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )


if __name__ == "__main__":
    main()
