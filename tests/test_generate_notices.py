"""G7 — pure functions and main paths of ``packaging/generate_notices.py``.

The script is loaded by path (``packaging/`` is not an importable package).
Every ``main`` test redirects ``NOTICES``/``ROOT`` to ``tmp_path`` so the real
``THIRD_PARTY_NOTICES.md`` is never read or written.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "packaging" / "generate_notices.py"


def _load():
    spec = importlib.util.spec_from_file_location("pg_generate_notices_f2", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Meta:
    def __init__(self, **fields) -> None:
        self.fields = fields

    def __getitem__(self, key):
        return self.fields[key]

    def get(self, key, default=None):
        return self.fields.get(key, default)

    def get_all(self, key):
        value = self.fields.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


class _Dist:
    def __init__(self, name: str, version: str, **fields) -> None:
        self.metadata = _Meta(Name=name, **fields)
        self.version = version


def _row(name: str = "alpha", version: str = "1.0") -> dict[str, str]:
    return {"name": name, "version": version, "license": "MIT", "source": "https://example.test"}


def test_platform_tag_uses_system_and_machine(monkeypatch) -> None:
    module = _load()
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    assert module.platform_tag() == "Linux / x86_64"


def test_collect_rows_filters_project_and_sorts(monkeypatch) -> None:
    module = _load()
    distributions = [
        _Dist("zeta", "2.0", License="MIT", **{"Home-page": "https://zeta.example"}),
        _Dist("photo-guard", "0.1.0"),
        _Dist(
            "alpha",
            "1.0",
            **{
                "License-Expression": "Apache-2.0",
                "Project-URL": ["Source, https://alpha.example"],
            },
        ),
    ]
    monkeypatch.setattr(module.md, "distributions", lambda: distributions)

    rows = module.collect_rows()
    assert [row["name"] for row in rows] == ["alpha", "zeta"]
    assert rows[0]["license"] == "Apache-2.0"
    assert rows[0]["source"] == "https://alpha.example"
    assert rows[1]["source"] == "https://zeta.example"
    assert all(set(row) == {"name", "version", "license", "source"} for row in rows)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"License-Expression": "MIT"}, "MIT"),
        ({"License": "BSD-3-Clause"}, "BSD-3-Clause"),
        (
            {"Classifier": ["License :: OSI Approved :: Apache Software License"]},
            "Apache Software License",
        ),
        ({}, "declared in package metadata"),
    ],
)
def test_license_precedence(fields, expected) -> None:
    module = _load()
    assert module._license_of(_Meta(**fields)) == expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"Home-page": "https://home.example"}, "https://home.example"),
        ({"Project-URL": ["Source, https://source.example"]}, "https://source.example"),
        ({"Author-email": "author@example.test"}, "author@example.test"),
        ({}, "unknown"),
    ],
)
def test_source_precedence(fields, expected) -> None:
    module = _load()
    assert module._source_of(_Meta(**fields)) == expected


def test_compare_section_reports_missing_and_extra() -> None:
    module = _load()
    tag = "Test / x86_64"
    first, second = _row("alpha", "1"), _row("beta", "2")

    missing, extra = module.compare_section(
        module.render_section([first], tag), [first, second], tag
    )
    assert missing == [module.render_row(second)] and extra == []

    missing, extra = module.compare_section(
        module.render_section([first, second], tag), [first], tag
    )
    assert missing == [] and extra == [module.render_row(second)]


def test_replace_section_appends_when_absent() -> None:
    module = _load()
    text = "# Third-party notices\n\n## Hand-maintained\n\nmanual\n"
    section = module.render_section([_row()], "Test / x86_64")

    result = module.replace_section(text, section, "Test / x86_64")
    assert "## Hand-maintained" in result
    assert "manual" in result
    assert section.strip() in result


def _check_fixture(monkeypatch, tmp_path, rows, *, stale: bool = False):
    module = _load()
    root = tmp_path / "root"
    root.mkdir()
    relative = (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "licenses/GPL-3.0.txt",
        "licenses/LGPL-3.0.txt",
        "licenses/LICENSE-3RD-PARTY-opencv.txt",
    )
    for name in relative:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub\n", encoding="utf-8")

    tag = "Test / x86_64"
    notices = root / "THIRD_PARTY_NOTICES.md"
    written_rows = rows[:1] if stale else rows
    notices.write_text(module.render_section(written_rows, tag), encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "NOTICES", notices)
    monkeypatch.setattr(module, "HAND_MAINTAINED_LICENSES", relative)
    monkeypatch.setattr(module, "platform_tag", lambda: tag)
    monkeypatch.setattr(module, "collect_rows", lambda: rows)
    return module, root, notices


def test_check_passes_when_current(monkeypatch, tmp_path, capsys) -> None:
    module, _, _ = _check_fixture(monkeypatch, tmp_path, [_row()])
    assert module.main(["--check"]) == 0
    assert "notices OK" in capsys.readouterr().out


def test_check_fails_when_stale(monkeypatch, tmp_path, capsys) -> None:
    module, _, _ = _check_fixture(
        monkeypatch, tmp_path, [_row("alpha", "1"), _row("beta", "2")], stale=True
    )
    assert module.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "stale" in err and "missing:" in err


def test_check_fails_when_licence_material_missing(monkeypatch, tmp_path, capsys) -> None:
    module, root, _ = _check_fixture(monkeypatch, tmp_path, [_row()])
    (root / "LICENSE").unlink()
    assert module.main(["--check"]) == 1
    assert "licence material missing" in capsys.readouterr().err


def test_write_rewrites_only_current_section(monkeypatch, tmp_path, capsys) -> None:
    module = _load()
    tag = "Test / x86_64"
    manual = "## Hand-maintained\n\nmanual text\n"
    other = "## Other / arm64\n\n| name | version | license | source |\n|---|---|---|---|\n| x | 1 | MIT | u |\n"
    old = _row("old", "0")
    new = _row("new", "1")

    root = tmp_path / "root"
    root.mkdir()
    notices = root / "THIRD_PARTY_NOTICES.md"
    notices.write_text(
        f"# Third-party notices\n\n{manual}\n{other}\n{module.render_section([old], tag)}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "NOTICES", notices)
    monkeypatch.setattr(module, "platform_tag", lambda: tag)
    monkeypatch.setattr(module, "collect_rows", lambda: [new])

    assert module.main([]) == 0
    text = notices.read_text(encoding="utf-8")
    assert manual in text
    assert "## Other / arm64" in text and "| x | 1 | MIT | u |" in text
    assert module.render_row(new) in text
    assert module.render_row(old) not in text
    assert "wrote" in capsys.readouterr().out
