# Style: hype montage

The user's own clips cut to the music: slow-motion intro, faster cuts through the build, a cut on every beat after the drop with flashes and punches. Short captions in boxes.

- **Format:** footage with captions. 9:16, 30 fps. Landscape clips use `fit='blur'` in the intro (whole frame visible) and `fit='cover'` once it gets fast.
- **Pacing:** intro: one shot per bar at `speed=0.5`. Build: a cut every 2 beats. Last beat before the drop: black frame or a countdown. Drop: a cut on every beat (or every kick) for 4-8 bars, then every 2 beats.
- **Text timing:** captions arrive on a beat and leave on the next cut. Keep captions to 1-3 words after the drop.
- **Type:** `bold` or `heavy`, 80-110 px for captions in the lower third (y 0.72-0.82) with a `box='#000000AA'`; one huge `display` word (250-320 px, `slam`) on the drop.
- **Colours:** white text; accent from the footage (pick one colour from the clips, or gold).
- **Backgrounds:** the clips. Grade `faded` in the intro, `punchy` from the drop.
- **Entrances:** captions `pop` or `snap`; the drop word `slam`.
- **Transitions:** `blur` in the intro, hard `cut` in the build, `flash` on every cut in the first bar of the drop and every bar after; `whip` once or twice.
- **Camera:** push 1.2%/s, punch 4-5% on kicks with shake 8 after the drop; 1% on beats in the intro.
- **Finish:** grain 4, vignette 0.35, chroma 5, `ed.flash(drop, 0.9, 0.3)` and `ed.shake(drop, 1.2)`.
- **Signature tricks:** slow-mo to real speed at the drop; a black frame with a countdown right before the drop; the best shot of the set repeated as the very last shot.
- **Arc:** atmosphere (slow) → build (faster, captions set up the message) → silence/black → drop (fast, bright) → best shot + title card → fade.

## Engine settings

```python
ed = Edit('song.mp3', size=(1080, 1920), grain=4, vignette=0.35, chroma=5)
intro = ed.montage('clips', [bar(i) for i in range(0, 5)], speed=0.5, fit='blur', punch='beats',
                   punch_amount=0.01, intro='blur', grade='faded')
drop = ed.montage('clips', [B.beat(B.fdi + 32 + i) for i in range(17)], fit='cover', punch='kicks',
                  punch_amount=0.045, shake=8, intro='flash', grade='punchy')
drop[0].add(Text('GO', B.drop, size=300, anim='slam', glow=24))
```
See `examples/montage/edit.py` for a full edit in this style.
