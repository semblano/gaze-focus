"""systemd --user service management for gaze-focus.

The service lets gaze-focus start automatically at login and restart
itself if it crashes, independent of any single terminal/session. It's a
*user* unit (not system-wide): gaze-focus needs the logged-in X11/D-Bus
session for its tray icon, global hotkey, and window focus control, so it
can't run as a system daemon.

ExecStart uses `sys.executable` (the interpreter gaze-focus is currently
running under) rather than a hardcoded path, so the same code works
whether gaze-focus is running from a dev checkout's .venv or from a
packaged install's private venv.
"""
import subprocess
import sys
from pathlib import Path

from .paths import CONFIG_DIR

SERVICE_NAME = "gaze-focus.service"
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PATH = USER_UNIT_DIR / SERVICE_NAME
ENV_FILE = CONFIG_DIR / "service.env"

UNIT_TEMPLATE = """\
[Unit]
Description=gaze-focus: webcam gaze-tracking window focus switcher
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory={workdir}
EnvironmentFile=-{env_file}
ExecStart={python} -m gaze_focus run $GAZE_FOCUS_ARGS
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
"""


def _unit_content():
    workdir = Path(__file__).resolve().parent.parent
    return UNIT_TEMPLATE.format(python=sys.executable, env_file=ENV_FILE, workdir=workdir)


def is_installed():
    return UNIT_PATH.exists()


def install(force=False):
    """Write the unit file (and a starter env file) and make systemd aware
    of it. Safe to call repeatedly; only rewrites if `force` or the
    rendered content changed, so re-enabling stays idempotent."""
    content = _unit_content()
    if not force and UNIT_PATH.exists() and UNIT_PATH.read_text() == content:
        return
    USER_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    UNIT_PATH.write_text(content)
    if not ENV_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text(
            "# Extra CLI flags for the gaze-focus service, e.g.:\n"
            "# GAZE_FOCUS_ARGS=--cameras 4 --no-clicks\n"
            "GAZE_FOCUS_ARGS=\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def is_enabled():
    """True if the service is installed and enabled to start at login."""
    if not is_installed():
        return False
    result = subprocess.run(
        ["systemctl", "--user", "is-enabled", SERVICE_NAME],
        capture_output=True, text=True)
    return result.stdout.strip() == "enabled"


def set_enabled(enabled):
    """Enable/disable (and start/stop now) the service. Installs the unit
    first if needed. Raises RuntimeError with the systemctl error text on
    failure (e.g. no systemd, no user session bus)."""
    install()
    action = "enable" if enabled else "disable"
    result = subprocess.run(
        ["systemctl", "--user", action, "--now", SERVICE_NAME],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"systemctl {action} failed")


def available():
    """Best-effort check that systemd --user is usable at all here (some
    minimal containers/WMs don't run a user systemd instance)."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True, text=True, timeout=3)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return "Failed to connect to bus" not in (result.stderr or "")


def status():
    """One of 'unavailable' / 'not_installed' / 'enabled' / 'disabled', for
    UI display."""
    if not available():
        return "unavailable"
    if not is_installed():
        return "not_installed"
    return "enabled" if is_enabled() else "disabled"
