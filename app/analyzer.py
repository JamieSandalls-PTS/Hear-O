"""Turns a block of multi-channel audio into per-band directional peaks.

Instead of collapsing each frequency band into a single averaged direction
(which makes a sound on the left and one on the right cancel to "centre"), we:

  1. estimate a direction for *every* frequency bin from the per-channel
     energy at that bin (different sources usually occupy different bins),
  2. accumulate those bin directions, weighted by loudness, into an angular
     histogram spanning the full circle,
  3. smooth that histogram over time (this is where jitter is removed), and
  4. find the local maxima - each surviving peak is one direction a sound is
     coming from. Two simultaneous sources -> two peaks -> two arcs.

Stereo can only place sounds on the left/right (front) arc; surround adds real
front/back/side separation. The angle-scale from Geometry widens stereo for
readability.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from .geometry import Geometry

_EPS = 1e-12
_PEAK_DECAY = 0.999      # adaptive loudness auto-gain memory (~15 s)

HIST_BINS = 72          # 5 deg resolution around the circle
PEAK_REL = 0.40         # a peak must be >= 40% of the histogram's max
MIN_SEP = np.deg2rad(34)  # merge peaks closer than this
MAX_PEAKS = 3           # arcs per band


@dataclass
class BandResult:
    name: str
    hint: str
    level: float                       # 0..1 overall loudness of the band
    peaks: List[Tuple[float, float]]   # [(angle_rad, level0..1), ...] strongest first
    active: bool

    @property
    def angle(self):
        """Direction of the strongest peak (front if none) - for label borrow."""
        return self.peaks[0][0] if self.peaks else 0.0


@dataclass
class AudioFrame:
    channels: int
    channel_desc: str
    overall_level: float
    bands: List[BandResult] = field(default_factory=list)


class Analyzer:
    def __init__(self, settings):
        self.settings = settings
        self._geom = None
        self._freqs = None
        self._nfft = None
        self._rate = None
        self._window = None
        # histogram bin edges/centres (constant once HIST_BINS is fixed)
        self._edges = np.linspace(-np.pi, np.pi, HIST_BINS + 1)
        self._centres = (self._edges[:-1] + self._edges[1:]) / 2.0
        # state
        self._peak = {}          # band -> running loudness peak (auto-gain)
        self._hist = {}          # band -> smoothed angular histogram
        self._overall_peak = _EPS
        self._overall_smooth = 0.0

    def _ensure(self, channels, nfft, rate):
        if self._geom is None or self._geom.channels != channels:
            self._geom = Geometry(channels)
        if self._nfft != nfft or self._rate != rate:
            self._nfft = nfft
            self._rate = rate
            self._freqs = np.fft.rfftfreq(nfft, 1.0 / rate)
            self._window = np.hanning(nfft).astype(np.float64)

    def channel_desc(self):
        return self._geom.describe() if self._geom else "waiting for audio"

    def process(self, samples, rate):
        if samples.ndim == 1:
            samples = samples[:, None]
        nfft, channels = samples.shape
        self._ensure(channels, nfft, rate)

        s = samples.astype(np.float64) * self._window[:, None]
        spec = np.fft.rfft(s, axis=0)
        power = spec.real ** 2 + spec.imag ** 2      # (freqs, channels)

        sensitivity = float(self.settings.get("analysis.sensitivity", 1.0))
        gate = float(self.settings.get("analysis.noise_gate", 0.06))
        smoothing = float(self.settings.get("analysis.smoothing", 0.5))
        alpha = min(1.0, max(0.01, 1.0 - smoothing))  # histogram EMA weight

        dir_mask = self._geom.has_dir
        dir_vecs = self._geom.vectors[dir_mask]       # (Cd, 2)
        scale = self._geom.angle_scale

        bands_out = []
        for band in self.settings.get("bands", []):
            name = band.get("name", "?")
            if not band.get("enabled", True):
                continue

            lo = np.searchsorted(self._freqs, band.get("low_hz", 20))
            hi = np.searchsorted(self._freqs, band.get("high_hz", 20000))
            hi = max(hi, lo + 1)
            band_power = power[lo:hi, :]              # (Fb, C)
            total = float(band_power.sum())

            hist_inst = self._bin_histogram(band_power, dir_mask, dir_vecs, scale)
            hist = self._hist.get(name)
            if hist is None or hist.shape[0] != HIST_BINS:
                hist = np.zeros(HIST_BINS)
            hist = hist * (1.0 - alpha) + hist_inst * alpha
            self._hist[name] = hist

            # Adaptive loudness -> 0..1 (unchanged behaviour, used for colour).
            peak = max(total, self._peak.get(name, _EPS) * _PEAK_DECAY)
            self._peak[name] = peak
            level = float(np.clip(np.sqrt(total / (peak + _EPS)) * sensitivity, 0, 1))

            peaks = self._find_peaks(hist, level)
            active = level >= gate and bool(peaks)
            bands_out.append(BandResult(name, band.get("hint", ""),
                                        level, peaks, active))

        overall_total = float(power.sum())
        self._overall_peak = max(overall_total, self._overall_peak * _PEAK_DECAY)
        overall = np.sqrt(overall_total / (self._overall_peak + _EPS)) * sensitivity
        overall = float(np.clip(overall, 0, 1))
        self._overall_smooth = self._overall_smooth * (1 - alpha) + overall * alpha

        return AudioFrame(channels, self._geom.describe(),
                          self._overall_smooth, bands_out)

    # -- direction histogram -----------------------------------------------
    def _bin_histogram(self, band_power, dir_mask, dir_vecs, scale):
        """Per-bin direction -> loudness-weighted angular histogram."""
        hist = np.zeros(HIST_BINS)
        if dir_vecs.shape[0] == 0:
            return hist
        dir_power = band_power[:, dir_mask]          # (Fb, Cd)
        bin_energy = dir_power.sum(axis=1)           # (Fb,)
        strong = bin_energy > _EPS
        if not strong.any():
            return hist
        dp = dir_power[strong]                       # (n, Cd)
        resultant = dp @ dir_vecs                    # (n, 2): x=right, y=front
        angles = np.arctan2(resultant[:, 0], resultant[:, 1]) * scale
        angles = np.clip(angles, -np.pi + 1e-6, np.pi - 1e-6)
        weights = bin_energy[strong]
        hist, _ = np.histogram(angles, bins=self._edges, weights=weights)
        # Small circular blur to fill discretisation gaps.
        hist = 0.5 * hist + 0.25 * np.roll(hist, 1) + 0.25 * np.roll(hist, -1)
        return hist

    def _find_peaks(self, hist, level):
        """Local maxima of the smoothed histogram -> [(angle, peak_level), ...]."""
        mx = float(hist.max())
        if mx <= _EPS:
            return []
        norm = hist / mx
        cand = []
        for i in range(HIST_BINS):
            c = norm[i]
            if c < PEAK_REL:
                continue
            l = norm[(i - 1) % HIST_BINS]
            r = norm[(i + 1) % HIST_BINS]
            if c >= l and c > r:
                # Parabolic interpolation for a smooth sub-bin angle.
                denom = (l - 2 * c + r)
                delta = 0.5 * (l - r) / denom if abs(denom) > 1e-6 else 0.0
                angle = self._centres[i] + delta * (2 * np.pi / HIST_BINS)
                angle = (angle + np.pi) % (2 * np.pi) - np.pi
                cand.append((angle, c))
        cand.sort(key=lambda x: -x[1])
        kept = []
        for angle, height in cand:
            if all(_ang_dist(angle, ka) >= MIN_SEP for ka, _ in kept):
                kept.append((angle, height))
            if len(kept) >= MAX_PEAKS:
                break
        # Peak brightness = band loudness scaled by relative peak height.
        return [(a, float(level * h)) for a, h in kept]


def _ang_dist(a, b):
    d = a - b
    return abs(np.arctan2(np.sin(d), np.cos(d)))
