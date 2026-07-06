"""User settings: defaults, load/save to JSON, and dotted-path access."""

import copy
import json
import os

# Location of the user's config file (next to the project, in the user profile).
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".hearo")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
PRESET_DIR = os.path.join(CONFIG_DIR, "presets")


def _safe_name(name):
    """Turn a preset name into a safe filename stem."""
    keep = "-_ ()"
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned or "preset"

# Every tunable lives here. The settings window edits copies of these values.
DEFAULTS = {
    # Global hotkey (uses the `keyboard` library syntax) that opens the settings window.
    "hotkey_settings": "ctrl+alt+o",

    "audio": {
        # None = follow the Windows default output device. Otherwise a WASAPI
        # loopback device index chosen in the settings window.
        "device_index": None,
    },

    "analysis": {
        # Multiplies the computed intensity. >1 = more reactive, <1 = calmer.
        "sensitivity": 1.0,
        # Levels below this (0..1) are treated as silence and hidden.
        "noise_gate": 0.06,
        # 0 = instant/jittery, 1 = very smooth/slow. Controls how fast indicators move.
        "smoothing": 0.7,
    },

    "classification": {
        # Recognise sound types (footsteps/gunshot/speech/...) with YAMNet and
        # show them as named indicators instead of raw frequency bands.
        "enabled": True,
        # "detailed" = raw class names (widest variety); "grouped" = ~40 tidy
        # categories spanning the whole taxonomy.
        "mode": "detailed",
        # Confidence needed (0..1) before a sound type is shown.
        "threshold": 0.30,
        # Boost quiet windows before recognition so soft sounds (e.g. footsteps)
        # are detected. Disable if it causes false positives in quiet scenes.
        "boost_soft": True,
    },

    "subtitles": {
        # Live speech-to-text (local Whisper). Triggered by the Speech detector,
        # so it needs sound recognition enabled too.
        "enabled": True,
        "model": "base.en",     # tiny.en (fast) / base.en / small.en (accurate)
        "language": "en",       # "" = auto-detect (needs a non-.en model)
        "silence_gap": 0.7,     # seconds of quiet that ends a phrase
        "max_segment": 8.0,     # force-transcribe a monologue this long
        "duration": 7.0,        # seconds a subtitle stays on screen
        "position_y": 0.82,     # vertical position (fraction of screen height)
        "font_size": 18,
    },

    "overlay": {
        "center_x": 0.5,        # fraction of screen width  (0=left, 1=right)
        "center_y": 0.5,        # fraction of screen height (0=top, 1=bottom)
        "base_radius": 90,      # radius (px) of the innermost ring
        "ring_spacing": 34,     # gap (px) between each band's ring
        "opacity": 0.9,         # overall overlay opacity (0..1)
        "thickness": 12,        # thickness (px) of the highlighted direction arc
        "blip_span_deg": 46,    # angular width of the direction arc
        "label_font_size": 9,   # point size of the sound-type labels
        "label_fade": 1.5,      # seconds a label takes to fade out after its sound stops
        "show_labels": True,    # draw the band name / hint next to active indicators
        "show_compass": True,   # draw F / B / L / R around the ring
        "click_through": True,  # let mouse clicks pass through to the game
    },

    # Frequency bands act as separate sound-type indicators. Each gets its own
    # concentric ring. When the ML classifier lands later, these become named
    # sound types instead of frequency ranges.
    "bands": [
        {"name": "Low",  "hint": "explosions / footsteps", "low_hz": 20,   "high_hz": 250,   "enabled": True},
        {"name": "Mid",  "hint": "voices / bodies",        "low_hz": 250,  "high_hz": 2000,  "enabled": True},
        {"name": "High", "hint": "gunshots / clicks",      "low_hz": 2000, "high_hz": 16000, "enabled": True},
    ],

    # Intensity colour ramp: list of [position 0..1, hex colour]. Indicators
    # interpolate along this as the sound gets louder.
    "gradient": [
        [0.0, "#2b7bff"],
        [0.45, "#39e639"],
        [0.72, "#ffd21a"],
        [1.0, "#ff2020"],
    ],
}


def _deep_merge(base, override):
    """Recursively merge `override` into a copy of `base` (dicts only)."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Settings:
    """Thin wrapper over the config dict with dotted-path get/set and persistence."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    user = json.load(fh)
                self.data = _deep_merge(DEFAULTS, user)
            except (OSError, ValueError):
                # Corrupt or unreadable config: fall back to defaults silently.
                self.data = copy.deepcopy(DEFAULTS)

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)

    # -- presets: named snapshots of the whole config ----------------------
    def list_presets(self):
        if not os.path.isdir(PRESET_DIR):
            return []
        names = [os.path.splitext(f)[0] for f in os.listdir(PRESET_DIR)
                 if f.endswith(".json")]
        return sorted(names, key=str.lower)

    def _preset_path(self, name):
        return os.path.join(PRESET_DIR, _safe_name(name) + ".json")

    def save_preset(self, name):
        os.makedirs(PRESET_DIR, exist_ok=True)
        with open(self._preset_path(name), "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)

    def load_preset(self, name):
        path = self._preset_path(name)
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return False
        # Merge onto defaults so a preset from an older version stays valid.
        self.data = _deep_merge(DEFAULTS, data)
        self.save()
        return True

    def delete_preset(self, name):
        path = self._preset_path(name)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted, value):
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
