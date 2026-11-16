from __future__ import annotations

import logging

from .cli import main

__all__ = ["main"]

# P57: a library must not write to stderr on its own. Without a handler anywhere in the
# chain, Python's last-resort handler prints WARNING+ records; the null handler keeps the
# default silent until the CLI's ``-v`` installs one.
logging.getLogger(__name__).addHandler(logging.NullHandler())
