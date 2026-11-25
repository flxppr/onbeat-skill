"""Beat map for a song: steady beat grid, bars, kicks, snares, energy and drops.

    python beats.py song.mp3 [--start 10.4] [--end 34] [--out beats.json]
                             [--plot beats.png] [--click click.wav]
                             [--bpm 124] [--bpm-min 70 --bpm-max 180]
                             [--beats-per-bar 4] [--downbeat 0]

All times in the output are seconds from --start (0 = first frame of the edit).
Only numpy + ffmpeg are needed. The beat grid is fitted as one steady tempo and then
nudged by a smoothed local offset, so it does not jitter or drift on long songs.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_audio, write_wav  # noqa: E402

SR = 22050
NFFT = 1024
HOP = 256
FR = SR / HOP  # envelope frames per second
# spectral flux peaks before the true attack (the window sees it early); measured on
# a synthetic track with exact beat times and compensated here
LAG = 0.008


# ------------------------------------------------------------------ features
def spectrogram(y):
    pad = NFFT // 2
    y = np.pad(y, (pad, pad))
    win = np.hanning(NFFT).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(y, NFFT)[::HOP]
    out = np.empty((len(frames), NFFT // 2 + 1), np.float32)
    for i in range(0, len(frames), 2048):
        out[i:i + 2048] = np.abs(np.fft.rfft(frames[i:i + 2048] * win, axis=1))
    return out


def band_flux(L, freqs, lo, hi):
    sel = (freqs >= lo) & (freqs < hi)
    d = np.diff(L[:, sel], axis=0, prepend=L[:1, sel])
    return np.maximum(d, 0).sum(1)


def detrend(x, secs=0.4):
    k = max(3, int(secs * FR))
    m = np.convolve(x, np.ones(k) / k, mode='same')
    x = np.maximum(x - m, 0)
    return x / (x.max() + 1e-9)


def peaks(x, thresh_k=2.5, min_gap=0.09, floor=0.08):
    """Local maxima above an adaptive (median + k*MAD over ~2 s) threshold."""
    k = int(2.0 * FR)
    n = len(x)
    out = []
    last = -1e9
    w = max(1, int(0.05 * FR))
    for i in range(1, n - 1):
        v = x[i]
        if v < floor or v < x[i - 1] or v < x[i + 1]:
            continue
        a, b = max(0, i - w), min(n, i + w + 1)
        if v < x[a:b].max():
            continue
        seg = x[max(0, i - k):min(n, i + k)]
        med = np.median(seg)
        mad = np.median(np.abs(seg - med)) + 1e-6
        if v < med + thresh_k * mad:
            continue
        t = i / FR
        if t - last < min_gap:
            continue
        out.append(t)
        last = t
    return out


# ------------------------------------------------------------------ tempo + grid
def tempo_scan(env, total, bpm_min, bpm_max, full=None):
    """Score every tempo two ways and average them:
    - envelope: how much onset energy the best-phase steady grid lands on. Good at telling
      octaves apart (161 vs 80.5), but a loud, clipped master smears the envelope.
    - peaks: what share of the clear, sharp hits sit on the grid's half-beats (above chance).
      Robust to clipping and dense rolls, but cannot tell octaves apart on its own.
    Both are weighted by a prior centred on 120 BPM. Returns candidates, best first."""
    t_env = np.arange(len(env)) / FR
    bpms = np.arange(bpm_min, bpm_max + 0.01, 0.5)
    prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    e_sc = np.zeros(len(bpms))
    for i, bpm in enumerate(bpms):
        p = 60.0 / bpm
        k = np.arange(int(total / p) + 1) * p
        g = np.arange(0, p, 0.006)[:, None] + k[None, :]
        e_sc[i] = np.interp(g, t_env, env, right=0).mean(1).max()
    score = e_sc * prior
    score = score / (score.max() + 1e-12)
    if full is not None:
        pk = np.array(peaks(full, 2.0, 0.06, 0.08))
        if len(pk) >= 8:
            w = full[(pk * FR).astype(int).clip(0, len(full) - 1)]
            sigma = 0.02
            p_sc = np.zeros(len(bpms))
            for i, bpm in enumerate(bpms):
                g = 30.0 / bpm  # half a beat
                ph = np.arange(0, g, 0.004)[:, None]
                d = ((pk[None, :] - ph + g / 2) % g) - g / 2
                hit = (w[None, :] * np.exp(-0.5 * (d / sigma) ** 2)).sum(1).max() / w.sum()
                p_sc[i] = max(0.0, hit - sigma * np.sqrt(2 * np.pi) / g)  # minus chance
            p_sc = p_sc * prior
            if p_sc.max() > 0:
                score = 0.5 * score + 0.5 * p_sc / p_sc.max()
    # octave tie-break: if the runner-up is double/half the winner and nearly tied, let the
    # envelope score (the one that is good at octaves) decide between the two
    env_only = e_sc * prior
    order = list(np.argsort(-score))
    top = order[0]
    for j in order[1:12]:
        r = bpms[j] / bpms[top]
        if (abs(r - 2) < 0.04 or abs(r - 0.5) < 0.01) and score[j] >= 0.95 * score[top]:
            if env_only[j] > env_only[top]:
                score[j] = score[top] + 1e-6
            break
    order = np.argsort(-score)
    picked = []
    for i in order:
        bpm = float(bpms[i])
        if all(abs(bpm - q) > 3 for _, q in picked):
            picked.append((float(score[i]), bpm))
        if len(picked) == 4:
            break
    return picked


def fit_grid(env, period, dur, search=0.02):
    """Brute-force the steady grid (period, phase) that lands on the most onset energy."""
    t_env = np.arange(len(env)) / FR
    best = (-1.0, period, 0.0)
    for p in np.linspace(period * (1 - search), period * (1 + search), 161):
        nb = int(dur / p) + 2
        k = np.arange(nb) * p
        phases = np.arange(0, p, 0.004)
        g = phases[:, None] + k[None, :]
        sc = np.interp(g, t_env, env, right=0).sum(1)
        i = int(np.argmax(sc))
        if sc[i] > best[0]:
            best = (float(sc[i]), float(p), float(phases[i]))
    return best[1], best[2]


def local_correct(grid, env, win=0.07, sigma=0.03):
    """Smoothed per-beat offset toward nearby onset peaks (handles slow tempo drift)."""
    t_env = np.arange(len(env)) / FR
    offs = np.full(len(grid), np.nan)
    for i, g in enumerate(grid):
        m = (t_env > g - win) & (t_env < g + win)
        if m.sum() < 3:
            continue
        w = env[m] * np.exp(-0.5 * ((t_env[m] - g) / sigma) ** 2)
        j = int(np.argmax(w))
        if env[m][j] > 0.15:
            offs[i] = t_env[m][j] - g
    if np.isfinite(offs).sum() < 4:
        return grid
    sm = np.empty_like(offs)
    for i in range(len(offs)):
        seg = offs[max(0, i - 6):i + 7]
        seg = seg[np.isfinite(seg)]
        sm[i] = np.median(seg) if len(seg) else np.nan
    idx = np.arange(len(sm))
    ok = np.isfinite(sm)
    sm = np.interp(idx, idx[ok], sm[ok])
    return grid + sm


def at(env, ts, w=0.03):
    t_env = np.arange(len(env)) / FR
    out = []
    for t in ts:
        m = (t_env > t - w) & (t_env < t + w)
        out.append(float(env[m].max()) if m.any() else 0.0)
    return np.array(out)


def pick_downbeat(beats, low, mid_high, L, bpb):
    """Index (0..bpb-1) of the first downbeat. Kicks on 1 and 3, snares on 2 and 4,
    and the sound changing at bar starts all vote."""
    K = at(low, beats)
    S = at(mid_high, beats)
    # spectral change across each beat
    N = np.zeros(len(beats))
    fi = (np.array(beats) * FR).astype(int).clip(0, len(L) - 1)
    for i in range(1, len(beats) - 1):
        a = L[fi[i - 1]:fi[i]].mean(0) if fi[i] > fi[i - 1] else L[fi[i]]
        b = L[fi[i]:fi[i + 1]].mean(0) if fi[i + 1] > fi[i] else L[fi[i]]
        N[i] = np.abs(b - a).mean()
    N /= N.max() + 1e-9
    idx = np.arange(len(beats))
    scores = []
    for ph in range(bpb):
        on = (idx - ph) % bpb == 0
        if bpb == 4:
            half = (idx - ph) % 2 == 0
            s = K[half].mean() - K[~half].mean() + S[~half].mean() - S[half].mean()
            s += 0.6 * (N[on].mean() - N[~on].mean()) + 0.4 * (K[on].mean() - K[~on].mean())
        else:
            s = K[on].mean() - K[~on].mean() + N[on].mean() - N[~on].mean()
        scores.append(float(s))
    return int(np.argmax(scores)), scores


# ------------------------------------------------------------------ main analysis
def analyze(path, start=0.0, end=None, bpm=None, bpm_min=70, bpm_max=180, bpb=4, downbeat=None):
    pre = min(start, 1.0)  # analyse a little before the edit so beat 0 is not lost
    dur_req = (end - start) if end else None
    y, _ = load_audio(path, SR, start - pre, (dur_req + pre + 1.0) if dur_req else None)
    if len(y) < SR:
        raise SystemExit('audio is shorter than a second')
    S = spectrogram(y)
    L = np.log1p(100 * S)
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    full = detrend(band_flux(L, freqs, 30, 11000))
    low = detrend(band_flux(L, freqs, 30, 150))
    mid = detrend(band_flux(L, freqs, 150, 2500))
    high = detrend(band_flux(L, freqs, 2500, 11000))
    env = 0.6 * full + 0.4 * low
    env /= env.max() + 1e-9
    total = len(y) / SR

    cands = tempo_scan(env, total, bpm_min, bpm_max, full)
    if bpm:
        period, phase = fit_grid(env, 60.0 / bpm, total, search=0.004)
    else:
        # refine the top candidates and keep the best-scoring one
        best = None
        for sc, c in cands[:3]:
            p, ph = fit_grid(env, 60.0 / c, total, search=0.006)
            if best is None or sc > best[0]:
                best = (sc, p, ph)
        _, period, phase = best
    grid = phase + period * np.arange(-2, int((total - phase) / period) + 2)
    grid = grid[(grid > -0.3) & (grid < total + 0.3)]
    beats = local_correct(grid, env) + LAG

    db, db_scores = (downbeat % bpb, None) if downbeat is not None else pick_downbeat(beats, low, 0.5 * mid + 0.5 * high, L, bpb)

    # kicks: sub-band (20-100 Hz) onsets that also carry real sub energy, so risers,
    # pads and off-beat bass notes are not mistaken for kicks
    sub = detrend(band_flux(L, freqs, 20, 100))
    subE = (S[:, (freqs >= 20) & (freqs < 100)] ** 2).sum(1)
    subE /= np.percentile(subE, 99) + 1e-12
    gate = int(0.06 * FR)
    kicks = [t for t in peaks(sub, 2.5, 0.1, 0.12) if subE[int(t * FR):int(t * FR) + gate].max() >= 0.1]
    # the sub-bass builds up after the attack, so move each kick to the sharp broadband
    # attack just before (or at) it
    snapped = []
    for t in kicks:
        a, b = int((t - 0.045) * FR), int((t + 0.012) * FR) + 1
        seg = full[max(0, a):max(0, b)]
        snapped.append((max(0, a) + int(np.argmax(seg))) / FR if len(seg) and seg.max() > 0.08 else t)
    kicks = np.array(snapped) + LAG
    snares = np.array(peaks(0.5 * mid + 0.5 * high, 3.0, 0.1, 0.15)) + LAG
    hits = np.array(peaks(full, 3.0, 0.08, 0.2)) + LAG

    # shift to edit time
    def shift(a):
        a = np.asarray(a, float) - pre
        lim = (dur_req if dur_req else total - pre) + 0.25
        return a[(a > -0.25) & (a < lim)]

    beats_e = np.asarray(beats) - pre
    keep = (beats_e > -0.25) & (beats_e < (dur_req if dur_req else total - pre) + 0.25)
    first_kept = int(np.argmax(keep)) if keep.any() else 0
    beats_e = beats_e[keep]
    # a forced --downbeat counts from the edit's first beat; a detected one from the pre-roll
    db = downbeat % bpb if downbeat is not None else (db - first_kept) % bpb
    downbeats = beats_e[db::bpb]

    # energy per bar (RMS dB) and bass energy, for sections and drops
    rms = np.sqrt(np.convolve(y.astype(np.float64) ** 2, np.ones(1024) / 1024, mode='same'))
    bass_env = S[:, freqs < 150].sum(1)
    bars = []
    edges = list(downbeats) + [downbeats[-1] + period * bpb] if len(downbeats) else []
    for i in range(len(edges) - 1):
        a, b = edges[i] + pre, edges[i + 1] + pre
        sa, sb = int(max(0, a) * SR), int(min(total, b) * SR)
        fa, fb = int(max(0, a) * FR), int(min(total, b) * FR)
        e = 20 * np.log10(rms[sa:sb].mean() + 1e-6) if sb > sa else -90.0
        bb = float(bass_env[fa:fb].mean()) if fb > fa else 0.0
        bars.append({'t': round(float(edges[i]), 4), 'db': round(float(e), 2), 'bass': bb})
    if bars:
        bmax = max(b['bass'] for b in bars) + 1e-9
        for b in bars:
            b['bass'] = round(b['bass'] / bmax, 3)
    drops = []
    for i in range(1, len(bars)):
        before = np.mean([b['db'] for b in bars[max(0, i - 2):i]])
        after = np.mean([b['db'] for b in bars[i:i + 2]])
        bb = np.mean([b['bass'] for b in bars[max(0, i - 2):i]])
        ba = np.mean([b['bass'] for b in bars[i:i + 2]])
        jump = (after - before) + 8 * (ba - bb)
        if jump > 3.5:
            drops.append({'t': bars[i]['t'], 'bar': i, 'jump': round(float(jump), 2)})
    drops.sort(key=lambda d: -d['jump'])
    drops = drops[:4]

    r4 = lambda a: [round(float(v), 4) for v in a]  # noqa: E731
    return {
        'source': os.path.abspath(path),
        'start': start,
        'duration': round(float(dur_req if dur_req else total - pre), 4),
        'bpm': round(60.0 / period, 3),
        'period': round(period, 6),
        'beats_per_bar': bpb,
        'beats': r4(beats_e),
        'first_downbeat_index': int(db),
        'downbeats': r4(downbeats),
        'kicks': r4(shift(kicks)),
        'snares': r4(shift(snares)),
        'hits': r4(shift(hits)),
        'bars': bars,
        'drops': drops,
        'downbeat_scores': db_scores,
        'tempo_candidates': [{'bpm': c, 'score': round(sc, 4)} for sc, c in cands],
    }


# ------------------------------------------------------------------ outputs
def plot(an, path, envs=None):
    from PIL import Image, ImageDraw
    row_s, pxs, rh = 10.0, 160, 150
    dur = an['duration']
    rows = int(np.ceil(dur / row_s))
    W, H = int(row_s * pxs) + 60, rows * rh + 40
    im = Image.new('RGB', (W, H), (18, 18, 20))
    d = ImageDraw.Draw(im)
    d.text((10, 10), f"{os.path.basename(an['source'])}  {an['bpm']} BPM  start={an['start']}s  "
                     f"(white=bar start, grey=beat, red=kick, cyan=snare, gold=drop)", fill=(220, 220, 220))

    def xy(t):
        r = int(t // row_s)
        return 40 + (t - r * row_s) * pxs, 40 + r * rh

    if envs is not None:
        env, fr = envs
        for r in range(rows):
            pts = []
            for i in range(int(r * row_s * fr), min(len(env), int((r + 1) * row_s * fr))):
                x, y0 = xy(i / fr)
                pts.append((x, y0 + rh - 20 - env[i] * (rh - 50)))
            if len(pts) > 1:
                d.line(pts, fill=(90, 110, 140), width=1)
    for i, t in enumerate(an['beats']):
        if t < 0:
            continue
        x, y0 = xy(t)
        d.line([(x, y0 + 20), (x, y0 + rh - 20)], fill=(80, 80, 80))
    for i, t in enumerate(an['downbeats']):
        if t < 0:
            continue
        x, y0 = xy(t)
        d.line([(x, y0 + 10), (x, y0 + rh - 14)], fill=(240, 240, 240), width=2)
        d.text((x + 3, y0 + 6), f'bar {i}  {t:.2f}s', fill=(240, 240, 240))
    for t in an['kicks']:
        if t >= 0:
            x, y0 = xy(t)
            d.ellipse([x - 4, y0 + rh - 22, x + 4, y0 + rh - 14], fill=(230, 60, 60))
    for t in an['snares']:
        if t >= 0:
            x, y0 = xy(t)
            d.ellipse([x - 3, y0 + rh - 34, x + 3, y0 + rh - 28], fill=(60, 200, 230))
    for dr in an['drops']:
        x, y0 = xy(dr['t'])
        d.rectangle([x - 2, y0 + 10, x + 2, y0 + rh - 14], fill=(247, 197, 66))
        d.text((x + 6, y0 + 22), f"DROP? +{dr['jump']}", fill=(247, 197, 66))
    im.save(path)


def click_track(an, out):
    """The song section with a click on every beat (high click on bar starts) to check by ear."""
    sr = 44100
    y, _ = load_audio(an['source'], sr, an['start'], an['duration'])
    y = y * 0.6
    n = int(0.03 * sr)
    tt = np.arange(n) / sr
    env = np.exp(-tt * 120)
    hi = np.sin(2 * np.pi * 1760 * tt) * env
    lo = np.sin(2 * np.pi * 990 * tt) * env
    downs = set(round(t, 4) for t in an['downbeats'])
    for t in an['beats']:
        i = int(t * sr)
        if i < 0 or i + n > len(y):
            continue
        y[i:i + n] += (0.55 * hi if round(t, 4) in downs else 0.4 * lo)
    write_wav(out, np.clip(y, -1, 1), sr)


def _octave(bpm, ref):
    r = bpm / ref
    if abs(r - 0.5) < 0.02:
        return ', half tempo: same bars, beats twice as long'
    if abs(r - 2) < 0.04:
        return ', double tempo: same bars, beats twice as fast'
    return ''


def summary(an):
    lines = [f"BPM {an['bpm']}  |  {len(an['beats'])} beats, {len(an['downbeats'])} bars, "
             f"{len(an['kicks'])} kicks, {len(an['snares'])} snares  |  {an['duration']:.2f}s"]
    lines.append('first downbeat = beat index %d' % an['first_downbeat_index'])
    alts = [c for c in an['tempo_candidates'] if abs(c['bpm'] - an['bpm']) > 3]
    if alts:
        lines.append('other tempos that also fit (use --bpm to force one): ' +
                     ', '.join(f"{c['bpm']:g} ({c['score'] / an['tempo_candidates'][0]['score']:.0%}{_octave(c['bpm'], an['bpm'])})"
                               for c in alts[:3]))
    if an['drops']:
        lines.append('drop candidates: ' + ', '.join(f"bar {d['bar']} @ {d['t']:.2f}s (+{d['jump']})" for d in an['drops']))
    lines.append('bars: ' + '  '.join(f"{i}:{b['t']:.2f}s/{b['db']:.0f}dB" for i, b in enumerate(an['bars'][:24])))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('song')
    ap.add_argument('--start', type=float, default=0.0)
    ap.add_argument('--end', type=float)
    ap.add_argument('--duration', type=float)
    ap.add_argument('--out', default='beats.json')
    ap.add_argument('--plot')
    ap.add_argument('--click')
    ap.add_argument('--bpm', type=float, help='force the tempo (the grid is still fitted)')
    ap.add_argument('--bpm-min', type=float, default=70)
    ap.add_argument('--bpm-max', type=float, default=180)
    ap.add_argument('--beats-per-bar', type=int, default=4)
    ap.add_argument('--downbeat', type=int, help='force which beat (0..bpb-1) is the first bar start')
    a = ap.parse_args()
    end = a.end if a.end else (a.start + a.duration if a.duration else None)
    an = analyze(a.song, a.start, end, a.bpm, a.bpm_min, a.bpm_max, a.beats_per_bar, a.downbeat)
    with open(a.out, 'w') as f:
        json.dump(an, f, indent=1)
    print(summary(an))
    print('wrote', a.out)
    if a.plot:
        plot(an, a.plot)
        print('wrote', a.plot)
    if a.click:
        click_track(an, a.click)
        print('wrote', a.click)


if __name__ == '__main__':
    main()
