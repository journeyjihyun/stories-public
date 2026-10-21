"""Offline bidirectional trimming and pitch review flags; never calls the API."""
import argparse
import json
import os
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
import parselmouth
from generate import save

def boundary(samples, sr, timestamp, previous_end, target_end, fallback):
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    hop = max(1, round(sr * .005))
    window = max(1, round(sr * .010))
    power = np.square(samples)
    sums = np.concatenate(([0.], np.cumsum(power)))
    offsets = np.arange(0, len(samples)-window+1, hop)
    db = 10*np.log10(np.maximum((sums[offsets+window]-sums[offsets])/window, 1e-12))
    times = offsets/sr
    threshold = float(np.clip(np.percentile(db,95)-32, -48, -38))
    lower = max(0, timestamp-.180, previous_end-.080)
    upper = min(timestamp+.220, target_end-.120)
    runs=[]
    begin=None
    for i, quiet in enumerate(np.r_[db < threshold, False]):
        if quiet and begin is None:
            begin=i
        if not quiet and begin is not None:
            a,b=times[begin],min(len(samples)/sr,i*hop/sr)
            if b-a>=.020 and lower<=a<=upper and b<=upper+.100:
                before=db[(times>=a-.060)&(times<a)]
                after=db[(times>=b)&(times<b+.100)]
                # Reject silence without surrounding speech and weak contrast.
                if len(before) and len(after) and np.max(before)>threshold+8 and np.max(after)>threshold+8:
                    runs.append((float(a),float(b)))
            begin=None
    detail=dict(threshold_db=round(threshold,1), search_start=lower, search_end=upper,
                candidates=runs, needs_review=True)
    if len(runs)!=1:
        return fallback, dict(**detail,mode='ambiguous_keep' if runs else 'no_boundary_keep')
    a,b=runs[0]
    start=a+.005  # Leave most of the closure/quiet interval before the onset.
    if not lower<=start<=upper or target_end-start<.120:
        return fallback, dict(**detail,mode='guard_keep')
    return start, dict(**detail,mode='forward' if start>timestamp else 'backward')


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




def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def recut(args):
    manifest=read(args.input/'manifest.json')
    if not manifest.get('complete'):
        raise ValueError('Generation is incomplete')
    overrides=read(args.overrides) if args.overrides else {}
    known={r['word'] for r in manifest['results']}
    if set(overrides)-known:
        raise ValueError('Unknown override words')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'clips').mkdir()
    results=[]
    for r in manifest['results']:
        meta=read(args.input/'metadata'/f'{r["id"]}.json')
        full=args.input/r['full']
        samples,sr=sf.read(full)
        j=next(j for j,w in enumerate(meta['words']) if abs(w['start']-r['timestamp'])<.001)
        start,detail=boundary(samples,sr,r['timestamp'],meta['words'][j-1]['end'],
                              meta['words'][-1]['end'],r['start'])
        if r['word'] in overrides:
            start=float(overrides[r['word']]['start_seconds'])
            detail=dict(mode='manual_override',reason=overrides[r['word']].get('reason',''),needs_review=True)
        end=r['end']
        if not np.isfinite(start) or not 0<=start<end<=len(samples)/sr+.1:
            raise ValueError('Invalid cut bounds')
        dst=args.output/'clips'/f'{r["id"]}.mp3'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(full),'-ss',f'{start:.6f}',
                        '-t',f'{end-start:.6f}','-c:a','libmp3lame','-q:a','3',str(dst)],check=True)
        audio,rate=sf.read(dst)
        assert len(audio)>0 and np.isfinite(audio).all()
        metrics=measure(parselmouth.Sound(audio.mean(axis=1) if audio.ndim>1 else audio,sampling_frequency=rate))
        results.append(dict(r,clip=f'clips/{r["id"]}.mp3',start=start,boundary=detail,
             full=Path(os.path.relpath(full,args.output)).as_posix(),
             previous=Path(os.path.relpath(args.input/r['clip'],args.output)).as_posix(),
             seconds=len(audio)/rate,pitch=metrics,pitch_candidate=is_rising_issue(metrics)))
    save(args.output/'manifest.json',dict(settings=manifest['settings'],results=results,
             complete=True,total_seconds=sum(r['seconds'] for r in results)))
    print(f'Cut and decoded {len(results)} clips; pitch candidates: {sum(r["pitch_candidate"] for r in results)}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--overrides', type=Path)
    recut(parser.parse_args())
