from __future__ import annotations

import sys
from pathlib import Path


def _smoke_test() -> int:
    from photo_guard import config, device, pipeline

    if not config.PHOTOGUARD_MODEL_ID:
        return 2
    # G6: a configured path is not a model — without this check a machine that never ran
    # `download-models` (or whose models/ was not shipped) still reported success.
    if not Path(config.PHOTOGUARD_MODEL_ID).is_dir():
        return 2
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
