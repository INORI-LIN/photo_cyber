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

X1 (P75/P76) adds the same kind of locks for the bundle smoke steps: the Windows step must
read the GUI-subsystem executable's real exit code through ``Start-Process``, both steps
run a negative control that must fail with exactly 2 before the real smoke, macOS exits
with the smoke's own code, and both build legs carry timeouts.

The failure branches are pinned by what they exit with and the result variables by where they
are assigned: a presence check on the comparison text alone let ``exit 0`` in a branch, an
extra ``exit``/``return``, or a later ``rc=0`` turn a failing smoke into a green step.
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
    # X1：唯一性照旧按整段 step 文本计；命中还必须落在可执行行里——注释里为排查保留的旧写法
    # 不能替真实脚本作证（只剩注释提到 marker 时，旧实现会照样返回这个 step）。
    assert marker in _code(matches[0]), f"{marker!r} only occurs in comments of the {job!r} step"
    return matches[0]


# 只读可执行行，旧失效命令可能仍保留在注释中供排查。
def _code(step: str) -> str:
    """The step's executable lines (comments may mention the old, broken invocations)."""
    return "\n".join(line for line in step.splitlines() if not line.lstrip().startswith("#"))


# PowerShell 以行尾反引号续行；拼回一行后，一条命令的开关不论怎么折行都按同一条调用检查。
def _join_continuations(code: str) -> str:
    """Fold PowerShell backtick line continuations into single logical lines."""
    return re.sub(r"`\n[ \t]*", " ", code)


# 引号里的文案（如 "::error::… must exit 2"）不是命令：先清空引号内容，再判断一行是否真的执行了某个词。
def _unquoted(line: str) -> str:
    """The line with every quoted string emptied, so message text cannot pass for a command."""
    quotes = r'"[^"]*"|\'[^\']*\''
    return re.sub(quotes, '""', line).partition(" #")[0]


# 只看 run: | 块里的脚本：步骤名（name:）里提到 exit code 之类不影响命令清单。
def _run_block(step: str) -> str:
    """The step's script body (everything after ``run: |``), comments excluded."""
    _, _, body = step.partition("run: |")
    return _code(body)


# bash 的 if 块按整行表头定位（`elif …` 也含 "if "，按子串找会认错块），块体取到第一行 fi 为止。
def _bash_if_block(code: str, header: str) -> list[str]:
    """Stripped body lines of the single bash ``if`` block whose header line is exactly ``header``.

    A closer may carry a trailing ``;`` or comment (``fi # …``); a ``fi`` inside a message is
    quoted, so it never closes a block.
    """
    lines = [line.strip() for line in code.splitlines()]
    starts = [i for i, line in enumerate(lines) if line == header]
    assert len(starts) == 1, f"expected one {header!r} line, got {len(starts)}"
    body = lines[starts[0] + 1 :]
    closers = [i for i, line in enumerate(body) if re.fullmatch(r"fi\s*(?:;.*)?", _unquoted(line))]
    assert closers, f"no bare 'fi' closes {header!r}"
    return body[: closers[0]]


# 真正执行 exit 的行（引号外的 exit 一词）：分支与整步都只许出现预期的那几处退出。
def _bash_exits(lines: list[str]) -> list[str]:
    """Stripped lines that run ``exit``."""
    return [line.strip() for line in lines if re.search(r"(?<![\w-])exit\b", _unquoted(line))]


# 给 shell 变量 name 赋值的行：行首，或空白与 ; & | ( 之后的 `name=`。
def _bash_assignments(lines: list[str], name: str) -> list[str]:
    """Stripped lines that assign the shell variable ``name``."""
    pattern = rf"(?:^|[\s;&|(]){re.escape(name)}="
    return [line.strip() for line in lines if re.search(pattern, _unquoted(line))]


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
        assert "actions/upload-artifact@v7" in build
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
        assert "actions/download-artifact@v8" in step
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


# P23：ISCC 必须先解析再调用；缺失时由 resolver 与显式退码检查共同响亮失败。
def test_windows_installer_resolves_iscc_before_building() -> None:
    locate = _code(_step_containing("find_iscc.py", job="windows"))
    assert "uv run --no-sync python packaging\\find_iscc.py" in locate
    assert "$LASTEXITCODE" in locate and "throw" in locate
    assert "GITHUB_ENV" in locate

    build = _code(_step_containing("windows-installer.iss", job="windows"))
    assert "C:\\Program Files" not in build
    assert "$env:ISCC" in build
    assert build.index("$env:ISCC") < build.index("$LASTEXITCODE")


# P69：两条构建腿必须在本 OS 的发布依赖集上跑 fast 档，红了按缺陷修而不是排除。
def test_build_legs_run_the_fast_tier_before_packaging() -> None:
    for job in ("windows", "macos-arm64"):
        text = _job(job)
        assert "--group dev" in text, job
        step = _step_containing("pytest -m 'not slow' -q", job=job)
        assert "uv run --no-sync pytest -m 'not slow' -q" in _code(step)
        # 测试必须在 Nuitka 打包之前：失败应在几十秒内出现，而不是等一轮构建。
        assert text.index("pytest -m 'not slow' -q") < text.index("build_desktop.py"), job

    # offscreen 是显式设置的：Windows 走 pwsh 赋值，macOS 走 step env。
    assert '$env:QT_QPA_PLATFORM = "offscreen"' in _code(
        _step_containing("pytest -m 'not slow' -q", job="windows")
    )
    assert "QT_QPA_PLATFORM: offscreen" in _step_containing(
        "pytest -m 'not slow' -q", job="macos-arm64"
    )


# P69：构建成功但零产物时 upload-artifact 默认只警告，发布 job 才会晚失败。
def test_build_legs_refuse_empty_artifacts() -> None:
    for job in ("windows", "macos-arm64"):
        step = _step_containing("actions/upload-artifact@v7", job=job)
        assert "if-no-files-found: error" in step, job


# P69：bundle 的 smoke 必须同时证明 Qt 与 SD 运行时在包里真的可用。
def test_build_legs_smoke_the_gui_and_photoguard_runtimes() -> None:
    for job in ("windows", "macos-arm64"):
        code = _code(_step_containing("--smoke-test", job=job))
        assert "--with-photoguard" in code, job
        assert "--with-gui" in code, job


# P75：PhotoGuard.exe 以 --windows-console-mode=disable 构建，是 GUI 子系统程序；PowerShell
# 裸调用它既不等待也不设 $LASTEXITCODE——run 44473940993 打印了退 5 文案，这一步仍判绿。
def test_windows_smoke_reads_the_real_exit_code_through_start_process() -> None:
    step = _step_containing("--smoke-test", job="windows")
    assert "shell: powershell" in step
    code = _join_continuations(_code(step))
    lines = code.splitlines()

    calls = [line for line in lines if "Start-Process" in line]
    assert len(calls) == 1, f"expected one Start-Process call, got {calls}"
    for flag in (
        "-FilePath",
        "-ArgumentList",
        "-NoNewWindow",
        "-Wait",
        "-PassThru",
        "-RedirectStandardOutput",
        "-RedirectStandardError",
    ):
        assert re.search(rf"(?<![\w-]){flag}(?![\w-])", calls[0]), flag
    # Start-Process 不走 PowerShell 的命令查找，可执行文件给绝对路径。
    assert "Resolve-Path" in code
    assert code.index("function Invoke-Smoke") < code.index("Start-Process")
    # 两份重定向文件都要回显进日志，且必须经 Out-Host：函数里任何没接住的输出都会混进返回值。
    for flag in ("-RedirectStandardOutput", "-RedirectStandardError"):
        target = re.search(rf"{flag}\s+(\$\w+)", calls[0])
        assert target is not None, flag
        assert any(
            "Get-Content" in line
            and target.group(1) in line
            and line.rstrip().endswith("| Out-Host")
            for line in lines
        ), f"the {flag} file is not echoed through Out-Host"
    # 取不到 ExitCode 必须响亮失败，不能当成 0 放行；取到的码要打印进日志。
    assert re.search(r"\$null\s+-eq\s+\$\w+\.ExitCode\s*\)\s*\{\s*throw\b", code)
    assert re.search(r'Write-Host "\$\{?Label\}? exit code: ', code)
    # 两处调用都校验返回值是 [int]：被污染的返回（数组或 $null）不能比较成通过。
    assert code.count("-isnot [int]") >= 2

    # 旧的裸调用（含 & 调用运算符）不得回到可执行行；带 --smoke-test 的行一律经 Invoke-Smoke。
    for line in lines:
        command = line.strip()
        if command.startswith("run:"):
            command = command[len("run:"):].strip()
        assert not command.startswith("&"), line
        assert not re.match(r"""["']?[^\s"']*PhotoGuard\.exe(?![\w.])""", command), line
    smoke = [line for line in lines if "--smoke-test" in line]
    assert smoke and all("Invoke-Smoke" in line for line in smoke), smoke
    # 双引号里的 "$Label:" 会被解析成驱动器限定变量（要写 "${Label}:"）；这一步只该出现 $env:。
    assert set(re.findall(r"\$(\w+):", code)) <= {"env"}, re.findall(r"\$\w+:", code)


# P75/P76：负控与正式 smoke 在同一 step 且先跑：资源根指向空目录（模型与许可都缺），首个
# 失败码恰为 2——证明这一步看得见失败退码；退 0 或别的码都说明判定链本身失灵。
def test_build_leg_smokes_run_a_negative_control_first() -> None:
    for job in ("windows", "macos-arm64"):
        code = _code(_step_containing("--smoke-test", job=job))
        runs = [line for line in code.splitlines() if "--smoke-test" in line]
        assert len(runs) >= 2, f"{job}: the negative control must run inside the smoke step"
        negative, real = runs[0], runs[-1]
        assert "--with-" not in negative, f"{job}: the negative control runs only --smoke-test"
        assert "--with-photoguard" in real and "--with-gui" in real, job
        assert code.index("PHOTO_GUARD_RESOURCE_DIR") < code.index("--with-photoguard"), job
        assert "-ne 2" in code, f"{job}: the negative control must exit exactly 2"

    # Windows：先设变量、跑负控，finally 里置回 $null，之后才跑正式 smoke。
    windows = _run_block(_step_containing("--smoke-test", job="windows"))
    # 只认这一条失败通道：$ErrorActionPreference 改宽（throw 变通知）、trap 吞错、try/catch
    # 不重抛，都会让失败静默通过；这几种写法出现即红。
    assert not re.search(r"(?i)\$ErrorActionPreference\s*=", _unquoted(windows))
    assert not re.search(r"(?i)(?<![\w$.-])trap\b", _unquoted(windows))
    assert not re.search(r"(?i)(?<![\w$.-])catch\b", _unquoted(windows))
    runs = [line for line in windows.splitlines() if "--smoke-test" in line]
    assign = re.search(r"\$env:PHOTO_GUARD_RESOURCE_DIR\s*=\s*(?!\$null\b)\S", windows)
    reset = re.search(
        r"finally\s*\{[^}]*\$env:PHOTO_GUARD_RESOURCE_DIR\s*=\s*\$null[^}]*\}", windows
    )
    assert assign is not None, "the negative control must point the resource root somewhere"
    assert reset is not None, "the resource override must be cleared in a finally block"
    assert assign.start() < windows.index(runs[0]) < reset.start() < windows.index(runs[-1])
    assert '-Label "negative-control"' in runs[0] and '-Label "smoke"' in runs[-1]
    # 比较的必须是各自调用接住的那个返回值：负控恰为 2，正式 smoke 恰为 0，否则 throw。
    for run, expected in ((runs[0], 2), (runs[-1], 0)):
        captured = re.match(r"\s*(\$\w+)\s*=\s*Invoke-Smoke\b", run)
        assert captured is not None, run
        name = re.escape(captured.group(1))
        assert re.search(rf"if \(.*{name} -ne {expected}\) \{{\s*throw\b", windows), run
        # 接住返回值的只能是这一次调用：之后再写一句 `$rc = 0`（变量名不分大小写，复合赋值同理）
        # 就会把失败改判成通过。
        assigned = [
            line
            for line in windows.splitlines()
            if re.search(rf"(?i)(?:^|[;{{(])\s*{name}\s*[-+*/%]?=", _unquoted(line))
        ]
        assert assigned == [run], assigned
    # 这一步只能经 throw 失败，或跑完正式 smoke 后自然结束：除函数自己的 `return $code` 外再出现
    # exit/return（如负控检查之后插一句 exit 0）都会跳过正式 smoke 判绿。关键字同样不分大小写。
    leaves = [
        line.strip()
        for line in windows.splitlines()
        if re.search(r"(?i)(?<![\w$.-])(?:exit|return)\b", _unquoted(line))
    ]
    assert leaves == ["return $code"], leaves

    # macOS：变量只作负控那一条命令的前缀，不得 export 给正式 smoke。
    macos = _run_block(_step_containing("--smoke-test", job="macos-arm64"))
    runs = [line.strip() for line in macos.splitlines() if "--smoke-test" in line]
    assert runs[0].startswith("PHOTO_GUARD_RESOURCE_DIR="), runs[0]
    assert [line.strip() for line in macos.splitlines() if "PHOTO_GUARD_RESOURCE_DIR" in line] == [runs[0]]
    # 两条命令都必须就是它们应有的形状：负控只带 --smoke-test 接住 `|| neg=$?`，正式 smoke
    # 带两个 --with- 接住 `|| rc=$?`。前面加 `true ||`、`echo`、`|| true ||` 或把命令换掉都红。
    assert re.fullmatch(
        r'PHOTO_GUARD_RESOURCE_DIR="\$\w+"\s+"\$BIN"\s+--smoke-test\s+\|\|\s+neg=\$\?', runs[0]
    ), runs[0]
    assert re.fullmatch(r'"\$BIN"\s+--smoke-test\s+--with-photoguard\s+--with-gui\s+\|\|\s+rc=\$\?', runs[-1]), runs[-1]
    assert re.search(r'\[ "\$neg" -ne 2 \]', macos)
    assert 'echo "negative-control exit code: $neg"' in macos
    # 负控结果只在两处赋值：先置 0，再由负控那条命令的 `|| neg=$?` 接住；之后再赋值（如 neg=2）
    # 或干脆 unset 掉换别的变量判定（后者已由上面两条命令的形状锁住）都会放行。
    assert _bash_assignments(macos.splitlines(), "neg") == ["neg=0", runs[0].strip()]
    # neg 只出现在这五条上（引号内的引用也算）：两处赋值、那句 echo、判定与 ::error::。
    mentions = [
        line.strip() for line in macos.splitlines() if re.search(r"(?<!\w)neg\b", line)
    ]
    assert mentions == [
        "neg=0",
        runs[0].strip(),
        'echo "negative-control exit code: $neg"',
        'if [ "$neg" -ne 2 ]; then',
        'echo "::error::negative control must exit 2 (bundle model missing), got $neg"',
    ], mentions
    # 负控失败的分支必须以 exit 1 收尾：删掉 exit、改成 exit 0（正式 smoke 被跳过、整步判绿）或只
    # 降级成 ::warning:: 都会放行。
    branch = _bash_if_block(macos, 'if [ "$neg" -ne 2 ]; then')
    assert _bash_exits(branch) == ["exit 1"] and branch[-1] == "exit 1", branch


# P76：macOS 旧写法 `if ! "$BIN" …; then … exit 1` 把所有非零退码压成 1；须打印并以原码退出。
def test_macos_smoke_keeps_the_original_exit_code() -> None:
    step = _step_containing("--smoke-test", job="macos-arm64")
    code = _run_block(step)
    # 整段 step（含注释）都不得再出现旧写法，免得有人照注释抄回去。
    assert 'if ! "$BIN"' not in step
    real = [line for line in code.splitlines() if "--with-photoguard" in line]
    assert len(real) == 1, real
    assert real[0].rstrip().endswith("|| rc=$?"), real[0]
    # 经管道（如 tee）时 $? 是管道末段的状态，不再是 smoke 自己的码。
    # 这一步没写 shell:，GitHub 以 `bash -e {0}` 运行（不开 pipefail；显式 `shell: bash` 才是 -eo pipefail）。
    assert "|" not in real[0].split("||")[0], real[0]
    initial = re.search(r"(?m)^[ \t]*rc=0[ \t]*$", code)
    assert initial is not None and initial.start() < code.index(real[0])
    assert 'echo "smoke exit code: $rc"' in code
    assert re.search(r'(?m)^[ \t]*if \[ "\$rc" -ne 0 \]; then$', code)
    assert 'exit "$rc"' in code
    # 布局转储保留，且在以原码退出之前。
    assert code.index('ls -la "$APP/Contents"') < code.index('exit "$rc"')
    # smoke 码只在两处赋值：先置 0，再由正式 smoke 的 `|| rc=$?` 接住；之后再写 rc=0 或
    # `(( rc = 0 ))` 会把失败改判成通过。
    assert _bash_assignments(code.splitlines(), "rc") == ["rc=0", real[0].strip()]
    # rc 只出现在这五处（引号内的引用也算）：两处赋值、那句 echo、判定与退出。`unset rc`、
    # `printf -v rc` 之类出现即红。
    mentions = [
        line.strip() for line in code.splitlines() if re.search(r"(?<!\w)rc\b", line)
    ]
    assert mentions == [
        "rc=0",
        real[0].strip(),
        'echo "smoke exit code: $rc"',
        'if [ "$rc" -ne 0 ]; then',
        'echo "::error::smoke test failed (exit $rc) — dumping layout for diagnosis"',
        'exit "$rc"',
    ], mentions
    # 失败分支先转储、最后以原码退出，且这是分支里唯一的退出：在转储前插一句 exit 1 就回到 P76。
    branch = _bash_if_block(code, 'if [ "$rc" -ne 0 ]; then')
    assert _bash_exits(branch) == ['exit "$rc"'] and branch[-1] == 'exit "$rc"', branch
    # 整步只有这两处退出；别处再插 exit（如负控检查之后 exit 0）会跳过正式 smoke 判绿。
    assert _bash_exits(code.splitlines()) == ["exit 1", 'exit "$rc"']


# P76：两条构建腿实测 macOS 3h02m、Windows 约 2h50m，原先都没有超时，一次挂起会烧满托管
# runner 的 6 小时上限；Start-Process -Wait 自己也没有超时，所以 smoke 步另设 30 分钟。
def test_build_legs_and_their_smoke_steps_have_timeouts() -> None:
    for job in ("windows", "macos-arm64"):
        # job 级键缩进 4 格；step 级键缩进 8 格，不会被这条正则误收。
        values = re.findall(r"(?m)^    timeout-minutes: (\d+)[ \t]*$", _job(job))
        assert len(values) == 1, f"{job}: expected one job-level timeout-minutes, got {values}"
        assert 0 < int(values[0]) < 360, f"{job}: {values[0]} must stay below the 6-hour limit"
        step = _step_containing("--smoke-test", job=job)
        assert re.findall(r"(?m)^        timeout-minutes: (\d+)[ \t]*$", step) == ["30"], job
