#!/usr/bin/env python3
"""packtrim: cut PACK.md down to what a model with no tools actually needs (Moosa, 28 Oct: "reduce
PACK.md from ~130k to minimum tokens").

PACK.md is the whole vault flattened into one file. 56% of it is progress diaries - history that is
already in git and in the vault itself, and that a model reading the pack never acts on. This keeps
every goal, decision, status and readme intact and keeps only the newest entries of each progress
log, so the pack still says where things stand without replaying months of work.

    packtrim.py                  # rewrite ~/Axon/PACK.md, full copy kept as PACK-full.md
    packtrim.py --keep 6         # newest 6 entries per progress log (default 8)
    packtrim.py --dry-run
"""
import argparse, re, shutil, sys
from pathlib import Path

PACK = Path.home() / "Axon/PACK.md"
FULL = Path.home() / "Axon/PACK-full.md"
ENTRY = re.compile(r"^(#{3,6}\s|\s*[-*]\s*\*\*|\s*[-*]\s*\d{4}-\d\d-\d\d|\d{4}-\d\d-\d\d)")


def split_sections(lines):
    """[(heading_line_index, heading_text, start, end)] for every top-level '# ' section."""
    idx = [i for i, l in enumerate(lines) if l.startswith("# ")]
    out = []
    for n, i in enumerate(idx):
        end = idx[n + 1] if n + 1 < len(idx) else len(lines)
        out.append((i, lines[i][2:].strip(), i, end))
    return out


def trim_progress(body, keep):
    """Keep the section heading, any intro before the first entry, and the newest `keep` entries."""
    starts = [i for i, l in enumerate(body) if ENTRY.match(l)]
    if len(starts) <= keep:
        return body, 0
    cut_at = starts[-keep]
    dropped = len(starts) - keep
    head = body[:starts[0]] if starts else body
    return head + [f"_[{dropped} older entries trimmed by packtrim - full history in PACK-full.md and in git]_", ""] + body[cut_at:], dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pack", default=str(PACK))
    a = ap.parse_args()
    pack = Path(a.pack)
    lines = pack.read_text(encoding="utf-8").split("\n")
    before = len("\n".join(lines))

    out, dropped_total, trimmed = [], 0, []
    for i, title, s, e in split_sections(lines):
        body = lines[s:e]
        if title.lower().startswith("progress"):
            body, dropped = trim_progress(body, a.keep)
            if dropped:
                dropped_total += dropped
                trimmed.append(f"{title} (-{dropped})")
        out += body
    if not out:
        sys.exit("nothing parsed - is this a pack file?")

    text = "\n".join(out)
    after = len(text)
    note = (f"\n\n---\n_packtrim: {dropped_total} old progress entries trimmed; "
            f"{before // 1024} KB -> {after // 1024} KB (~{after // 4000}k tokens). "
            f"Full copy: PACK-full.md_\n")
    text += note

    print(f"{before//1024} KB -> {(len(text))//1024} KB  (~{before//4000}k -> ~{len(text)//4000}k tokens), "
          f"{dropped_total} entries trimmed")
    for t in trimmed:
        print("  ", t)
    if a.dry_run:
        return
    if not FULL.exists() or FULL.stat().st_mtime < pack.stat().st_mtime:
        shutil.copy2(pack, FULL)
    pack.write_text(text, encoding="utf-8")
    print("written:", pack, "| full copy:", FULL)


if __name__ == "__main__":
    main()
