#!/usr/bin/env bash
# G10：分别安装直接构建的 wheel 与 sdist 重建的 wheel，避免源码树安装造成假绿。
# CI 在 Linux 执行；本地运行需已同步 dev 环境，脚本不重装项目 .venv。
# 负控：错误的 SMOKE_EXPECTED_VERSION_OVERRIDE 必须失败，SMOKE_VENV=$PWD/.venv 必须提前拒绝。
set -euo pipefail

UV=${UV:-uv}
SMOKE_VENV=${SMOKE_VENV:-}
SMOKE_EXPECTED_VERSION_OVERRIDE=${SMOKE_EXPECTED_VERSION_OVERRIDE:-}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
VENV=${SMOKE_VENV:-$TMP/venv}

# 兼容 BSD/GNU 的未创建路径解析，避免依赖 realpath -m。
resolve_dir() {
  if [ -e "$1" ]; then
    realpath "$1"
    return
  fi
  dir=$(dirname "$1")
  if [ -d "$dir" ]; then
    (cd "$dir" && printf '%s/%s\n' "$(pwd -P)" "$(basename "$1")")
  else
    case "$1" in
      /*) printf '%s\n' "$1" ;;
      *) printf '%s/%s\n' "$PWD" "$1" ;;
    esac
  fi
}

# 0. 拒绝覆盖项目环境；自定义路径先转绝对路径以便在临时 cwd 校验。
PROJECT_VENV=$(resolve_dir "$PWD/.venv")
VENV=$(resolve_dir "$VENV")
if [ "$VENV" = "$PROJECT_VENV" ] || [ "$VENV" = "$(resolve_dir "${UV_PROJECT_ENVIRONMENT:-$PROJECT_VENV}")" ]; then
  echo "refusing to run: the smoke venv would be the project venv ($VENV)" >&2
  exit 1
fi

# 1. 只从 pyproject.toml 取版本；frozen 导出锁定 core 依赖，不改写 uv.lock。
V=$(env -u UV_PROJECT_ENVIRONMENT "$UV" run --frozen --no-sync \
      python packaging/build_desktop.py --print-version)
EXPECTED=${SMOKE_EXPECTED_VERSION_OVERRIDE:-$V}
echo "pyproject version: $V"
"$UV" export --frozen --no-dev --no-emit-project --no-hashes > "$TMP/core-requirements.txt"

# 2. 两条构建链分别产出 wheel，后续必须实际安装各自产物。
"$UV" build --out-dir "$TMP/dist" >/dev/null
WHEEL=$(ls "$TMP"/dist/*.whl)
SDIST=$(ls "$TMP"/dist/*.tar.gz)
echo "wheel + sdist built: $(basename "$WHEEL"), $(basename "$SDIST")"
"$UV" build --wheel --out-dir "$TMP/from-sdist" "$SDIST" >/dev/null
SDIST_WHEEL=$(ls "$TMP"/from-sdist/*.whl)
echo "wheel rebuilt from sdist: $(basename "$SDIST_WHEEL")"

# 3. 对每份 wheel 先核验归档 RECORD，再安装到各自 venv 并脱离源码树验收。
smoke_distribution() {
  local wheel=$1 venv=$2 resolved
  "$UV" venv --managed-python --python 3.11 "$venv" >/dev/null
  [ -x "$venv/bin/python" ] || { echo "no interpreter in $venv" >&2; exit 1; }

  (cd "$TMP" && env -u PYTHONPATH "$venv/bin/python" -I - "$wheel" "$V" <<'PY'
import base64
import csv
import email
import hashlib
import io
import sys
import zipfile
from pathlib import PurePosixPath

with zipfile.ZipFile(sys.argv[1]) as archive:
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)) or any(
        name.startswith("/") or ".." in PurePosixPath(name).parts for name in names
    ):
        raise SystemExit("duplicate or unsafe wheel members")
    members = {entry.filename for entry in entries if not entry.is_dir()}
    records = [name for name in members if name.endswith(".dist-info/RECORD")]
    if len(records) != 1 or "photo_guard/__main__.py" not in members:
        raise SystemExit("wheel missing RECORD or entry point")
    record = records[0]
    rows = list(csv.reader(io.StringIO(archive.read(record).decode("utf-8"))))
    recorded = {}
    for row in rows:
        if len(row) != 3 or row[0] in recorded:
            raise SystemExit("duplicate or malformed RECORD row")
        recorded[row[0]] = (row[1], row[2])
    if set(recorded) != members or recorded[record] != ("", ""):
        raise SystemExit("RECORD members mismatch")

    # RECORD 自身允许空摘要；其他文件必须逐项验证真实字节数与 SHA-256。
    for name, (digest, size) in recorded.items():
        if name == record:
            continue
        data = archive.read(name)
        actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if digest != f"sha256={actual}" or size != str(len(data)):
            raise SystemExit(f"RECORD hash/size mismatch: {name}")

    metadata_path = record.rsplit("/", 1)[0] + "/METADATA"
    metadata = email.message_from_bytes(archive.read(metadata_path))
    licenses = metadata.get_all("License-File") or []
    if (metadata.get("Name") != "photo-guard" or metadata.get("Version") != sys.argv[2]
            or metadata.get("License-Expression") != "MIT"
            or not {"LICENSE", "THIRD_PARTY_NOTICES.md", "licenses/GPL-3.0.txt",
                    "licenses/LGPL-3.0.txt"}.issubset(licenses)
            or any(record.rsplit("/", 1)[0] + "/licenses/" + name not in members
                   for name in licenses)):
        raise SystemExit("wheel version or license metadata/files mismatch")
print("wheel RECORD + metadata OK:", sys.argv[1])
PY
  )

  # 仅在临时 requirements 中追加当前 wheel，pip sync 不读取源码项目配置。
  cp "$TMP/core-requirements.txt" "$TMP/requirements.txt"
  printf '%s\n' "$wheel" >> "$TMP/requirements.txt"
  (cd "$TMP" && env -u PYTHONPATH "$UV" pip sync --python "$venv/bin/python" \
      --strict "$TMP/requirements.txt" >/dev/null)

  (cd "$TMP" && env -u PYTHONPATH "$venv/bin/python" -I - "$venv" "$EXPECTED" <<'PY'
import importlib.metadata as md
from pathlib import Path
import sys
import photo_guard

root = Path(sys.argv[1]).resolve()
source = Path(photo_guard.__file__).resolve()
dist = md.distribution("photo-guard")
licenses = dist.metadata.get_all("License-File") or []
if not source.is_relative_to(root) or source != Path(dist.locate_file("photo_guard/__init__.py")).resolve():
    raise SystemExit(f"photo_guard loaded outside installed venv: {source}")
if dist.version != sys.argv[2]:
    raise SystemExit(f"installed version {dist.version} != expected {sys.argv[2]}")
if (dist.metadata.get("License-Expression") != "MIT"
        or not {"LICENSE", "THIRD_PARTY_NOTICES.md", "licenses/GPL-3.0.txt",
                "licenses/LGPL-3.0.txt"}.issubset(licenses)):
    raise SystemExit("installed license metadata mismatch")

# 已安装的许可文件必须出现在此 distribution 的文件清单内且真实存在。
files = dist.files or []
for name in licenses:
    if not any(str(item).endswith(".dist-info/licenses/" + name)
               and Path(dist.locate_file(item)).is_file() for item in files):
        raise SystemExit(f"installed license file missing: {name}")
PY
  )
  (cd "$TMP" && env -u PYTHONPATH "$venv/bin/photo-guard" --help >/dev/null)
  resolved=$(realpath "$venv")
  echo "smoke OK: $resolved reports photo-guard $EXPECTED and its console script runs"
}

smoke_distribution "$WHEEL" "$VENV"
if [ -z "$SMOKE_VENV" ]; then
  case "$(realpath "$VENV")" in
    "$(realpath "$TMP")"/*) ;;
    *) echo "the venv escaped the temp directory: $VENV" >&2; exit 1 ;;
  esac
fi
smoke_distribution "$SDIST_WHEEL" "$TMP/from-sdist-venv"
