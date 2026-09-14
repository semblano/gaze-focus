"""Best-effort check for existing Cinnamon/GNOME desktop keybindings that
already use a given key combination, so gaze-focus doesn't silently steal
someone else's shortcut.

This only sees bindings registered through gsettings/dconf (desktop
environment shortcuts, media keys, and anything else that stores its
binding there) — not every possible global hotkey grabbed by other means
(e.g. an app using its own X11 grab). An empty result is a helpful sign,
not a guarantee of no clash. Never raises: any failure just means "no
conflicts found".
"""
import ast
import re
import subprocess

_MOD_MAP = {
    "primary": "ctrl", "control": "ctrl", "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "super": "cmd", "mod4": "cmd", "meta": "cmd", "hyper": "cmd",
}
_KEYSYM_MAP = {
    "space": "space", "tab": "tab", "backspace": "backspace", "return": "enter",
    "escape": "esc", "delete": "delete", "home": "home", "end": "end",
    "page_up": "page_up", "page_down": "page_down", "up": "up", "down": "down",
    "left": "left", "right": "right", "insert": "insert", "caps_lock": "caps_lock",
    "num_lock": "num_lock", "scroll_lock": "scroll_lock", "print": "print_screen",
    "pause": "pause", "menu": "menu",
}
_MOD_ORDER = ["ctrl", "alt", "shift", "cmd"]


def _accel_to_combo(accel):
    """GTK accelerator string (e.g. '<Primary><Alt>t') -> our pynput-style
    combo string (e.g. '<ctrl>+<alt>+t'), or None if unparseable/empty."""
    if not accel:
        return None
    mods_raw = re.findall(r"<([^>]+)>", accel)
    rest = re.sub(r"<[^>]+>", "", accel).strip()
    if not rest:
        return None
    seen = {_MOD_MAP[m.lower()] for m in mods_raw if m.lower() in _MOD_MAP}
    mods = [f"<{o}>" for o in _MOD_ORDER if o in seen]
    key_lower = rest.lower()
    if key_lower in _KEYSYM_MAP:
        main = f"<{_KEYSYM_MAP[key_lower]}>"
    elif re.fullmatch(r"f([1-9]|[12][0-9]|3[0-5])", key_lower):
        main = f"<{key_lower}>"
    elif len(rest) == 1:
        main = rest.lower()
    else:
        return None  # unrecognized keysym (e.g. XF86 media keys) — skip
    return "+".join(mods + [main])


def _iter_raw_bindings():
    """Yield (schema, key, raw_gsettings_value) for every gsettings key whose
    schema name suggests it's a keybinding."""
    try:
        out = subprocess.run(["gsettings", "list-recursively"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        schema, key, value = parts
        if "keybinding" not in schema.lower():
            continue
        yield schema, key, value


def _extract_accels(raw_value):
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return []
    if isinstance(parsed, str):
        return [parsed]
    if isinstance(parsed, (list, tuple)):
        return [a for a in parsed if isinstance(a, str)]
    return []


def find_conflicts(combo):
    """Return a list of human-readable 'schema key (accelerator)' strings
    for desktop keybindings that already use `combo`."""
    conflicts = []
    try:
        for schema, key, raw_value in _iter_raw_bindings():
            for accel in _extract_accels(raw_value):
                if accel and _accel_to_combo(accel) == combo:
                    conflicts.append(f"{schema} {key} ({accel})")
    except Exception:
        return []  # best-effort: any unexpected failure -> no conflicts found
    return conflicts
