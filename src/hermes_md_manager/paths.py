"""Path resolution.

ALL path resolution goes through this module. Every consumer of a Hermes path
imports from here. ``hermes_home()`` is the *only* place that resolves
``HERMES_HOME`` and vendored-imports ``hermes_constants.get_hermes_home``.

State directory (``state_dir()``) lives OUTSIDE ``HERMES_HOME`` per the design
proposal (so backups/trash/index never touch Hermes' tree). It defaults to
``$XDG_STATE_HOME/hermes-md-manager`` and falls back to
``~/.local/state/hermes-md-manager``.

This module is import-safe and has no other package deps.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- Vendored Hermes path resolution ------------------------------------------
#
# We add Hermes' source root to sys.path exactly once so ``import
# hermes_constants`` etc. resolve. Doing this here (not at top-level imports)
# keeps the package importable without Hermes on the path for pure helpers.
_HERMES_SRC = "/home/app/.hermes/hermes-agent"
if _HERMES_SRC not in sys.path:
    sys.path.insert(0, _HERMES_SRC)


def hermes_src() -> Path:
    return Path(_HERMES_SRC)


def hermes_home() -> Path:
    """Resolve the active HERMES_HOME (Hermes' own helper)."""
    from hermes_constants import get_hermes_home  # vendored
    return Path(get_hermes_home())


def hermes_python() -> Path:
    """The python interpreter Hermes itself uses (where FastAPI/uvicorn/ruamel live)."""
    return hermes_src() / "venv" / "bin" / "python"


# --- Tool state (always OUTSIDE hermes_home) ----------------------------------
_STATE_DEFAULT = Path.home() / ".local" / "state" / "hermes-md-manager"


def state_dir() -> Path:
    """Resolve the tool's own state directory (config, backups, trash, index)."""
    env = os.environ.get("HERMES_MD_STATE_DIR", "").strip()
    base = Path(env).expanduser() if env else (
        Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local"))) / "state" / "hermes-md-manager"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def backups_dir() -> Path:
    p = state_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def trash_dir() -> Path:
    p = state_dir() / "trash"
    p.mkdir(parents=True, exist_ok=True)
    return p


def index_db_path() -> Path:
    return state_dir() / "index.sqlite"


def config_path() -> Path:
    return state_dir() / "config.json"


def static_dir() -> Path:
    return Path(__file__).parent / "static"


def vendor_dir() -> Path:
    return Path(__file__).parent / "vendor"


# --- Profile-id (hash of resolved HERMES_HOME) --------------------------------
import hashlib


def profile_id() -> str:
    """Stable id derived from the resolved HERMES_HOME. Namespaces state per
    profile so profile switching (handled by Hermes) never crosses backups.
    """
    h = hashlib.sha256()
    try:
        h.update(str(hermes_home().resolve()).encode("utf-8"))
    except OSError:
        h.update(str(hermes_home()).encode("utf-8"))
    return h.hexdigest()[:16]