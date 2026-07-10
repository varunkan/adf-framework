"""Make stdlib domain modules importable from the monolith portal tree."""

from __future__ import annotations

import sys
from pathlib import Path

PORTAL_ROOT = Path(__file__).resolve().parents[3]
if str(PORTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTAL_ROOT))
