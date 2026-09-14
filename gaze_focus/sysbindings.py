"""Best-effort check for existing Cinnamon/GNOME desktop keybindings that
already use a given key combination, so gaze-focus doesn't silently steal
someone else's shortcut.

This only sees bindings registered through gsettings/dconf (desktop
environment shortcuts, media keys, and anything else that stores its
binding there), plus a best-effort check for XKB keyboard-layout
group-toggle options (e.g. "grp:win_space_toggle") that intercept
modifier+Space combos at the X server level — not every possible global
hotkey grabbed by other means (e.g. an app using its own X11 grab). An
empty result is a helpful sign, not a guarantee of no clash. Never raises:
any failure just means "no conflicts found".
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


# XKB "grp:*_toggle" options rebind keyboard-layout switching to a modifier
# + key combo at the X server level, below window-manager shortcuts — a
# combo consumed there never reaches apps as a normal key event. In
# practice the option name (e.g. "win_space_toggle") doesn't reliably
# describe what's actually live: XKB option changes can lag a running X
# session, so the name and the enforced combo can disagree (observed on
# this project: option said "win_space_toggle", but Shift+Space was what
# actually got intercepted). Rather than trust the name, treat *any*
# "grp:*_toggle" option as evidence that *some* modifier+Space combo is
# being intercepted, and flag every modifier+Space combo as a possible
# conflict — since Space is the key virtually all of these options bind.
_SINGLE_MODIFIERS = {"<ctrl>", "<alt>", "<shift>", "<cmd>"}


def _is_modifier_space_combo(combo):
    parts = combo.split("+")
    return len(parts) == 2 and parts[0] in _SINGLE_MODIFIERS and parts[1] == "<space>"


def _xkb_conflicts(combo):
    """Best-effort check for XKB layout group-toggle options (configured via
    setxkbmap/gsettings input-sources) that shadow `combo` at the X server
    level, beneath any window-manager shortcut."""
    if not _is_modifier_space_combo(combo):
        return []
    try:
        out = subprocess.run(["setxkbmap", "-query"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    options_line = next((l for l in out.splitlines()
                          if l.startswith("options:")), "")
    options = options_line.split(":", 1)[1].strip() if ":" in options_line else ""
    conflicts = []
    for opt in options.split(","):
        opt = opt.strip()
        if opt.startswith("grp:") and opt[len("grp:"):].endswith("_toggle"):
            conflicts.append(
                f"XKB keyboard layout switch option ({opt}) — a "
                f"modifier+Space combo may be consumed by the X server "
                f"before it reaches any app; verify this exact combo works "
                f"before relying on it"
            )
    return conflicts


def find_conflicts(combo):
    """Return a list of human-readable strings describing desktop keybindings
    or XKB layout-switch options that already use `combo`."""
    conflicts = []
    try:
        for schema, key, raw_value in _iter_raw_bindings():
            for accel in _extract_accels(raw_value):
                if accel and _accel_to_combo(accel) == combo:
                    conflicts.append(f"{schema} {key} ({accel})")
    except Exception:
        pass  # best-effort: any unexpected failure -> no conflicts found
    conflicts.extend(_xkb_conflicts(combo))
    return conflicts
