"""Example: motivational kinetic typography, 9:16, on the demo song (124 BPM, drop at bar 8).

    python edit.py sheet      # contact sheet of key frames (half size)
    python edit.py timeline   # every scene and word with its bar/beat position
    python edit.py preview    # quick half-size 15 fps video
    python edit.py render     # final 1080x1920 30 fps video
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
from engine import *  # noqa: E402,F403

SONG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'demo', 'song.wav')
if not os.path.exists(SONG):  # the demo track is synthesized, not shipped
    import demo_song, common
    os.makedirs(os.path.dirname(SONG), exist_ok=True)
    common.write_wav(SONG, demo_song.build(), demo_song.SR)

ed = Edit(SONG, size=(1080, 1920), grain=5, vignette=0.45, chroma=4)
B = ed.beats
bar = B.bar

# --- intro: quiet, one bar per line -------------------------------------------
s = ed.scene(bar(0), bar(1), bg='spotlight', punch='beats', punch_amount=0.012, intro='fade')
s.add(Words('EVERYONE WANTS THE *VIEW*', [bar(0, 0), bar(0, 1), bar(0, 2), bar(0, 3)], size=150))

s = ed.scene(bar(1), bar(2), bg='spotlight', punch=None, intro='blur')
s.add(Text('nobody wants the climb.', bar(1, 0), font='serif-italic', size=78, anim='type', type_speed=0.05,
           color='grey'))

s = ed.scene(bar(2), bar(3), bg='spotlight', punch='beats', punch_amount=0.015)
s.add(Text('YOU', bar(2, 0), size=120, pos=(0.5, 0.40)),
      Text('FAILED', bar(2, 1), size=210, pos=(0.5, 0.5), strike=bar(2, 2), color='offwhite'),
      Text('LEARNED', bar(2, 3), size=150, pos=(0.5, 0.62), color='gold', anim='pop', glow=14))

s = ed.scene(bar(3), bar(4), bg='radial', punch='beats', punch_amount=0.02)
s.add(Text('ATTEMPT', bar(3, 0), font='sans', size=60, pos=(0.5, 0.42), tracking=14, color='grey'),
      Counter(1, 500, bar(3, 0), bar(3, 3.5), fmt='#{}', size=230, pos=(0.5, 0.52), anim='none'))

# --- build: claps on 2 and 4 -----------------------------------------------------
s = ed.scene(bar(4), bar(6), bg='paper', punch='snares', punch_amount=0.02, intro='flash')
s.add(Words('DISCIPLINE', bar(4, 0), size=170, color='ink', pos=(0.5, 0.45)),
      Rect(bar(4, 2), pos=(0.5, 0.505), w=700, h=14, color='red'),
      Text('beats', bar(5, 0), font='serif-italic', size=80, color='#4a4744', pos=(0.5, 0.57)),
      Words('*MOTIVATION*', bar(5, 2), size=150, color='ink', highlight='red', pos=(0.5, 0.65)))

s = ed.scene(bar(6), bar(7), bg='spotlight', punch='snares', punch_amount=0.03)
s.add(Words('EVERY SINGLE *DAY*', [bar(6, 0), bar(6, 1), bar(6, 3)], size=190))

s = ed.scene(bar(7), bar(8), bg='black', punch='hits', punch_amount=0.02, intro='zoom',
             glitch=[bar(7, 3.5)])
s.add(Text('READY?', bar(7, 0), size=200, anim='type', type_speed=0.08, font='mono'),
      Text('3', bar(7, 1), size=90, pos=(0.3, 0.62), color='grey'),
      Text('2', bar(7, 2), size=90, pos=(0.5, 0.62), color='grey'),
      Text('1', bar(7, 3), size=90, pos=(0.7, 0.62), color='red'))

# --- the drop --------------------------------------------------------------------------
s = ed.scene(bar(8), bar(9), bg='gold', punch='kicks', punch_amount=0.04, shake=10)
s.add(Text('NOW.', bar(8, 0), size=380, anim='slam', color='gold', glow=30, pulse=0.05))
ed.flash(bar(8), strength=0.9, dur=0.35)
ed.shake(bar(8), amount=1.2)

words = ['WAKE', 'UP', 'WORK', 'HARD', 'STAY', '*HUNGRY*', 'NO', 'EXCUSES', 'NO', 'DAYS', '*OFF*',
         'TRUST', 'THE', '*PROCESS*']
intros = ['cut', 'whip', 'cut', 'glitch', 'cut', 'zoom', 'cut', 'flash']
for i, w in enumerate(words):
    t0, t1 = B.beat(B.fdi + 36 + 2 * i), B.beat(B.fdi + 38 + 2 * i)
    hl = w.startswith('*')
    s = ed.scene(t0, t1, bg='gold' if hl else ('ink' if i % 2 else 'radial'), punch='kicks', punch_amount=0.035,
                 intro=intros[i % len(intros)], grade='punchy' if hl else None)
    s.add(Words(w, t0, size=260 if len(w) < 7 else 200, anim='slam' if hl else 'snap', highlight_glow=22,
                pulse=0.04 if hl else 0))

# --- outro ----------------------------------------------------------------------------
s = ed.scene(bar(16), ed.duration, bg='spotlight', punch=None, camera=0.02, intro='flash')
s.add(Text('keep going.', bar(16), font='serif-italic', size=110, anim='blur', anim_dur=0.6))

ed.run()
