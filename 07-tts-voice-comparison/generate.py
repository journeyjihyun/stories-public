"""Generate original speech, timestamps and initial clips from an explicit word list."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import soundfile as sf
from typecast import Typecast
from typecast.models import Output, PresetPrompt, TTSModel, TTSRequestWithTimestamps
import argparse
import numpy as np

BASE = Path(__file__).parent
OUT = None  # Assigned by the CLI
SETTINGS = dict(model='ssfm-v30', voice_id='tc_6731b2b2478a48710ecc9158',
                language='kor', emotion_preset='normal', emotion_intensity=0.0,
                audio_tempo=0.9, audio_pitch=0, audio_format='mp3')


def save(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(10):
        try:
            temp.replace(path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.2 * (attempt + 1))


def normalized(text):
    return re.sub(r"[\s'\".,…‘’]", '', text)


def generate_one(pair):
    index, item = pair
    stem = f'{index:04d}'
    full, meta, clip = (OUT / folder / f'{stem}.{ext}' for folder, ext in
                        [('full', 'mp3'), ('metadata', 'json'), ('clips', 'mp3')])
    text = f"다음 단어는. '{item['word']}'."
    if full.exists() and meta.exists():
        data = json.loads(meta.read_text(encoding='utf-8'))
        if data['input'] != text or data['settings'] != SETTINGS:
            raise ValueError('Cache settings mismatch')
    else:
        client = Typecast(api_key=os.environ['TYPECAST_API_KEY'].strip())
        for attempt in range(3):
            try:
                response = client.text_to_speech_with_timestamps(TTSRequestWithTimestamps(
                    text=text, model=TTSModel.SSFM_V30, voice_id=SETTINGS['voice_id'],
                    language='kor', prompt=PresetPrompt(emotion_preset='normal', emotion_intensity=0.0),
                    output=Output(audio_format='mp3', audio_tempo=0.9, audio_pitch=0)), granularity='word')
                response.save_audio(str(full))
                data = dict(**item, input=text, settings=SETTINGS, duration=response.audio_duration,
                            words=[w.model_dump() for w in response.words])
                save(meta, data)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
    # Match the complete target suffix, including every space-separated word.
    words = data['words']
    target_index = None
    for j in range(1, len(words)):
        if normalized(''.join(w['text'] for w in words[j:])) == normalized(item['word']):
            target_index = j
            break
    if target_index is None:
        raise ValueError('Target timestamp text mismatch; original retained for review')
    start = float(words[target_index]['start'])
    end = min(float(data['duration']), float(words[-1]['end']) + 0.14)
    snap, detail = choose_start(full, start)
    if snap > start or snap < float(words[target_index - 1]['end']):
        snap = start
        detail['mode'] = 'timestamp_fallback_guard'
    if not 0 <= snap < end:
        raise ValueError('Invalid clip boundaries')
    if not clip.exists():
        temp = clip.with_name(stem + '-pending.mp3')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(full), '-ss', f'{snap:.6f}',
                        '-t', f'{end-snap:.6f}', '-c:a', 'libmp3lame', '-q:a', '3', str(temp)],
                       check=True, capture_output=True)
        temp.replace(clip)
    seconds = sf.info(clip).duration
    result = dict(**item, id=stem, clip=f'clips/{stem}.mp3', full=f'full/{stem}.mp3',
                  seconds=seconds, start=snap, end=end, timestamp=start, **detail)
    data['edit'] = result
    save(meta, data)
    return result


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


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def generate(args):
    spec=read(args.input)
    items=spec['items']
    assert items and all(isinstance(r.get('word'),str) and r['word'].strip() for r in items)
    assert len({r['word'] for r in items})==len(items), 'Duplicate display words'
    # Freeze source order before API use: numbered metadata must remain aligned.
    args.output.mkdir(parents=True,exist_ok=True)
    snapshot=args.output/'input.json'
    if snapshot.exists() and read(snapshot)!=spec:
        raise ValueError('Input changed; use a new output directory')
    save(snapshot,spec)
    global OUT
    OUT=args.output
    for name in ['full','metadata','clips']:
        (args.output/name).mkdir(exist_ok=True)
    results=[]
    for i,item in enumerate(items,1):
        spoken=item.get('spoken_text',item['word'])
        if not isinstance(spoken,str) or not spoken.strip():
            raise ValueError('Empty spoken_text')
        r=generate_one((i,dict(word=spoken)))
        r.update(word=item['word'],spoken_text=spoken)
        results.append(r)
        save(args.output/'manifest.json',dict(settings=SETTINGS,results=results,
                 expected=len(items),complete=len(results)==len(items)))
        print(f'{i}/{len(items)} {item["word"]}',flush=True)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate Typecast originals and timestamps (paid API).")
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    generate(parser.parse_args())
