"""Shared helpers: finding ffmpeg, decoding audio, probing media."""
import os
import re
import shutil
import subprocess

import numpy as np


def ffmpeg_exe():
    p = os.environ.get('ONBEAT_FFMPEG') or shutil.which('ffmpeg')
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit('ffmpeg not found. Install ffmpeg, or run: pip install imageio-ffmpeg')


def load_audio(path, sr=22050, start=0.0, duration=None, channels=1):
    """Decode any audio/video file to float32 samples with ffmpeg."""
    cmd = [ffmpeg_exe(), '-v', 'error']
    if start and start > 0:
        cmd += ['-ss', f'{start:.4f}']
    cmd += ['-i', str(path)]
    if duration:
        cmd += ['-t', f'{duration:.4f}']
    cmd += ['-vn', '-ac', str(channels), '-ar', str(sr), '-f', 'f32le', '-']
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f'ffmpeg could not decode {path}:\n{r.stderr.decode(errors="replace")[-800:]}')
    y = np.frombuffer(r.stdout, np.float32).copy()
    if channels > 1:
        y = y.reshape(-1, channels)
    return y, sr


def probe(path):
    """Duration, size, fps and whether there is audio, parsed from `ffmpeg -i`."""
    r = subprocess.run([ffmpeg_exe(), '-hide_banner', '-i', str(path)], capture_output=True)
    s = r.stderr.decode(errors='replace')
    info = {'duration': None, 'width': None, 'height': None, 'fps': None, 'has_audio': False, 'has_video': False}
    m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', s)
    if m:
        info['duration'] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    for line in s.splitlines():
        if 'Stream #' in line and 'Video:' in line and not info['has_video']:
            if 'attached pic' in line:
                continue
            info['has_video'] = True
            m = re.search(r', (\d{2,5})x(\d{2,5})', line)
            if m:
                info['width'], info['height'] = int(m[1]), int(m[2])
            m = re.search(r'([\d.]+) fps', line) or re.search(r'([\d.]+) tbr', line)
            if m:
                info['fps'] = float(m[1])
        if 'Stream #' in line and 'Audio:' in line:
            info['has_audio'] = True
    return info


def write_wav(path, y, sr):
    import wave
    y = np.asarray(y, np.float32)
    if y.ndim == 1:
        y = y[:, None]
    pcm = (np.clip(y, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
