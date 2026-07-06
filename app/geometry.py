"""Maps loudspeaker channels to directions around the listener.

The whole app's sense of "where a sound is" comes from here. Each output
channel has a fixed angle (0 deg = front, positive = clockwise toward the
right). We turn that into a unit vector so the analyzer can compute an
energy-weighted direction across all channels.

Stereo (2 ch) only carries left/right information, so front/back cannot be
recovered - the resulting direction stays in the front hemisphere. A true
5.1 / 7.1 stream gives real front/back/side separation.
"""

import numpy as np

# Angle of each named speaker position, in degrees. 0 = front, clockwise +.
# None means the channel carries no usable direction (the LFE/subwoofer, or an
# unknown channel), so it contributes to loudness but not to direction.
_ANGLE = {
    "FC": 0.0,      # front centre
    "FL": -30.0,    # front left
    "FR": 30.0,     # front right
    "SL": -90.0,    # side left
    "SR": 90.0,     # side right
    "BL": -150.0,   # back left
    "BR": 150.0,    # back right
    "LFE": None,    # subwoofer - no direction
    "?": None,      # unknown channel
}

# WASAPI channel ordering for common layouts (matches Windows' KSAUDIO order).
_LAYOUTS = {
    1: ["FC"],
    2: ["FL", "FR"],
    3: ["FL", "FR", "FC"],
    4: ["FL", "FR", "BL", "BR"],
    6: ["FL", "FR", "FC", "LFE", "BL", "BR"],            # 5.1
    8: ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],  # 7.1
}


class Geometry:
    """Direction vectors for a given channel count."""

    def __init__(self, channels):
        self.channels = channels
        labels = _LAYOUTS.get(channels)
        if labels is None:
            # Unknown layout: assume the first two are front L/R, ignore the rest.
            if channels >= 2:
                labels = ["FL", "FR"] + ["?"] * (channels - 2)
            else:
                labels = ["FC"] * max(channels, 1)
        # Pad/truncate defensively so we always have exactly `channels` labels.
        labels = (labels + ["?"] * channels)[:channels]
        self.labels = labels

        vectors = np.zeros((channels, 2), dtype=np.float64)
        has_dir = np.zeros(channels, dtype=bool)
        for i, label in enumerate(labels):
            angle = _ANGLE.get(label)
            if angle is None:
                continue
            theta = np.deg2rad(angle)
            # x = rightward component, y = forward component.
            vectors[i] = (np.sin(theta), np.cos(theta))
            has_dir[i] = True

        self.vectors = vectors      # (channels, 2)
        self.has_dir = has_dir      # (channels,) bool

        # Stereo only pans within the front +/-30 deg arc, which looks cramped.
        # We keep the +/-30 vectors (needed for continuous phantom-centre
        # interpolation) but scale the resulting angle up so a hard-left sound
        # reaches the 9 o'clock position and hard-right the 3 o'clock position.
        # Surround layouts already span the full circle, so no scaling.
        self.angle_scale = 3.0 if channels == 2 else 1.0

    @property
    def is_directional(self):
        """True when the layout can express more than plain left/right."""
        return self.channels >= 4

    def describe(self):
        if self.channels >= 8:
            return "7.1 surround - full front/back/side direction"
        if self.channels == 6:
            return "5.1 surround - full front/back direction"
        if self.channels == 4:
            return "quad - front/back direction"
        if self.channels == 2:
            return "stereo - left/right + intensity only"
        if self.channels == 1:
            return "mono - intensity only"
        return f"{self.channels} channels"
