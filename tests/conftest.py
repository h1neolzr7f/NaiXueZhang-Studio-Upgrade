"""Force UTF-8 stdio so Windows runners (cp1252) can round-trip Chinese JSON."""

from __future__ import annotations

import os

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
