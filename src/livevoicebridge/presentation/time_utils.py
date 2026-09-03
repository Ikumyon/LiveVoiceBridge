from __future__ import annotations

import time


def now_text() -> str:
    return time.strftime("%H:%M:%S")
