from __future__ import annotations

import sys
from pathlib import Path


def _smoke_test() -> int:
    from photo_guard import config, device, pipeline, resources

    if not config.PHOTOGUARD_MODEL_ID:
        return 2
    # G6: a configured path is not a model — without this check a machine that never ran
    # `download-models` (or whose models/ was not shipped) still reported success.
    if not Path(config.PHOTOGUARD_MODEL_ID).is_dir():
        return 2
    # G2/P33: the licence material must ship beside the bundle; a build that forgot to include
    # it (or an install that dropped it) must not report success. The macOS bundle keeps the
    # two layouts apart — Nuitka's data-dirs land in Contents/Resources while data-files land
    # next to the executable in Contents/MacOS — so probe every candidate root and, when
    # something is missing, say which roots were tried (that is what turned a 40-minute build
    # round into a diagnosis last time).
    missing = [
        name
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")
        if resources.find_resource(name) is None
    ]
    if missing:
        tried = ", ".join(str(root) for root in resources.candidate_roots())
        print(
            f"licence material missing from the bundle: {', '.join(missing)} "
            f"(looked in: {tried})",
            file=sys.stderr,
        )
        return 4
    if not any(item.backend == "cpu" for item in device.discover_devices(include_unsupported=False)):
        return 3
    pipeline.validate_options(pipeline.ProtectOptions())
    print("Photo Guard desktop smoke test passed")
    return 0


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        raise SystemExit(_smoke_test())
    from photo_guard.gui import main
    raise SystemExit(main())
