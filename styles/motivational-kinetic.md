# Style: motivational kinetic

Kinetic typography only, no footage: one short motivational line per bar, words snapping in on the kicks, a dark room with a spotlight, gold for the goal. Calm and heavy, then a big gold payoff.

- **Format:** kinetic text only. 9:16 or 1:1, 30 fps.
- **Pacing:** one scene per bar. If the song is fast (over ~140 BPM) use two bars (8 beats) per scene. After the drop, half a bar per scene for a while, then back to whole bars for the finale.
- **Text timing:** the words of a line appear on the bar's kicks (`B.between('kicks', t0, t1)`); if the kick pattern is sparse, use beats 0, 1(or 2) and 3. The payoff word always lands on the last kick of the bar.
- **Type:** `display` (condensed bold caps) for punch lines, 150-220 px. `serif-italic` lowercase for quiet lines, 70-110 px, in grey. `sans` with wide tracking (12-16) for small labels.
- **Colours:** text offwhite `#F2F0EB`, the goal/payoff gold `#F7C542` with glow 14-30, failure/quitting red `#DC263A`, quiet lines grey `#96948F`.
- **Backgrounds:** `spotlight` for most scenes, `gold` for the big moments, `paper` once in the middle to break it up (dark ink text on it), `radial` for variety.
- **Entrances:** `snap` (in from blurred and 15% larger) for words; `pop` for the payoff; `type` for quiet serif lines; `slam` only on the drop.
- **Transitions:** white `flash` (with blur-in) on every scene change. A `glitch` on the last beat before the drop is fine.
- **Camera:** slow push 1.2%/s, punch 3% with a small shake on every kick (`punch='kicks'`); for quiet bars `punch='beats'` at 1.5%.
- **Finish:** grain 5, vignette 0.45, chroma 0-4.
- **Signature tricks** (use 2-4 per edit, never all):
  - Strike out the wrong word and put the right one under it: `Text('FAILED', t, strike=t2)` then `Text('LEARNED', t3, color='gold', anim='pop', glow=14)`.
  - An object stands in for a letter "O" (put a `Picture` where the O would be, with `Words` split around it).
  - Dim letters so a phrase becomes another ("Don't quit" → "Do it"): two `Text` layers, fade the dimmed one with `out_anim='fade'`.
  - A counter of attempts (`Counter(1, 500, t, t1, fmt='#{}')`), ending on the goal in gold.
  - Toggles or a little diagram drawn with `Custom` (Luck: off, Discipline: on).
  - Definition card: word, pronunciation in small serif, one-line meaning.
- **Arc:** hook question → doubt → reframes (the tricks above) → a quiet break (serif lines, no punches) → drop: one huge gold word with flash + shake → fast single words → finale on `gold` → one quiet closing line in serif → fade to black.

## Engine settings

```python
ed = Edit('song.mp3', size=(1080, 1920), grain=5, vignette=0.45, chroma=3)
s = ed.scene(bar(i), bar(i + 1), bg='spotlight', punch='kicks', punch_amount=0.03, shake=6, intro='flash')
kicks = B.between('kicks', bar(i), bar(i + 1))
s.add(Words('YOU ARE *CLOSER* THAN YOU THINK', kicks or [bar(i, b) for b in (0, 1, 2, 3)], size=150,
            highlight='gold', highlight_glow=18))
```
See `examples/kinetic/edit.py` for a full edit in this style.
