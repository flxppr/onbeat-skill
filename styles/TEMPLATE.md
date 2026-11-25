# Style: <name>

Source: <reference video file / preset / option the user picked>. One line on the overall feel.

- **Format:** <footage / kinetic text only / mixed>, <9:16 | 1:1 | 16:9>, <fps>.
- **Pacing:** <a new scene every N beats/bars; how it changes at the drop>. From the reference: <cuts on beat %, median shot length in beats>.
- **Cut timing:** <exactly on the beat, or N ms early (the report's "Cut timing" line; becomes `Edit(lead=...)`)>.
- **Text timing:** <words land on kicks / beats / all at once; where the payoff word goes>.
- **Type:** <role or font name, case, weight, tracking> for punch lines; <...> for quiet lines. Size about <N> design px. Position <centre / lower third / ...>.
- **Colours:** background <hex>, main text <hex>, accent <hex> (used for <what>), warning/negative <hex>.
- **Backgrounds:** <preset names or footage treatment, grade>.
- **Entrances:** <snap / slam / type / pop ...>, exits <cut / fade>.
- **Transitions:** <flash / whip / glitch / zoom / hard cut>, used <where>.
- **Camera:** push <amount>, punch on <kicks / snares / nothing>, shake <amount>.
- **Finish:** grain <0-12>, vignette <0-1>, chroma <px>, letterbox <0-0.2>, glitch hits <where>.
- **Signature tricks:** <the 2-4 things that make this style recognisable>.
- **Arc:** <hook → ... → drop moment → ending>.

## Engine settings

```python
ed = Edit('song.mp3', size=(1080, 1920), grain=5, vignette=0.4, chroma=0, look=None, lead=0)
# typical scene
s = ed.scene(bar(i), bar(i + 1), bg='spotlight', punch='kicks', punch_amount=0.03, intro='flash')
s.add(Words('...', [...], font='display', size=150, highlight='gold'))
```
