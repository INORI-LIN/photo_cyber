#!/usr/bin/env bash
# G5 — distribution smoke test: build the sdist and wheel, rebuild a wheel from the sdist, then
# install the project into a throw-away environment and check the version it reports.
#
# POSIX-only on purpose (the CI step that runs it is Linux-only). Needs a dev-synced project.
#
# Negative controls (both must go red):
#   SMOKE_EXPECTED_VERSION_OVERRIDE=0.0.0 packaging/smoke_wheel.sh
#       -> the installed version no longer matches; step 5 fails.
#   SMOKE_VENV="$PWD/.venv" packaging/smoke_wheel.sh
#       -> refused up front, before anything is synced, because the smoke venv would be the
#          project venv (AGENTS.md §六 keeps development dependencies project-local; this
#          check needs an isolated one, see docs/fix-plan.md §6 G5).
set -euo pipefail

UV=${UV:-uv}
SMOKE_VENV=${SMOKE_VENV:-}
SMOKE_EXPECTED_VERSION_OVERRIDE=${SMOKE_EXPECTED_VERSION_OVERRIDE:-}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
VENV=${SMOKE_VENV:-$TMP/venv}

# Canonicalise a path that may not exist yet (BSD realpath has no -m, GNU has no portability).
resolve_dir() {
  dir=$(dirname "$1")
  if [ -d "$dir" ]; then
    (cd "$dir" && printf '%s/%s\n' "$(pwd -P)" "$(basename "$1")")
  else
    printf '%s\n' "$1"
  fi
}

# 0. never touch the project's own environment
PROJECT_VENV=$(resolve_dir "${UV_PROJECT_ENVIRONMENT:-$PWD/.venv}")
if [ "$(resolve_dir "$VENV")" = "$PROJECT_VENV" ]; then
  echo "refusing to run: the smoke venv would be the project venv ($VENV)" >&2
  exit 1
fi

# 1. the version comes from pyproject.toml only (--print-version answers before any guard)
V=$(env -u UV_PROJECT_ENVIRONMENT "$UV" run --frozen --no-sync \
      python packaging/build_desktop.py --print-version)
echo "pyproject version: $V"

# 2. build both artefacts into an isolated directory, and require the console entry point
"$UV" build --out-dir "$TMP/dist" >/dev/null
WHEEL=$(ls "$TMP"/dist/*.whl)
SDIST=$(ls "$TMP"/dist/*.tar.gz)
"$UV" run --frozen --no-sync python - "$WHEEL" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
assert any(name.endswith("photo_guard/__main__.py") for name in names), names
PY
echo "wheel + sdist built: $(basename "$WHEEL"), $(basename "$SDIST")"

# 3. a wheel rebuilt from the sdist must build too (the sdist must be self-contained)
"$UV" build --wheel --out-dir "$TMP/from-sdist" "$SDIST" >/dev/null
echo "wheel rebuilt from sdist: $(basename "$(ls "$TMP"/from-sdist/*.whl)")"

# 4. install into the throw-away environment
UV_PROJECT_ENVIRONMENT="$VENV" "$UV" sync --frozen --no-dev --no-editable >/dev/null
[ -x "$VENV/bin/python" ] || { echo "no interpreter in $VENV" >&2; exit 1; }

# 5. it must really be the throw-away environment, and it must report the pyproject version
RESOLVED=$(realpath "$VENV")
if [ -z "$SMOKE_VENV" ]; then
  case "$RESOLVED" in
    "$(realpath "$TMP")"/*) ;;
    *) echo "the venv escaped the temp directory: $RESOLVED" >&2; exit 1 ;;
  esac
fi
EXPECTED=${SMOKE_EXPECTED_VERSION_OVERRIDE:-$V}
INSTALLED=$("$VENV/bin/python" -c "import importlib.metadata as m; print(m.version('photo-guard'))")
if [ "$INSTALLED" != "$EXPECTED" ]; then
  echo "installed version $INSTALLED != expected $EXPECTED" >&2
  exit 1
fi
"$VENV/bin/photo-guard" --help >/dev/null
echo "smoke OK: $RESOLVED reports photo-guard $INSTALLED and its console script runs"
