#!/usr/bin/env bash
# Repeatable independent verification of the portable PALM release.
#
# It prefers a real Ubuntu 22.04 container. In this offline sandbox no such
# image exists, so it falls back to a bubblewrap minimal root containing only
# the bundle, bash and the shared libraries the bundle needs. The fallback is
# recorded explicitly; the container path is the primary evidence in CI.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DIST=${DIST:-"$ROOT/dist"}
DOC="$ROOT/packaging/VERIFICATION.md"
LOG=$(mktemp "${TMPDIR:-/tmp}/palm-verify.XXXXXX.log")
SCRATCH=""
MODE="clean-room"
ENGINE=""
HEALTH=""
PAGE_STATUS=""
SETUP_STATUS=""
APP_DIFF="not checked"
DATA_FILES="not checked"
CONTAINER_PYTHON="not checked"

cleanup() {
    if [ -n "${BROWSER_PID:-}" ]; then
        kill -TERM "-$BROWSER_PID" 2>/dev/null || kill -TERM "$BROWSER_PID" 2>/dev/null || true
        wait "$BROWSER_PID" 2>/dev/null || true
    fi
    if [ -n "${CONTAINER_NAME:-}" ] && [ -n "${ENGINE:-}" ]; then
        "$ENGINE" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    [ -n "$SCRATCH" ] && rm -rf "$SCRATCH"
    rm -f "$LOG"
}
trap cleanup EXIT

fail() {
    local message=$1
    {
        echo "# Clean-room verification"
        echo
        echo "Status: **FAILED**"
        echo
        echo "- Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "- Mode: $MODE"
        echo "- Failure: $message"
        echo
        echo '```text'
        tail -80 "$LOG" 2>/dev/null || true
        echo '```'
    } > "$DOC"
    echo "clean-room: $message" >&2
    exit 1
}
trap 'fail "command failed at line $LINENO"' ERR

log() { printf '%s\n' "$*" | tee -a "$LOG"; }
run() {
    log "+ $*"
    "$@" 2>&1 | tee -a "$LOG"
    return "${PIPESTATUS[0]}"
}

port_for() {
    python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

wait_for_state() {
    local state=$1
    for _ in $(seq 1 150); do
        if [ -f "$state" ]; then
            return 0
        fi
        sleep 0.2
    done
    return 1
}

check_http() {
    local base=$1
    HEALTH=$(curl -fsS "$base/api/health")
    log "GET /api/health -> $HEALTH"
    printf '%s' "$HEALTH" | grep -q '"status":"ok"' || fail "health did not report ok"
    PAGE_STATUS=$(curl -fsS -o "$SCRATCH/page.html" -w '%{http_code}' "$base/")
    log "GET / -> HTTP $PAGE_STATUS"
    [ "$PAGE_STATUS" = "200" ] || fail "setup page did not return 200"
    grep -q 'id="root"' "$SCRATCH/page.html" || fail "setup page did not contain the app root"
    SETUP_STATUS=$(curl -fsS -o "$SCRATCH/setup.json" -w '%{http_code}' "$base/api/setup/status")
    log "GET /api/setup/status -> HTTP $SETUP_STATUS"
    [ "$SETUP_STATUS" = "200" ] || fail "setup status did not return 200"
    grep -q '"mode":"packaged"' "$SCRATCH/setup.json" || fail "setup status was not in packaged mode"
}

check_tree() {
    local app=$1
    local data=$2
    local before=$3
    local after
    after=$(find "$app" -type f -printf '%P %s\n' | sort | sha256sum)
    [ "$before" = "$after" ] || fail "the app root changed during the run"
    APP_DIFF="unchanged ($before)"
    DATA_FILES=$(find "$data" -type f -printf '%P %s\n' | sort)
    [ -n "$DATA_FILES" ] || fail "the data root stayed empty"
    log "data-root files:"
    printf '%s\n' "$DATA_FILES" | tee -a "$LOG"
}

find_container_engine() {
    for candidate in podman docker; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if [ "$candidate" = podman ]; then
                "$candidate" image exists ubuntu:22.04 >/dev/null 2>&1 || continue
            else
                "$candidate" image inspect ubuntu:22.04 >/dev/null 2>&1 || continue
            fi
            ENGINE=$candidate
            return 0
        fi
    done
    return 1
}

run_container() {
    local app=$1
    local data=$2
    local port=$3
    CONTAINER_NAME="palm-verify-$$"
    run "$ENGINE" run --rm --name "$CONTAINER_NAME" -d \
        -v "$app:/palm:ro" -v "$data:/data" \
        -e HOME=/tmp -e PALM_DATA_DIR=/data \
        -p "127.0.0.1:$port:$port" ubuntu:22.04 \
        /palm/bin/palm --no-browser --port "$port"
    wait_for_state "$data/run/server.json" || fail "container launcher did not record the URL"
    check_http "http://127.0.0.1:$port"
    CONTAINER_PYTHON=$("$ENGINE" exec "$CONTAINER_NAME" sh -c 'command -v python3 || command -v python || true')
    [ -z "$CONTAINER_PYTHON" ] || fail "the clean Ubuntu image unexpectedly contains Python: $CONTAINER_PYTHON"
    run "$ENGINE" rm -f "$CONTAINER_NAME"
    CONTAINER_NAME=""
}

make_clean_root() {
    local app=$1
    local root=$2
    mkdir -p "$root/bin" "$root/lib64" "$root/usr/lib64" "$root/proc" "$root/dev" "$root/tmp" "$root/data"
    cp -a "$app"/. "$root/palm/"
    cp /bin/bash "$root/bin/bash"
    ln -s bash "$root/bin/sh"
    cp "$(command -v dirname)" "$root/bin/dirname"
    chmod 755 "$root/bin/bash" "$root/bin/dirname"
    python3 - "$root" "$app" <<'PY'
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
app = Path(sys.argv[2])
libs = set()
for binary in (root / "palm/python/bin/python3.11", root / "bin/bash", root / "bin/dirname"):
    output = subprocess.check_output(["ldd", str(binary)], text=True)
    for line in output.splitlines():
        if "=>" in line:
            lib = line.split("=>", 1)[1].strip().split()[0]
        elif line.strip().startswith("/"):
            lib = line.strip().split()[0]
        else:
            continue
        if lib.startswith("/") and not lib.startswith(str(app)):
            libs.add(lib)
for shared in (root / "palm/python").rglob("*.so*"):
    try:
        output = subprocess.check_output(
            ["ldd", str(shared)], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        continue
    for line in output.splitlines():
        if "=>" in line:
            lib = line.split("=>", 1)[1].strip().split()[0]
            if lib.startswith("/") and not lib.startswith(str(app)):
                libs.add(lib)
for lib in sorted(libs):
    source = Path(lib)
    destination = root / source.relative_to("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
print(f"copied {len(libs)} shared libraries into the minimal root")
PY
}

run_bwrap() {
    local app=$1
    local data=$2
    local port=$3
    local root=$4
    setsid bwrap --ro-bind "$root" / --proc /proc --dev /dev --tmpfs /tmp \
        --bind "$data" /data --setenv HOME /tmp --setenv PALM_DATA_DIR /data \
        --setenv PATH /bin --chdir /palm /palm/bin/palm --no-browser --port "$port" \
        >"$SCRATCH/bwrap.out" 2>&1 &
    BROWSER_PID=$!
    wait_for_state "$data/run/server.json" || {
        cat "$SCRATCH/bwrap.out" >&2 || true
        fail "clean-room launcher did not record the URL"
    }
    check_http "http://127.0.0.1:$port"
    kill -TERM "-$BROWSER_PID" 2>/dev/null || kill -TERM "$BROWSER_PID" 2>/dev/null || true
    wait "$BROWSER_PID" 2>/dev/null || true
    BROWSER_PID=""
}

main() {
    mkdir -p "$DIST"
    [ -f "$DIST/SHA256SUMS" ] || fail "dist/SHA256SUMS is missing; run make package"
    local tar_path
    tar_path=$(find "$DIST" -maxdepth 1 -name 'PALM-*-linux-x86_64.tar.gz' | head -1)
    [ -n "$tar_path" ] || fail "no PALM tar in dist; run make package"
    if tar -tzf "$tar_path" | grep -Eq '^/|(^|/)\.\.(/|$)'; then
        fail "tar contains an absolute or parent-relative member"
    fi
    local size
    size=$(stat -c%s "$tar_path")
    [ "$size" -lt 2147483648 ] || fail "tar is at least 2 GiB"
    log "asset: $tar_path ($size bytes)"
    run make -C "$ROOT" test-package
    (cd "$DIST" && sha256sum -c SHA256SUMS) | tee -a "$LOG"

    SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/palm-clean-room.XXXXXX")
    local app="$SCRATCH/app"
    local data="$SCRATCH/data"
    mkdir -p "$app" "$data"
    tar -xzf "$tar_path" -C "$app"
    local root
    root=$(find "$app" -mindepth 1 -maxdepth 1 -type d | head -1)
    [ -n "$root" ] || fail "tar did not contain a top-level directory"
    if grep -RIl --binary-files=without-match --exclude='*.so' --exclude='*.so.*' --exclude='*.pyc' \
        "$ROOT" "$root" >/dev/null 2>&1; then
        fail "staged tree contains the repository absolute path"
    fi
    local before
    before=$(find "$root" -type f -printf '%P %s\n' | sort | sha256sum)
    local port
    port=$(port_for)

    if find_container_engine; then
        MODE="Ubuntu 22.04 container ($ENGINE)"
        run_container "$root" "$data" "$port"
    else
        MODE="bubblewrap minimal root (Ubuntu 22.04 image unavailable offline)"
        log "container image unavailable; using the documented bubblewrap fallback"
        local minimal="$SCRATCH/root"
        make_clean_root "$root" "$minimal"
        run_bwrap "$root" "$data" "$port" "$minimal"
    fi
    check_tree "$root" "$data" "$before"

    {
        echo "# Clean-room verification"
        echo
        echo "Status: **PASSED**"
        echo
        echo "- Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "- Mode: $MODE"
        echo "- Asset: \`$(basename "$tar_path")\` ($size bytes)"
        echo "- SHA256SUMS: verified"
        echo "- /api/health: \`$HEALTH\`"
        echo "- setup page: HTTP $PAGE_STATUS, contains \`id=\"root\"\`"
        echo "- /api/setup/status: HTTP $SETUP_STATUS, packaged mode"
        echo "- app root: $APP_DIFF"
        echo "- data-root files:"
        echo
        echo '```text'
        printf '%s\n' "$DATA_FILES"
        echo '```'
        echo
        echo "- Python in clean container: ${CONTAINER_PYTHON:-not checked (bubblewrap fallback)}"
        echo
        echo "## Commands run"
        echo
        echo '```sh'
        echo "make test-package"
        echo "tar -xzf $tar_path"
        if [ -n "$ENGINE" ]; then
            echo "$ENGINE run ... ubuntu:22.04 /palm/bin/palm --no-browser --port $port"
        else
            echo "bwrap --ro-bind <minimal-root> / ... /palm/bin/palm --no-browser --port $port"
        fi
        echo "curl http://127.0.0.1:$port/api/health"
        echo "curl http://127.0.0.1:$port/"
        echo "curl http://127.0.0.1:$port/api/setup/status"
        echo '```'
        echo
        echo "The full command/output transcript is retained in the build log while"
        echo "this script runs. The container path is preferred; the bubblewrap"
        echo "fallback is used only when no Ubuntu 22.04 image is available offline."
    } > "$DOC"
    log "clean-room verification passed; wrote $DOC"
}

main "$@"
