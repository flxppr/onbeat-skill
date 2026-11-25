---
name: onbeat
description: Make beat-synced video edits (TikTok / Reels / Shorts / YouTube) from a song plus text, images or video clips - kinetic typography, footage montages cut on the beat, lyric-style edits, hype edits with punches on every kick. Can copy the style of a reference video. Use when the user asks for an edit, a beat-synced or "on beat" video, a montage cut to music, kinetic text / motivational edit, "make it like this TikTok", or to sync anything to a song's beat or drop.
---

# onbeat: beat-synced edits

You write a short Python script against this skill's engine; the engine finds the beats, renders every frame and muxes the song. `$ONBEAT` below means the folder this SKILL.md is in; substitute its real path. Everything runs locally with Python 3.9+, numpy, Pillow and ffmpeg.

**The one rule: never guess the style.** Every edit gets its look from exactly one of: a reference video, a named preset, or a style option the user picked from stills. If you are about to invent fonts, colours or pacing the user did not ask for, stop and use step 3.

## 0. Setup (first time only)

```bash
python -c "import numpy, PIL" || pip install numpy pillow
python -c "import sys; sys.path.insert(0, '$ONBEAT/scripts'); from common import ffmpeg_exe; print(ffmpeg_exe())" || pip install imageio-ffmpeg
```

Make a project folder for the edit (e.g. `edits/<name>/`) and copy the user's files into it, or reference them by absolute path.

## 1. Gather inputs (ask only for what is missing)

- **Song** (mp3/wav/m4a, or a video to take the audio from) and **which part**: start and end in seconds. If they don't know, run step 2 on the whole song and suggest a 15-35 s window that contains the drop (`drops` in the beat map).
- **Content**: the lines of text, a folder of clips, images (logos, products, a character), or a topic you write lines for. If you write the words, show them before rendering.
- **Format**: 9:16 1080x1920 (TikTok/Reels/Shorts, the default), 1:1 1080x1080 or 16:9 1920x1080.
- **Style source**: a reference video, a preset from `styles/`, or a description (step 3 C).

## 2. Map the beats

```bash
python $ONBEAT/scripts/beats.py song.mp3 --start 10.4 --end 34 --out beats.json --plot beats.png --click click.wav
```

- Read the printed summary: BPM, first downbeat, drop candidates, per-bar loudness. **Look at `beats.png`** (white = bar starts, red = kicks, cyan = snares, gold = drop candidates). Kicks and snares should sit on the grey beat lines.
- If "other tempos that also fit" are close (above ~85%), or the plot looks off, give the user `click.wav` (the song with a click on every beat, higher on bar starts) and ask whether it's on time. Fix with `--bpm <value>` and/or `--downbeat <0-3>` (which beat of the first four is "1").
- `beats.json` must sit next to `edit.py` (or pass `Edit(..., beats='path')`). `Edit` creates it automatically if missing, but running it yourself lets you check it first.

## 3. Pin down the style (pick one path)

**A. Reference video (best).**

```bash
python $ONBEAT/scripts/analyze_ref.py reference.mp4 --out ref
```

Read `ref/report.md` and **look at** `ref/shots.png`, `ref/timeline.png` and `ref/detail.png`. Then write `STYLE.md` in the project folder by filling in `styles/TEMPLATE.md`: format, fonts (match the feel with `python $ONBEAT/scripts/engine.py fonts`, which lists installed fonts), colours (from the palette), text placement and size, how text and shots enter, cut rhythm in beats and cut timing (from the report: if it says cuts land a steady few frames early, use its `lead=` value), camera (punch on kicks if `motion_on_kicks_ratio` > 1.6), flashes, grain/glitch/vignette, and the arc. Summarise it to the user in 4-6 bullets and get a yes before building. Copy the *style*, never the reference's words, footage, logos or characters.
If the reference has few detected cuts (kinetic text on one background), re-run with `--threshold 0.15`. If the report says the tempo is uncertain, don't trust its cut-on-beat numbers until the user has checked `beats.py reference.mp4 --click click.wav` by ear.

**B. Preset.** Read the file in `styles/` and follow it:
- `motivational-kinetic.md`: dark spotlight, condensed caps, words landing on kicks, strike-and-replace payoffs, gold for the goal.
- `bw-glitch.md`: black-and-white, stretched condensed words, glitch hits, deadpan.
- `hype-montage.md`: footage cut on the beat, slow-mo intro, cut-per-beat drop, flashes, punchy grade.

**C. Only a description.** Do not interpret it once and build. If it contradicts itself ("ultra realistic but low poly"), ask one short question first. Otherwise make 3-4 clearly different readings as single frames and let the user pick:

```python
# options.py: one still per interpretation, then compare them side by side
import sys; sys.path.insert(0, r'$ONBEAT/scripts')
from engine import *
def option(name, bg, **text):
    ed = Edit('song.mp3', size=(1080, 1920)); B = ed.beats
    ed.scene(0, 4, bg=bg, punch=None, intro='cut').add(Words('YOUR *LINE* HERE', 0, anim='none', **text))
    return ed.still(1.0, f'option_{name}.png')
paths = [option('A', 'spotlight', font='display', size=170),
         option('B', 'paper', font='serif', size=120, color='ink', highlight='red'),
         option('C', 'neon', font='heavy', size=140, color='cyan', highlight='magenta', highlight_glow=24)]
```
```bash
python options.py && python $ONBEAT/scripts/engine.py compare options.png option_A.png option_B.png option_C.png --labels "A: ..." "B: ..." "C: ..."
```
Show `options.png`, say in one line what each option means, and wait for a pick. Write the choice into `STYLE.md`.

## 4. Plan on the grid before writing code

Write a short beat sheet (in chat or in `STYLE.md`): one row per scene with bar/beat, what is on screen, and how it enters. Rules that make edits feel on-beat:
- Scenes change on **bar starts** (`B.bar(i)`); speed up to every 2 beats or every beat after the drop.
- Each word or shot lands **on a hit**: beats for steady reveals, `B.between('kicks', t0, t1)` for the punchy ones. The payoff word goes on the strongest hit of the bar.
- The **drop** (`B.drop`, or the bar where loudness jumps) gets the biggest moment: slam text, flash, shake, gold, first fast cuts.
- Quiet bars get quiet type (serif, small, fades). Don't punch the camera where there is no kick.
- 9:16 safe zone: keep text between y 0.15 and 0.75 and x 0.08 to 0.92 (TikTok's UI covers the rest).

## 5. Write `edit.py`

Start from `examples/kinetic/edit.py` (text) or `examples/montage/edit.py` (footage). Skeleton:

```python
import sys; sys.path.insert(0, r'$ONBEAT/scripts')
from engine import *
ed = Edit('song.mp3', size=(1080, 1920), grain=5, vignette=0.4)   # start/duration only matter if beats.json is missing
B = ed.beats; bar = B.bar
s = ed.scene(bar(0), bar(1), bg='spotlight', punch='kicks', intro='flash')
s.add(Words("DON'T *STOP*", [bar(0, 0), bar(0, 2)], size=160))
ed.run()
```

### Engine cheat sheet
Times are seconds from the start of the edit. Positions are fractions of the frame. Sizes are design px (1080 = the frame's short side).

| | |
|---|---|
| `B.bar(i, beat=0)` | time of bar i (+ beats, fractional ok). `B.beat(x)` beat x from the start. `B.bpm`, `B.period`, `B.nbars`, `B.drop` |
| `B.between(kind, t0, t1)` | event times in a range; kind = `'beats' 'downbeats' 'kicks' 'snares' 'hits'` |
| `B.label(t)` / `B.snap(t)` | 'bar 3 beat 2' / nearest beat |
| `ed.scene(t0, t1, bg=, camera=0.012, punch='kicks', punch_amount=0.03, shake=6, intro='flash', grade=None, glitch=[...], flash=[...], chroma=None)` | intro: `flash blur zoom whip glitch fade cut`. grade: `bw warm cool punchy faded teal dark` or a list |
| backgrounds | `'spotlight' 'gold' 'black' 'ink' 'white' 'paper' 'radial' 'night' 'blood' 'neon'`, any colour, an image or video path, or `Solid() Spotlight() Gradient() Radial() Paper() Still(path, blur, darken) Clip(path, src, speed, fit='cover'/'contain'/'blur')` |
| `Text(text, t, font='display', size=120, color='offwhite', pos=(.5,.5), anim='snap', out=None, out_anim='cut', glow=0, stroke=0, shadow=0, box=None, tracking=0, strike=None, pulse=0, rotate=0, move=(t0,t1,(x,y)), upper=False, type_speed=0.04)` | anim: `snap pop slam fade blur rise drop left right zoom flicker type none`; out_anim: `cut fade snap drop rise shrink` |
| `Words(line, times, size=130, highlight='gold', highlight_glow=0, max_width=0.88, ...)` | one time per word; `*stars*` mark highlighted words (can span words); wraps and shares a baseline |
| `Counter(a, b, t, t1, fmt='#{}')` | ticking number, same styling as Text |
| `Picture(path, t, size=500, pos, anim='pop', glow=0, glow_pulse=0, spin=0, tint=None, mono=False, shadow=0)` | png/jpg/webp, alpha kept |
| `Rect(t, pos, w, h, color, anim='wipe'/'grow', radius, outline)` | bars, underlines, frames |
| `Custom(fn, t, out)` | `fn(canvas, t, ed)` draws anything with PIL for one-offs (diagrams, toggles, stick figures) |
| `ed.montage(clips_or_folder, cut_times, speed=1, fit='cover', order='sequential', **scene_kw)` | one scene per shot, never reusing footage; returns the scenes to add text to |
| `ed.flash(t, strength, dur)`, `ed.shake(t, amount)`, `ed.glitch(t, dur, amount)` | one-off hits (use on the drop) |
| `ed.overlay(el)` | drawn on every scene after the camera move (watermark, progress bar) |
| `Edit(..., grain=5, vignette=0.4, chroma=0, letterbox=0, look=None, fade_in, fade_out, lead=0)` | global finish. `lead` = seconds the whole picture runs ahead of the music (0.03-0.07 copies editors who cut 1-2 frames early) |
| fonts | roles `display impact heavy bold sans light serif serif-italic serif-bold mono`, any installed font name (`'LEMONMILK-Bold'`), or a .ttf path |

## 6. Check before rendering (every time)

```bash
python edit.py timeline   # every scene and word with its bar/beat; flags gaps and a short last scene
python edit.py sheet      # sheet.png: key frames at half size, labelled with time and bar/beat
```
**Look at `sheet.png`.** Check: text readable and inside the safe zone, nothing clipped, highlight colours right, scenes match the style guide, no empty frames. Fix and re-run. `python edit.py stills 12.5 13.0` grabs exact frames.

## 7. Render

```bash
python edit.py preview    # half size, 15 fps: fast, for the user to check timing
python edit.py render     # final, writes <script name>.mp4 next to edit.py
```
A full 1080x1920 render takes about 5 s per second of video (run it in the background if your tool times out). Send the preview first, ask for changes, then render the final. To double-check sync, `analyze_ref.py` on your own render reports how many cuts land on the beat.

## Notes
- Songs the user supplies are theirs to use; mention that platforms may mute copyrighted audio, and that posting with the platform's own sound is the usual workaround.
- Footage: `fit='blur'` puts landscape clips into vertical edits without cropping heads off. `speed=0.5` needs clips at least 2x as long as the shot.
- `python $ONBEAT/scripts/demo_song.py demo.wav` makes an original royalty-free 124 BPM track for tests and demos.
