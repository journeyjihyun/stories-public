"""Resumable local-only generation of the approved Korean-filename CDN list."""
import concurrent.futures
import json
import os
import re
import subprocess
import time
from pathlib import Path

import soundfile as sf
from typecast import Typecast
from typecast.models import Output, PresetPrompt, TTSModel, TTSRequestWithTimestamps
from recut_waveform_snap_test import choose_start

BASE = Path(__file__).parent
OUT = None  # Assigned by pipeline.py
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


def generate(pair):
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
