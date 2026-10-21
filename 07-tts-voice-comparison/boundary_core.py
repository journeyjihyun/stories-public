"""Experimental energy boundary search; human review remains required."""
import numpy as np

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
