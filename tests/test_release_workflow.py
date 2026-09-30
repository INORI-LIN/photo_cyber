"""G9 — static pins for the release workflow's checksum steps.

Neither leg can be executed from a developer machine (one needs Windows PowerShell, the other
a macOS runner), and both were broken by the same mechanism at different times: the shell
opens the redirection target *before* it runs the command, so enumerating the output
directory re-reads the file being written. The Windows step failed outright on
windows-latest 2026-09-29 (``… being used by another process`` → exit 1 → the upload and
release steps were skipped); the macOS step had the same shape and additionally wrote a name
the other platform also used.

These assertions pin the invariants that let the steps run at all — output excluded from the
enumeration, explicit encoding, distinct per-platform filenames — rather than the exact
wording of either script.
"""
from __future__ import annotations

import re
from pathlib import Path

RELEASE = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "release-desktop.yml"
).read_text(encoding="utf-8")


# 只按 YAML step 的固定缩进切分，避免脚本内容中的连字符误分段。
def _steps(text: str) -> list[str]:
    """Split a job's step list on the 6-space ``- `` that starts each step."""
    parts = text.split("\n      - ")
    return [parts[0], *parts[1:]]


# 将静态检查限制在目标 job，发布 job 重复引用校验和文件名不应影响生成步骤定位。
def _job(name: str) -> str:
    """只取指定 job；发布 job 会再次引用两个平台的校验和文件名。"""
    marker = f"\n  {name}:\n"
    assert RELEASE.count(marker) == 1, f"expected one {name!r} job"
    remainder = RELEASE.split(marker, 1)[1]
    return re.split(r"\n  [\w-]+:\n", remainder, maxsplit=1)[0]


# 同一 job 内应只命中一个步骤；重复生成校验和的步骤必须响亮失败。
def _step_containing(marker: str, *, job: str) -> str:
    """在指定 job 内定位唯一的 step，避免跨 job 同名文本误匹配。"""
    matches = [step for step in _steps(_job(job)) if marker in step]
    assert len(matches) == 1, f"expected one {job!r} step containing {marker!r}, got {len(matches)}"
    return matches[0]


# 只读可执行行，旧失效命令可能仍保留在注释中供排查。
def _code(step: str) -> str:
    """The step's executable lines (comments may mention the old, broken invocations)."""
    return "\n".join(line for line in step.splitlines() if not line.lstrip().startswith("#"))


# 防止 Windows 校验和步骤把正在写入的清单再次纳入哈希输入。
def test_windows_checksum_step_excludes_its_own_output() -> None:
    code = _code(_step_containing("SHA256SUMS-Windows-x64.txt", job="windows"))
    assert "$_.Name -notlike 'SHA256SUMS*'" in code
    # Enumerate first, write second: the old one-liner opened the (globbed) output file
    # before hashing it, which is what produced "being used by another process".
    assert "Get-FileHash release\\*" not in code
    assert code.index("$sums =") < code.index("WriteAllText")


# 锁住发布清单可被标准校验工具读取的 ASCII 与 LF 格式。
def test_windows_checksum_step_writes_plain_ascii_lf() -> None:
    code = _code(_step_containing("SHA256SUMS-Windows-x64.txt", job="windows"))
    # `Out-File` defaults to UTF-16 + CRLF + a table layout; nothing else can parse that.
    assert "WriteAllText" in code
    assert "[System.Text.Encoding]::ASCII" in code
    assert "Out-File" not in code
    assert '$sums -join "`n"' in code, "line endings must be explicit LF"


# macOS 生成步骤也必须避免自包含，并保留对带空格文件名的引号保护。
def test_macos_checksum_step_uses_the_same_guards() -> None:
    # 只在 macOS 构建 job 内检查枚举防护；发布 job 会复用校验和文件名。
    code = _code(_step_containing("SHA256SUMS-macOS-arm64.txt", job="macos-arm64"))
    assert 'case "$f" in SHA256SUMS*)' in code
    assert "cd release && for f in *" in code
    assert '"$f"' in code, "quote the loop variable: a future artifact name may hold a space"


# 两平台必须保留不同清单名，避免同一 Release 中后上传者覆盖前者。
def test_the_two_platforms_do_not_share_a_checksum_filename() -> None:
    """两个平台的校验和汇总到同一 Release，同名文件会被后上传者覆盖。"""
    windows = _code(_step_containing("SHA256SUMS-Windows-x64.txt", job="windows"))
    macos = _code(_step_containing("SHA256SUMS-macOS-arm64.txt", job="macos-arm64"))

    assert "SHA256SUMS-Windows-x64.txt" in windows
    assert "SHA256SUMS-macOS-arm64.txt" in macos
    assert "SHA256SUMS.txt" not in windows
    assert "SHA256SUMS.txt" not in macos


# 发布前 GUI 门必须实际执行用例且拒绝跳过，不能仅靠安装 PySide6。
def test_release_verify_requires_real_gui_tests_before_building() -> None:
    """tag 链必须安装 Qt 并执行 GUI 档，不能用 importorskip 或零用例假绿。"""
    verify = _job("verify")
    assert "uv sync --frozen --group dev\n" in verify
    assert "pytest -m 'not slow' -q" in verify
    assert 'if [ "${GITHUB_REF_TYPE}" = "tag" ]' in verify
    assert "apt-get install" in verify and "libxkbcommon0" in verify
    assert "uv sync --frozen --group dev --extra desktop" in verify
    assert 'uv run --no-sync python -c "import PySide6"' in verify
    # 有 passed 且无 skipped 才允许构建；仅 import 成功仍可能被 importorskip 绕过。
    gui = _code(_step_containing("pytest -m gui -q", job="verify"))
    assert "QT_QPA_PLATFORM=offscreen uv run --no-sync pytest -m gui -q" in gui
    assert "set -euo pipefail" in gui and "tee" in gui
    assert any(
        line.strip() == 'QT_QPA_PLATFORM=offscreen uv run --no-sync pytest -m gui -q | tee "$RUNNER_TEMP/gui-pytest.log"'
        for line in gui.splitlines()
    )
    assert "|| true" not in gui, "GUI 测试失败不得被管道吞掉"
    assert "grep -Eq" in gui and "[1-9][0-9]* passed" in gui
    assert "[1-9][0-9]* skipped" in gui and "exit 1" in gui
    assert "uv run --no-sync photo-guard-gui --help" in verify
    assert verify.index("--extra desktop") < verify.index('python -c "import PySide6"')
    assert verify.index('python -c "import PySide6"') < verify.index("pytest -m gui -q")


# 锁住 tag push 独占发布权与双平台/GUI 前置条件，手工 dispatch 不得误发。
def test_only_tag_pushes_publish_after_both_platforms_and_verify() -> None:
    """构建 job 只产出 artifact；仅 tag push 的串行发布 job 有写权限。"""
    # 先锁两条构建腿的只读范围，再锁唯一发布 job 的 tag 触发和依赖关系。
    for job, artifact in (
        ("windows", "PhotoGuard-Windows-x64"),
        ("macos-arm64", "PhotoGuard-macOS-arm64"),
    ):
        build = _job(job)
        assert "needs: verify" in build
        assert "actions/upload-artifact@v4" in build
        assert f"name: {artifact}" in build
        assert "contents: write" not in build
        assert "gh release" not in _code(build)

    publish = _job("publish")
    assert re.findall(r"(?m)^    if: (.+)$", publish) == [
        "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')"
    ], "发布条件必须是真正生效的 job if，不能只出现在注释中"
    assert "needs: [verify, windows, macos-arm64]" in publish
    assert "contents: write" in publish
    assert RELEASE.count("contents: write") == 1
    assert "GH_TOKEN: ${{ github.token }}" in publish
    assert "GH_REPO: ${{ github.repository }}" in publish
    assert publish.count("gh release create") == 1
    assert publish.count("gh release upload") == 1
    assert "--clobber" in publish


# 上传前逐平台核验预期文件、清单成员和字节哈希，禁止只验证文件存在。
def test_publish_checks_each_download_before_upload() -> None:
    """独立下载两份 artifact，按原目录验文件与校验和，再逐一上传。"""
    windows = _step_containing("name: PhotoGuard-Windows-x64", job="publish")
    macos = _step_containing("name: PhotoGuard-macOS-arm64", job="publish")
    for step, directory in ((windows, "windows"), (macos, "macos-arm64")):
        assert "actions/download-artifact@v4" in step
        assert f"path: release/{directory}" in step

    # 文件存在但未列入清单也不能算已验证；两份清单必须在各自目录核对。
    publish = _job("publish")
    for directory, filename, checksum in (
        ("windows", "PhotoGuard-Windows-x64-Setup.exe", "SHA256SUMS-Windows-x64.txt"),
        ("macos-arm64", "PhotoGuard-macOS-arm64.dmg", "SHA256SUMS-macOS-arm64.txt"),
    ):
        assert f"test -s release/{directory}/{filename}" in publish
        assert f"test -s release/{directory}/{checksum}" in publish
        assert f"{filename}$'" in publish, "预期文件必须列在其平台校验清单中"
        assert f"(cd release/{directory} && sha256sum -c {checksum})" in publish
        assert f"release/{directory}/{filename}" in publish.split("gh release upload", 1)[1]
        assert f"release/{directory}/{checksum}" in publish.split("gh release upload", 1)[1]
    assert publish.index("sha256sum -c SHA256SUMS-macOS-arm64.txt") < publish.index("gh release upload")


# 要求直接构建和 sdist 重建的 wheel 各自进入隔离环境，不允许源码树冒充。
def test_wheel_smoke_installs_both_built_wheels_not_the_source_tree() -> None:
    """G10：源码树 sync 与检查压缩包清单都不能证明两个 wheel 可安装。"""
    script = (Path(__file__).resolve().parents[1] / "packaging" / "smoke_wheel.sh").read_text(
        encoding="utf-8"
    )
    code = _code(script).replace("\\\n", " ")
    rebuilt = re.search(r"(?m)^([A-Z][A-Z0-9_]*)=.*from-sdist/\*\.whl", code)
    assert rebuilt is not None, "sdist 重建的 wheel 必须有可安装的路径"

    # 两个产物分别进入不同 venv，helper 必须把收到的 wheel 写入安装输入。
    calls = re.findall(r'(?m)^smoke_distribution "(\$[A-Z_]+)" "([^"]+)"$', code)
    built = [venv for wheel, venv in calls if wheel == "$WHEEL"]
    from_sdist = [venv for wheel, venv in calls if wheel == f"${rebuilt.group(1)}"]
    assert len(built) == len(from_sdist) == 1, "必须分别安装直接构建与重建的 wheel"
    assert built[0] != from_sdist[0], "两个 wheel 不得共用同一安装环境"
    helper = re.search(r"(?ms)^smoke_distribution\(\) \{(.*?)^\}", code)
    assert helper is not None
    body = helper.group(1)
    assert '"$UV" venv --managed-python --python 3.11 "$venv"' in body
    assert 'printf \'%s\\n\' "$wheel" >> "$TMP/requirements.txt"' in body
    assert re.search(
        r'"\$UV"\s+pip\s+sync\s+--python\s+"\$venv/bin/python"\s+'
        r'--strict\s+"\$TMP/requirements.txt"', body
    ), "安装命令必须实际消费包含该 wheel 的输入"
    assert body.index('"$wheel" >>') < body.index('"$UV" pip sync')
    assert body.index('"$UV" pip sync') < body.index("import photo_guard")
    assert "License-Expression" in body and 'photo-guard" --help' in body
