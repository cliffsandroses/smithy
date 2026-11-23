#!/usr/bin/env python3
"""Endless Hum — ambient loop video generator (faceless channel, Moosa 2026-11-14 greenlit).

Everything is made here, so there is nothing to license: the soundscape is synthesised by ffmpeg
(a slow evolving pad chord + brown-noise hum + soft rain), the picture is one still scene with a
slow push-in, falling-rain streaks and a gently breathing lamp glow.

  make.py SCENE.jpg OUT.mp4 [--minutes 60] [--key A] [--crop x:y:w:h] [--loop 60]

How it stays fast: the picture is rendered once as a short seamless loop (--loop seconds; zoom and
glow complete whole cycles in it), then repeated with stream copy; only the audio is made full length.
"""
import argparse, os, subprocess, sys, tempfile

NOTES = {"A": 110.0, "C": 130.81, "D": 146.83, "E": 82.41, "F": 87.31, "G": 98.0}

def run(cmd):
    r = subprocess.call(["nice", "-n", "15"] + cmd)
    if r: sys.exit(f"ffmpeg failed ({r}): {' '.join(cmd)[:200]}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene"); ap.add_argument("out")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--key", default="A", choices=NOTES)
    ap.add_argument("--crop", default="", help="x:y:w:h crop of the scene first (drop watermarks)")
    ap.add_argument("--loop", type=int, default=60, help="seconds of picture rendered, then repeated")
    a = ap.parse_args()
    T, L, f = int(a.minutes * 60), a.loop, NOTES[a.key]
    tmp = tempfile.mkdtemp(prefix="hum-")
    seg, wav = f"{tmp}/loop.mp4", f"{tmp}/audio.m4a"

    # 1. picture loop (L seconds). Glow period divides L, zoom is one full cycle, so the cut is invisible.
    crop = ""
    if a.crop:
        x, y, w, h = a.crop.split(":"); crop = f"crop={w}:{h}:{x}:{y},"
    vf = (f"[0:v]{crop}scale=2304:1296:flags=lanczos,"
          f"zoompan=z='1.06+0.05*sin(2*PI*on/{L*30})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,"
          "eq=brightness='0.02*sin(2*PI*t/10)':eval=frame,vignette=PI/5,format=yuv420p[bg];"
          # rain: sparse dots on a small canvas, stretched into streaks, then screened on
          f"nullsrc=s=480x270:r=30:d={L},format=gray,geq=lum='if(lt(random(1),0.004),230,0)',"
          "scale=1920:1080:flags=neighbor,boxblur=luma_radius=0:luma_power=0:chroma_radius=0:chroma_power=0,"
          "avgblur=sizeX=1:sizeY=14,format=yuv420p[rain];"
          "[bg][rain]blend=all_mode=screen:all_opacity=0.28,noise=alls=2:allf=t,hqdn3d=0:0:3:3[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-stats", "-loop", "1", "-framerate", "30", "-i", a.scene,
         "-filter_complex", vf, "-map", "[v]", "-t", str(L),
         "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-tune", "grain", "-pix_fmt", "yuv420p", "-g", "60", seg])

    # 2. soundscape, full length: pad (each voice breathing on its own slow cycle) + hum + rain
    voices = [(f, 0.16, 1), (f * 1.5, 0.11, 2), (f * 2, 0.08, 3), (f * 2.25, 0.05, 5), (f * 3, 0.035, 7)]
    P = 600  # breath cycle seconds
    pad = "+".join(f"{amp}*sin(2*PI*{fr:.3f}*t)*(0.6+0.4*sin(2*PI*{k}*t/{P}))" for fr, amp, k in voices)
    af = (f"aevalsrc='{pad}':s=48000:d={T}[pad];"
          f"anoisesrc=color=brown:amplitude=0.25:d={T}:r=48000,lowpass=f=220[hum];"
          f"anoisesrc=color=pink:amplitude=0.12:d={T}:r=48000,highpass=f=900,lowpass=f=6000[rain];"
          "[pad]aecho=0.8:0.85:1200|1900:0.35|0.25,lowpass=f=2400[padv];"
          "[padv][hum][rain]amix=inputs=3:weights=1 0.55 0.45:normalize=0,"
          f"afade=t=in:d=4,afade=t=out:st={T-4}:d=4,alimiter=limit=0.8,aformat=channel_layouts=stereo[a]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-filter_complex", af, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", wav])

    # 3. repeat the picture loop to full length and mux (stream copy: seconds, not hours)
    n = -(-T // L)
    run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", str(n - 1), "-i", seg, "-i", wav,
         "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", str(T), "-movflags", "+faststart", a.out])
    for p in (seg, wav): os.remove(p)
    os.rmdir(tmp)
    print(f"done: {a.out} ({T//60} min)")

if __name__ == "__main__":
    main()
