"""Break down a reference edit so its style can be copied instead of guessed.

    python analyze_ref.py reference.mp4 [--out ref_analysis] [--threshold 0.3]

Writes to the out folder:
  report.md      the numbers: aspect, fps, BPM, how cuts line up with the beat, shot lengths
                 in beats, flashes, whether the picture moves on the kicks, colour palette
  report.json    the same, machine-readable (cut times, flash times, beat map)
  shots.png      one frame from the middle of every shot, labelled with its length in beats
  timeline.png   evenly spaced frames across the whole video
  detail.png     frame-by-frame strips of the first moments of a few shots (how things animate in)
  beats.json     beat map of the reference's own audio
Look at the three images, read report.md, then write the style guide (see styles/TEMPLATE.md).
"""
import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import ffmpeg_exe, probe  # noqa: E402


def detect_cuts(path, threshold):
    cmd = [ffmpeg_exe(), '-hide_banner', '-i', path, '-an', '-vf',
           f"scale=320:-2,select='gt(scene,{threshold})',showinfo", '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True)
    s = r.stderr.decode(errors='replace')
    return sorted(set(round(float(m), 4) for m in re.findall(r'pts_time:([\d.]+)', s)))


def luma_track(path, fps=30):
    """Mean brightness and frame-to-frame change at low resolution, one value per frame."""
    w, h = 64, 64
    cmd = [ffmpeg_exe(), '-v', 'error', '-i', path, '-an', '-vf', f'fps={fps},scale={w}:{h}',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    fr = np.frombuffer(raw[:n * w * h * 3], np.uint8).reshape(n, h, w, 3).astype(np.float32)
    luma = fr.mean((1, 2, 3))
    diff = np.zeros(n)
    if n > 1:
        diff[1:] = np.abs(np.diff(fr, axis=0)).mean((1, 2, 3))
    return fr, luma, diff


def grab(path, t, width):
    cmd = [ffmpeg_exe(), '-v', 'error', '-ss', f'{max(0, t):.3f}', '-i', path, '-frames:v', '1',
           '-vf', f'scale={width}:-2', '-f', 'image2pipe', '-vcodec', 'png', '-']
    r = subprocess.run(cmd, capture_output=True)
    try:
        from io import BytesIO
        return Image.open(BytesIO(r.stdout)).convert('RGB')
    except Exception:
        return None


def sheet(items, out, cols, title):
    """items: list of (PIL image or None, label)."""
    items = [(im, l) for im, l in items if im is not None]
    if not items:
        return
    tw, th = items[0][0].size
    lab, pad, top = 22, 6, 30
    rows = (len(items) + cols - 1) // cols
    S = Image.new('RGB', (cols * (tw + pad) + pad, top + rows * (th + lab + pad) + pad), (22, 22, 24))
    d = ImageDraw.Draw(S)
    d.text((8, 8), title, fill=(235, 235, 235))
    for i, (im, l) in enumerate(items):
        r, c = divmod(i, cols)
        x, y = pad + c * (tw + pad), top + pad + r * (th + lab + pad)
        S.paste(im.resize((tw, th)), (x, y))
        d.text((x + 2, y + th + 4), l, fill=(210, 210, 210))
    S.save(out)


def palette(frames, k=6):
    sub = frames[:: max(1, len(frames) // 40)]
    if not len(sub):
        return []
    mosaic = Image.fromarray(np.concatenate(list(sub.astype(np.uint8)), axis=1))
    q = mosaic.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:k * 3]
    counts = sorted(q.getcolors(), reverse=True)
    out = []
    total = sum(c for c, _ in counts)
    for c, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        out.append({'hex': f'#{r:02X}{g:02X}{b:02X}', 'share': round(c / total, 3)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video')
    ap.add_argument('--out')
    ap.add_argument('--threshold', type=float, default=0.3, help='scene-change sensitivity (lower = more cuts)')
    ap.add_argument('--thumb', type=int, default=240)
    a = ap.parse_args()
    path = a.video
    out = a.out or os.path.splitext(os.path.basename(path))[0] + '_analysis'
    os.makedirs(out, exist_ok=True)
    info = probe(path)
    dur = info['duration'] or 0
    W, H = info['width'] or 1080, info['height'] or 1920
    print(f'{os.path.basename(path)}: {W}x{H}, {info["fps"]} fps, {dur:.2f}s, audio={info["has_audio"]}')

    # --- beats of the reference's own audio
    an = None
    if info['has_audio']:
        import beats as B
        an = B.analyze(path)
        with open(os.path.join(out, 'beats.json'), 'w') as f:
            json.dump(an, f, indent=1)
        print(B.summary(an).splitlines()[0])

    # --- cuts, flashes, motion
    raw_cuts = [c for c in detect_cuts(path, a.threshold) if 0.05 < c < dur - 0.05]
    vfps = info['fps'] or 30
    # cuts at most 2 frames apart are one cut plus flicker (strobe frames, a flash frame,
    # a double detection), not separate shots
    cuts, flicker, last = [], 0, -1e9
    for c in raw_cuts:
        if c - last <= 2.5 / vfps:
            flicker += 1
        else:
            cuts.append(c)
        last = c
    fps_t = 30
    frames, luma, diff = luma_track(path, fps_t)
    tl = np.arange(len(luma)) / fps_t
    flashes = []
    for i in range(2, len(luma) - 1):
        base = np.median(luma[max(0, i - 15):i])
        if luma[i] - base > 45 and luma[i] >= luma[i - 1] and luma[i] >= luma[i + 1]:
            if not flashes or tl[i] - flashes[-1] > 0.2:
                flashes.append(round(float(tl[i]), 3))
    shots = [0.0] + cuts + [dur]
    lengths = np.diff(shots)

    rep = {'file': os.path.abspath(path), 'width': W, 'height': H, 'aspect': f'{W}:{H}' if W and H else None,
           'fps': info['fps'], 'duration': round(dur, 3), 'cuts': cuts, 'n_shots': len(shots) - 1,
           'flicker_frames': flicker,
           'shot_seconds': {'median': round(float(np.median(lengths)), 3), 'min': round(float(lengths.min()), 3),
                            'max': round(float(lengths.max()), 3)},
           'flashes': flashes, 'brightness_mean': round(float(luma.mean()), 1),
           'palette': palette(frames)}

    def rel(ev, t):
        ev = np.asarray(ev)
        if not len(ev):
            return None
        i = int(np.argmin(np.abs(ev - t)))
        return float(t - ev[i])

    if an:
        beats_ = an['beats']
        period = an['period']
        # timing habit: do the cuts sit at the same small offset from the beat every time?
        # Many editors cut 1-2 frames early on purpose; re-encoded uploads can also shift audio.
        offs = np.array([rel(beats_, c) for c in cuts]) if cuts else np.array([])
        near = offs[np.abs(offs) < 0.35 * period]
        shift, rep['cut_timing'] = 0.0, None
        if len(near) >= max(4, 0.5 * len(cuts)):
            med = float(np.median(near))
            mad = float(np.median(np.abs(near - med)))
            if abs(med) >= 0.02 and mad <= 0.03:
                rep['cut_timing'] = {'offset_ms': round(med * 1000), 'frames': round(med * vfps, 1),
                                     'spread_ms': round(mad * 1000), 'cuts': int(len(near))}
                if abs(med) <= 0.1:
                    shift = med
        tol = max(0.06, 1.5 / vfps)
        on_beat = [abs(rel(beats_, c - shift)) < tol for c in cuts]
        on_down = [abs(rel(an['downbeats'], c - shift)) < tol for c in cuts]
        on_half = [abs(rel(np.array(beats_) + period / 2, c - shift)) < tol for c in cuts]
        rep['cuts_on_beat_raw'] = round(float(np.mean([abs(o) < tol for o in offs])), 3) if cuts else None
        rep['bpm'] = an['bpm']
        rep['cuts_on_beat'] = round(float(np.mean(on_beat)), 3) if cuts else None
        rep['cuts_on_downbeat'] = round(float(np.mean(on_down)), 3) if cuts else None
        rep['cuts_on_offbeat'] = round(float(np.mean(on_half)), 3) if cuts else None
        lb = lengths / period
        q = np.round(lb * 2) / 2
        rep['shot_beats'] = {'median': round(float(np.median(lb)), 2),
                             'histogram': {('<0.25' if k == 0 else str(k)): int(v) for k, v in zip(*np.unique(q, return_counts=True))}}
        rep['cut_offsets_ms'] = [round(rel(beats_, c) * 1000) for c in cuts]
        # does the picture jolt on the kicks? (zoom punches, shakes, flashes)
        kicks = np.array(an['kicks'])
        if len(kicks) > 3 and len(diff) > 10:
            cutset = np.array(raw_cuts) if raw_cuts else np.array([-9])
            dk = [diff[int(k * fps_t):int(k * fps_t) + 3].max() for k in kicks
                  if int(k * fps_t) + 3 < len(diff) and np.min(np.abs(cutset - k)) > 0.1]
            rnd = np.random.default_rng(0).uniform(0, dur - 0.2, 200)
            dr = [diff[int(r * fps_t):int(r * fps_t) + 3].max() for r in rnd
                  if np.min(np.abs(cutset - r)) > 0.1 and int(r * fps_t) + 3 < len(diff)]
            if dk and dr:
                rep['motion_on_kicks_ratio'] = round(float(np.median(dk) / (np.median(dr) + 1e-6)), 2)
        rep['flashes_on_beat'] = round(float(np.mean([abs(rel(beats_, f)) < 0.07 for f in flashes])), 2) if flashes else None
        rep['drops'] = an['drops']

    with open(os.path.join(out, 'report.json'), 'w') as f:
        json.dump(rep, f, indent=1)

    # --- sheets
    tw = a.thumb
    lab = lambda t: (f'{t:.2f}s' + (f' b{(t - an["beats"][0]) / an["period"]:.1f}' if an else ''))  # noqa: E731
    items = []
    for i in range(len(shots) - 1):
        if i >= 60:
            break
        mid = (shots[i] + shots[i + 1]) / 2
        L = lengths[i] / an['period'] if an else None
        items.append((grab(path, mid, tw), f'#{i} {shots[i]:.2f}s' + (f' {L:.1f}b' if L is not None else f' {lengths[i]:.2f}s')))
    sheet(items, os.path.join(out, 'shots.png'), 8 if H > W else 6,
          f'shots: one frame per shot (start time, length in beats)  - {len(shots) - 1} shots')
    n = 32
    items = [(grab(path, t, tw), lab(t)) for t in np.linspace(0.05, dur - 0.1, n)]
    sheet(items, os.path.join(out, 'timeline.png'), 8, f'timeline: {n} evenly spaced frames over {dur:.1f}s')
    det = []
    picks = [0.0] + [cuts[i] for i in np.linspace(0, len(cuts) - 1, min(4, len(cuts))).astype(int)] if cuts else [0.0]
    for c in picks[:5]:
        for j in range(8):
            t = c + j / 30 * 1.5
            det.append((grab(path, t, int(tw * 0.75)), f'{t:.2f}s +{j * 50}ms'))
    sheet(det, os.path.join(out, 'detail.png'), 8, 'detail: the first ~0.35s of a few shots, 50ms apart (entrances, flashes, blur)')

    # --- report.md
    L = [f'# Reference analysis: {os.path.basename(path)}', '',
         f'- **Format:** {W}x{H} ({"vertical" if H > W else "horizontal" if W > H else "square"}), {info["fps"]} fps, {dur:.2f}s',
         f'- **Brightness:** mean {rep["brightness_mean"]}/255 ({"dark" if rep["brightness_mean"] < 70 else "bright" if rep["brightness_mean"] > 150 else "mid"})',
         '- **Palette:** ' + ', '.join(f'{p["hex"]} ({p["share"]:.0%})' for p in rep['palette']),
         f'- **Shots:** {rep["n_shots"]} (median {rep["shot_seconds"]["median"]}s, shortest {rep["shot_seconds"]["min"]}s, longest {rep["shot_seconds"]["max"]}s)'
         + (f'; plus {flicker} flicker frame{"s" if flicker > 1 else ""} (strobe / single-frame flashes right after a cut)' if flicker else '')]
    if an:
        alts = [c for c in an.get('tempo_candidates', [])[1:] if c['score'] >= 0.85
                and min(abs(c['bpm'] / an['bpm'] - r) for r in (0.5, 1, 2)) > 0.03]
        L += [f'- **Music:** {an["bpm"]} BPM' + (f', drop around {an["drops"][0]["t"]:.2f}s' if an['drops'] else '')
              + (f'. Tempo uncertain: {", ".join(str(c["bpm"]) for c in alts)} also fit{"s" if len(alts) == 1 else ""}, so the '
                 'cut-on-beat numbers below may be wrong. Run beats.py with --click and check by ear.' if alts else ''),
              f'- **Cuts on the beat:** {rep["cuts_on_beat"]:.0%} (on bar starts {rep["cuts_on_downbeat"]:.0%}, on off-beats {rep["cuts_on_offbeat"]:.0%})'
              + (f' after allowing for the early cut below (exactly on the beat: {rep["cuts_on_beat_raw"]:.0%})' if shift else '') if cuts else '- **Cuts:** none detected (one continuous shot, or kinetic text on one background; try --threshold 0.15)',
              f'- **Shot length in beats:** median {rep["shot_beats"]["median"]}; counts {rep["shot_beats"]["histogram"]}' if cuts else '']
        ct = rep.get('cut_timing')
        if ct and shift:
            ms = ct['offset_ms']
            L.append(f'- **Cut timing:** {ct["cuts"]} cuts land {abs(ms)} ms ({abs(ct["frames"])} frames) '
                     + ('before' if ms < 0 else 'after') + f' the beat, give or take {ct["spread_ms"]} ms: a deliberate habit, not sloppiness. '
                     + (f'Copy it with `Edit(..., lead={-ms / 1000:.3f})`.' if ms < 0 else 'Copying it is optional; usually leave lead=0.'))
        elif ct:
            L.append(f'- **Cut timing:** {ct["cuts"]} cuts sit a steady {ct["offset_ms"]} ms from the detected beats. That is too far '
                     'to be an editing habit: the beat grid may be off (check click.wav from beats.py) or the cuts follow '
                     'something else (vocals, a different instrument).')
        if 'motion_on_kicks_ratio' in rep:
            r = rep['motion_on_kicks_ratio']
            L.append(f'- **Picture jolts on kicks:** {r}x normal motion ' + ('(yes: zoom punches / shake on kicks)' if r > 1.6 else '(not noticeably)'))
    L.append(f'- **Flashes:** {len(flashes)}' + (f' ({rep.get("flashes_on_beat", 0):.0%} on the beat) at ' + ', '.join(f'{f:.2f}' for f in flashes[:20]) if flashes else ''))
    L += ['', 'Now look at shots.png, timeline.png and detail.png and describe: format (footage / text / mixed),',
          'fonts (condensed? serif? weight, case), text size and position, colours, how text and shots enter,',
          'transitions, camera motion, overlays (grain, glitch, vignette, letterbox), and the arc of the edit.']
    with open(os.path.join(out, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(x for x in L if x is not None) + '\n')
    print('\n'.join(L[2:-3]))
    print('wrote', out)


if __name__ == '__main__':
    main()
