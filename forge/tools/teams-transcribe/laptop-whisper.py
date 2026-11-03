"""Runs on the laptop (pcai-inbox sends the work here: 12 threads vs the homelab's 4). Args: <offset_seconds piece.wav>...
16 kHz mono wav pieces in; '[h:mm:ss] text' lines out on stdout. Reads the wav with numpy (the venv's PyAV decode is broken)."""
import sys, wave, numpy as np
from faster_whisper import WhisperModel
m = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=6)
a = sys.argv[1:]
for off, p in zip(a[::2], a[1::2]):
    w = wave.open(p); x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    for s in m.transcribe(x, language="en", vad_filter=True, beam_size=1)[0]:
        h, r = divmod(int(s.start) + int(off), 3600); print(f"[{h}:{r//60:02d}:{r%60:02d}] {s.text.strip()}", flush=True)
