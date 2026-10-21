"""Portable generation and offline recutting entry point. Never uploads to CDN."""
import argparse
import json
import os
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
import parselmouth
import generation_core as gen
from boundary_core import boundary
from analyze_tts_pitch import measure, is_rising_issue


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
    gen.save(snapshot,spec)
    gen.OUT=args.output
    for name in ['full','metadata','clips']:
        (args.output/name).mkdir(exist_ok=True)
    results=[]
    for i,item in enumerate(items,1):
        spoken=item.get('spoken_text',item['word'])
        if not isinstance(spoken,str) or not spoken.strip():
            raise ValueError('Empty spoken_text')
        r=gen.generate((i,dict(word=spoken)))
        r.update(word=item['word'],spoken_text=spoken)
        results.append(r)
        gen.save(args.output/'manifest.json',dict(settings=gen.SETTINGS,results=results,
                 expected=len(items),complete=len(results)==len(items)))
        print(f'{i}/{len(items)} {item["word"]}',flush=True)


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
    gen.save(args.output/'manifest.json',dict(settings=manifest['settings'],results=results,
             complete=True,total_seconds=sum(r['seconds'] for r in results)))
    print(f'Cut and decoded {len(results)} clips; pitch candidates: {sum(r["pitch_candidate"] for r in results)}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    g=commands.add_parser('generate')
    g.add_argument('--input',type=Path,required=True)
    g.add_argument('--output',type=Path,required=True)
    g.set_defaults(run=generate)
    r=commands.add_parser('recut')
    r.add_argument('--input',type=Path,required=True)
    r.add_argument('--output',type=Path,required=True)
    r.add_argument('--overrides',type=Path)
    r.set_defaults(run=recut)
    args=parser.parse_args()
    args.run(args)
