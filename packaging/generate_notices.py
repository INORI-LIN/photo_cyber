"""Generate / verify ``THIRD_PARTY_NOTICES.md``.

The notices are a per-platform view of the environment that ships: rows come from
``importlib.metadata`` of the interpreter this tool runs in, so a section is only ever as
good as the environment that produced it. ``--check`` compares **the current platform's
section only** against the installed set. Desktop release verifies its full extra set, while
Docker CI verifies the image's smaller ``photoguard --no-dev`` set after building it.

Hand-maintained material (``LICENSE``, ``licenses/*.txt``) is never generated and never
overwritten — this tool only reads those files; only the platform section of the notices is
rewritten.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"

# Never generated, never overwritten (G2). Listed here so the write path and ``--check``
# both refuse to treat them as output.
HAND_MAINTAINED_LICENSES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "licenses/GPL-3.0.txt",
    "licenses/LGPL-3.0.txt",
    "licenses/LICENSE-3RD-PARTY-opencv.txt",
)
# 写平台段前与 CI/测试同样识别多空白；不会命中本文件中的字面代码。
FORBIDDEN_PATTERN = re.compile(r"pip\s+install")
ROW_FIELDS = ("name", "version", "license", "source")
PROJECT_NAME = "photo-guard"
SECTION_PREFIX = "## "
TABLE_HEADER = "| " + " | ".join(ROW_FIELDS) + " |"
TABLE_SEPARATOR = "|" + "---|" * len(ROW_FIELDS)

SECTION_TEMPLATE = """{prefix}{tag}

Rows measured in this environment with ``importlib.metadata``. Other platforms' sections are
appended by running this tool on those platforms; ``--check`` validates one section at a time.

{header}
{separator}
{rows}
"""


# 用镜像或桌面构建环境的实际系统/架构命名平台段，不能从锁文件猜测。
def platform_tag() -> str:
    return f"{platform.system()} / {platform.machine()}"


# 平台行只复述发行版声明；随 wheel 嵌入组件的许可由手工段单列。
def _license_of(metadata) -> str:
    expression = (metadata.get("License-Expression") or "").strip()
    if expression:
        return expression
    field = (metadata.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= 60:
        return field
    for classifier in metadata.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "declared in package metadata"


# 按发行版公开元数据回退来源，避免把来源猜成当前仓库地址。
def _source_of(metadata) -> str:
    homepage = (metadata.get("Home-page") or "").strip()
    if homepage:
        return homepage
    for url in metadata.get_all("Project-URL") or []:
        _, _, link = url.partition(",")
        if link.strip():
            return link.strip()
    return (metadata.get("Author-email") or "").strip() or "unknown"


# 只枚举当前解释器已安装的发行版，不把未装的桌面依赖混进 Docker 段。
def collect_rows() -> list[dict[str, str]]:
    """One row per installed distribution, the project itself excluded."""
    rows = []
    for dist in md.distributions():
        metadata = dist.metadata
        name = (metadata["Name"] or "").strip()
        if not name or name.lower() == PROJECT_NAME:
            continue
        rows.append(
            {
                "name": name,
                "version": dist.version,
                "license": _license_of(metadata),
                "source": _source_of(metadata),
            }
        )
    return sorted(rows, key=lambda row: row["name"].lower())


# 四列保持固定顺序，供生成和精确差集比对共用。
def render_row(row: dict[str, str]) -> str:
    return "| " + " | ".join(row[field] for field in ROW_FIELDS) + " |"


# 将真实安装集渲染成独立平台段，首轮镜像引导只读取此结果。
def render_section(rows: list[dict[str, str]], tag: str) -> str:
    body = "\n".join(render_row(row) for row in rows) or "| (none installed) | | | |"
    return SECTION_TEMPLATE.format(
        prefix=SECTION_PREFIX, tag=tag, header=TABLE_HEADER, separator=TABLE_SEPARATOR,
        rows=body,
    )


# 下一个二级标题即平台段边界，手工声明必须放在首个平台段之前。
def _section_bounds(text: str, tag: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"{SECTION_PREFIX}{tag}":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith(SECTION_PREFIX):
            end = index
            break
    return start, end


# 仅比对当前环境的行集合，缺行与多行都应响亮失败。
def compare_section(text: str, rows: list[dict[str, str]], tag: str) -> tuple[list[str], list[str]]:
    """``(missing, extra)`` row lines for ``tag``; both empty means the section is current."""
    bounds = _section_bounds(text, tag)
    expected = {render_row(row) for row in rows}
    if bounds is None:
        return sorted(expected), []
    start, end = bounds
    present = {
        line.strip()
        for line in text.splitlines()[start:end]
        if line.startswith("|") and not line.startswith("|---") and line.strip() != TABLE_HEADER
    }
    return sorted(expected - present), sorted(present - expected)


# 刷新目标平台段时保留手工声明和其它 OS 的既有段落。
def replace_section(text: str, section: str, tag: str) -> str:
    bounds = _section_bounds(text, tag)
    if bounds is None:
        separator = "" if text.endswith("\n\n") else "\n"
        return f"{text}{separator}\n{section}"
    start, end = bounds
    lines = text.splitlines()
    return "\n".join([*lines[:start], *section.splitlines(), "", *lines[end:]]) + "\n"


# 校验模式只读；生成模式先拦下不合规行，再仅重写当前平台段。
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_notices.py", description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the current platform's section instead of rewriting it",
    )
    args = parser.parse_args(argv)

    tag = platform_tag()
    rows = collect_rows()
    if args.check:
        if NOTICES.name not in HAND_MAINTAINED_LICENSES:
            raise SystemExit("the notices file must stay in HAND_MAINTAINED_LICENSES")
        missing_paths = [p for p in HAND_MAINTAINED_LICENSES if not (ROOT / p).is_file()]
        if missing_paths:
            print(f"licence material missing: {missing_paths}", file=sys.stderr)
            return 1
        missing, extra = compare_section(NOTICES.read_text(encoding="utf-8"), rows, tag)
        if missing or extra:
            print(f"notices are stale for {tag}:", file=sys.stderr)
            for line in missing:
                print(f"  missing: {line}", file=sys.stderr)
            for line in extra:
                print(f"  extra:   {line}", file=sys.stderr)
            return 1
        print(f"notices OK for {tag} ({len(rows)} rows)")
        return 0

    section = render_section(rows, tag)
    # 平台表按行扫描，与合规门等价；跨行词组不应被当成一条安装命令。
    if any(FORBIDDEN_PATTERN.search(line) for line in section.splitlines()):
        print("refusing to write: a forbidden install literal is present", file=sys.stderr)
        return 1
    text = NOTICES.read_text(encoding="utf-8") if NOTICES.exists() else "# Third-party notices\n"
    NOTICES.write_text(replace_section(text, section, tag), encoding="utf-8")
    print(f"wrote {tag} section ({len(rows)} rows) to {NOTICES.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
