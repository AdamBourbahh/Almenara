"""Read-only access to Germán's ``scripts/0N_*.py`` modules (file names start with a digit)."""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache

from pipeline import config

SCRIPTS = config.ROOT / "scripts"


@lru_cache(maxsize=None)
def load(stem: str):
    """Import ``scripts/<stem>.py`` without modifying it; scripts/04 imports its siblings by name."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    if stem in sys.modules:
        return sys.modules[stem]
    spec = importlib.util.spec_from_file_location(stem, SCRIPTS / f"{stem}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scripts/{stem}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[stem] = module
    spec.loader.exec_module(module)
    return module
