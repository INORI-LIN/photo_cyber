"""AGENTS.md 6.4 compliance: the forbidden install string must not appear
in code or scripts. This watchdog is scanned too; its example strings are split so
both CI and the cross-platform scan retain the same whitelist.

G2 turned this file into the licence/notices gate as well: the MIT text, the canonical
copyleft texts, the PEP 639 fields of the built metadata and the packaging wiring are all
pinned here, so a missing or drifted licence artefact fails the fast tier.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import re
import runpy
import sys
import platform
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN = re.compile(r"pip\s+install")  # 与 CI 一样识别一行内的连续空白
# .github/ is deliberately NOT excluded (G5): excluding it left a blind spot in the gate,
# and AGENTS.md §11 now records the whitelist as AGENTS.md + README.md only.
_EXCLUDE_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache"}
_EXCLUDE_FILES = {"uv.lock", "AGENTS.md", "README.md"}


# 扫描每行可疑安装命令，含 .github 工作流但跳过二进制及规则说明文件。
def _scan_repo_for_forbidden() -> list[tuple[Path, int, str]]:
    """Pure-Python equivalent of the grep CI step.

    Cross-platform (the shell-based grep step in ci.yml is Linux-only;
    this test runs on every OS via pytest). Walks the repo, skips binary
    files via UnicodeDecodeError, and reports every line that contains
    the forbidden literal.
    """
    hits: list[tuple[Path, int, str]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.name in _EXCLUDE_FILES:
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if _FORBIDDEN.search(line):
                        hits.append((path, lineno, line.rstrip()))
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable — not a source/script file we care about.
            continue
    return hits


# 保证仓库实际内容无禁用安装语句，而不仅是合成用例能识别。
def test_no_forbidden_install_in_code_or_scripts() -> None:
    hits = _scan_repo_for_forbidden()
    assert not hits, (
        "forbidden install reference found in code/scripts "
        "(AGENTS.md 6.4 forbids):\n"
        + "\n".join(f"{p}:{ln}: {text}" for p, ln, text in hits)
    )


# 阻止旁路依赖清单进入仓库，保持 uv.lock 为依赖事实源。
def test_no_requirements_txt() -> None:
    """AGENTS.md 6.4: 仓库不得包含 requirements.txt（避免诱导他人裸装依赖）."""
    assert not (REPO_ROOT / "requirements.txt").exists()


# 多空格和制表符不得绕过全平台的 Python 合规门；目标串分开构造以免规则扫到测试本身。
@pytest.mark.parametrize("gap", [" ", "  ", "\t", " \t "])
def test_forbidden_install_detects_all_horizontal_whitespace(tmp_path, monkeypatch, gap) -> None:
    workflow = tmp_path / ".github" / "workflows" / "probe.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("pip" + gap + "install fixture\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)

    hits = _scan_repo_for_forbidden()
    assert [(path.relative_to(tmp_path), line) for path, line, _ in hits] == [
        (Path(".github/workflows/probe.yml"), 1)
    ]


# 每行独立扫描，不把跨行文本误识别为同一条安装命令。
def test_forbidden_install_does_not_join_lines(tmp_path, monkeypatch) -> None:
    (tmp_path / "probe.sh").write_text("pip" + "\n" + "install", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    assert _scan_repo_for_forbidden() == []


# 合规监视文件没有额外豁免；任何同名测试文件中的禁令也必须被发现。
def test_forbidden_install_scans_its_own_filename(tmp_path, monkeypatch) -> None:
    witness = tmp_path / "tests" / "test_compliance.py"
    witness.parent.mkdir()
    witness.write_text("pip" + "\t" + "install fixture\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    assert [(path.relative_to(tmp_path), line) for path, line, _ in _scan_repo_for_forbidden()] == [
        (Path("tests/test_compliance.py"), 1)
    ]


# notices 生成器也必须在写盘前拒绝带多空白禁用命令的发行版元数据。
def test_notices_generator_rejects_forbidden_multispace_row(tmp_path, monkeypatch) -> None:
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging" / "generate_notices.py"))
    shared = namespace["main"].__globals__
    target = tmp_path / "THIRD_PARTY_NOTICES.md"
    monkeypatch.setitem(shared, "NOTICES", target)
    monkeypatch.setitem(shared, "collect_rows", lambda: [
        {"name": "example", "version": "1", "license": "MIT", "source": "pip" + "  " + "install"}
    ])

    assert namespace["main"]([]) == 1
    assert not target.exists(), "不合规声明不得落盘"


# --- licence material and third-party notices (G2) ----------------------------------
LICENSE_FILE = REPO_ROOT / "LICENSE"
NOTICES_FILE = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
# Canonical texts fetched from gnu.org; the hashes make accidental edits loud.
COPYLEFT_TEXTS = {
    "licenses/GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "licenses/LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
}
OPENCV_THIRD_PARTY = "licenses/LICENSE-3RD-PARTY-opencv.txt"
OPENCV_THIRD_PARTY_SHA256 = "0e8fac55c2f5bff939c1e7aae1fa2799e1cece5fd0857d8e5fafeb46562aafc9"


# 仓内逐字转录和随 OpenCV wheel 分发的 FFmpeg 不属于已安装发行版表格行，必须单列。
def test_hand_maintained_notices_name_vendored_and_bundled_code() -> None:
    text = NOTICES_FILE.read_text(encoding="utf-8")
    hand, marker, _ = text.partition("## Darwin / arm64")
    assert marker, "手工声明必须位于首个平台段之前"
    for snippet in (
        "invisible-watermark", "0.2.0", "Copyright (c) 2021 ShieldMnt",
        "MIT", "https://pypi.org/project/invisible-watermark/",
        "opencv-python-headless", "4.13.0.92", "FFmpeg", "LGPL-2.1", OPENCV_THIRD_PARTY,
    ):
        assert snippet in hand, snippet

    generator = runpy.run_path(str(REPO_ROOT / "packaging" / "generate_notices.py"))
    section = generator["render_section"]([], "Darwin / arm64")
    refreshed = generator["replace_section"](text, section, "Darwin / arm64")
    assert refreshed.partition("## Darwin / arm64")[0] == hand
    assert OPENCV_THIRD_PARTY in generator["HAND_MAINTAINED_LICENSES"]

    # Linux 平台表按首轮实际镜像的完整行数/专属依赖锁定，空缺与猜测将使测试变红。
    linux = text.partition("## Linux / x86_64")[2].partition("## Windows / AMD64")[0]
    assert len([line for line in linux.splitlines() if line.startswith("| ")]) == 63
    assert "| nvidia-cublas | 13.1.1.3 |" in linux
    assert "| opencv-python-headless | 4.13.0.92 |" in linux
    assert "| PySide6 |" not in linux and "| Nuitka |" not in linux

    source = (REPO_ROOT / "src" / "photo_guard" / "_dwt_dct_svd.py").read_text(encoding="utf-8")
    doc = source.split('"""', 2)[1]
    for clause in (
        "Source: https://pypi.org/project/invisible-watermark/ 0.2.0 (MIT).",
        "Copyright (c) 2021 ShieldMnt",
        "Permission is hereby granted, free of charge",
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY',
    ):
        assert clause in doc, "仓内转录须继续携带上游 MIT 正文及署名"


# 固定上游 wheel 的完整声明，并在所有运行平台核对实际安装轮内同名原文。
def test_opencv_third_party_text_matches_installed_wheel() -> None:
    raw = (REPO_ROOT / OPENCV_THIRD_PARTY).read_bytes()
    assert len(raw) == 177835
    assert hashlib.sha256(raw).hexdigest() == OPENCV_THIRD_PARTY_SHA256
    assert raw.count(b"\n") == 3575 and b"\r" not in raw
    assert b"FFmpeg is redistributed within all opencv-python packages" in raw
    assert b"Version 2.1, February 1999" in raw

    dist = importlib.metadata.distribution("opencv-python-headless")
    assert dist.version == "4.13.0.92"
    original = dist.locate_file("cv2/LICENSE-3RD-PARTY.txt")
    assert original.is_file(), "当前平台 OpenCV wheel 缺少第三方许可原文"
    actual = original.read_bytes()
    if platform.system() == "Windows":
        # 经锁定 win_amd64 wheel 原文与随包 LF 正文相比仅有 3575 个 CR；先钉原字节，
        # 再严格比较每个字节，不能用 splitlines/strip 掩盖正文变化。
        assert len(actual) == 181410
        assert hashlib.sha256(actual).hexdigest() == (
            "55bf7d4a1de21d130a39ca38824eb61ba061edbf8449838634246bde30fde403"
        )
        assert actual == raw.replace(b"\n", b"\r\n"), "Windows wheel 原文除了换行还存在差异"
    else:
        assert actual == raw, "当前平台的 wheel 原文与随包声明不同，需逐平台裁定"


# 主项目 MIT 许可不得只保留标题或缺少免责声明。
def test_license_file_is_complete_mit_text() -> None:
    text = LICENSE_FILE.read_text(encoding="utf-8")
    assert text.splitlines()[0].strip() == "MIT License"
    assert "Copyright (c) 2026 INORI-LIN" in text
    for phrase in (
        "Permission is hereby granted, free of charge",
        "copies or substantial portions of the Software",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ):
        assert phrase in text, phrase


# 锁定原有 GPL/LGPL-3.0 正文及 LF 字节，避免平台检出改变许可证哈希。
def test_copyleft_texts_are_canonical_and_hashes_match() -> None:
    for relative, digest in COPYLEFT_TEXTS.items():
        raw = (REPO_ROOT / relative).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != digest:
            # Turn the most likely cause (a checkout that rewrote LF to CRLF) into an
            # actionable message instead of a bare hash mismatch.
            hint = ""
            if hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == digest:
                hint = (
                    " — the file was checked out with CRLF line endings; check that "
                    ".gitattributes still marks it `text eol=lf`"
                )
            raise AssertionError(f"{relative}: sha256 {actual} != {digest}{hint}")
        lines = [line.strip() for line in raw.decode("utf-8").splitlines() if line.strip()]
        assert lines[0] in {
            "GNU GENERAL PUBLIC LICENSE",
            "GNU LESSER GENERAL PUBLIC LICENSE",
        }, lines[0]
        assert lines[1] == "Version 3, 29 June 2007", lines[1]


# 许可元数据的 glob 必须继续覆盖整个 licenses 目录，包括新增第三方正文。
def test_pyproject_declares_license_and_files() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == [
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "licenses/*.txt",
    ]
    assert "classifiers" not in project


# 验证实际已安装项目的 PEP 639 元数据含新增 OpenCV 第三方声明。
def test_installed_distribution_carries_license_metadata() -> None:
    """PEP 639 fields must survive into the built metadata (G2's S1 spike, pinned)."""
    metadata = importlib.metadata.metadata("photo-guard")
    assert (metadata.get("License-Expression") or "").strip() == "MIT"
    files = set(metadata.get_all("License-File") or [])
    assert set(COPYLEFT_TEXTS) | {"LICENSE", "THIRD_PARTY_NOTICES.md", OPENCV_THIRD_PARTY} <= files, files


# 主依赖版本必须出现在声明内，手工组件段不能替代已安装依赖表格。
def test_third_party_notices_cover_core_dependencies() -> None:
    """Every core dependency must appear with the version uv.lock actually resolves."""
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = {
        package["name"].lower(): package["version"]
        for package in tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]
    }
    notices = NOTICES_FILE.read_text(encoding="utf-8").lower()
    missing = []
    for specifier in project["project"]["dependencies"]:
        name = re.split(r"[<>=!~;\[\s]", specifier.strip(), maxsplit=1)[0].lower()
        row = f"| {name} | {lock[name]} |"
        if row not in notices:
            missing.append(row)
    assert not missing, missing


# 模型声明须继续绑定实际下载仓库及不可变 revision。
def test_sd_vae_notice_is_mit_and_pinned_to_the_configured_repo() -> None:
    from photo_guard import config

    notices = NOTICES_FILE.read_text(encoding="utf-8")
    rows = [line for line in notices.splitlines() if config.PHOTOGUARD_REMOTE_REPO in line]
    assert rows, "no notice row mentions the configured model repo"
    assert any("| MIT |" in row for row in rows), rows
    # P15: the row must carry the revision both sides pin to, so the notice cannot drift.
    assert any(config.PHOTOGUARD_REVISION in row for row in rows), rows


# 检查 Windows/macOS 打包链仍携带目录和手工许可材料。
def test_packaging_wires_license_material() -> None:
    # 先钉桌面构建参数与安装器/DMG 的整个许可目录，避免只把文本留在源码树。
    build = (REPO_ROOT / "packaging" / "build_desktop.py").read_text(encoding="utf-8")
    for fragment in (
        "--include-data-dir={ROOT / 'licenses'}=licenses",
        "--include-data-files={ROOT / 'LICENSE'}=LICENSE",
        "--include-data-files={ROOT / 'THIRD_PARTY_NOTICES.md'}=THIRD_PARTY_NOTICES.md",
    ):
        assert fragment in build, fragment
    iss = (REPO_ROOT / "packaging" / "windows-installer.iss").read_text(encoding="utf-8")
    assert "LicenseFile=..\\LICENSE" in iss
    dmg = (REPO_ROOT / "packaging" / "create_dmg.sh").read_text(encoding="utf-8")
    assert "THIRD_PARTY_NOTICES.md" in dmg and "licenses" in dmg
    # 然后分别约束两份 wheel 的元数据与两平台 bundle 探针，不允许新许可漏包仍报成功。
    wheel_smoke = (REPO_ROOT / "packaging" / "smoke_wheel.sh").read_text(encoding="utf-8")
    assert wheel_smoke.count(f'"{OPENCV_THIRD_PARTY}"') == 2, "两份 wheel 都必须锁新增许可"
    release = (REPO_ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(encoding="utf-8")
    assert release.count("LICENSE-3RD-PARTY-opencv.txt") == 2, "两平台打包探针都必须找许可文件"
    # 最后确认镜像不仅拷入许可目录，还保留可在真环境比对 Linux 行的生成器。
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY licenses/ /app/licenses/" in dockerfile
    assert "COPY packaging/generate_notices.py /app/packaging/" in dockerfile


