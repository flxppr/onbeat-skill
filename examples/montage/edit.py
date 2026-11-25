"""Example: footage montage cut on the beat, 9:16, on the demo song.

Put your clips (any size, any length) in a folder called clips/ next to this file,
or point ONBEAT_CLIPS at a folder, then:

    python edit.py sheet | preview | render
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

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.environ.get('ONBEAT_CLIPS', os.path.join(HERE, 'clips'))

ed = Edit(SONG, size=(1080, 1920), grain=4, vignette=0.35, chroma=5)
B = ed.beats
bar = B.bar
drop = bar(8)

# intro: one shot per bar, slow motion, landscape footage fitted over a blurred copy
intro = ed.montage(CLIPS, [bar(i) for i in range(0, 5)], speed=0.5, fit='blur', punch='beats',
                   punch_amount=0.01, intro='blur', grade='faded')
intro[0].add(Text('a beat-synced edit', bar(0, 0), font='serif-italic', size=70, pos=(0.5, 0.82), anim='fade'))
intro[2].add(Words('made from *one prompt*', [bar(2, 0), bar(2, 1), bar(2, 2)], size=90, pos=(0.5, 0.82),
                   font='bold', shadow=8))

# build: a cut every two beats, filling the frame
ed.montage(CLIPS, [bar(4, b) for b in range(0, 16, 2)] + [bar(7, 2)], fit='cover', punch='snares',
           punch_amount=0.02, intro='cut')
s = ed.scene(bar(7, 2), drop, bg='black', punch='hits', intro='zoom')
s.add(Text('3', bar(7, 2), size=200), Text('2', bar(7, 3), size=200, pos=(0.5, 0.5)))

# drop: a cut on every beat, punchy grade, flash + shake on the drop
shots = ed.montage(CLIPS, [B.beat(B.fdi + 32 + i) for i in range(0, 33)], fit='cover', punch='kicks',
                   punch_amount=0.045, shake=8, intro='flash', grade='punchy')
shots[0].add(Text('DROP', drop, size=300, anim='slam', glow=24, color='offwhite', out=B.beat(B.fdi + 33)))
ed.flash(drop, 0.9, 0.3)
ed.shake(drop, 1.2)
for i, w in enumerate(['NO', 'EDITING', '*SKILLS*', 'NEEDED']):
    shots[8 + 4 * i].add(Words(w, B.beat(B.fdi + 40 + 4 * i), size=200, box='#000000AA', anim='pop',
                               pos=(0.5, 0.5)))

s = ed.scene(bar(16), ed.duration, bg='black', punch=None, intro='flash')
s.add(Text('onbeat', bar(16), font='display', size=200, anim='blur', anim_dur=0.5),
      Text('a Claude skill', bar(16, 1), font='serif-italic', size=60, pos=(0.5, 0.58), anim='fade', color='grey'))

ed.overlay(Rect(0, pos=(0.5, 0.985), w=2000, h=10, color='#ffffff30', anim='none'))
ed.run()
