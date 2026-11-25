"""Self-test for analyze_ref.py: render a small edit that cuts on every beat of the demo song,
once exactly on the beat and once with the picture 50 ms early (Edit lead=0.05), and check
that the analysis finds every cut on the beat and measures the early cut.

    python tests/test_ref.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')

EDIT = r'''
import os, sys
sys.path.insert(0, {scripts!r})
from engine import *
ed = Edit('song.wav', size=(270, 480), grain=0, vignette=0, fade_in=0, fade_out=0, lead={lead})
B = ed.beats
cols = ['red', 'gold', 'white', 'black', '#2050ff', '#20c060']
ed.scene(0, B.beat(4), bg='ink', punch=None, camera=0, intro='cut')
for i in range(4, 40):
    ed.scene(B.beat(i), B.beat(i + 1), bg=cols[i % len(cols)], punch=None, camera=0, intro='cut')
ed.run()
'''


def main():
    sys.path.insert(0, SCRIPTS)
    import common
    import demo_song
    ok = True

    def check(name, cond, detail):
        nonlocal ok
        print(('PASS ' if cond else 'FAIL ') + name + ': ' + detail)
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as d:
        audio = demo_song.build()
        audio = audio[: int(demo_song.SR * 22)]  # the first 22 s is enough
        for lead in (0.0, 0.05):
            sub = os.path.join(d, f'lead{lead}')
            os.makedirs(sub)
            common.write_wav(os.path.join(sub, 'song.wav'), audio, demo_song.SR)
            with open(os.path.join(sub, 'edit.py'), 'w') as f:
                f.write(EDIT.format(scripts=SCRIPTS, lead=lead))
            r = subprocess.run([sys.executable, 'edit.py', 'render'], cwd=sub, capture_output=True, text=True)
            if r.returncode:
                print(r.stdout[-2000:], r.stderr[-2000:])
                check(f'render lead={lead}', False, 'render failed')
                continue
            out = os.path.join(sub, 'ref')
            subprocess.run([sys.executable, os.path.join(SCRIPTS, 'analyze_ref.py'), os.path.join(sub, 'edit.mp4'),
                            '--out', out, '--thumb', '120'], capture_output=True, check=True)
            rep = json.load(open(os.path.join(out, 'report.json')))
            check(f'cuts found (lead={lead})', len(rep['cuts']) >= 34, f"{len(rep['cuts'])} cuts (expected 36)")
            check(f'cuts on the beat (lead={lead})', rep['cuts_on_beat'] >= 0.97, f"{rep['cuts_on_beat']:.0%}")
            ct = rep.get('cut_timing')
            if lead:
                check('early cut measured', ct is not None and abs(-ct['offset_ms'] - 50) <= 12,
                      f"{ct['offset_ms'] if ct else None} ms (expected -50)")
            else:
                check('no false early cut', ct is None, f'{ct}')
    print('all passed' if ok else 'SOME CHECKS FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
