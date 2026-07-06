"""Live speech subtitles via faster-whisper (local, CPU).

Speech is not transcribed continuously - that wastes CPU and makes Whisper
hallucinate on music/effects. Instead we lean on the YAMNet "Speech" detector
(see classifier.py): while it reports speech we accumulate the audio, and when
the talking stops (or a segment gets long) we transcribe that chunk and show
the text. A short pre-roll is kept so the start of a sentence isn't clipped
before the detector reacts.
"""

import threading
import time
from collections import deque

import numpy as np

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover
    WhisperModel = None

from .classifier import _fft_resample

WHISPER_RATE = 16000


class SubtitleEngine:
    def __init__(self, settings, on_text, on_status=None):
        self.settings = settings
        self.on_text = on_text
        self.on_status = on_status or (lambda msg: None)

        self._model = None
        self._rate = 48000
        self._preroll_samples = int(1.0 * self._rate)
        self._preroll = deque()      # recent chunks, to capture sentence onset
        self._segment = []           # chunks being accumulated during speech
        self._active = False
        self._last_speech = 0.0
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.status = "idle"
        self.loaded = False

    def available(self):
        return WhisperModel is not None

    # -- speech gate (driven by the YAMNet Speech detection) ---------------
    def set_speech_active(self, is_speech):
        if not self.settings.get("subtitles.enabled", True):
            return
        now = time.time()
        with self._lock:
            if is_speech:
                if not self._active:
                    self._active = True
                    self._segment = list(self._preroll)  # seed with onset audio
                self._last_speech = now

    # -- audio feed (from the capture thread) ------------------------------
    def feed(self, mono, rate):
        if not self.settings.get("subtitles.enabled", True):
            return
        chunk = mono.astype(np.float32)
        with self._lock:
            if rate != self._rate:
                self._rate = rate
                self._preroll_samples = int(1.0 * rate)
                self._preroll.clear()
                self._segment = []
                self._active = False
            self._preroll.append(chunk)
            total = sum(len(c) for c in self._preroll)
            while total > self._preroll_samples and len(self._preroll) > 1:
                total -= len(self._preroll.popleft())
            if self._active:
                self._segment.append(chunk)

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        if WhisperModel is None:
            self._set_status("faster-whisper not installed - subtitles off")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _set_status(self, msg):
        self.status = msg
        self.on_status(msg)

    def _ensure_model(self):
        if self._model is not None:
            return True
        try:
            name = self.settings.get("subtitles.model", "base.en")
            self._set_status(f"Loading subtitle model ({name})... first time downloads it")
            self._model = WhisperModel(name, device="cpu", compute_type="int8")
            self.loaded = True
            self._set_status("Subtitles ready")
            return True
        except Exception as exc:  # pragma: no cover
            self._set_status(f"Subtitle model error: {exc}")
            return False

    # -- worker loop --------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            time.sleep(0.15)
            if not self.settings.get("subtitles.enabled", True):
                continue
            if self._model is None and not self._ensure_model():
                time.sleep(2.0)
                continue

            job = self._take_ready_segment()
            if job is not None:
                self._transcribe(job)

    def _take_ready_segment(self):
        """Return (audio, rate) if a speech segment should be transcribed now."""
        now = time.time()
        gap = float(self.settings.get("subtitles.silence_gap", 0.7))
        max_seg = float(self.settings.get("subtitles.max_segment", 8.0))
        with self._lock:
            if not self._active or not self._segment:
                return None
            seg_dur = sum(len(c) for c in self._segment) / self._rate
            end_silence = (now - self._last_speech) > gap
            end_length = seg_dur >= max_seg
            if not (end_silence or end_length):
                return None
            audio = np.concatenate(self._segment)
            rate = self._rate
            if end_silence:
                self._active = False
                self._segment = []
            else:
                # Long monologue: flush but keep going with a little overlap.
                self._segment = list(self._preroll)
                self._last_speech = now
            return audio, rate

    def _transcribe(self, job):
        audio, rate = job
        if rate != WHISPER_RATE:
            n_out = int(round(len(audio) * WHISPER_RATE / rate))
            audio = _fft_resample(audio, n_out)
        if len(audio) < WHISPER_RATE * 0.3:   # too short to be words
            return
        try:
            lang = self.settings.get("subtitles.language", "en") or None
            segments, _ = self._model.transcribe(
                audio, language=lang, vad_filter=True, beam_size=1)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:  # pragma: no cover
            self._set_status(f"Subtitle error: {exc}")
            return
        if text:
            self.on_text(text)
