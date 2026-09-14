"""Persistent user settings (currently just the enable/disable hotkey).

Stored as JSON next to the calibration file so `gaze-focus config --hotkey
...` sticks across runs without needing --hotkey on every invocation.
CLI flags always take precedence over the config file for a single run.
"""
import json

from .paths import CONFIG_DIR

CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "hotkey": "<ctrl>+<alt>+g",
}


def load_config():
    """Return settings merged over DEFAULTS. Never raises: a missing or
    corrupt config file just falls back to defaults."""
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return cfg


def save_config(updates):
    """Merge `updates` into the on-disk config and return the new config."""
    cfg = load_config()
    cfg.update(updates)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg
