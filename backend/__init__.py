"""Backend package bootstrap to expose the `retrieval` namespace."""

import importlib
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Ensure `import retrieval` works by aliasing backend.retrieval
if "retrieval" not in sys.modules:
    sys.modules["retrieval"] = importlib.import_module("backend.retrieval")
