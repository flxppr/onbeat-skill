"""onbeat engine: beat-synced edits from a short Python script.

An edit script looks like this (see ../examples):

    import sys; sys.path.insert(0, r'<path to onbeat>/scripts')
    from engine import *

    ed = Edit('song.mp3', size=(1080, 1920))     # beats.json is made automatically
    B = ed.beats
    s = ed.scene(B.bar(0), B.bar(1), bg='spotlight')
    s.add(Words("DON'T *STOP*", [B.bar(0, 0), B.bar(0, 2)], size=150))
    ed.run()                                      # python edit.py render|preview|sheet|stills|timeline

Units: positions are fractions of the frame (0..1). Sizes are "design pixels": 1 unit is
1/1080 of the frame's shorter side, so an edit looks the same in 9:16, 1:1 and 16:9 and in
half-resolution previews. Times are seconds from the start of the edit.
"""
import bisect
import json
import math
import os
import re
import subprocess
import sys
import time as _time

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import ffmpeg_exe, probe  # noqa: E402

__all__ = ['Edit', 'Scene', 'Text', 'Words', 'Picture', 'Rect', 'Counter', 'Custom', 'Clip',
           'Solid', 'Spotlight', 'Gradient', 'Radial', 'Paper', 'Still', 'contact_sheet',
           'ease', 'back', 'pulse', 'rgb', 'font', 'list_fonts']


# ====================================================================== small helpers
def ease(p):
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def ease_in_out(p):
    p = min(1.0, max(0.0, p))
    return 3 * p * p - 2 * p * p * p


def back(p, c=1.9):
    p = min(1.0, max(0.0, p))
    q = p - 1
    return 1 + (c + 1) * q ** 3 + c * q ** 2


def pulse(times, t, tau=0.11):
    """1.0 right on an event, decaying exponentially until the next one."""
    i = bisect.bisect_right(times, t) - 1
    if i < 0:
        return 0.0
    return math.exp(-(t - times[i]) / tau)


_NAMED = {'gold': '#F7C542', 'red': '#DC263A', 'offwhite': '#F2F0EB', 'ink': '#0B0B0C',
          'grey': '#96948F', 'gray': '#96948F', 'cyan': '#3FE0F0', 'magenta': '#FF3EA5',
          'lime': '#B6FF3B', 'orange': '#FF8A1F', 'purple': '#9B5CFF', 'blue': '#3A7BFF'}


def rgb(c, alpha=False):
    """'#F7C542', '#F7C54280', 'gold', (r,g,b) or (r,g,b,a) -> tuple."""
    if isinstance(c, (tuple, list)):
        t = tuple(int(v) for v in c)
    else:
        c = _NAMED.get(str(c).lower(), c)
        s = str(c)
        if s.startswith('#') and len(s) == 9:
            t = tuple(int(s[i:i + 2], 16) for i in (1, 3, 5, 7))
        else:
            t = ImageColor.getrgb(s)
    if alpha:
        return t if len(t) == 4 else t + (255,)
    return t[:3]


# ====================================================================== fonts
ROLES = {
    'display': [('bahnschrift', 'Bold Condensed'), 'Anton-Regular', 'BebasNeue-Regular', 'Oswald-Bold',
                'DIN Condensed Bold', 'Impact', 'DejaVuSansCondensed-Bold', 'LiberationSansNarrow-Bold'],
    'impact': ['Impact', 'impact', 'Anton-Regular', 'DejaVuSansCondensed-Bold'],
    'heavy': ['Montserrat-Black', 'Montserrat-ExtraBold', 'ariblk', 'Arial Black', 'seguibl', 'DejaVuSans-Bold'],
    'bold': ['Montserrat-Bold', 'arialbd', 'Arial Bold', 'segoeuib', 'DejaVuSans-Bold'],
    'sans': ['Montserrat-SemiBold', 'Montserrat-Medium', 'segoeui', 'Arial', 'arial', 'Helvetica', 'DejaVuSans'],
    'light': ['Montserrat-Light', 'segoeuil', 'Arial', 'arial', 'DejaVuSans'],
    'serif': ['georgia', 'Georgia', 'DejaVuSerif', 'LiberationSerif-Regular'],
    'serif-italic': ['georgiai', 'Georgia Italic', 'DejaVuSerif-Italic', 'LiberationSerif-Italic'],
    'serif-bold': ['georgiab', 'Georgia Bold', 'DejaVuSerif-Bold', 'LiberationSerif-Bold'],
    'mono': ['JetBrainsMono-Bold', 'consolab', 'Menlo', 'Courier New Bold', 'DejaVuSansMono-Bold'],
}
_font_index = None
_font_cache = {}
FONT_DIRS = []


def _norm(s):
    return re.sub(r'[\s_\-]', '', s.lower())


def _index_fonts():
    global _font_index
    if _font_index is not None:
        return _font_index
    dirs = list(FONT_DIRS) + [os.path.join(os.path.dirname(HERE), 'fonts')]
    if sys.platform == 'win32':
        dirs += [os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts')]
    elif sys.platform == 'darwin':
        dirs += ['/System/Library/Fonts', '/System/Library/Fonts/Supplemental', '/Library/Fonts',
                 os.path.expanduser('~/Library/Fonts')]
    else:
        dirs += ['/usr/share/fonts', '/usr/local/share/fonts', os.path.expanduser('~/.fonts'),
                 os.path.expanduser('~/.local/share/fonts')]
    idx = {}
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(('.ttf', '.otf', '.ttc')):
                    idx.setdefault(_norm(os.path.splitext(f)[0]), os.path.join(root, f))
    _font_index = idx
    return idx


def _find_font(name):
    if os.path.isfile(name):
        return name
    idx = _index_fonts()
    n = _norm(name)
    if n in idx:
        return idx[n]
    hits = sorted((k for k in idx if n in k), key=len)
    return idx[hits[0]] if hits else None


def font(name='display', size=100):
    """A PIL font for a role ('display', 'heavy', 'bold', 'sans', 'light', 'serif', 'serif-italic',
    'serif-bold', 'mono', 'impact'), an installed font name ('LEMONMILK-Bold') or a file path."""
    size = max(4, int(round(size)))
    key = (name, size)
    if key in _font_cache:
        return _font_cache[key]
    cands = ROLES.get(name, [name])
    f = None
    for c in cands:
        var = None
        if isinstance(c, tuple):
            c, var = c
        p = _find_font(c)
        if not p:
            continue
        try:
            f = ImageFont.truetype(p, size)
            if var:
                f.set_variation_by_name(var)
            break
        except Exception:
            f = None
    if f is None:
        if name not in ROLES:
            print(f'[onbeat] font "{name}" not found, using "sans"', file=sys.stderr)
            f = font('sans', size)
        else:
            f = ImageFont.load_default(size)
    _font_cache[key] = f
    return f


def list_fonts():
    idx = _index_fonts()
    out = {}
    for role in ROLES:
        f = font(role, 40)
        try:
            out[role] = ' '.join(f.getname())
        except Exception:
            out[role] = '?'
    return out, sorted(os.path.basename(p) for p in set(idx.values()))


# ====================================================================== sprites
_sprite_cache = {}


class Sprite:
    """RGBA image plus the anchor point (in image px) that gets placed at the element's position."""
    __slots__ = ('img', 'ax', 'ay', 'w', 'cap')

    def __init__(self, img, ax, ay, w=0, cap=0):
        self.img, self.ax, self.ay, self.w, self.cap = img, ax, ay, w, cap


def _alpha_mul(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel('A').point(lambda v: int(v * a)))
    return im


def _glow(im, radius, color, strength=1.3):
    a = im.getchannel('A').filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * strength)))
    g = Image.new('RGBA', im.size, rgb(color) + (0,))
    g.putalpha(a)
    return Image.alpha_composite(g, im)


def text_sprite(text, fname, size, color, glow=0, glow_color=None, stroke=0, stroke_color='black',
                tracking=0, align='center', line_height=1.0, shadow=0, box=None, box_pad=0.25,
                upto=None, colors=None):
    key = (text, fname, size, rgb(color, True), glow, glow_color, stroke, stroke_color, tracking, align,
           line_height, shadow, box, box_pad, upto, tuple(colors) if colors else None)
    sp = _sprite_cache.get(key)
    if sp:
        return sp
    f = font(fname, size)
    lines = text.split('\n')
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * line_height)
    try:
        cap = -f.getbbox('H', anchor='ls')[1]
    except Exception:
        cap = asc * 0.7

    def width(s):
        if not s:
            return 0
        return f.getlength(s) + (tracking * (len(s) - 1) if tracking else 0)

    ws = [width(l) for l in lines]
    maxw = max(ws) if ws else 0
    bp = int(size * box_pad) if box else 0
    pad = int(glow * 2.5 + stroke + shadow * 2.5 + 6) + bp
    W = int(math.ceil(maxw)) + 2 * pad
    H = lh * (len(lines) - 1) + asc + desc + 2 * pad
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if box:
        top = pad + asc - cap - bp
        bot = pad + asc + (len(lines) - 1) * lh + int(desc * 0.5) + bp
        x0 = pad - bp if align != 'center' else (W - maxw) / 2 - bp
        d.rounded_rectangle([x0, top, x0 + maxw + 2 * bp, bot], radius=int(bp * 0.8), fill=rgb(box, True))
    fill = rgb(color, True)
    sfill = rgb(stroke_color, True)
    n_drawn = 0
    ci = 0
    for i, l in enumerate(lines):
        if align == 'center':
            x = pad + (maxw - ws[i]) / 2
        elif align == 'right':
            x = pad + maxw - ws[i]
        else:
            x = pad
        y = pad + asc + i * lh
        if tracking or upto is not None or colors:
            for ch in l:
                if upto is not None and n_drawn >= upto:
                    break
                c = rgb(colors[ci], True) if colors and ci < len(colors) and colors[ci] else fill
                d.text((x, y), ch, font=f, fill=c, anchor='ls', stroke_width=stroke, stroke_fill=sfill)
                x += f.getlength(ch) + tracking
                n_drawn += 1
                ci += 1
        else:
            d.text((x, y), l, font=f, fill=fill, anchor='ls', stroke_width=stroke, stroke_fill=sfill)
    if shadow:
        sh = Image.new('RGBA', im.size, (0, 0, 0, 0))
        a = im.getchannel('A').filter(ImageFilter.GaussianBlur(shadow)).point(lambda v: int(v * 0.8))
        sh.putalpha(a)
        base = Image.new('RGBA', im.size, (0, 0, 0, 0))
        base.alpha_composite(sh, (0, int(shadow * 0.6)))
        im = Image.alpha_composite(base, im)
    if glow:
        im = _glow(im, glow, glow_color or color)
    if align == 'center':
        ax = pad + maxw / 2
    elif align == 'right':
        ax = pad + maxw
    else:
        ax = pad
    ay = pad + asc - cap + ((len(lines) - 1) * lh + cap) / 2
    sp = Sprite(im, ax, ay, maxw, cap)
    if len(_sprite_cache) > 4000:
        _sprite_cache.clear()
    _sprite_cache[key] = sp
    return sp


def paste(cv, sp, x, y, sc=1.0, alpha=1.0, blur=0.0, rot=0.0):
    """Composite a Sprite so its anchor lands on (x, y)."""
    im, ax, ay = sp.img, sp.ax, sp.ay
    if alpha <= 0.004 or sc <= 0.01:
        return
    if abs(rot) > 0.05:
        hw = int(math.ceil(max(ax, im.width - ax)))
        hh = int(math.ceil(max(ay, im.height - ay)))
        c = Image.new('RGBA', (2 * hw, 2 * hh), (0, 0, 0, 0))
        c.alpha_composite(im, (int(round(hw - ax)), int(round(hh - ay))))
        im = c.rotate(rot, resample=Image.BICUBIC, expand=True)
        ax, ay = im.width / 2, im.height / 2
    if abs(sc - 1) > 0.003:
        nw, nh = max(1, round(im.width * sc)), max(1, round(im.height * sc))
        im = im.resize((nw, nh), Image.BICUBIC)
        ax, ay = ax * sc, ay * sc
    if blur > 0.4:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im = _alpha_mul(im, alpha)
    px, py = int(round(x - ax)), int(round(y - ay))
    sx, sy = max(0, -px), max(0, -py)
    ex, ey = min(im.width, cv.width - px), min(im.height, cv.height - py)
    if ex <= sx or ey <= sy:
        return
    if sx or sy or ex < im.width or ey < im.height:
        im = im.crop((sx, sy, ex, ey))
    cv.alpha_composite(im, (px + sx, py + sy))


# ====================================================================== animation
ANIM_DUR = {'snap': 0.14, 'pop': 0.32, 'slam': 0.2, 'fade': 0.3, 'rise': 0.32, 'drop': 0.32,
            'left': 0.28, 'right': 0.28, 'type': None, 'flicker': 0.28, 'zoom': 0.4, 'none': 0.0, 'blur': 0.25}


def anim_in(kind, p, U):
    """-> scale, alpha, blur, dx, dy, rot for entrance progress p in 0..1."""
    e = ease(p)
    if kind == 'snap':
        return 1.15 - 0.15 * e, e, 8 * (1 - e), 0, 0, 0
    if kind == 'pop':
        return 0.3 + 0.7 * back(p), min(1, p * 3), 0, 0, 0, 0
    if kind == 'slam':
        q = (1 - p) ** 3
        return 1 + 1.3 * q, min(1, p * 2.5), 10 * q, 0, 0, 0
    if kind == 'fade':
        return 1, e, 0, 0, 0, 0
    if kind == 'blur':
        return 1, e, 14 * (1 - e), 0, 0, 0
    if kind == 'rise':
        return 1, e, 3 * (1 - e), 0, 60 * U * (1 - e), 0
    if kind == 'drop':
        return 1, e, 3 * (1 - e), 0, -60 * U * (1 - e), 0
    if kind == 'left':
        return 1, e, 4 * (1 - e), -90 * U * (1 - e), 0, 0
    if kind == 'right':
        return 1, e, 4 * (1 - e), 90 * U * (1 - e), 0, 0
    if kind == 'zoom':
        return 0.6 + 0.4 * e, e, 6 * (1 - e), 0, 0, 0
    if kind == 'flicker':
        on = p >= 1 or (int(p * 9) % 2 == 0 and p > 0.15)
        return 1, 1.0 if on else 0.15, 0, 0, 0, 0
    return 1, 1, 0, 0, 0, 0


def anim_out(kind, p, U):
    e = ease(p)
    if kind == 'fade':
        return 1, 1 - e, 0, 0, 0, 0
    if kind == 'snap':
        return 1 + 0.2 * e, 1 - e, 10 * e, 0, 0, 0
    if kind == 'drop':
        return 1, 1 - e, 2 * e, 0, 120 * U * e * e, 0
    if kind == 'rise':
        return 1, 1 - e, 2 * e, 0, -80 * U * e, 0
    if kind == 'shrink':
        return 1 - 0.8 * e, 1 - e, 0, 0, 0, 0
    return 1, 0.0 if p > 0 else 1.0, 0, 0, 0, 0  # cut


# ====================================================================== elements
class El:
    """Base element. t = when it appears, out = when it goes (default: end of scene)."""
    layer = 0

    def __init__(self, t=0.0, out=None, anim='snap', anim_dur=None, out_anim='cut', out_dur=0.2,
                 pos=(0.5, 0.5), alpha=1.0, rotate=0.0, pulse=0.0, pulse_on='kicks', float_=0.0,
                 layer=None, move=None):
        self.t, self.out, self.anim, self.anim_dur = t, out, anim, anim_dur
        self.out_anim, self.out_dur = out_anim, out_dur
        self.pos, self.alpha, self.rotate, self.pulse, self.pulse_on = pos, alpha, rotate, pulse, pulse_on
        self.float_ = float_
        self.move = move  # (t0, t1, (x, y)) glide to a new position
        if layer is not None:
            self.layer = layer

    @property
    def t_last(self):
        """When this element's last part appears (for picking frames to check)."""
        return self.t

    def visible(self, t):
        if t < self.t:
            return False
        if self.out is not None and self.out_anim == 'cut' and t >= self.out:
            return False
        if self.out is not None and t >= self.out + self.out_dur:
            return False
        return True

    def state(self, t, ed):
        U = ed.U
        d = self.anim_dur if self.anim_dur is not None else (ANIM_DUR.get(self.anim) or 0.0)
        if d > 0 and t < self.t + d:
            sc, al, bl, dx, dy, rot = anim_in(self.anim, (t - self.t) / d, U)
        else:
            sc, al, bl, dx, dy, rot = 1, 1, 0, 0, 0, 0
        if self.out is not None and t >= self.out:
            s2, a2, b2, dx2, dy2, _ = anim_out(self.out_anim, (t - self.out) / max(self.out_dur, 1e-3), U)
            sc *= s2
            al *= a2
            bl += b2
            dx += dx2
            dy += dy2
        if self.pulse:
            sc *= 1 + self.pulse * pulse(ed.beats.events(self.pulse_on), t)
        x, y = self.pos
        if self.move and t >= self.move[0]:
            k = ease_in_out((t - self.move[0]) / max(1e-3, self.move[1] - self.move[0]))
            x += (self.move[2][0] - x) * k
            y += (self.move[2][1] - y) * k
        if self.float_:
            dy += self.float_ * U * math.sin(2 * math.pi * (t - self.t) / 2.2)
        return x * ed.W + dx, y * ed.H + dy, sc, al * self.alpha, bl, rot + self.rotate

    def draw(self, cv, t, ed):
        pass


class Text(El):
    """One piece of text. size is in design px (cap-to-baseline is ~0.7 of it).

    anim: snap pop slam fade blur rise drop left right zoom flicker type none
    out_anim: cut fade snap drop rise shrink
    strike=time draws a line through it; box='#000000AA' puts a caption box behind it."""

    def __init__(self, text, t=0.0, font='display', size=120, color='offwhite', pos=(0.5, 0.5),
                 glow=0, glow_color=None, stroke=0, stroke_color='black', tracking=0, align='center',
                 line_height=1.0, shadow=0, box=None, max_width=0.9, upper=False, strike=None,
                 strike_color='red', colors=None, type_speed=0.04, **kw):
        super().__init__(t=t, pos=pos, **kw)
        self.text = text.upper() if upper else text
        self.font, self.size, self.color = font, size, color
        self.glow, self.glow_color, self.stroke, self.stroke_color = glow, glow_color, stroke, stroke_color
        self.tracking, self.align, self.line_height, self.shadow, self.box = tracking, align, line_height, shadow, box
        self.max_width, self.strike, self.strike_color, self.colors = max_width, strike, strike_color, colors
        self.type_speed = type_speed
        if self.anim == 'type' and self.anim_dur is None:
            self.anim_dur = 0.0
        self._fit = {}

    def text_at(self, t):
        return self.text

    def sprite(self, ed, t, upto=None):
        U = ed.U
        txt = self.text_at(t)
        size = self.size * U
        key = (txt, ed.W)
        if key not in self._fit:  # shrink to max_width
            sp = text_sprite(txt, self.font, size, self.color, tracking=self.tracking * U)
            lim = self.max_width * ed.W
            self._fit[key] = min(1.0, lim / sp.w) if sp.w > lim else 1.0
        s = size * self._fit[key]
        k = s / size
        return text_sprite(txt, self.font, s, self.color, self.glow * U * k, self.glow_color, int(self.stroke * U * k),
                           self.stroke_color, self.tracking * U * k, self.align, self.line_height,
                           self.shadow * U * k, self.box, upto=upto, colors=self.colors)

    def draw(self, cv, t, ed):
        x, y, sc, al, bl, rot = self.state(t, ed)
        upto = None
        if self.anim == 'type':
            n = len(self.text_at(t).replace('\n', ''))
            upto = min(n, int((t - self.t) / self.type_speed) + 1)
            if upto >= n:
                upto = None
        sp = self.sprite(ed, t, upto)
        paste(cv, sp, x, y, sc, al, bl, rot)
        if self.strike is not None and t >= self.strike:
            p = ease((t - self.strike) / 0.12)
            w = sp.w * sc
            x0 = x - (w / 2 if self.align == 'center' else (w if self.align == 'right' else 0))
            th = max(3, int(self.size * ed.U * 0.09 * sc))
            d = ImageDraw.Draw(cv)
            d.rectangle([x0 - 6 * ed.U, y - th / 2, x0 - 6 * ed.U + (w + 12 * ed.U) * p, y + th / 2],
                        fill=rgb(self.strike_color, True))


class Counter(Text):
    """A number that counts from a to b between t and t1. fmt like '#{:,}' or '{}%'."""

    def __init__(self, a, b, t, t1, fmt='{:,}', easing='out', **kw):
        super().__init__(fmt.format(int(a)), t=t, **kw)
        self.a, self.b, self.t1, self.fmt, self.easing = a, b, t1, fmt, easing

    def text_at(self, t):
        p = min(1.0, max(0.0, (t - self.t) / max(1e-3, self.t1 - self.t)))
        p = ease(p) if self.easing == 'out' else p
        return self.fmt.format(int(round(self.a + (self.b - self.a) * p)))


class Words(El):
    """A line whose words appear one by one at `times` (one time per word; a single number
    shows them all at once). Wrap a word in *stars* to colour it with `highlight`.
    Words wrap onto new lines to fit max_width; all words share one baseline per line."""

    def __init__(self, line, times, font='display', size=130, color='offwhite', highlight='gold',
                 pos=(0.5, 0.5), gap=0.28, max_width=0.88, line_height=1.05, align='center', anim='snap',
                 highlight_glow=0, upper=False, **kw):
        out = kw.pop('out', None)
        layer = kw.pop('layer', None)
        super().__init__(t=0, out=out, pos=pos, anim=anim, layer=layer)
        toks = line.split()
        if isinstance(times, (int, float)):
            times = [times] * len(toks)
        times = list(times) + [times[-1]] * max(0, len(toks) - len(times))
        self.items = []
        inside = False  # *highlights* may span several words
        for tok, tt in zip(toks, times):
            opens, closes = tok.startswith('*'), tok.endswith('*') and len(tok) > 1
            hl = inside or opens
            if opens and not closes:
                inside = True
            elif closes:
                inside = False
            word = tok.strip('*')
            self.items.append((word.upper() if upper else word, tt, hl))
        self.t = min(times) if times else 0
        self.font, self.size, self.color, self.highlight = font, size, color, highlight
        self.gap, self.max_width, self.line_height, self.align = gap, max_width, line_height, align
        self.highlight_glow, self.kw = highlight_glow, kw
        self._built_for = None
        self.children = []

    def build(self, ed):
        U = ed.U
        size = self.size
        while True:
            f = font(self.font, size * U)
            gap = self.gap * size * U
            widths = [f.getlength(w) for w, _, _ in self.items]
            lim = self.max_width * ed.W
            if max(widths) <= lim or size < 20:
                break
            size *= 0.92
        rows, cur, cw = [], [], 0
        for i, w in enumerate(widths):
            add = w if not cur else cw + gap + w
            if cur and add > lim:
                rows.append(cur)
                cur, cw = [i], w
            else:
                cur.append(i)
                cw = add
        if cur:
            rows.append(cur)
        asc, desc = f.getmetrics()
        lh = (asc + desc) * self.line_height
        cx, cy = self.pos[0] * ed.W, self.pos[1] * ed.H
        y0 = cy - lh * (len(rows) - 1) / 2
        self.children = []
        for r, row in enumerate(rows):
            rw = sum(widths[i] for i in row) + gap * (len(row) - 1)
            x = cx - rw / 2 if self.align == 'center' else (cx if self.align == 'left' else cx - rw)
            for i in row:
                word, tt, hl = self.items[i]
                kw = dict(self.kw)
                if hl and self.highlight_glow:
                    kw['glow'] = self.highlight_glow
                    kw['glow_color'] = self.highlight
                ch = Text(word, t=tt, font=self.font, size=size, color=self.highlight if hl else self.color,
                          pos=((x + widths[i] / 2) / ed.W, (y0 + r * lh) / ed.H), anim=self.anim,
                          out=self.out, max_width=2.0, **kw)
                self.children.append(ch)
                x += widths[i] + gap
        self._built_for = ed.W

    def visible(self, t):
        return t >= self.t and (self.out is None or t < self.out + 0.5)

    def draw(self, cv, t, ed):
        if self._built_for != ed.W:
            self.build(ed)
        for c in self.children:
            if c.visible(t):
                c.draw(cv, t, ed)

    @property
    def t_last(self):
        return max(tt for _, tt, _ in self.items) if self.items else self.t

    def word(self, i):
        """The Text element for word i (after the first draw), e.g. to strike it."""
        return self.children[i]


class Picture(El):
    """An image (png/jpg/webp, transparency kept). size = width in design px.
    spin = degrees per second, tint = colour to multiply with, glow pulses on kicks if glow_pulse."""

    def __init__(self, path, t=0.0, size=500, pos=(0.5, 0.5), anim='pop', glow=0, glow_color='gold',
                 glow_pulse=0.0, spin=0.0, tint=None, shadow=0, mono=False, **kw):
        super().__init__(t=t, pos=pos, anim=anim, **kw)
        self.path, self.size, self.glow, self.glow_color = path, size, glow, glow_color
        self.glow_pulse, self.spin, self.tint, self.shadow, self.mono = glow_pulse, spin, tint, shadow, mono
        self._cache = {}

    def _img(self, ed, g):
        key = (ed.W, round(g, 1))
        if key in self._cache:
            return self._cache[key]
        if 'base' not in self._cache or self._cache['base'][0] != ed.W:
            im = self.path if isinstance(self.path, Image.Image) else Image.open(self.path)
            im = im.convert('RGBA')
            w = max(1, int(self.size * ed.U))
            im = im.resize((w, max(1, int(im.height * w / im.width))), Image.LANCZOS)
            if self.mono:
                a = im.getchannel('A')
                im = im.convert('L').convert('RGBA')
                im.putalpha(a)
            if self.tint:
                arr = np.asarray(im).astype(np.float32)
                arr[..., :3] *= np.array(rgb(self.tint)) / 255.0
                im = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')
            pad = int((self.glow * 3 + self.shadow * 3) * ed.U) + 4
            c = Image.new('RGBA', (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
            c.alpha_composite(im, (pad, pad))
            if self.shadow:
                sh = Image.new('RGBA', c.size, (0, 0, 0, 0))
                sh.putalpha(c.getchannel('A').filter(ImageFilter.GaussianBlur(self.shadow * ed.U)).point(lambda v: int(v * 0.7)))
                base = Image.new('RGBA', c.size, (0, 0, 0, 0))
                base.alpha_composite(sh, (0, int(self.shadow * ed.U * 0.5)))
                c = Image.alpha_composite(base, c)
            self._cache = {'base': (ed.W, c)}
        c = self._cache['base'][1]
        if g > 0:
            c = _glow(c, g * ed.U, self.glow_color, 1.6)
        sp = Sprite(c, c.width / 2, c.height / 2, c.width, 0)
        self._cache[key] = sp
        return sp

    def draw(self, cv, t, ed):
        x, y, sc, al, bl, rot = self.state(t, ed)
        g = self.glow * (1 + self.glow_pulse * pulse(ed.beats.kicks, t)) if self.glow else 0
        paste(cv, self._img(ed, g), x, y, sc, al, bl, rot + self.spin * (t - self.t))


class Rect(El):
    """A filled box: pos = centre, w/h in design px. anim 'wipe' grows it from the left,
    'grow' from the centre; radius rounds the corners; outline draws only the border."""

    def __init__(self, t=0.0, pos=(0.5, 0.5), w=400, h=12, color='offwhite', radius=0, outline=0,
                 anim='wipe', anim_dur=0.25, **kw):
        super().__init__(t=t, pos=pos, anim=anim if anim not in ('wipe', 'grow') else 'none', **kw)
        self.kind, self.wipe_dur = anim, anim_dur
        self.w, self.h, self.color, self.radius, self.outline = w, h, color, radius, outline

    def draw(self, cv, t, ed):
        x, y, sc, al, bl, rot = self.state(t, ed)
        U = ed.U
        w, h = self.w * U * sc, self.h * U * sc
        x0 = x - w / 2
        if self.kind in ('wipe', 'grow'):
            p = ease((t - self.t) / self.wipe_dur)
            if self.kind == 'wipe':
                w *= p
            else:
                x0 = x - w * p / 2
                w *= p
        if w < 1 or al <= 0.01:
            return
        c = rgb(self.color, True)
        c = c[:3] + (int(c[3] * al),)
        layer = Image.new('RGBA', cv.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        box = [x0, y - h / 2, x0 + w, y + h / 2]
        if self.outline:
            d.rounded_rectangle(box, radius=self.radius * U, outline=c, width=max(1, int(self.outline * U)))
        else:
            d.rounded_rectangle(box, radius=self.radius * U, fill=c)
        cv.alpha_composite(layer)


class Custom(El):
    """fn(canvas, t, ed) draws anything with PIL (canvas is RGBA, ed.W x ed.H, ed.U = design px)."""

    def __init__(self, fn, t=0.0, out=None, layer=None):
        super().__init__(t=t, out=out, anim='none', layer=layer)
        self.fn = fn

    def draw(self, cv, t, ed):
        self.fn(cv, t, ed)


# ====================================================================== backgrounds
class Background:
    static = True

    def render(self, ed):
        raise NotImplementedError

    def get(self, t, ed, scene):
        k = (id(self), ed.W, ed.H)
        if k not in ed._bg_cache:
            ed._bg_cache[k] = self.render(ed).convert('RGBA')
        return ed._bg_cache[k].copy()


def _grid(ed):
    yy, xx = np.mgrid[0:ed.H, 0:ed.W].astype(np.float32)
    return xx, yy


class Solid(Background):
    def __init__(self, color='ink'):
        self.color = color

    def render(self, ed):
        return Image.new('RGB', (ed.W, ed.H), rgb(self.color))


class Gradient(Background):
    def __init__(self, top='#1b1b22', bottom='#050506'):
        self.top, self.bottom = top, bottom

    def render(self, ed):
        k = np.linspace(0, 1, ed.H, dtype=np.float32)[:, None, None]
        a = np.array(rgb(self.top), np.float32) * (1 - k) + np.array(rgb(self.bottom), np.float32) * k
        return Image.fromarray(np.broadcast_to(a, (ed.H, ed.W, 3)).astype(np.uint8))


class Radial(Background):
    def __init__(self, center='#262626', edge='#060607', cx=0.5, cy=0.5, radius=0.75):
        self.center, self.edge, self.cx, self.cy, self.radius = center, edge, cx, cy, radius

    def render(self, ed):
        xx, yy = _grid(ed)
        m = min(ed.W, ed.H)
        r = np.clip(np.hypot(xx - self.cx * ed.W, yy - self.cy * ed.H) / (self.radius * max(ed.W, ed.H)), 0, 1)[..., None]
        a = np.array(rgb(self.center), np.float32) * (1 - r) + np.array(rgb(self.edge), np.float32) * r
        return Image.fromarray(a.clip(0, 255).astype(np.uint8))


class Spotlight(Background):
    """Dark room with a soft cone of light from above (the 'motivational' look)."""

    def __init__(self, base='#242220', edge='#060607', light='#ffffff', strength=30, warmth=0.0):
        self.base, self.edge, self.light, self.strength, self.warmth = base, edge, light, strength, warmth

    def render(self, ed):
        xx, yy = _grid(ed)
        W, H = ed.W, ed.H
        m = max(W, H)
        r = np.clip(np.hypot(xx - W / 2, yy - H * 0.52) / (0.7 * m), 0, 1)[..., None]
        a = np.array(rgb(self.base), np.float32) * (1 - r) + np.array(rgb(self.edge), np.float32) * r
        hw = 0.075 * W + 0.42 * yy * (W / max(H, 1)) ** 0.3
        cone = (np.clip(1 - np.abs(xx - W / 2) / hw, 0, 1) ** 1.4 * (1 - 0.5 * yy / H))[..., None]
        a = a + cone * self.strength * np.array(rgb(self.light), np.float32) / 255.0
        if self.warmth:
            a = a + np.exp(-r ** 2 * 6) * np.array([34, 22, 6], np.float32) * self.warmth
        return Image.fromarray(a.clip(0, 255).astype(np.uint8))


class Paper(Background):
    def __init__(self, color='#E4E1DA', edge='#968F84'):
        self.color, self.edge = color, edge

    def render(self, ed):
        xx, yy = _grid(ed)
        r = np.clip(np.hypot(xx - ed.W / 2, yy - ed.H / 2) / (0.75 * max(ed.W, ed.H)), 0, 1)[..., None] * 0.9
        a = np.array(rgb(self.color), np.float32) * (1 - r) + np.array(rgb(self.edge), np.float32) * r
        rng = np.random.default_rng(3)
        a += rng.normal(0, 3, (ed.H, ed.W, 1)).astype(np.float32)
        return Image.fromarray(a.clip(0, 255).astype(np.uint8))


class Still(Background):
    """An image filling the frame (cover), optionally blurred and darkened."""

    def __init__(self, path, blur=0, darken=0.0, fit='cover'):
        self.path, self.blur, self.darken, self.fit = path, blur, darken, fit

    def render(self, ed):
        im = Image.open(self.path).convert('RGB')
        s = max(ed.W / im.width, ed.H / im.height) if self.fit == 'cover' else min(ed.W / im.width, ed.H / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        c = Image.new('RGB', (ed.W, ed.H), (0, 0, 0))
        c.paste(im, ((ed.W - im.width) // 2, (ed.H - im.height) // 2))
        if self.blur:
            c = c.filter(ImageFilter.GaussianBlur(self.blur * ed.U))
        if self.darken:
            c = Image.eval(c, lambda v: int(v * (1 - self.darken)))
        return c


class Clip(Background):
    """A video clip as the scene background.
    src = where to start in the clip (s), speed = playback speed (0.5 = slow-mo),
    fit = 'cover' (crop to fill), 'contain' (letterbox) or 'blur' (fit over a blurred copy:
    good for putting landscape footage in a vertical edit)."""
    static = False

    def __init__(self, path, src=0.0, speed=1.0, fit='cover', darken=0.0):
        if not os.path.isfile(path):
            raise SystemExit(f'Clip: file not found: {path}')
        self.path, self.src, self.speed, self.fit, self.darken = path, src, speed, fit, darken
        self._proc = None
        self._idx = -1
        self._last = None
        self._t0 = None
        self._size = None

    def duration(self):
        return probe(self.path)['duration'] or 0.0

    def _filters(self, W, H, fps):
        sp = f'setpts=PTS/{self.speed},' if self.speed != 1 else ''
        if self.fit == 'contain':
            return f'{sp}fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1'
        if self.fit == 'blur':
            return (f'{sp}fps={fps},split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},'
                    f'boxblur=20:2,eq=brightness=-0.08[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];'
                    f'[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1')
        return f'{sp}fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1'

    def _open(self, idx, ed):
        self.close()
        ss = self.src + idx / ed.fps * self.speed
        cmd = [ffmpeg_exe(), '-v', 'error', '-ss', f'{max(0, ss):.4f}', '-i', self.path, '-an',
               '-filter_complex' if self.fit == 'blur' else '-vf', self._filters(ed.W, ed.H, ed.fps),
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=ed.W * ed.H * 3 * 2)
        self._idx = idx - 1
        self._size = (ed.W, ed.H)

    def _read(self, ed):
        n = ed.W * ed.H * 3
        buf = self._proc.stdout.read(n) if self._proc else b''
        self._idx += 1
        if len(buf) == n:
            self._last = buf

    def get(self, t, ed, scene):
        idx = max(0, int(round((t - scene.t0) * ed.fps)))
        if self._proc is None or idx < self._idx or self._size != (ed.W, ed.H) or idx - self._idx > ed.fps * 3:
            self._open(idx, ed)
        while self._idx < idx:
            self._read(ed)
        if self._last is None:
            im = Image.new('RGB', (ed.W, ed.H), (0, 0, 0))
        else:
            im = Image.frombuffer('RGB', (ed.W, ed.H), self._last)
        if self.darken:
            im = Image.eval(im, lambda v: int(v * (1 - self.darken)))
        ed._open_clips.add(self)
        return im.convert('RGBA')

    def close(self):
        if self._proc:
            try:
                self._proc.stdout.close()
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        self._idx = -1


BG_PRESETS = {
    'black': lambda: Solid('#050505'), 'ink': lambda: Solid('ink'), 'white': lambda: Solid('#F4F2EE'),
    'spotlight': lambda: Spotlight(), 'gold': lambda: Spotlight(base='#2a2216', light='#ffcf66', strength=70, warmth=1.0),
    'paper': lambda: Paper(), 'radial': lambda: Radial(), 'night': lambda: Gradient('#0d1426', '#020308'),
    'blood': lambda: Radial('#3a0a10', '#070102'), 'neon': lambda: Radial('#1a0b2e', '#030106'),
}


def as_bg(bg):
    if isinstance(bg, Background):
        return bg
    if isinstance(bg, str) and bg in BG_PRESETS:
        return BG_PRESETS[bg]()
    if isinstance(bg, str) and os.path.isfile(bg):
        ext = os.path.splitext(bg)[1].lower()
        return Clip(bg) if ext in ('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v') else Still(bg)
    return Solid(bg)


# ====================================================================== beat map
class BeatMap:
    def __init__(self, d):
        self.d = d
        self.beats = d['beats']
        self.downbeats = d['downbeats']
        self.kicks = d['kicks']
        self.snares = d['snares']
        self.hits = d['hits']
        self.bpm = d['bpm']
        self.period = d['period']
        self.bpb = d['beats_per_bar']
        self.fdi = d['first_downbeat_index']
        self.drops = [x['t'] for x in d.get('drops', [])]
        self.bars = d.get('bars', [])
        self.duration = d['duration']

    def beat(self, x):
        """Time of beat x (0 = first beat in the edit; fractions interpolate, e.g. 4.5)."""
        i = int(math.floor(x))
        f = x - i
        n = len(self.beats)
        if 0 <= i < n - 1:
            return self.beats[i] + (self.beats[i + 1] - self.beats[i]) * f
        if i < 0:
            return self.beats[0] + x * self.period
        return self.beats[-1] + (x - (n - 1)) * self.period

    def bar(self, i, beat=0.0):
        """Time of bar i (+ `beat` beats into it). Bar 0 starts at the first downbeat."""
        return self.beat(self.fdi + i * self.bpb + beat)

    @property
    def nbars(self):
        return len(self.downbeats)

    @property
    def drop(self):
        return self.drops[0] if self.drops else None

    def events(self, kind):
        if isinstance(kind, (list, tuple)):
            return kind
        return {'kicks': self.kicks, 'beats': self.beats, 'downbeats': self.downbeats, 'bars': self.downbeats,
                'snares': self.snares, 'hits': self.hits, None: [], 'none': []}[kind]

    def between(self, kind, t0, t1):
        ev = self.events(kind)
        return [t for t in ev if t0 - 1e-6 <= t < t1 - 1e-6]

    def snap(self, t, kind='beats'):
        ev = self.events(kind)
        return min(ev, key=lambda v: abs(v - t)) if ev else t

    def position(self, t):
        """Fractional beat index of time t (inverse of beat())."""
        b = self.beats
        if t <= b[0]:
            return (t - b[0]) / self.period
        if t >= b[-1]:
            return len(b) - 1 + (t - b[-1]) / self.period
        i = bisect.bisect_right(b, t) - 1
        return i + (t - b[i]) / (b[i + 1] - b[i])

    def label(self, t):
        """'bar 3 beat 2' when t is on a beat (within 15 ms), else 'bar 3 beat 2.4'."""
        x = self.position(t) - self.fdi
        bar_i = int(math.floor(x / self.bpb))
        beat = x - bar_i * self.bpb
        r = round(beat)
        if abs(beat - r) * self.period < 0.015:
            if r == self.bpb:
                bar_i, r = bar_i + 1, 0
            return f'bar {bar_i} beat {r}'
        return f'bar {bar_i} beat {beat:.1f}'


# ====================================================================== scenes + edit
class Scene:
    """A stretch of the edit with one background. Usually one bar or a few beats long.

    camera   slow push-in per second (0.012 = 1.2%/s), negative pulls out
    punch    events that kick the camera: 'kicks', 'beats', 'downbeats', 'snares', a list, or None
    intro    how the scene arrives: flash, blur, zoom, whip, glitch, fade, cut
    grade    None or any of: bw, warm, cool, punchy, faded, teal (string or list)
    glitch   times to glitch inside the scene; flash = extra white flashes"""

    def __init__(self, ed, t0, t1, bg='spotlight', camera=0.012, punch='kicks', punch_amount=0.03,
                 shake=6, intro='flash', intro_dur=None, grade=None, glitch=(), flash=(), chroma=None):
        self.ed, self.t0, self.t1 = ed, t0, t1
        self.bg = as_bg(bg)
        self.camera, self.punch, self.punch_amount, self.shake = camera, punch, punch_amount, shake
        self.intro, self.intro_dur, self.grade = intro, intro_dur, grade
        self.glitch, self.flash, self.chroma = list(glitch), list(flash), chroma
        self.els = []

    def add(self, *items):
        for it in items:
            if isinstance(it, (list, tuple)):
                self.add(*it)
            else:
                if isinstance(it, El) and it.out is None:
                    it.out = None  # lives until the scene ends
                self.els.append(it)
        return self

    @property
    def length(self):
        return self.t1 - self.t0


def _grade(a, g):
    if not g:
        return a
    for k in ([g] if isinstance(g, str) else g):
        if k == 'bw':
            l = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
            l = (l - 128) * 1.15 + 128
            a = np.repeat(l[..., None], 3, 2)
        elif k == 'warm':
            a = a * np.array([1.07, 1.0, 0.86], np.float32)
        elif k == 'cool':
            a = a * np.array([0.9, 0.98, 1.1], np.float32)
        elif k == 'punchy':
            l = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114)[..., None]
            a = (l + (a - l) * 1.25 - 128) * 1.12 + 128
        elif k == 'faded':
            a = a * 0.86 + 20
        elif k == 'teal':
            l = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114)[..., None] / 255.0
            a = a + (l - 0.5) * np.array([36, 6, -30], np.float32)
        elif k == 'dark':
            a = a * 0.7
    return a


class Edit:
    def __init__(self, song, beats=None, size=(1080, 1920), fps=30, start=None, duration=None,
                 grain=5.0, vignette=0.4, fade_in=0.2, fade_out=0.6, chroma=0.0, letterbox=0.0,
                 look=None, out=None, bpm=None, downbeat=None, lead=0.0):
        """song: audio file. beats: beats.json path (made if missing; defaults to <script dir>/beats.json).
        start/duration pick the part of the song to use (only when making beats.json).
        grain (0-12), vignette (0-1), chroma (px of RGB split on punches), letterbox (0-0.2),
        look = global grade applied to every scene (same names as Scene grade).
        lead = seconds the picture runs ahead of the music: every cut, word and flash lands this
        much before its beat. Many editors cut 1-2 frames early (0.03-0.07) because it feels more
        on the beat; analyze_ref.py measures it on a reference. Default 0 (exactly on the beat)."""
        self.script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else os.path.abspath('edit.py')
        self.dir = os.path.dirname(self.script)
        self.song = song if os.path.isabs(song) else os.path.join(self.dir, song)
        mode = sys.argv[1] if len(sys.argv) > 1 else 'render'
        self.mode = mode
        self.preview = mode == 'preview' or (mode == '_part' and '--preview' in sys.argv)
        scale = 0.5 if (self.preview or mode in ('sheet', 'stills')) and '--full' not in sys.argv else 1.0
        self.full_size = size
        self.W = int(size[0] * scale) // 2 * 2
        self.H = int(size[1] * scale) // 2 * 2
        self.fps = 15 if self.preview else fps
        self.U = min(self.W, self.H) / 1080.0
        bp = beats or os.path.join(self.dir, 'beats.json')
        if not os.path.isabs(bp):
            bp = os.path.join(self.dir, bp)
        if not os.path.exists(bp):
            import beats as _beats
            end = (start or 0) + duration if duration else None
            an = _beats.analyze(self.song, start or 0.0, end, bpm=bpm, downbeat=downbeat)
            with open(bp, 'w') as f:
                json.dump(an, f, indent=1)
            print('[onbeat] analysed beats ->', bp)
            print(_beats.summary(an))
        with open(bp) as f:
            self.beats = BeatMap(json.load(f))
        self.start = self.beats.d.get('start', 0.0) if start is None else start
        self.duration = duration or self.beats.duration
        self.grain, self.vignette, self.fade_in, self.fade_out = grain, vignette, fade_in, fade_out
        self.chroma, self.letterbox, self.look = chroma, letterbox, look
        self.lead = float(lead or 0.0)
        self.out = out or os.path.splitext(os.path.basename(self.script))[0] + '.mp4'
        self.scenes = []
        self.overlays = []
        self.flashes, self.glitches, self.shakes = [], [], []
        self._bg_cache = {}
        self._open_clips = set()
        self._cur_scene = None
        self._vig = None
        self._grain = None

    # ---------------------------------------------------------------- building
    def scene(self, t0, t1, **kw):
        s = Scene(self, t0, t1, **kw)
        self.scenes.append(s)
        self.scenes.sort(key=lambda x: x.t0)
        return s

    def overlay(self, *els):
        """Elements drawn on top of every scene, after the camera move (watermarks, captions)."""
        self.overlays.extend(els)

    def flash(self, t, strength=0.6, dur=0.22):
        self.flashes.append((t, strength, dur))

    def glitch(self, t, dur=0.14, amount=1.0):
        self.glitches.append((t, dur, amount))

    def shake(self, t, amount=1.0, dur=0.35):
        self.shakes.append((t, amount, dur))

    def montage(self, clips, cuts, src=None, speed=1.0, fit='cover', order='sequential', seed=0, **scene_kw):
        """Cut footage on the beat. clips: folder or list of video files. cuts: times where a new
        shot starts (the last time ends the montage), e.g. ed.beats.between('downbeats', 0, 20) + [20].
        src: list of in-points, or None to walk through each clip without repeating footage.
        Returns the scenes so you can add text to them."""
        if isinstance(clips, str):
            d = clips if os.path.isabs(clips) else os.path.join(self.dir, clips)
            if os.path.isdir(d):
                clips = sorted(os.path.join(d, f) for f in os.listdir(d)
                               if f.lower().endswith(('.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi')))
            elif os.path.isfile(d):
                clips = [d]
            else:
                raise SystemExit(f'montage: clip folder not found: {d}')
        clips = [c if os.path.isabs(c) else os.path.join(self.dir, c) for c in clips]
        if not clips:
            raise SystemExit('montage: no clips found')
        durs = {c: (probe(c)['duration'] or 0.0) for c in clips}
        pos = {c: durs[c] * 0.08 for c in clips}
        rng = np.random.default_rng(seed)
        out = []
        for i in range(len(cuts) - 1):
            c = clips[i % len(clips)] if order == 'sequential' else clips[int(rng.integers(len(clips)))]
            seg = (cuts[i + 1] - cuts[i]) * speed
            if src is not None:
                s0 = src[i]
            else:
                if pos[c] + seg > durs[c] - 0.05:
                    pos[c] = durs[c] * 0.04
                s0 = pos[c]
                pos[c] += seg + 0.4
            out.append(self.scene(cuts[i], cuts[i + 1], bg=Clip(c, src=s0, speed=speed, fit=fit), **scene_kw))
        return out

    # ---------------------------------------------------------------- rendering
    def scene_at(self, t):
        s = None
        for sc in self.scenes:
            if sc.t0 <= t + 1e-6:
                s = sc
            else:
                break
        return s

    def _fx_tables(self):
        if self._vig is None:
            yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
            r = np.hypot((xx - self.W / 2) / (0.5 * self.W), (yy - self.H / 2) / (0.5 * self.H)) / 1.414
            self._vig = (1 - self.vignette * np.clip((r - 0.35) / 0.65, 0, 1) ** 1.5).astype(np.float32)[..., None]
            rng = np.random.default_rng(1)
            h2, w2 = (self.H + 1) // 2, (self.W + 1) // 2
            self._grain = [np.kron(rng.normal(0, 1, (h2, w2)), np.ones((2, 2)))[:self.H, :self.W].astype(np.float32)[..., None] * self.grain
                           for _ in range(8)]

    def frame(self, t):
        # a frame shows what happens nearest to it: events up to half a frame later count,
        # so cuts and hits are never more than half a frame off at any fps
        t = t + 0.5 / self.fps + self.lead
        s = self.scene_at(t)
        if s is not self._cur_scene:
            for c in list(self._open_clips):
                if s is None or c is not s.bg:
                    c.close()
                    self._open_clips.discard(c)
            self._cur_scene = s
        if s is None:
            return np.zeros((self.H, self.W, 3), np.uint8)
        cv = s.bg.get(t, self, s)
        for el in sorted(s.els, key=lambda e: e.layer):
            if el.visible(t):
                el.draw(cv, t, self)
        im = cv.convert('RGB')
        lt = t - s.t0
        # camera: push + punches + shake
        k = pulse(self.beats.events(s.punch), t) if s.punch else 0.0
        z = max(0.2, 1 + s.camera * lt + s.punch_amount * k)
        sh = s.shake * k
        for (ts, amt, dur) in self.shakes:
            if ts <= t < ts + dur:
                q = 1 - (t - ts) / dur
                sh += 18 * amt * q * q
                z += 0.02 * amt * q
        intro = s.intro
        idur = s.intro_dur or {'flash': 0.22, 'blur': 0.15, 'zoom': 0.22, 'whip': 0.16, 'glitch': 0.16,
                               'fade': 0.3}.get(intro, 0)
        ip = lt / idur if idur else 1.0
        if intro == 'zoom' and ip < 1:
            z *= 1 + 0.14 * (1 - ease(ip))
        dx = sh * self.U * math.sin(t * 93.1)
        dy = sh * self.U * math.cos(t * 71.7)
        if intro == 'whip' and ip < 1:
            dx += (1 - ease(ip)) * 0.35 * self.W
        if abs(z - 1) > 1e-4 or abs(dx) > 0.3 or abs(dy) > 0.3:
            w, h = self.W / z, self.H / z
            x0, y0 = self.W / 2 + dx - w / 2, self.H / 2 + dy - h / 2
            if intro == 'whip' and ip < 1:  # wrap so there is no empty edge
                im = Image.fromarray(np.roll(np.asarray(im), int(dx), axis=1))
                x0 -= dx
            im = im.resize((self.W, self.H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))
        if intro in ('flash', 'blur', 'zoom') and lt < 0.12:
            im = im.filter(ImageFilter.GaussianBlur(9 * self.U * 2 * (1 - lt / 0.12)))
        if intro == 'whip' and ip < 1:
            kx = int(2 + 40 * (1 - ip))
            im = im.resize((max(1, self.W // kx), self.H), Image.BILINEAR).resize((self.W, self.H), Image.BILINEAR)
        if self.overlays:
            cv2 = im.convert('RGBA')
            for el in sorted(self.overlays, key=lambda e: e.layer):
                if el.visible(t):
                    el.draw(cv2, t, self)
            im = cv2.convert('RGB')
        a = np.asarray(im, dtype=np.float32)
        # glitch
        g_amt = 0.0
        for gt in s.glitch:
            if gt <= t < gt + 0.14:
                g_amt = max(g_amt, 1.0)
        for (gt, gd, ga) in self.glitches:
            if gt <= t < gt + gd:
                g_amt = max(g_amt, ga)
        if intro == 'glitch' and ip < 1:
            g_amt = max(g_amt, 1.0)
        if g_amt:
            a = self._glitch(a, t, g_amt)
        a = _grade(a, s.grade)
        a = _grade(a, self.look)
        chroma = s.chroma if s.chroma is not None else self.chroma
        if chroma and k > 0.05:
            o = int(chroma * self.U * k)
            if o:
                a[..., 0] = np.roll(a[..., 0], o, axis=1)
                a[..., 2] = np.roll(a[..., 2], -o, axis=1)
        self._fx_tables()
        if self.vignette:
            a *= self._vig
        # flashes
        f = 0.0
        if intro == 'flash' and lt < 0.22:
            f = 0.5 * (1 - lt / 0.22) ** 2
        for ft in s.flash:
            if ft <= t < ft + 0.22:
                f = max(f, 0.55 * (1 - (t - ft) / 0.22) ** 2)
        for (ft, st, du) in self.flashes:
            if ft <= t < ft + du:
                f = max(f, st * (1 - (t - ft) / du) ** 2)
        if f:
            a = a * (1 - f) + 255 * f
        if self.grain:
            a += self._grain[int(t * self.fps) % 8]
        if self.letterbox:
            b = int(self.H * self.letterbox / 2)
            a[:b] = 0
            a[self.H - b:] = 0
        if intro == 'fade' and ip < 1:
            a *= ease(ip)
        if self.fade_in and t < self.fade_in:
            a *= t / self.fade_in
        if self.fade_out and t > self.duration - self.fade_out:
            a *= max(0.0, (self.duration - t) / self.fade_out)
        return np.clip(a, 0, 255).astype(np.uint8)

    def _glitch(self, a, t, amt):
        rng = np.random.default_rng(int(t * 1000))
        out = a.copy()
        H, W = self.H, self.W
        for _ in range(int(6 + 8 * amt)):
            y0 = int(rng.integers(0, H))
            hh = int(rng.integers(max(2, H // 80), max(3, H // 12)))
            sh = int(rng.normal(0, 0.06 * W * amt))
            out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], sh, axis=1)
        o = int(10 * self.U * amt)
        out[..., 0] = np.roll(out[..., 0], o, axis=1)
        out[..., 2] = np.roll(out[..., 2], -o, axis=1)
        return out

    def _encode(self, a, b, path, progress=True):
        """Render frames a..b-1 to a video-only file."""
        enc = ['-c:v', 'libx264', '-preset', 'veryfast' if self.preview else 'medium',
               '-crf', '24' if self.preview else '18', '-maxrate', '5M' if self.preview else '12M',
               '-bufsize', '12M', '-pix_fmt', 'yuv420p']
        cmd = [ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{self.W}x{self.H}', '-r', str(self.fps), '-i', '-'] + enc + [path]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = _time.time()
        for fi in range(a, b):
            p.stdin.write(self.frame(fi / self.fps).tobytes())
            done = fi - a + 1
            if progress and done % (self.fps * 4) == 0:
                el = _time.time() - t0
                print(f'  {done}/{b - a} frames  ({el:.0f}s, ~{el / done * (b - a - done):.0f}s left)', flush=True)
        p.stdin.close()
        p.wait()
        for c in list(self._open_clips):
            c.close()
        if p.returncode:
            raise SystemExit(f'ffmpeg failed writing {path}')

    def render(self, out=None, workers=None):
        """Render the edit with the song. Frames are split across worker processes
        (ONBEAT_WORKERS=1 to disable) and the parts joined without re-encoding."""
        out = out or self.out
        if not os.path.isabs(out):
            out = os.path.join(self.dir, out)
        n = int(round(self.duration * self.fps))
        workers = workers or int(os.environ.get('ONBEAT_WORKERS', 0) or 0) or max(1, min(8, (os.cpu_count() or 2) // 2))
        if n < self.fps * 6:
            workers = 1
        tmp = os.path.join(self.dir, '.onbeat_parts')
        os.makedirs(tmp, exist_ok=True)
        bounds = [int(round(n * k / workers)) for k in range(workers + 1)]
        parts = [os.path.join(tmp, f'part{k:02d}.mp4') for k in range(workers)]
        t0 = _time.time()
        print(f'[onbeat] rendering {n} frames at {self.W}x{self.H} {self.fps}fps with {workers} worker(s)', flush=True)
        if workers == 1:
            self._encode(0, n, parts[0])
        else:
            procs = []
            for k in range(workers):
                cmd = [sys.executable, self.script, '_part', str(bounds[k]), str(bounds[k + 1]), parts[k]]
                cmd += ['--preview'] if self.preview else []
                cmd += ['--quiet'] if k else []
                procs.append(subprocess.Popen(cmd))
            codes = [p.wait() for p in procs]
            if any(codes):
                raise SystemExit(f'a render worker failed (exit codes {codes}); try ONBEAT_WORKERS=1 to see the error')
        lst = os.path.join(tmp, 'parts.txt')
        with open(lst, 'w') as f:
            for p in parts:
                safe = p.replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        cmd = [ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst,
               '-ss', f'{self.start:.4f}', '-t', f'{self.duration:.4f}', '-i', self.song,
               '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-t', f'{self.duration:.4f}']
        if self.fade_out:
            cmd += ['-af', f'afade=t=out:st={max(0, self.duration - self.fade_out):.3f}:d={self.fade_out:.3f}']
        cmd += ['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out]
        r = subprocess.run(cmd)
        for p in parts + [lst]:
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
        if r.returncode:
            raise SystemExit('ffmpeg failed joining the parts')
        print(f'[onbeat] wrote {out}  ({self.W}x{self.H} {self.fps}fps, {self.duration:.2f}s, '
              f'rendered in {_time.time() - t0:.0f}s)')
        return out

    def still(self, t, path):
        """Save one frame (full size unless running in sheet/stills/preview mode)."""
        p = path if os.path.isabs(path) else os.path.join(self.dir, path)
        Image.fromarray(self.frame(t)).save(p)
        return p

    def stills(self, times, folder='stills'):
        folder = os.path.join(self.dir, folder)
        os.makedirs(folder, exist_ok=True)
        paths = []
        for t in times:
            p = os.path.join(folder, f't{t:07.3f}.png')
            Image.fromarray(self.frame(t)).save(p)
            paths.append(p)
        print('[onbeat] wrote', len(paths), 'stills to', folder)
        return paths

    def auto_times(self):
        """Frames worth checking: each scene just after it lands, after its last element
        finishes animating, and just before it ends."""
        ts = []
        for i, s in enumerate(self.scenes):
            t1 = s.t1
            if s.intro not in ('cut', None):
                ts.append(min(t1 - 0.02, s.t0 + 0.06))
            starts = sorted(set([e.t for e in s.els if e.t < t1] + [e.t_last for e in s.els if e.t_last < t1]))
            if len(starts) > 2:  # a frame between reveals too, for lines that build up
                mid = starts[len(starts) // 2]
                ts.append(min(t1 - 0.02, mid + 0.25))
            last = max(starts + [s.t0])
            ts.append(min(t1 - 0.02, max(s.t0 + 0.25, last + 0.3)))
        return sorted(set(round(t, 3) for t in ts if 0 <= t < self.duration))

    def sheet(self, times=None, path='sheet.png', cols=None, thumb=300):
        times = times or self.auto_times()
        frames = [Image.fromarray(self.frame(t)) for t in times]
        labels = []
        for t in times:
            si = next((i for i, s in enumerate(self.scenes) if s.t0 <= t < s.t1), -1)
            labels.append(f'{t:.2f}s  scene {si}  {self.beats.label(t)}')
        p = path if os.path.isabs(path) else os.path.join(self.dir, path)
        contact_sheet(frames, labels, p, cols=cols, thumb=thumb)
        print('[onbeat] wrote', p, f'({len(times)} frames)')
        return p

    def timeline(self):
        B = self.beats
        print(f'{B.bpm} BPM, {len(self.scenes)} scenes, {self.duration:.2f}s, {self.full_size[0]}x{self.full_size[1]}')
        prev = None
        for i, s in enumerate(self.scenes):
            gap = '' if prev is None or abs(prev - s.t0) < 0.02 else f'  !! gap/overlap {s.t0 - prev:+.2f}s'
            beats = s.length / B.period
            print(f'[{i:2}] {s.t0:6.2f}-{s.t1:6.2f}s  {beats:4.1f} beats  {B.label(s.t0)}  '
                  f'bg={type(s.bg).__name__} intro={s.intro}{gap}')
            for e in sorted(s.els, key=lambda e: e.t):
                if isinstance(e, Words):
                    for w, tt, _ in e.items:
                        print(f'        {tt:6.2f}s  {B.label(tt):24}  word "{w}"')
                else:
                    desc = getattr(e, 'text', None) or os.path.basename(str(getattr(e, 'path', ''))) or type(e).__name__
                    print(f'        {e.t:6.2f}s  {B.label(e.t):24}  {type(e).__name__} "{desc}"')
            prev = s.t1
        if self.scenes and self.scenes[-1].t1 < self.duration - 0.05:
            print(f'  !! last scene ends at {self.scenes[-1].t1:.2f}s but the edit runs to {self.duration:.2f}s')

    def run(self):
        """python edit.py render [out.mp4] | preview | sheet [t ...] | stills t [t ...] | timeline
        (preview = half size at 15 fps; sheet/stills are half size unless --full)."""
        args = [a for a in sys.argv[1:] if not a.startswith('--')]
        mode = args[0] if args else 'render'
        rest = args[1:]
        if mode == 'render':
            return self.render(rest[0] if rest else None)
        if mode == 'preview':
            return self.render(rest[0] if rest else os.path.splitext(self.out)[0] + '_preview.mp4')
        if mode == 'stills':
            return self.stills([float(x) for x in rest] or self.auto_times())
        if mode == 'sheet':
            return self.sheet([float(x) for x in rest] or None)
        if mode == 'timeline':
            return self.timeline()
        if mode == '_part':  # internal: one render worker
            return self._encode(int(rest[0]), int(rest[1]), rest[2], progress='--quiet' not in sys.argv)
        print(self.run.__doc__)


# ====================================================================== contact sheets
def contact_sheet(images, labels, out, cols=None, thumb=300, title=None):
    """Tile images (PIL or paths) with a label under each, for checking frames at a glance."""
    ims = [Image.open(i).convert('RGB') if isinstance(i, str) else i.convert('RGB') for i in images]
    if not ims:
        return
    cols = cols or min(len(ims), 6 if ims[0].height > ims[0].width else 4)
    tw = thumb
    th = int(ims[0].height * tw / ims[0].width)
    lab = 28
    top = 34 if title else 0
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new('RGB', (cols * (tw + 8) + 8, top + rows * (th + lab + 8) + 8), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    f = font('sans', 15)
    if title:
        d.text((10, 8), title, fill=(235, 235, 235), font=font('bold', 18))
    for i, (im, l) in enumerate(zip(ims, labels)):
        r, c = divmod(i, cols)
        x, y = 8 + c * (tw + 8), top + 8 + r * (th + lab + 8)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 2, y + th + 5), str(l)[:48], fill=(210, 210, 210), font=f)
    sheet.save(out)
    return out


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description='onbeat engine tools')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('fonts', help='show which font each role resolves to, and all installed fonts')
    c = sub.add_parser('compare', help='put style-option stills side by side')
    c.add_argument('out')
    c.add_argument('images', nargs='+')
    c.add_argument('--labels', nargs='*')
    c.add_argument('--title')
    c.add_argument('--thumb', type=int, default=360)
    a = ap.parse_args()
    if a.cmd == 'fonts':
        roles, files = list_fonts()
        for k, v in roles.items():
            print(f'{k:13} -> {v}')
        print(f'\n{len(files)} font files installed:')
        print(', '.join(files))
    elif a.cmd == 'compare':
        labels = a.labels or [os.path.basename(p) for p in a.images]
        contact_sheet(a.images, labels, a.out, cols=len(a.images) if len(a.images) <= 4 else None,
                      thumb=a.thumb, title=a.title)
        print('wrote', a.out)
    else:
        ap.print_help()


if __name__ == '__main__':
    _cli()
