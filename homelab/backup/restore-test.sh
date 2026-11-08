#!/usr/bin/env bash
# restore-test: prove the newest homelab backup can actually be restored (Moosa: "restore test").
#
# The old script was lost (not on disk, not in git, not on the VM); this is the replacement.
# A backup nobody has restored is a guess, so this reads the newest set and, for every archive:
#   1. gzip --test            - the compressed stream is intact
#   2. tar -t                 - the archive lists without error
#   3. tar -x into a temp dir - a named file per archive really comes back out, byte count checked
# Read-only against the backup; everything is extracted into mktemp and deleted at the end.
# Nothing in /home, /mnt/data or any container is touched.
#
#   restore-test.sh                 # newest set
#   restore-test.sh 2026-11-06_031501
#   restore-test.sh --keep          # leave the extraction behind for inspection
set -uo pipefail

ROOT=${BACKUP_ROOT:-/mnt/data/Backups/homelab}
KEEP=0
SET=""
for a in "$@"; do
  case "$a" in
    --keep) KEEP=1 ;;
    -*) echo "unknown option: $a" >&2; exit 2 ;;
    *) SET="$a" ;;
  esac
done

[ -d "$ROOT" ] || { echo "no backup root at $ROOT" >&2; exit 1; }
[ -n "$SET" ] || SET=$(ls -1 "$ROOT" | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}$' | sort | tail -1)
DIR="$ROOT/$SET"
[ -d "$DIR" ] || { echo "no such set: $DIR" >&2; exit 1; }

TMP=$(mktemp -d /tmp/restore-test.XXXXXX)
trap '[ "$KEEP" = 1 ] || rm -rf "$TMP"' EXIT

echo "restore test: $DIR"
echo "extracting into: $TMP"
echo

pass=0; fail=0
for f in "$DIR"/*.tar.gz; do
  [ -e "$f" ] || continue
  name=$(basename "$f")
  size=$(du -h "$f" | cut -f1)
  printf '%-34s %6s  ' "$name" "$size"

  if ! gzip --test "$f" 2>/dev/null; then
    echo "FAIL: gzip stream is corrupt"; fail=$((fail+1)); continue
  fi
  n=$(tar -tzf "$f" 2>/dev/null | wc -l)
  if [ "$n" -eq 0 ]; then
    echo "FAIL: lists no files"; fail=$((fail+1)); continue
  fi
  # take a real file out of the middle of the archive and check it arrives with bytes in it
  pick=$(tar -tzf "$f" 2>/dev/null | awk 'substr($0,length($0),1)!="/"' | sed -n "$(( (n/2) + 1 ))p")
  [ -n "$pick" ] || pick=$(tar -tzf "$f" 2>/dev/null | awk 'substr($0,length($0),1)!="/"' | head -1)
  if [ -z "$pick" ]; then
    echo "OK   $n entries (directories only, nothing to extract)"; pass=$((pass+1)); continue
  fi
  out="$TMP/$name"
  mkdir -p "$out"
  if tar -xzf "$f" -C "$out" -- "$pick" 2>/dev/null && [ -s "$out/$pick" ]; then
    bytes=$(stat -c %s "$out/$pick")
    echo "OK   $n entries, restored '$(basename "$pick")' ($bytes bytes)"
    pass=$((pass+1))
  elif tar -xzf "$f" -C "$out" -- "$pick" 2>/dev/null && [ -e "$out/$pick" ]; then
    echo "OK   $n entries, restored '$(basename "$pick")' (empty file, as stored)"
    pass=$((pass+1))
  else
    echo "FAIL: could not extract '$pick'"
    fail=$((fail+1))
  fi
done

echo
# a set with no archives at all is a failure, not a pass
if [ $((pass+fail)) -eq 0 ]; then
  echo "FAIL: $SET contains no .tar.gz archives"
  exit 1
fi
echo "restore test $SET: $pass ok, $fail failed"
[ "$KEEP" = 1 ] && echo "extraction kept at $TMP"
[ "$fail" -eq 0 ] || exit 1
exit 0
