"""Real-time sound-type recognition with YAMNet (AudioSet, 521 classes).

A background thread keeps a rolling buffer of the game's mono audio, resamples
~1 s of it to 16 kHz, and runs the YAMNet TFLite model (~2 ms/inference).

Two display modes read the same 521 scores:
  * "grouped"  - the classes are collapsed into ~40 readable categories that
    span the whole AudioSet taxonomy (people, animals, vehicles, nature,
    household, tools, music, weapons, impacts, ...).
  * "detailed" - the raw top scoring class names are shown (minus noise/meta
    classes), for the widest possible variety of labels.

Direction is not produced here (YAMNet works on the mono downmix). Each label is
tagged with a frequency band ("Low"/"Mid"/"High") so the overlay can borrow that
band's measured direction, which correlates with the sound's spectrum. This is
approximate - true per-source direction needs source separation.
"""

import csv
import os
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter
except Exception:  # pragma: no cover
    Interpreter = None


def _models_dir():
    """Locate app/models both when run from source and when frozen by PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:  # PyInstaller unpacks bundled data under _MEIPASS/app/models
        return os.path.join(base, "app", "models")
    return os.path.join(os.path.dirname(__file__), "models")


MODEL_DIR = _models_dir()
MODEL_PATH = os.path.join(MODEL_DIR, "yamnet.tflite")
CLASSMAP_PATH = os.path.join(MODEL_DIR, "yamnet_class_map.csv")

YAMNET_RATE = 16000
YAMNET_SAMPLES = 15600
INFER_INTERVAL = 0.12   # ~8 Hz: more chances to catch a brief sound
MAX_LABELS = 6          # most sounds shown at once

# Detection uses peak-hold (not averaging): a single strong window registers at
# full strength immediately, then decays by this factor each inference (~1 s
# memory at 8 Hz). This is what lets short, transient sounds be seen.
HOLD_RELEASE = 0.80

# Loudness normalisation applied to each window before recognition, so quiet
# sounds (footsteps) are boosted to a level YAMNet reacts to. We normalise by
# PEAK (not RMS) so impulsive sounds like footsteps are never clipped/distorted
# - clipping was destroying the very transients we want. Gain only amplifies,
# is capped, and is skipped near silence so room tone isn't blown up.
_TARGET_PEAK = 0.9
_MAX_GAIN = 8.0
_PEAK_FLOOR = 0.004

# Grouped taxonomy: (category, direction band, [inclusive index ranges]).
# Ranges follow YAMNet's fixed class ordering (see yamnet_class_map.csv).
GROUPED = [
    ("Speech", "Mid", [(0, 5), (65, 65)]),
    ("Shouting", "Mid", [(6, 11)]),
    ("Whisper", "Mid", [(12, 12)]),
    ("Laughter", "Mid", [(13, 18)]),
    ("Crying", "Mid", [(19, 23)]),
    ("Singing", "Mid", [(24, 32)]),
    ("Body/Breath", "Mid", [(33, 45), (49, 55)]),
    ("Footsteps", "Low", [(46, 48)]),
    ("Applause/Hands", "High", [(56, 58), (62, 62)]),
    ("Crowd/Cheer", "Mid", [(59, 61), (63, 66)]),
    ("Dog", "Mid", [(69, 75), (117, 117)]),
    ("Cat", "Mid", [(76, 80)]),
    ("Farm animals", "Mid", [(81, 102)]),
    ("Wild animal", "Mid", [(103, 105)]),
    ("Bird", "High", [(106, 116)]),
    ("Rodent", "High", [(118, 120)]),
    ("Insect", "High", [(121, 126)]),
    ("Frog/Reptile", "Mid", [(127, 131)]),
    ("Music", "Mid", [(132, 194), (203, 276)]),
    ("Bell/Chime", "High", [(173, 173), (195, 202)]),
    ("Wind", "Mid", [(277, 279)]),
    ("Thunder", "Low", [(280, 281)]),
    ("Water", "Mid", [(282, 291), (438, 450)]),
    ("Fire", "Mid", [(292, 293)]),
    ("Vehicle", "Low", [(294, 315), (320, 321), (335, 336)]),
    ("Emergency siren", "High", [(316, 319)]),
    ("Train", "Low", [(322, 328)]),
    ("Aircraft", "Low", [(329, 334)]),
    ("Engine/Motor", "Low", [(337, 347)]),
    ("Door/Knock", "Mid", [(348, 357)]),
    ("Kitchen/Home", "Mid", [(358, 371)]),
    ("Objects/Keys", "High", [(372, 377)]),
    ("Typing/Office", "High", [(378, 381), (408, 411)]),
    ("Telephone", "Mid", [(383, 388)]),
    ("Alarm/Siren", "High", [(382, 382), (389, 397)]),
    ("Clock/Mechanism", "Mid", [(398, 407)]),
    ("Tools", "Mid", [(412, 419)]),
    ("Explosion", "Low", [(420, 420), (429, 430)]),
    ("Gunfire", "High", [(421, 425)]),
    ("Fireworks", "High", [(426, 428)]),
    ("Wood/Crack", "Mid", [(431, 434)]),
    ("Glass", "High", [(435, 437)]),
    ("Impacts", "Mid", [(452, 474)]),
    ("Beeps/Alerts", "High", [(475, 479), (491, 492)]),
    ("Creak/Squeak", "High", [(480, 483)]),
    ("Clicks", "High", [(485, 486)]),
    ("Rumble", "Low", [(487, 487), (516, 517)]),
    ("TV/Radio", "Mid", [(518, 519)]),
]

# Detailed-mode band guess from the class name.
_LOW_KW = ["engine", "motor", "truck", "vehicle", "aircraft", "helicopter",
           "jet", "propeller", "train", "subway", "explosion", "boom",
           "eruption", "thunder", "rumble", "footstep", "heart", "idling",
           "accelerat", "diesel", "thud", "artillery", "foghorn", "bass"]
_HIGH_KW = ["whistle", "bell", "glass", "gun", "click", "hiss", "chirp",
            "tweet", "alarm", "siren", "beep", "ding", "ping", "clink",
            "insect", "cricket", "mosquito", "buzz", "wasp", "squeak", "cymbal",
            "hi-hat", "ringtone", "jingle", "jangl", "scratch", "static",
            "shatter", "snap", "tick", "sizzle", "bird", "squawk", "caw",
            "hoot", "clap", "spray", "chime", "clang", "creak", "squeal",
            "coin", "typ"]

# Classes hidden in detailed mode (noise/meta/recording-artefact labels).
_BLOCK_NAMES = {
    "Speech synthesizer", "Silence", "Sine wave", "Harmonic", "Chirp tone",
    "Sound effect", "Pulse", "Inside, small room", "Inside, large room or hall",
    "Inside, public space", "Outside, urban or manmade",
    "Outside, rural or natural", "Reverberation", "Echo", "Noise",
    "Environmental noise", "Static", "Mains hum", "Distortion", "Sidetone",
    "Cacophony", "White noise", "Pink noise", "Field recording",
}
# Music sub-genre / mood classes (indices 211..276): collapse to just "Music".
_BLOCK_RANGE = range(211, 277)

# Classes that mean "someone is talking" - used to gate subtitles.
_SPEECH_INDICES = np.array([0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 65])


@dataclass
class Detection:
    name: str
    score: float
    band: str


def _band_for_name(name):
    low = name.lower()
    if any(k in low for k in _LOW_KW):
        return "Low"
    if any(k in low for k in _HIGH_KW):
        return "High"
    return "Mid"


def _indices_from_ranges(ranges, n):
    out = []
    for lo, hi in ranges:
        out.extend(i for i in range(lo, hi + 1) if i < n)
    return np.array(sorted(set(out)), dtype=np.int64)


class Classifier:
    def __init__(self, settings, on_detections=None, on_status=None, on_speech=None):
        self.settings = settings
        self.on_detections = on_detections or (lambda dets: None)
        self.on_status = on_status or (lambda msg: None)
        self.on_speech = on_speech or (lambda active: None)

        self._interp = None
        self._in_index = None
        self._out_index = None
        self._names = []
        self._groups = []           # [(name, band, idx_array), ...]
        self._detail_band = []      # band per class index
        self._allowed_mask = None   # 1.0 allowed / 0.0 blocked (detailed mode)
        self._ema_grp = {}          # grouped smoothed scores
        self._ema_vec = None        # detailed smoothed scores (vectorised)
        self._mode = None

        self._buffer = np.zeros(0, dtype=np.float32)
        self._rate = YAMNET_RATE
        self._need = YAMNET_SAMPLES
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.status = "not loaded"
        self.loaded = False

    # -- model loading ------------------------------------------------------
    def available(self):
        return Interpreter is not None and os.path.exists(MODEL_PATH)

    def load(self):
        if Interpreter is None:
            self._set_status("ai-edge-litert not installed - recognition off")
            return False
        if not os.path.exists(MODEL_PATH) or not os.path.exists(CLASSMAP_PATH):
            self._set_status("YAMNet model files missing - recognition off")
            return False
        try:
            self._interp = Interpreter(model_path=MODEL_PATH)
            self._interp.allocate_tensors()
            self._in_index = self._interp.get_input_details()[0]["index"]
            self._out_index = self._interp.get_output_details()[0]["index"]
            self._load_classmap()
            self.loaded = True
            self._set_status("Sound recognition ready")
            return True
        except Exception as exc:  # pragma: no cover
            self._set_status(f"Recognition load error: {exc}")
            return False

    def _load_classmap(self):
        self._names = []
        with open(CLASSMAP_PATH, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                self._names.append(row["display_name"])
        n = len(self._names)
        self._detail_band = [_band_for_name(name) for name in self._names]
        self._groups = [(name, band, _indices_from_ranges(ranges, n))
                        for name, band, ranges in GROUPED]
        mask = np.ones(n, dtype=np.float64)
        for i, name in enumerate(self._names):
            if name in _BLOCK_NAMES or i in _BLOCK_RANGE:
                mask[i] = 0.0
        self._allowed_mask = mask
        self._ema_vec = np.zeros(n, dtype=np.float64)

    # -- audio feed ---------------------------------------------------------
    def feed(self, mono, rate):
        if not self.loaded:
            return
        with self._lock:
            if rate != self._rate:
                self._rate = rate
                self._need = int(round(YAMNET_SAMPLES * rate / YAMNET_RATE))
                self._buffer = np.zeros(0, dtype=np.float32)
            self._buffer = np.concatenate([self._buffer, mono.astype(np.float32)])
            if self._buffer.size > self._need:
                self._buffer = self._buffer[-self._need:]

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        if not self.loaded and not self.load():
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _set_status(self, msg):
        self.status = msg
        self.on_status(msg)

    # -- inference loop -----------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            time.sleep(INFER_INTERVAL)
            if not self.settings.get("classification.enabled", True):
                if self._ema_grp or (self._ema_vec is not None and self._ema_vec.any()):
                    self._ema_grp.clear()
                    if self._ema_vec is not None:
                        self._ema_vec[:] = 0
                    self.on_detections([])
                    self.on_speech(False)
                continue
            with self._lock:
                if self._buffer.size < self._need:
                    continue
                window = self._buffer[-self._need:].copy()
                rate = self._rate
            try:
                dets = self._classify(window, rate)
            except Exception as exc:  # pragma: no cover
                self._set_status(f"Recognition error: {exc}")
                continue
            self.on_detections(dets)

    def _classify(self, window, rate):
        wav = _fft_resample(window, YAMNET_SAMPLES) if rate != YAMNET_RATE else window
        wav = wav[:YAMNET_SAMPLES]
        if self.settings.get("classification.boost_soft", True):
            wav = _normalize(wav)
        wav = np.ascontiguousarray(wav.reshape(1, YAMNET_SAMPLES), dtype=np.float32)
        self._interp.set_tensor(self._in_index, wav)
        self._interp.invoke()
        scores = self._interp.get_tensor(self._out_index)[0].astype(np.float64)

        # Speech gate for subtitles (independent of display mode/threshold).
        self.on_speech(float(scores[_SPEECH_INDICES].max()) >= 0.30)

        mode = self.settings.get("classification.mode", "detailed")
        if mode != self._mode:
            self._mode = mode
            self._ema_grp.clear()
            if self._ema_vec is not None:
                self._ema_vec[:] = 0

        thresh_on = float(self.settings.get("classification.threshold", 0.35))
        if mode == "grouped":
            return self._classify_grouped(scores, thresh_on)
        return self._classify_detailed(scores, thresh_on)

    def _classify_grouped(self, scores, thresh_on):
        dets = []
        for name, band, idxs in self._groups:
            raw = float(scores[idxs].max()) if idxs.size else 0.0
            # Peak-hold: jump to the peak, then decay - so a brief sound shows.
            held = max(raw, self._ema_grp.get(name, 0.0) * HOLD_RELEASE)
            self._ema_grp[name] = held
            if held >= thresh_on:
                dets.append(Detection(name, held, band))
        dets.sort(key=lambda d: d.score, reverse=True)
        return dets[:MAX_LABELS]

    def _classify_detailed(self, scores, thresh_on):
        # Peak-hold across all classes at once (vectorised).
        self._ema_vec = np.maximum(scores, self._ema_vec * HOLD_RELEASE)
        held = self._ema_vec * self._allowed_mask
        order = np.argsort(held)[::-1][:MAX_LABELS * 2]
        dets = []
        for i in order:
            v = float(held[i])
            if v < thresh_on:
                break
            dets.append(Detection(self._names[i], v, self._detail_band[i]))
            if len(dets) >= MAX_LABELS:
                break
        return dets


def _normalize(wav):
    """Amplify a quiet window by its peak so soft sounds register.

    Peak-based (not RMS) and capped so the result never exceeds _TARGET_PEAK,
    which means impulsive footsteps/gunshots are boosted without any clipping.
    """
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak < _PEAK_FLOOR:
        return wav  # essentially silent - don't amplify the noise floor
    gain = min(max(_TARGET_PEAK / peak, 1.0), _MAX_GAIN)
    return wav * gain if gain > 1.0 else wav


def _fft_resample(x, n_out):
    """Alias-safe resample via FFT (good for down-sampling to 16 kHz)."""
    n_in = x.shape[0]
    if n_in == n_out:
        return x.astype(np.float32)
    spec = np.fft.rfft(x)
    out_bins = n_out // 2 + 1
    resized = np.zeros(out_bins, dtype=complex)
    keep = min(spec.shape[0], out_bins)
    resized[:keep] = spec[:keep]
    y = np.fft.irfft(resized, n=n_out) * (n_out / n_in)
    return y.astype(np.float32)
