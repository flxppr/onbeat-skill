"""Self-test: synthesize the demo track (exact beat times known) and check the beat map.

    python tests/test_beats.py
"""
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import beats  # noqa: E402
import common  # noqa: E402
import demo_song  # noqa: E402


def main():
    bpm = 124.0
    period = 60 / bpm
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'song.wav')
        common.write_wav(p, demo_song.build(bpm), demo_song.SR)
        an = beats.analyze(p)
        # a window that starts mid-song with a forced downbeat: bar 0 must be the window's first
        # beat (it used to be counted from the 1 s pre-roll, putting bar 0 two beats late)
        bar = 4 * period
        win = beats.analyze(p, start=5 * bar, end=13 * bar, downbeat=0)
    ok = True

    def check(name, cond, detail):
        nonlocal ok
        print(('PASS ' if cond else 'FAIL ') + name + ': ' + detail)
        ok &= bool(cond)

    check('tempo', abs(an['bpm'] - bpm) < 0.3, f"{an['bpm']} BPM (expected {bpm})")
    b = np.array(an['beats'])
    err = (b - np.round(b / period) * period) * 1000
    check('beat timing', np.abs(err).max() < 20, f'max error {np.abs(err).max():.1f} ms, mean {err.mean():+.1f} ms')
    d0 = an['downbeats'][0]
    check('downbeat', abs(d0 - round(d0 / (4 * period)) * 4 * period) < 0.02, f'first bar starts at {d0:.3f}s')
    drop = an['drops'][0]['t'] if an['drops'] else None
    check('drop', drop is not None and abs(drop - 8 * 4 * period) < 0.05, f'drop at {drop} (expected {8 * 4 * period:.3f})')
    k = np.array(an['kicks'])
    on = np.abs(k - np.round(k / period) * period) < 0.03
    in_drop = k[(k > 8 * 4 * period - 0.05) & (k < 16 * 4 * period - 0.05)]
    check('kicks', len(in_drop) >= 30 and on.mean() > 0.9, f'{len(in_drop)}/32 drop kicks found, {on.mean():.0%} of all kicks on a beat')
    wd = win['downbeats'][0]
    wdrop = win['drops'][0]['t'] if win['drops'] else None
    check('window + forced downbeat', abs(wd) < 0.02 and wdrop is not None and abs(wdrop - 3 * bar) < 0.05,
          f'bar 0 at {wd:.3f}s (expected 0), drop at {wdrop} (expected {3 * bar:.3f})')
    # loud, hard-clipped masters (TikTok rips) smear the onset envelope; a 150 BPM track
    # clipped this hard read as 75 or 100 BPM before peak scoring was added
    for cbpm, gain in ((150, 20), (100, 20), (130, 8)):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'clipped.wav')
            common.write_wav(p, np.clip(demo_song.build(cbpm) * gain, -1, 1), demo_song.SR)
            got = beats.analyze(p)['bpm']
        check(f'clipped {cbpm} BPM', abs(got - cbpm) < 0.5, f'{got} BPM at {gain}x gain, hard-clipped')
    print('all good' if ok else 'some checks failed')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
