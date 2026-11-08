#!/usr/bin/env python3
"""gitkeep: keep Moosa's repos pushed to GitHub without being asked (2026-11-08).

Pushes commits that already exist. It never writes commits of its own for code repos, because an
unreviewed auto-commit is how secrets and half-finished work reach a public remote. The one
exception is note-only repos listed in NOTES: there a dated "notes" commit is what you want.

Remotes are forced to SSH (git@github.com:...) because the gh token on this laptop is invalid while
the SSH key works. A repo that cannot fast-forward is reported, never forced.

    gitkeep.py                # push everything it can, print a summary
    gitkeep.py --dry-run
    gitkeep.py --quiet        # for the timer: only speak when something needs a human
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
REPOS = [HOME / "Projects/smithy", HOME / "Projects/clipper", HOME / "Projects/job-hunt",
         HOME / "Projects/my_linux_utils", HOME / "Axon"]
NOTES = {HOME / "Axon"}          # notes: a dated commit of local edits is wanted
STATE = HOME / ".local/state/gitkeep.json"
NTFY = os.environ.get("GITKEEP_NTFY", "")   # optional ntfy topic URL


def git(repo, *a, check=False):
    r = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=180)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r


def ssh_remote(repo, name):
    url = git(repo, "remote", "get-url", name).stdout.strip()
    m = re.match(r"https://github\.com/(.+?)(?:\.git)?$", url)
    if m:
        new = f"git@github.com:{m.group(1)}.git"
        git(repo, "remote", "set-url", name, new)
        return new, True
    return url, False


def remote_of(repo):
    names = git(repo, "remote").stdout.split()
    for pref in ("github", "origin"):
        if pref in names:
            return pref
    return names[0] if names else None


def handle(repo, dry):
    if not (repo / ".git").exists():
        return "no repo"
    name = remote_of(repo)
    if not name:
        return "no remote"
    url, changed = ssh_remote(repo, name)
    if "github.com" not in url:
        return f"skip ({url.split(':')[0]})"

    if repo in NOTES:
        dirty = git(repo, "status", "--porcelain").stdout.strip()
        if dirty and not dry:
            git(repo, "add", "-A")
            git(repo, "-c", "user.email=m3ldev@proton.me", "-c", "user.name=gitkeep",
                "commit", "-q", "-m", "notes: " + time.strftime("%Y-%m-%d %H:%M"))
        elif dirty:
            return "would commit %d files" % len(dirty.splitlines())

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch == "HEAD":
        return "detached HEAD - needs a human"
    git(repo, "fetch", "-q", name)
    ahead = git(repo, "rev-list", "--count", f"{name}/{branch}..HEAD").stdout.strip() or "0"
    behind = git(repo, "rev-list", "--count", f"HEAD..{name}/{branch}").stdout.strip() or "0"
    if behind != "0" and ahead != "0":
        return f"DIVERGED: {ahead} local, {behind} remote - needs a human (never force-pushed)"
    if ahead == "0":
        return "up to date"
    if dry:
        return f"would push {ahead}"
    r = git(repo, "push", name, f"HEAD:{branch}")
    if r.returncode:
        return "push failed: " + (r.stderr.strip().splitlines() or ["?"])[-1][:120]
    return f"pushed {ahead}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    out = {}
    for repo in REPOS:
        try:
            out[repo.name] = handle(repo, a.dry_run)
        except Exception as e:
            out[repo.name] = f"error: {type(e).__name__}: {e}"[:140]

    needs = {k: v for k, v in out.items()
             if any(w in v for w in ("DIVERGED", "failed", "error", "needs a human"))}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"at": time.time(), "repos": out}, indent=1))

    if not a.quiet or needs:
        for k, v in out.items():
            print(f"{k:16} {v}")
    if needs and NTFY:
        import urllib.request
        body = "; ".join(f"{k}: {v}" for k, v in needs.items())[:300]
        try:
            urllib.request.urlopen(urllib.request.Request(
                NTFY, data=body.encode(), headers={"Title": "GitHub: a repo needs you"}), timeout=20)
        except Exception:
            pass
    return 1 if needs else 0


if __name__ == "__main__":
    sys.exit(main())
