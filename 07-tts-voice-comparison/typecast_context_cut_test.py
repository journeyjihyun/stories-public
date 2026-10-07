"""Generate carrier-sentence audio and timestamp-aligned word-only clips."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from typecast import Typecast
from typecast.models import Output, PresetPrompt, TTSModel, TTSRequestWithTimestamps


WORDS = ["정말", "야호", "어휴"]
OVERRIDE_WORDS = os.environ.get("TYPECAST_TEST_WORDS")
if OVERRIDE_WORDS:
    WORDS = [word.strip() for word in OVERRIDE_WORDS.split(",") if word.strip()]
VOICES = {
    "jinhee": "tc_6731b2b2478a48710ecc9158",
    "hanyeong": "tc_6731b3ac075b04a944644234",
    "minjeong": "tc_6699eb0f10b8e361d6a9aba1",
    "eunsol": "tc_67db72eb93add6902ea41e5c",
    "geunseok": "tc_663c68c34652f4195ddea850",
    "jinhan": "tc_673ecaa071c8f61f01459243",
}
VOICE_NAMES = os.environ.get("TYPECAST_VOICE_NAMES")
if VOICE_NAMES:
    requested = [name.strip() for name in VOICE_NAMES.split(",") if name.strip()]
    unknown = [name for name in requested if name not in VOICES]
    if unknown:
        raise ValueError(f"Unknown voice names: {', '.join(unknown)}")
    VOICES = {name: VOICES[name] for name in requested}
PREFIX = "다음 단어는 "
WORD_LEFT = os.environ.get("TYPECAST_WORD_LEFT", "")
WORD_RIGHT = os.environ.get("TYPECAST_WORD_RIGHT", "")


def main() -> None:
    api_key = os.environ["TYPECAST_API_KEY"].strip()
    if not api_key:
        raise RuntimeError("TYPECAST_API_KEY is empty")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for timestamp-aligned clips")

    output_name = os.environ.get(
        "TYPECAST_OUTPUT_DIR", "typecast-sdk-quality-test-context-cut"
    )
    root = Path(__file__).with_name(output_name)
    full_dir = root / "full"
    clip_dir = root / "word-only"
    full_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)

    client = Typecast(api_key=api_key)
    outputs: list[dict[str, object]] = []

    for voice_name, voice_id in VOICES.items():
        for index, word in enumerate(WORDS, start=1):
            text = f"{PREFIX}{WORD_LEFT}{word}{WORD_RIGHT}."
            response = client.text_to_speech_with_timestamps(
                TTSRequestWithTimestamps(
                    text=text,
                    model=TTSModel.SSFM_V30,
                    voice_id=voice_id,
                    language="kor",
                    prompt=PresetPrompt(
                        emotion_preset="normal",
                        emotion_intensity=0.0,
                    ),
                    output=Output(audio_format="mp3"),
                ),
                granularity="word",
            )
            if not response.words:
                raise RuntimeError(f"No word timestamps returned for {voice_name}/{word}")

            target_word_count = len(word.split())
            target_words = response.words[-target_word_count:]
            final_word = target_words[-1]
            # No pre-roll: the carrier phrase can otherwise bleed into the clip.
            start = target_words[0].start
            end = min(response.audio_duration, final_word.end + 0.14)
            duration = end - start
            full_path = full_dir / f"{index:02d}_{voice_name}.mp3"
            clip_path = clip_dir / f"{index:02d}_{voice_name}.mp3"
            response.save_audio(str(full_path))
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(full_path),
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{duration:.3f}",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "3",
                    str(clip_path),
                ],
                check=True,
                capture_output=True,
            )
            outputs.append(
                {
                    "voice": voice_name,
                    "word": word,
                    "input": text,
                    "segments": [segment.model_dump() for segment in target_words],
                    "crop_start_seconds": round(start, 3),
                    "crop_end_seconds": round(end, 3),
                }
            )

    (root / "manifest.json").write_text(
        json.dumps(
            {
                "model": "ssfm-v30",
                "prompt": {"emotion": "normal", "emotion_intensity": 0.0},
                "prefix": PREFIX,
                "word_left": WORD_LEFT,
                "word_right": WORD_RIGHT,
                "words": WORDS,
                "voices": VOICES,
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
