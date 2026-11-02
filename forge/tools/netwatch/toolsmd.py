"""~/Axon/TOOLS.md: what tools exist and what each is for, one line each, so every agent knows at the start of a
session (Moosa, 2026-11-03: "Make it so that the agents know what tools are made and for what in short each time
they read the vault"). AGENTS.md points to it. Rebuilt by netwatch every 6 hours; `python3 toolsmd.py` now.
"""
import glob, os, re, time

H = os.path.expanduser("~"); OUT = f"{H}/Axon/TOOLS.md"; STATE = f"{H}/.local/share/netwatch/toolsmd.stamp"
TOOLS = f"{H}/Projects/smithy/forge/tools"


def gist(path):
    """First real sentence of the tool's docstring or header comment."""
    try: t = open(path, errors="ignore").read(5000)
    except OSError: return ""
    m = re.search(r'"""(.*?)"""', t, re.S) or re.search(r"((?:^#[^!\n].*\n)+)", t, re.M)
    s = re.sub(r"^#\s?", "", m.group(1), flags=re.M) if m else ""
    s = re.sub(r"\s+", " ", re.sub(r"\(Moosa[^)]*\)|\(\d{4}-\d\d-\d\d\)|\(\d{4}-\d\d-\d\d[^)]*\)", "", s)).strip()
    s = re.sub(r"^[\w./~-]+(\s*\([^)]*\))?\s*[:—-]\s*", "", s)              # drop a leading "toolname:" / "file.py —"
    s = re.sub(r"\s+\.", ".", s)
    s = re.split(r"(?<=[.!?])\s", s)[0] if s else ""
    return s[:150]


def build():
    rows = []
    for d in sorted(glob.glob(f"{TOOLS}/*/")):
        n = os.path.basename(d.rstrip("/"))
        main = next((p for p in [d + n, d + n + ".py", d + n + ".sh"] if os.path.isfile(p)), None)
        if not main:
            main = next((p for p in sorted(glob.glob(d + "*")) if os.path.isfile(p) and not p.endswith((".md", ".pyc", ".json", ".txt"))), "")
        where = "command" if os.path.exists(f"{H}/.local/bin/{n}") else "laptop/folder"
        rows.append(f"- **{n}** ({where}) — {gist(main) or 'see its folder'}")
    extra = []
    for p in sorted(glob.glob(f"{TOOLS}/netwatch/*.py")):
        n = os.path.basename(p)[:-3]
        if n in ("netwatch",): continue
        extra.append(f"  - netwatch/{n} — {gist(p)}")
    return ("# Tools (generated — do not edit)\n\n"
            f"Every tool Moosa has, one line each. Source: `~/Projects/smithy/forge/tools/<name>`; \"command\" = on PATH on\n"
            f"the homelab. Rebuilt every 6 h by netwatch (toolsmd.py); last {time.strftime('%Y-%m-%d %H:%M')}.\n"
            "Full detail: Soma → Vault → Artifacts → Where Everything Lives.\n\n"
            + "\n".join(rows) + "\n\nnetwatch modules (run every minute by the netwatch timer):\n" + "\n".join(extra) + "\n\n"
            "Other places: PNIP `~/EC01-work/pnip` (build.py) · job hunt `~/Projects/job-hunt` · starter pack `~/Projects/starter-pack`"
            " · Soma app `~/Projects/soma-app` (CI results on branch screens-out) · Docket `~/Projects/asks/ledger.json`\n"
            "Extra skills (not loaded each session): the `skill-library` skill lists them.\n")


def run(force=False):
    try: last = os.path.getmtime(STATE)
    except OSError: last = 0
    if not force and time.time() - last < 6 * 3600: return None
    open(OUT, "w").write(build()); os.makedirs(os.path.dirname(STATE), exist_ok=True); open(STATE, "w").close()
    return "toolsmd: TOOLS.md rebuilt"


if __name__ == "__main__": print(run(force=True))
