"""Offline bidirectional trimming and pitch review flags; never calls the API."""
import argparse
import json
import hashlib
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

def write_review(output, results):
    """Self-contained local review UI; audio remains beside HTML in clips/."""
    rows = [{k: r[k] for k in ('id', 'word', 'clip', 'pitch_candidate')} for r in results]
    # Audio hashes isolate review notes even for newly generated versions of the same words.
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode())
    for row in rows:
        digest.update((output/row['clip']).read_bytes())
    payload = json.dumps(dict(batch=digest.hexdigest(), rows=rows), ensure_ascii=False).replace('<', '\\u003c')
    page = r'''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>단어 음원 검수</title>
<style>body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:0 18px;background:#f5f7fa;color:#183047}button,input,textarea{font:inherit}button{padding:8px 12px;cursor:pointer}header{position:sticky;top:0;background:#f5f7fa;padding:12px 0}article{display:grid;grid-template-columns:180px 90px 110px 1fr;gap:12px;align-items:center;padding:16px;background:white;border-bottom:1px solid #ddd}article.active{outline:2px solid #2974b8}textarea{width:95%;min-height:48px}small{display:block;color:#79510b}#status{min-height:24px}@media(max-width:650px){article{grid-template-columns:1fr 1fr}textarea{grid-column:1/-1}}</style>
<h1>단어 음원 검수</h1><p>연속 재생 중에도 이상 표시와 코멘트를 입력할 수 있습니다. 피치 표시는 자동 검수 후보이며 정상 여부를 보장하지 않습니다.</p>
<p>기록은 이 브라우저에 저장됩니다. 파일 이동·브라우저 변경 시 유지되지 않을 수 있으니 검수 결과를 내려받아 보관하세요.</p>
<header><button id="start">처음부터 연속 재생</button> <button id="stop">정지</button> <button id="export">검수 결과 내려받기</button><p id="status" role="status" aria-live="polite"></p><audio id="player" controls></audio></header>
<main id="list"></main>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent), rows=data.rows;
const key='tts-review-v1:'+data.batch, player=document.getElementById('player'), status=document.getElementById('status');
let notes={}, current=-1, continuous=false, token=0, storageWarning='';
try{const saved=JSON.parse(localStorage.getItem(key)||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))notes=saved;}
catch(e){storageWarning=' 자동 저장 불가: 검수 결과를 반드시 내려받으세요.';}
function message(text){status.textContent=text+storageWarning;}
function save(){try{localStorage.setItem(key,JSON.stringify(notes));}catch(e){storageWarning=' 자동 저장 불가: 검수 결과를 반드시 내려받으세요.';}message('검수 기록 '+Object.values(notes).filter(n=>n.issue).length+'개 이상 표시');}
const elements=[];
rows.forEach((r,i)=>{
  const article=document.createElement('article'), title=document.createElement('div');
  title.textContent=(i+1)+'. '+r.word;
  if(r.pitch_candidate){const hint=document.createElement('small');hint.textContent='피치 상승 후보';title.append(hint);}
  const play=document.createElement('button');play.textContent='재생';play.setAttribute('aria-label',r.word+' 재생');play.onclick=()=>playAt(i,false);
  const label=document.createElement('label'), flag=document.createElement('input');flag.type='checkbox';flag.checked=notes[r.id]?.issue===true;label.append(flag,' 이상');
  const comment=document.createElement('textarea');comment.placeholder='코멘트';comment.setAttribute('aria-label',r.word+' 코멘트');comment.value=typeof notes[r.id]?.comment==='string'?notes[r.id].comment:'';
  const update=()=>{notes[r.id]={issue:flag.checked,comment:comment.value};save();};flag.onchange=update;comment.oninput=update;
  article.append(title,play,label,comment);document.getElementById('list').append(article);elements.push(article);
});
function stop(){token++;continuous=false;player.pause();}
async function playAt(i,sequence){
  const request=++token;player.pause();continuous=sequence;current=i;
  elements.forEach((el,j)=>el.classList.toggle('active',j===i));
  player.src=rows[i].clip;message((i+1)+' / '+rows.length+' — '+rows[i].word);
  try{await player.play();}catch(e){if(request===token){continuous=false;message('재생 실패: '+rows[i].word+' — 파일 위치를 확인하고 재생 버튼을 눌러주세요.');}}
}
player.onended=()=>{if(continuous&&current+1<rows.length)playAt(current+1,true);else{continuous=false;message('재생 완료');}};
player.onerror=()=>{continuous=false;message('음원 로드 실패 — clips 폴더를 함께 유지해 주세요.');};
document.getElementById('start').onclick=()=>{if(rows.length)playAt(0,true);};
document.getElementById('stop').onclick=()=>{stop();message('정지');};
document.getElementById('export').onclick=()=>{
  const result={batch:data.batch,exported_at:new Date().toISOString(),items:rows.map(r=>({...r,issue:notes[r.id]?.issue===true,comment:notes[r.id]?.comment||''}))};
  const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='review-'+data.batch.slice(0,12)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
message(rows.length+'개 음원');
</script></html>'''
    (output/'index.html').write_text(page.replace('__PAYLOAD__', payload), encoding='utf-8')

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
    write_review(args.output, results)
    print(f'Cut and decoded {len(results)} clips; pitch candidates: {sum(r["pitch_candidate"] for r in results)}')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--overrides', type=Path)
    recut(parser.parse_args())
