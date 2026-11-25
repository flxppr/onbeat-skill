"""The launch / README video: what onbeat does, made with onbeat itself.
9:16, about 24 s, on the royalty-free demo song (3 bars of build-up, then the drop).

    python edit.py timeline   # every scene and word with its bar/beat
    python edit.py sheet      # contact sheet of key frames
    python edit.py preview    # half size, 15 fps
    python edit.py render     # 1080x1920 30 fps -> edit.mp4
"""
import math
import os
import re
import sys

import numpy as np
from PIL import ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'scripts'))
from engine import *  # noqa: E402,F403
import common  # noqa: E402
import demo_song  # noqa: E402

NAME = 'onbeat'
REPO = 'github.com/flxppr/onbeat-skill'

SONG = os.path.join(HERE, '..', '..', 'demo', 'song.wav')
if not os.path.exists(SONG):  # the demo track is synthesized, not shipped
    os.makedirs(os.path.dirname(SONG), exist_ok=True)
    common.write_wav(SONG, demo_song.build(), demo_song.SR)

BAR = 4 * 60 / 124
START = 5 * BAR  # song bars 5-7 are the build-up, the drop is song bar 8 (edit bar 3)
ed = Edit(SONG, size=(1080, 1920), start=START, duration=11 * BAR + 2.6, downbeat=0,
          grain=4, vignette=0.4, chroma=3, fade_in=0.15, fade_out=0.6)
B = ed.beats
bar = B.bar

GREY, DIM, CODE_STR, CODE_FN = '#8A8780', '#4A4844', '#9BE37B', '#6EC7FF'


def step(n, label, t):
    """Small step caption at the top of the build-up scenes."""
    return Text(f'{n:02d}   {label}', t, font='sans', size=44, color='#B4B1AB', tracking=5, pos=(0.5, 0.2),
                anim='fade', anim_dur=0.15)


def code_colors(s):
    """Per-character colours for a line of Python: strings green, calls blue, punctuation grey."""
    cols = ['offwhite'] * len(s)
    for m in re.finditer(r"\b(Edit|Text|scene|add)\b", s):
        for i in range(m.start(), m.end()):
            cols[i] = CODE_FN
    for i, ch in enumerate(s):
        if ch in '()=,.':
            cols[i] = GREY
    for m in re.finditer(r"'[^']*'", s):
        for i in range(m.start(), m.end()):
            cols[i] = CODE_STR
    return cols


# --- bar 0: you type one line ------------------------------------------------------------
s = ed.scene(bar(0), bar(1), bg=Gradient('#141418', '#050506'), punch='snares', punch_amount=0.012,
             intro='fade', camera=0.01)
PX = 0.5 - 440 / 1080  # left edge of the text inside the terminal
TOP = 0.47 - 255 / 1920  # terminal title bar
s.add(step(1, 'YOU TYPE ONE LINE', bar(0)),
      Rect(bar(0), pos=(0.5, 0.47), w=980, h=600, color='#17171B', radius=30, anim='pop', anim_dur=0.25),
      Rect(bar(0), pos=(0.5, 0.47), w=980, h=600, color='#2A2A30', radius=30, outline=2, anim='pop', anim_dur=0.25),
      Rect(bar(0), pos=(0.5 - 410 / 1080, TOP), w=22, h=22, radius=11, color='#FF5F57', anim='none'),
      Rect(bar(0), pos=(0.5 - 372 / 1080, TOP), w=22, h=22, radius=11, color='#FEBC2E', anim='none'),
      Rect(bar(0), pos=(0.5 - 334 / 1080, TOP), w=22, h=22, radius=11, color='#28C840', anim='none'),
      Text('claude', bar(0), font='mono', size=32, color=DIM, pos=(0.5, TOP), anim='none'))
prompt = '> /onbeat make a\n  motivational edit\n  to song.mp3, 9:16'
s.add(Text(prompt, bar(0, 0.25), font='mono', size=62, align='left', pos=(PX, 0.455), line_height=1.3,
           anim='type', type_speed=0.028,
           colors=['gold'] * 9 + ['offwhite'] * (len(prompt.replace('\n', '')) - 9)),
      Text('* finding the beat...', bar(0, 3), font='mono', size=42, color=GREY, align='left',
           pos=(PX, 0.575), anim='flicker'))

# --- bar 1: it finds the beat ------------------------------------------------------------
y, _ = common.load_audio(SONG, 8000, START, ed.duration)
COLS = 180
ENV = np.array([np.sqrt((c.astype(np.float64) ** 2).mean()) for c in np.array_split(y, COLS)])
ENV = ENV / ENV.max()


def beatmap(cv, t, ed):
    """The song's waveform with beats, bar starts, kicks and the drop drawn in as a scan sweeps across."""
    d = ImageDraw.Draw(cv)
    W, H, U = ed.W, ed.H, ed.U
    X0, X1, YC, AMP = 0.07 * W, 0.93 * W, 0.49 * H, 0.075 * H
    p = ease(min(1.0, max(0.0, (t - bar(1)) / (bar(1, 3) - bar(1)))))
    scan = X0 + (X1 - X0) * p
    D = ed.duration

    def tx(s):
        return X0 + (X1 - X0) * s / D

    cw = (X1 - X0) / COLS
    for i, e in enumerate(ENV):
        x = X0 + i * cw
        h = max(2 * U, e * AMP)
        d.rectangle([x + 1 * U, YC - h, x + cw - 1 * U, YC + h], fill=(232, 230, 225) if x + cw / 2 < scan else (52, 51, 48))
    down = set(round(v, 3) for v in B.downbeats)
    for b in B.beats:
        x = tx(b)
        if x > scan or x < X0:
            continue
        big = round(b, 3) in down
        top = YC - AMP - (46 if big else 26) * U
        d.rectangle([x - (2 if big else 1) * U, top, x + (2 if big else 1) * U, YC - AMP - 10 * U],
                    fill=(242, 240, 235) if big else (120, 118, 113))
    for k in B.kicks:
        x = tx(k)
        if X0 <= x <= scan:
            r = 6 * U
            d.ellipse([x - r, YC + AMP + 22 * U - r, x + r, YC + AMP + 22 * U + r], fill=rgb('red'))
    if B.drop is not None and tx(B.drop) <= scan:
        x = tx(B.drop)
        d.rectangle([x - 3 * U, YC - AMP - 60 * U, x + 3 * U, YC + AMP + 40 * U], fill=rgb('gold'))
    if p < 1:
        d.rectangle([scan - 2 * U, YC - AMP - 70 * U, scan + 2 * U, YC + AMP + 50 * U], fill=(247, 197, 66, 160))


s = ed.scene(bar(1), bar(2), bg=Gradient('#141418', '#050506'), punch='snares', punch_amount=0.015, intro='cut',
             camera=0.01)
s.add(step(2, 'IT FINDS THE BEAT', bar(1)),
      Counter(60, 124, bar(1), bar(1, 2.5), fmt='{} BPM', size=150, pos=(0.5, 0.31), anim='none'),
      Custom(beatmap, bar(1)),
      Text('BEATS', bar(1, 1), size=64, pos=(0.27, 0.64), color='offwhite'),
      Text('KICKS', bar(1, 2), size=64, pos=(0.5, 0.64), color='red'),
      Text('DROP', bar(1, 3), size=64, pos=(0.73, 0.64), color='gold', glow=10))

# --- bar 2: it writes the edit (snare roll) --------------------------------------------
lines = ["ed = Edit('song.mp3')",
         "s = ed.scene(B.drop, B.bar(4))",
         "s.add(Text('DROP.', B.drop,",
         "           anim='slam'))"]
s = ed.scene(bar(2), bar(3), bg=Gradient('#141418', '#050506'), punch='hits', punch_amount=0.012, intro='cut',
             camera=0.02, glitch=[bar(2, 3.5)])
s.add(step(3, 'IT WRITES THE EDIT', bar(2)))
for i, ln in enumerate(lines):
    s.add(Text(ln, bar(2, i), font='mono', size=50, align='left', pos=(PX, 0.38 + i * 0.058), anim='type',
               type_speed=0.009, colors=code_colors(ln)))

# --- bar 3: the drop -----------------------------------------------------------------------
s = ed.scene(bar(3), bar(4), bg='gold', punch='kicks', punch_amount=0.05, shake=10)
s.add(Text('DROP.', bar(3), size=420, anim='slam', color='gold', glow=30, pulse=0.05, pos=(0.5, 0.47)),
      Text('right on the drop.', bar(3, 2), font='serif-italic', size=64, pos=(0.5, 0.62), anim='blur'))
ed.flash(bar(3), strength=0.9, dur=0.35)
ed.shake(bar(3), amount=1.2)

# --- bar 4: words on the beat ----------------------------------------------------------
s = ed.scene(bar(4), bar(5), bg='spotlight', punch='kicks', punch_amount=0.035, intro='cut')
s.add(Words('EVERY WORD ON THE *BEAT.*', [bar(4, 0), bar(4, 1), bar(4, 2), bar(4, 2.5), bar(4, 3)], size=210,
            highlight_glow=20))

# --- bar 5: a cut on every kick ----------------------------------------------------------
for i, (w, bg, intro) in enumerate([('EVERY', 'radial', 'cut'), ('CUT', 'ink', 'whip'),
                                    ('ON THE', 'radial', 'cut'), ('KICK.', 'gold', 'flash')]):
    t0 = bar(5, i)
    s = ed.scene(t0, bar(5, i + 1), bg=bg, punch='kicks', punch_amount=0.04, intro=intro)
    hl = w == 'KICK.'
    s.add(Text(w, t0, size=330, color='gold' if hl else 'offwhite', anim='slam' if hl else 'snap',
               glow=24 if hl else 0))

# --- bars 6-7: the effects, each on its own hit -----------------------------------------
s = ed.scene(bar(6), bar(6, 2), bg='spotlight', punch='kicks', punch_amount=0.03, intro='flash', flash=[bar(6, 1)])
s.add(Text('FLASHES.', bar(6), size=250))
s = ed.scene(bar(6, 2), bar(7), bg='ink', punch='kicks', punch_amount=0.03, intro='glitch',
             glitch=[bar(6, 3), bar(6, 3.5)], grade='bw')
s.add(Text('GLITCHES.', bar(6, 2), size=250, font='mono', anim='flicker'))
s = ed.scene(bar(7), bar(7, 2), bg='radial', punch='beats', punch_amount=0.09, intro='zoom')
s.add(Text('PUNCHES.', bar(7), size=250, color='gold'))
s = ed.scene(bar(7, 2), bar(8), bg='spotlight', punch='kicks', punch_amount=0.04, intro='cut', shake=14)
s.add(Text('SHAKES.', bar(7, 2), size=260, anim='slam'))
ed.shake(bar(7, 2), amount=1.0)
ed.shake(bar(7, 3), amount=1.3)

# --- bars 8-9: the pitch ---------------------------------------------------------------
s = ed.scene(bar(8), bar(9), bg='spotlight', punch='kicks', punch_amount=0.03, intro='flash')
s.add(Words('YOU TYPE *ONE LINE.*', [bar(8, 0), bar(8, 1), bar(8, 2), bar(8, 3)], size=210, highlight_glow=20))
s = ed.scene(bar(9), bar(10), bg='radial', punch='kicks', punch_amount=0.035, intro='cut', glitch=[bar(9, 3.5)])
s.add(Words('CLAUDE MAKES THE *EDIT.*', [bar(9, 0), bar(9, 1), bar(9, 2), bar(9, 3)], size=210,
            highlight_glow=20))


# --- bar 10 to the end: the name -----------------------------------------------------------
def beat_dots(cv, t, ed):
    """Four dots under the name; the current beat lights up, all gold from the final hit."""
    d = ImageDraw.Draw(cv)
    U = ed.U
    final = t >= bar(11)
    cur = int(math.floor(B.position(t) - B.fdi)) % 4
    for i in range(4):
        x, yy, r = ed.W * 0.5 + (i - 1.5) * 46 * U, ed.H * 0.565, 11 * U
        on = final or i == cur
        d.ellipse([x - r, yy - r, x + r, yy + r], fill=rgb('gold' if on else '#3A3936'))


s = ed.scene(bar(10), ed.duration, bg='spotlight', punch='kicks', punch_amount=0.03, intro='flash', camera=0.015)
s.add(Text(NAME, bar(10), size=330, anim='slam', glow=8, pos=(0.5, 0.45)),
      Custom(beat_dots, bar(10)),
      Text('a Claude skill for beat-synced edits', bar(10, 2), font='sans', size=44, color=GREY, pos=(0.5, 0.62),
           anim='fade'),
      Text('free on GitHub', bar(11), size=96, color='gold', pos=(0.5, 0.69), anim='pop', glow=14),
      Text(REPO, bar(11, 1), font='mono', size=40, color='offwhite', pos=(0.5, 0.735), anim='fade'))
ed.flash(bar(11), strength=0.6, dur=0.3)

ed.run()
