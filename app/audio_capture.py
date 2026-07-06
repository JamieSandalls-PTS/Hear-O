"""WASAPI loopback capture: records whatever is playing to the speakers.

Uses PyAudioWPatch (a PyAudio fork with Windows loopback support). We capture
the output device's *native* channel count so surround information survives -
that is what makes front/back direction possible on 5.1 / 7.1 outputs.
"""

import threading

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover - reported to the user at runtime
    pyaudio = None

# Analysis block size. 1024 frames @ 48 kHz ~= 47 updates/sec: responsive
# enough for footstep transients while keeping FFT cost low.
CHUNK = 1024


class AudioEngine:
    """Background thread that reads loopback audio and feeds the analyzer."""

    def __init__(self, settings, analyzer, on_frame, on_status=None,
                 mono_consumers=None):
        self.settings = settings
        self.analyzer = analyzer
        self.on_frame = on_frame
        self.on_status = on_status or (lambda msg: None)
        # Objects with a .feed(mono, rate) method (classifier, subtitles).
        self.mono_consumers = list(mono_consumers or [])
        self._thread = None
        self._stop = threading.Event()
        self.status = "idle"

    # -- device discovery ---------------------------------------------------
    def available(self):
        return pyaudio is not None

    def list_loopback_devices(self):
        """Return [(index, name), ...] of WASAPI loopback devices."""
        if pyaudio is None:
            return []
        p = pyaudio.PyAudio()
        try:
            return [(d["index"], d["name"])
                    for d in p.get_loopback_device_info_generator()]
        finally:
            p.terminate()

    def _resolve_device(self, p):
        """Pick the configured device, or the default output's loopback."""
        idx = self.settings.get("audio.device_index", None)
        if idx is not None:
            try:
                return p.get_device_info_by_index(int(idx))
            except Exception:
                pass  # fall through to the default
        # Find the loopback that matches the current default output device.
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if default_out.get("isLoopbackDevice"):
            return default_out
        for lb in p.get_loopback_device_info_generator():
            if default_out["name"] in lb["name"]:
                return lb
        return None

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        if pyaudio is None:
            self._set_status("PyAudioWPatch not installed - audio disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def restart(self):
        self.stop()
        self.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _set_status(self, msg):
        self.status = msg
        self.on_status(msg)

    def _run(self):
        p = pyaudio.PyAudio()
        stream = None
        try:
            dev = self._resolve_device(p)
            if dev is None:
                self._set_status("No loopback device found")
                return
            channels = int(dev["maxInputChannels"])
            rate = int(dev["defaultSampleRate"])
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=rate,
                input=True,
                frames_per_buffer=CHUNK,
                input_device_index=dev["index"],
            )
            self._set_status(f"Capturing: {dev['name']} ({channels}ch @ {rate}Hz)")
            while not self._stop.is_set():
                raw = stream.read(CHUNK, exception_on_overflow=False)
                data = np.frombuffer(raw, dtype=np.float32)
                if data.size < channels:
                    continue
                frames = data.reshape(-1, channels)
                result = self.analyzer.process(frames, rate)
                self.on_frame(result)
                # Feed the mono downmix to the classifier + subtitle engine.
                if self.mono_consumers:
                    mono = frames.mean(axis=1)
                    for consumer in self.mono_consumers:
                        consumer.feed(mono, rate)
        except Exception as exc:  # pragma: no cover
            self._set_status(f"Audio error: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()
