"""Per-tool config (HERMES_HOME, external_dirs override, lock confirmations)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths


_DEFAULTS = {
    "hermes_home": str(paths.hermes_home()),
    "external_dirs_override": [],   # if non-empty, used INSTEAD of config.yaml's external_dirs
    "confirm_destructive": True,    # type-name confirmation before destructive ops
    "auto_clear_snapshot": True,    # delete .skills_prompt_snapshot.json after content writes
    "token_chars_per_token": 4,     # matches Hermes (agent/prompt_builder.py:1181)
}


def load() -> dict[str, Any]:
    p = paths.config_path()
    if not p.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULTS)
    cfg = dict(_DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k in _DEFAULTS})
    return cfg


def save(cfg: dict[str, Any]) -> None:
    paths.config_path().write_text(
        json.dumps(cfg, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def update(**patch: Any) -> dict[str, Any]:
    cfg = load()
    cfg.update(patch)
    save(cfg)
    return cfg