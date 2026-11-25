"""Synthesize an original, royalty-free demo track (124 BPM, A minor, 16 bars + tail).

    python demo_song.py out.wav [--bpm 124]

Structure: bars 0-3 intro (pad + offbeat hats), 4-7 build (claps, riser, snare roll),
bars 8-15 drop (four-on-the-floor kick, sidechained bass, pluck arp), then a final hit.
The beat times are exact, which makes this a ground-truth test for beats.py.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import write_wav  # noqa: E402

SR = 44100
rng = np.random.default_rng(7)


def note(n):  # MIDI -> Hz
    return 440.0 * 2 ** ((n - 69) / 12)


def kick():
    t = np.arange(int(0.42 * SR)) / SR
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.5)
    click = rng.normal(0, 1, len(t)) * np.exp(-t * 400) * 0.35
    return np.tanh(1.6 * (body + click)) * 0.95


def clap():
    t = np.arange(int(0.32 * SR)) / SR
    nz = rng.normal(0, 1, len(t))
    nz = nz - np.convolve(nz, np.ones(6) / 6, 'same')  # brighter
    env = np.zeros_like(t)
    for o in (0, 0.011, 0.022):
        env += np.where(t >= o, np.exp(-(t - o) * 60), 0)
    env += np.exp(-t * 14) * 0.5
    return nz * env * 0.45


def hat(open_=False):
    t = np.arange(int((0.22 if open_ else 0.06) * SR)) / SR
    nz = rng.normal(0, 1, len(t))
    nz = nz - np.convolve(nz, np.ones(3) / 3, 'same')
    return nz * np.exp(-t * (14 if open_ else 70)) * 0.22


def tone(freq, dur, harmonics=8, detune=(0.0,), decay=None, attack=0.005, bright=1.0):
    t = np.arange(int(dur * SR)) / SR
    y = np.zeros_like(t)
    for dt in detune:
        f0 = freq * (1 + dt)
        ph0 = rng.uniform(0, 2 * np.pi)
        for h in range(1, harmonics + 1):
            if f0 * h > 16000:
                break
            y += np.sin(2 * np.pi * f0 * h * t + ph0 * h) / h ** (1.0 / bright)
    y /= len(detune)
    env = np.minimum(1, t / attack)
    if decay:
        env *= np.exp(-t * decay)
    rel = int(0.02 * SR)
    env[-rel:] *= np.linspace(1, 0, rel)
    return y * env


def place(buf, x, t, gain=1.0):
    i = int(round(t * SR))
    if i >= len(buf):
        return
    n = min(len(x), len(buf) - i)
    buf[i:i + n] += x[:n] * gain


def build(bpm=124):
    beat = 60.0 / bpm
    bar = 4 * beat
    total = 17 * bar + 2.5
    n = int(total * SR)
    drums, bass, pad, lead, fx = (np.zeros(n) for _ in range(5))
    K, C, H, HO = kick(), clap(), hat(), hat(True)
    chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
    roots = [33, 29, 36, 31]
    arp = [0, 1, 2, 1, 2, 0, 1, 2]

    for b in range(17):
        t0 = b * bar
        ch = chords[b % 4]
        if b < 16:
            for m in ch:  # pad
                place(pad, tone(note(m), bar + 0.15, 10, (-0.006, 0, 0.007), attack=0.25 if b < 8 else 0.02), t0, 0.075)
            for i in range(8):  # offbeat hats everywhere, 16ths in the drop
                place(drums, H, t0 + (i + 0.5) * beat / 2 if b < 8 else t0 + i * beat / 2, 0.8)
            if b >= 8:
                for i in range(8):
                    place(drums, H, t0 + i * beat / 2 + beat / 4, 0.45)
                place(drums, HO, t0 + 3.5 * beat, 0.6)
        if 4 <= b < 16:  # claps on 2 and 4
            place(drums, C, t0 + beat, 0.9)
            place(drums, C, t0 + 3 * beat, 0.9)
        if b == 7:  # snare roll into the drop
            for i in range(16):
                place(drums, C, t0 + i * beat / 4, 0.25 + 0.5 * i / 16)
        if 4 <= b < 8:  # riser
            t = np.arange(int(bar * SR)) / SR
            p = (b - 4 + t / bar) / 4
            nz = rng.normal(0, 1, len(t))
            nz = nz - np.convolve(nz, np.ones(int(12 - 10 * p.mean())) / max(1, int(12 - 10 * p.mean())), 'same')
            place(fx, nz * p ** 2 * 0.25, t0)
        if b == 3:  # little kick pickup at the end of the intro
            place(drums, K, t0 + 3.5 * beat, 0.6)
        if 8 <= b < 16:
            for i in range(4):
                place(drums, K, t0 + i * beat)
            # bass: offbeat eighth notes on the root
            for i in range(4):
                place(bass, tone(note(roots[b % 4] + 12), beat / 2 * 0.95, 9, (-0.004, 0.004), decay=3, bright=1.3), t0 + i * beat + beat / 2, 0.5)
            # pluck arp, 8ths
            for i in range(8):
                m = ch[arp[i]] + 12 + (12 if i in (3, 7) else 0)
                place(lead, tone(note(m), beat / 2, 7, (0, 0.004), decay=9), t0 + i * beat / 2, 0.16)
        if b == 16:  # final hit
            place(drums, K, t0, 1.0)
            place(drums, C, t0, 0.8)
            for m in chords[0]:
                place(pad, tone(note(m), 2.3, 10, (-0.006, 0, 0.007), decay=1.5), t0, 0.1)
            place(bass, tone(note(33), 2.0, 9, (0,), decay=2), t0, 0.6)

    # sidechain pad/bass/lead to the kick in the drop
    t = np.arange(n) / SR
    duck = np.ones(n)
    for b in range(8, 16):
        for i in range(4):
            k0 = (b * bar + i * beat)
            m = (t >= k0) & (t < k0 + beat)
            duck[m] = np.minimum(duck[m], 0.25 + 0.75 * np.clip((t[m] - k0) / (beat * 0.7), 0, 1) ** 1.5)
    mix = drums * 0.9 + (bass + pad * 1.2 + lead) * duck + fx
    mix = np.tanh(mix * 1.2)
    mix *= 0.89 / np.abs(mix).max()
    st = np.stack([mix, mix], 1)
    # a touch of width on pad/lead
    st[:, 1] = np.roll(st[:, 1], int(0.0007 * SR))
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--bpm', type=float, default=124)
    a = ap.parse_args()
    write_wav(a.out, build(a.bpm), SR)
    beat = 60 / a.bpm
    print(f'wrote {a.out}: {a.bpm} BPM, beat {beat:.4f}s, bar {4 * beat:.4f}s, drop at {8 * 4 * beat:.3f}s')


if __name__ == '__main__':
    main()
