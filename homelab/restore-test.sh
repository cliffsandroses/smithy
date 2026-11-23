#!/bin/bash
# Restore test for the homelab offsite copy (rewritten 2026-11-04 after the 2026-10-08 script went missing).
# Test cases: ~/Axon/Homelab/restore-test.md (T1-T15). Usage: restore-test.sh [backup-folder]  (default: newest)
# Works on copies in ~/.cache/homelab-restore-test/<backup>/; never touches the backup or the real homelab.
# Docker parts run on an --internal network (no internet, no LAN, no published ports). Deletes nothing: lists what it made.
set -u
OFF=${OFFSITE:-$HOME/homelab-offsite}
B=${1:-$(ls -d "$OFF"/20*_* | sort | tail -1)}; B=$(readlink -f "$B"); NAME=$(basename "$B")
W=$HOME/.cache/homelab-restore-test/$NAME; mkdir -p "$W"; NET=restore-test-net
RES=(); pass=0; total=0
rec() { # name status detail seconds
  total=$((total+1)); [ "$2" = PASS ] && pass=$((pass+1)); RES+=("| $1 | **$2** | $3 | ${4}s |"); printf '%-34s %-5s %s\n' "$1" "$2" "$3"; }
run() { local n=$1; shift; local s=$SECONDS out; out=$("$@" 2>&1); local rc=$?; local st=PASS; [ $rc -ne 0 ] && st=FAIL
  rec "$n" "$st" "$(echo "$out" | tail -1 | cut -c1-200)" $((SECONDS-s)); }
x() { tar xzf "$B/$1" -C "$W" 2>/dev/null; }

t1() { local age=$(( ($(date +%s)-$(stat -c %Y "$B/backup.log"))/3600 )); [ $age -lt 26 ] || { echo "taken $age h ago"; return 1; }
  local bad; bad=$(cd "$B" && sha256sum -c SHA256SUMS 2>&1 | grep -vc ': OK$'); local n; n=$(wc -l < "$B/SHA256SUMS")
  local errs; errs=$(grep -ci 'error\|fail' "$B/backup.log"); echo "taken ${age}h ago; $n files checksummed, $bad mismatches; $errs errors in backup.log"; [ "$bad" = 0 ] && [ "$errs" = 0 ]; }
t2() { mkdir -p "$W/cfg"; tar xzf "$B/homelab-config.tar.gz" -C "$W/cfg" 2>/dev/null; local ok=0 n=0 f
  while read -r f; do n=$((n+1)); (cd "$(dirname "$f")" && docker compose -f "$(basename "$f")" config -q >/dev/null 2>&1) && ok=$((ok+1)); done < <(find "$W/cfg" -name 'docker-compose.yml' 2>/dev/null)
  echo "$ok of $n stacks render"; [ $n -gt 0 ] && [ $ok = $n ]; }
t3() { local ok=0 n=0 f; mkdir -p "$W/db"; tar xzf "$B/homelab-config.tar.gz" -C "$W/db" 2>/dev/null
  while read -r f; do n=$((n+1)); [ "$(sqlite3 "file:$f?mode=ro" 'pragma integrity_check' 2>/dev/null)" = ok ] && ok=$((ok+1)); done < <(find "$W/db" \( -name '*.db' -o -name '*.sqlite*' \) ! -name '*-wal' ! -name '*-shm' ! -name 'mosquitto.db' ! -path '*/plex/*' -size +0 2>/dev/null)  # Plex uses a custom collation stock sqlite cannot open; mosquitto.db is not SQLite
  echo "$ok of $n pass integrity_check"; [ $n -gt 0 ] && [ $ok = $n ]; }
arr() { mkdir -p "$W/arr"; tar xzf "$B/arr-native-backups.tar.gz" -C "$W/arr" 2>/dev/null; local z; z=$(ls -t "$W"/arr/homelab/arr/config/$1/Backups/*/*.zip 2>/dev/null | head -1); [ -n "$z" ] || { echo "no $1 backup zip"; return 1; }
  local d="$W/arr/$1"; rm -rf "$d"; mkdir -p "$d"; unzip -qo "$z" -d "$d"; local db; db=$(ls "$d"/*.db | head -1); [ "$(sqlite3 "file:$db?mode=ro" 'pragma integrity_check')" = ok ] || { echo "db corrupt"; return 1; }
  local c; c=$(sqlite3 "file:$db?mode=ro" "select count(*) from $2" 2>/dev/null); echo "$(basename "$z"): database ok, holds $c $2"; [ "${c:-0}" -gt 0 ]; }
t7() { zcat "$B/immich-db.sql.gz" | head -c 200000 | grep -q 'PostgreSQL database dump' || { echo "dump header missing"; return 1; }
  local n; n=$(zcat "$B/immich-db.sql.gz" | grep -cE '^[0-9a-f-]{36}	.*	(IMAGE|VIDEO)	'); local lib; lib=$(find "$OFF/immich-library/upload" "$OFF/immich-library/library" -type f ! -name '.*' 2>/dev/null | wc -l)
  echo "dump readable; ~$n asset rows; $lib original files in offsite library (full DB load = not run, needs Immich's Postgres image)"; [ "$lib" -gt 0 ]; }
t8() { local u p; u=$(grep -oP "'dbuser'\s*=>\s*'\K[^']+" "$B/nextcloud-config.php"); p=$(grep -oP "'dbpassword'\s*=>\s*'\K[^']+" "$B/nextcloud-config.php")
  docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
  docker rm -f restore-test-pg >/dev/null 2>&1; docker run -d --name restore-test-pg --network $NET -e POSTGRES_PASSWORD=x postgres:16-alpine >/dev/null || return 1
  for i in $(seq 30); do docker exec restore-test-pg pg_isready -q && break; sleep 1; done
  docker exec restore-test-pg psql -U postgres -qc "create role \"$u\" login password '$p'" -c "create database nextcloud owner \"$u\"" || return 1
  zcat "$B/nextcloud-db.sql.gz" | docker exec -i -e PGPASSWORD="$p" restore-test-pg psql -U "$u" -d nextcloud -q -v ON_ERROR_STOP=0 2>"$W/nc.err" >/dev/null
  local errs; errs=$(grep -c ERROR "$W/nc.err"); local files; files=$(docker exec restore-test-pg psql -U postgres -d nextcloud -Atc 'select count(*) from oc_filecache'); local users; users=$(docker exec restore-test-pg psql -U postgres -d nextcloud -Atc 'select count(*) from oc_users')
  docker rm -f restore-test-pg >/dev/null 2>&1
  echo "$errs restore errors; $files files indexed, $users users"; [ "$errs" = 0 ] && [ "${files:-0}" -gt 0 ]; }
t9() { [ -s "$B/AdGuardHome.yaml" ] || return 1; local u r; u=$(grep -c '^  - name:' "$B/AdGuardHome.yaml"); r=$(grep -c "^  - '" "$B/AdGuardHome.yaml"); echo "config present; $u user(s), user_rules lines: $r"; [ "$u" -gt 0 ]; }
t10() { mkdir -p "$W/hs"; tar xzf "$B/vol-headscale_headscale_data.tar.gz" -C "$W/hs" 2>/dev/null; local db; db=$(find "$W/hs" -name 'db.sqlite' | head -1); [ -n "$db" ] || { echo "no db"; return 1; }
  local n; n=$(sqlite3 "file:$db?mode=ro" 'select count(*) from nodes'); local k; k=$(find "$W/hs" -name 'noise_private.key' | wc -l); echo "database lists $n devices; noise key present: $k"; [ "${n:-0}" -gt 0 ] && [ "$k" = 1 ]; }
t11() { mkdir -p "$W/caddy"; tar xzf "$B/vol-caddy_caddy_data.tar.gz" -C "$W/caddy" 2>/dev/null; local c; c=$(find "$W/caddy" -name '*.crt' | wc -l)
  local cf; cf=$(find "$W/cfg" -iname Caddyfile | head -1); [ -n "$cf" ] || { echo "no Caddyfile in the config archive"; return 1; }; if true; then docker run --rm --network none -v "$cf":/etc/caddy/Caddyfile:ro caddy:2 caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 || { echo "Caddyfile invalid"; return 1; }; fi
  echo "Caddyfile validates; $c certificate file(s) restored"; [ "$c" -gt 0 ]; }
t12() { mkdir -p "$W/ha"; tar xzf "$B/vol-homeassistant_ha_config.tar.gz" -C "$W/ha" 2>/dev/null; local y; y=$(find "$W/ha" -name configuration.yaml | head -1); [ -n "$y" ] || { echo "no configuration.yaml"; return 1; }
  local s ok=0 n=0; for s in "$(dirname "$y")"/.storage/*; do [ -f "$s" ] || continue; n=$((n+1)); python3 -m json.tool "$s" >/dev/null 2>&1 && ok=$((ok+1)); done
  echo "configuration.yaml present; $ok of $n .storage files parse (HA not started)"; [ $n -gt 0 ] && [ $ok = $n ]; }
t13() { mkdir -p "$W/qb"; tar xzf "$B/qbittorrent-config.tar.gz" -C "$W/qb" 2>/dev/null; local f t; f=$(find "$W/qb" -name '*.fastresume' | wc -l); t=$(find "$W/qb" -name '*.torrent' | wc -l)
  find "$W/qb" -iname 'qBittorrent.conf' | grep -q . || { echo "no settings"; return 1; }; echo "settings present; $f resume files, $t .torrent files"; [ "$f" -gt 0 ]; }
t14() { local n=0 s; for s in crontab '/etc/cron.d' fstab 'nfs exports' 'user services\|systemd' '^## ip' routes packages; do grep -qi "$s" "$B/host-facts.txt" && n=$((n+1)); done; echo "$n of 8 sections found"; [ $n = 8 ]; }
t15() { local miss=() ; git --git-dir="$W/cfg/homelab/.git" cat-file -e HEAD:backup/backup-homelab.sh 2>/dev/null || miss+=("backup scripts"); [ -d "$OFF/nextcloud-files" ] && [ -n "$(ls -A "$OFF/nextcloud-files" 2>/dev/null)" ] || miss+=("Nextcloud files")
  grep -qi vaultwarden "$B/manifest.txt" && ! tar tzf "$B/homelab-config.tar.gz" | grep -qi vaultwarden && miss+=("Vaultwarden data")
  [ ${#miss[@]} = 0 ] && echo "nothing missing" || { echo "not in offsite copy: ${miss[*]}"; return 1; }; }

command -v docker >/dev/null && docker info >/dev/null 2>&1 || echo "WARNING: Docker not available: T2, T8, T11 will fail"
echo "Restore test of $NAME"
run "T1 Backup fresh and intact" t1
run "T2 Compose files render" t2
run "T3 Every SQLite database" t3
run "T4 Sonarr from its zip" arr sonarr series
run "T5 Radarr from its zip" arr radarr movies
run "T6 Prowlarr from its zip" arr prowlarr indexers
run "T7 Immich dump + photos" t7
run "T8 Nextcloud database" t8
run "T9 AdGuard config" t9
run "T10 Headscale" t10
run "T11 Caddy" t11
run "T12 Home Assistant config" t12
run "T13 qBittorrent" t13
run "T14 Rebuild notes" t14
run "T15 Coverage" t15
echo; echo "### $(date '+%F %H:%M') · backup $NAME · $pass of $total passed"; echo; echo "| Test | Result | Detail | Time |"; echo "|---|---|---|---|"; printf '%s\n' "${RES[@]}"
docker network rm $NET >/dev/null 2>&1
echo; echo "Left for you to remove if you want: copies in $W (the test container and network are removed)"
