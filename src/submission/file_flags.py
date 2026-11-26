"""Flags for reading files this application wrote itself."""

import os
from typing import Final

# shortcut: Windows has no O_NOFOLLOW, so symlinks are not refused at open time there.
# O_BINARY stops Windows from translating line endings.
READ_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_BINARY", 0)
)
