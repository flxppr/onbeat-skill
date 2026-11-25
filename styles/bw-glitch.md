# Style: black-and-white glitch

Dark, deadpan black-and-white typography with digital glitch hits on the beat. Big stretched condensed words, tiny monospace "system" text, a cold ending.

- **Format:** kinetic text, sometimes over dark footage graded `bw`. 16:9 or 9:16, 30 fps.
- **Pacing:** one scene per bar, two bars for the long lines. Glitch hits on the snares.
- **Text timing:** main word lands on beat 0 of the bar, its small subtitle on beat 2, then a glitch on beat 3.5 into the next scene.
- **Type:** main words `display` or `impact`, all caps, very large (240-420 px), tight. Secondary text `mono`, 40-60 px, tracking 6-10, sometimes with `anim='type'` like a terminal.
- **Colours:** pure black `#050505`, off-white `#F0F0EC`, mid grey `#96968F`. No colour at all, except optionally one red `#DC263A` word for the turn.
- **Backgrounds:** `black`, and footage with `grade='bw'` plus `darken=0.3` if there is footage.
- **Entrances:** `flicker` or `snap`; mono text uses `type`. Exits are hard cuts.
- **Transitions:** `glitch` on most scene changes, hard `cut` on others; no white flashes except one on the drop.
- **Camera:** almost still (camera 0.004), punch on snares 2%, no shake.
- **Finish:** `look='bw'`, grain 9, vignette 0.55, chroma 6 (RGB split on punches), extra `ed.glitch(t)` hits on fills.
- **Signature tricks:** a word stretched to fill the width (`size` large with `max_width=0.96`); a counter in mono (`Counter(..., font='mono')`); a strike-through in white; the last line is small, deadpan, lower case.
- **Arc:** cold open (one word) → statements, one per bar → the turn (the red word) → drop: glitch storm + flash, words every beat → deadpan small final line → cut to black (no fade).

## Engine settings

```python
ed = Edit('song.mp3', size=(1920, 1080), grain=9, vignette=0.55, chroma=6, look='bw', fade_out=0)
s = ed.scene(bar(i), bar(i + 1), bg='black', camera=0.004, punch='snares', punch_amount=0.02, shake=0,
             intro='glitch', glitch=[bar(i, 3.5)])
s.add(Text('STILL', bar(i), size=380, anim='flicker', max_width=0.96),
      Text('> searching...', bar(i, 2), font='mono', size=48, tracking=8, pos=(0.5, 0.72), anim='type', color='grey'))
```
