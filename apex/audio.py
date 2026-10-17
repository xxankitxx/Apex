"""
Audio alerts — the same scheme as MYTHOS and VAJRA, played from the ENGINE on
the PC speaker (the browser also beeps, but a browser tab can be muted or
hidden; these cannot).

Sounds:
  armed  — the Triangle is closing (all three corners past 80 %): look up
  entry  — a paper BUY was placed
  win    — a paper trade closed in profit
  loss   — a paper trade closed at a loss
  learn  — the after-close learning step changed something

Files: assets/alert_<kind>.mp3 in this repo; if absent, the MYTHOS files in
D:\\ClaudeCode\\mythos\\assets are used; if those are absent too, a synthesised
tone is played. Audio starts UNMUTED (owner asked for sound).  Set
config.AUDIO = False to silence it.
"""
import math
import os
import struct
import threading

from . import config

ASSETS = [os.path.join(config.ROOT, "assets"),
          os.path.join(os.path.dirname(config.ROOT), "ClaudeCode", "mythos", "assets"),
          r"D:\ClaudeCode\mythos\assets"]
NAMES = {"armed": "alert_armed.mp3", "entry": "alert_entry.mp3", "win": "alert_win.mp3",
         "loss": "alert_loss.mp3", "learn": "alert_commentary.mp3"}
TONES = {"armed": (660, 2600, 0.75), "entry": (1000, 600, 0.90), "win": (880, 500, 0.85),
         "loss": (330, 700, 0.95), "learn": (1320, 320, 0.60)}

_ready = False
_sounds = {}
_lock = threading.Lock()
_last = {}


def _tone(freq, ms, vol):
    sr = 22050
    n = int(sr * ms / 1000)
    buf = bytearray(n * 2)
    for i in range(n):
        fade = 1.0 - (i / n) ** 0.3
        v = int(32767 * vol * fade * math.sin(2 * math.pi * freq * i / sr))
        struct.pack_into("<h", buf, i * 2, max(-32767, min(32767, v)))
    return bytes(buf)


def _chime(vol=0.75):
    sr = 22050
    notes = [(660.0, 1.2), (880.0, 1.4)]
    total = int(sr * sum(d for _, d in notes))
    buf = bytearray(total * 2)
    pos = 0
    for f, dur in notes:
        n = int(sr * dur)
        for i in range(n):
            t = i / sr
            env = min(1.0, t / 0.04) * (1.0 - i / n) ** 1.4
            s = math.sin(2 * math.pi * f * t) + 0.35 * math.sin(4 * math.pi * f * t)
            struct.pack_into("<h", buf, (pos + i) * 2, max(-32767, min(32767, int(32767 * vol * env * s / 1.35))))
        pos += n
    return bytes(buf)


def init(log=print):
    """Returns a one-line description of what will play, or None if audio is off."""
    global _ready
    if not getattr(config, "AUDIO", True):
        return None
    try:
        import pygame
        pygame.mixer.pre_init(22050, -16, 1, 2048)
        pygame.mixer.init()
        if not pygame.mixer.get_init():
            return None
        src = {}
        for kind, fname in NAMES.items():
            path = next((os.path.join(d, fname) for d in ASSETS if os.path.exists(os.path.join(d, fname))), None)
            if path:
                _sounds[kind] = path
                src[kind] = os.path.basename(os.path.dirname(path)) + "/" + fname
            else:
                f, ms, vol = TONES[kind]
                snd = pygame.mixer.Sound(buffer=_chime(vol) if kind == "armed" else _tone(f, ms, vol))
                snd.set_volume(vol)
                _sounds[kind] = snd
                src[kind] = "tone"
        _ready = True
        return ", ".join(f"{k}: {v}" for k, v in src.items())
    except Exception as e:
        log(f"audio disabled ({e}); pip install pygame to enable")
        return None


def play(kind, now_s=None, min_gap_s=0.0):
    """Non-blocking. min_gap_s throttles repeats of the same kind (the armed chime)."""
    if not _ready or kind not in _sounds:
        return
    if now_s is not None and min_gap_s and now_s - _last.get(kind, -1e9) < min_gap_s:
        return
    _last[kind] = now_s if now_s is not None else 0.0
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init(22050, -16, 1, 2048)
        snd = _sounds[kind]
        if isinstance(snd, str):
            def mp3(path):
                with _lock:
                    try:
                        pygame.mixer.music.load(path)
                        pygame.mixer.music.set_volume(0.95)
                        pygame.mixer.music.play()
                    except Exception:
                        pass
            threading.Thread(target=mp3, args=(snd,), daemon=True).start()
        else:
            snd.play()
    except Exception:
        pass
