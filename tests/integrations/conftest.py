from __future__ import annotations

import sys
from pathlib import Path

# src/ must precede tests/ so that `integrations.apex_swe` resolves to the
# source package, not the test directory.
_SRC = Path(__file__).parent.parent.parent / "src"
for _ in range(sys.path.count(str(_SRC))):
    sys.path.remove(str(_SRC))
sys.path.insert(0, str(_SRC))
