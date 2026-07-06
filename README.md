# Hear-O

**Hear-O** is an on-screen overlay that turns game audio into **visual direction
and intensity indicators** for players who are deaf or hard of hearing.

It listens to whatever your game is playing through your speakers/headset and
draws indicators around the centre of your screen showing **where** sounds are
coming from, **how loud** they are, and **what kind** of sound they are — plus
live **subtitles** for speech.

---

## ⚠️ Important — please read before using online

Hear-O only *listens* to your system audio; it does not read game memory, inject
code, or modify any game. However:

> **Some game publishers and anti-cheat systems prohibit third-party overlays or
> accessibility tools in online multiplayer or competitive games.** Using Hear-O
> in such games is entirely **at your own risk**. The author accepts **no
> liability** for any bans, suspensions, or other action taken against your
> account. If in doubt, use it only in single-player or offline games, or check
> the game's rules first.

---

## What it shows

- **Direction** — indicators swing around a ring to point where a sound is coming
  from (top = front, bottom = behind, left/right as expected).
- **Multiple sounds at once** — a sound on your left and one on your right are
  pinpointed as separate arcs instead of averaging to "centre".
- **Intensity** — colour shifts from calm blue (quiet) through green and yellow
  to red (loud).
- **Sound type** — an on-device AI model (YAMNet) recognises the *kind* of sound
  from **~500 categories** (footsteps, gunfire, explosions, vehicles, animals,
  doors, alarms, glass, speech, and much more) and labels it on screen.
- **Stacked labels** — when several sound types share a direction, their labels
  stack neatly (newest on top) and fade out smoothly instead of overlapping.
- **Speech subtitles** — speech is transcribed live (local Whisper) and shown at
  the bottom of the screen.

## Requirements

- **Windows 10 or 11** (64-bit).
- **CPU-only** — no GPU required. Runs comfortably on a modern PC; sound
  recognition costs ~2 ms per check.
- Running from source additionally needs **Python 3.10+**.
- **Disk / download:** the packaged app is a ~400 MB folder (it bundles Qt and
  the AI runtimes). The speech-subtitle model (~140 MB) downloads automatically
  the first time speech is detected, and then works offline.
- An **internet connection is needed once** (to install dependencies / download
  the subtitle model); everything runs locally after that. No audio ever leaves
  your PC.

## Getting started

### Option A — standalone app (no Python needed)

1. Download / build the app folder (`dist\Hear-O`) and open it.
2. Double-click **`Hear-O.exe`**.
3. A tray icon appears. Start your game and sounds will show on the overlay.

> To build it yourself: run **`build_exe.bat`** once, then find the app at
> `dist\Hear-O\Hear-O.exe`. Zip the whole `dist\Hear-O` folder to share it — the
> target PC does not need Python.

### Option B — run from source

1. Install **Python 3.10+** (<https://www.python.org/downloads/>), ticking
   *"Add Python to PATH"*.
2. Double-click **`Hear-O.bat`**. The first launch installs everything it needs
   (a few minutes, once only); later launches are instant.
3. A tray icon appears.

## Using it

Press **Ctrl + Alt + O** (or click the tray icon) to open **Settings**, where you
can adjust:

- **Overlay layout** — position, ring size/spacing, arc thickness, opacity,
  **label text size**, and **label fade time**.
- **Sensitivity** — sensitivity, noise gate, and smoothing.
- **Sound recognition** — turn it on/off, choose **Detailed** (widest variety of
  labels) or **Grouped** (~40 tidy categories), set the detection threshold, and
  toggle **Boost soft sounds** (helps quiet footsteps).
- **Speech subtitles** — turn on/off and pick a model (tiny / base / small).
- **Presets** — save your tuned settings under a name and switch between them
  (e.g. one preset per game). Stored in `~/.hearo/presets/`.

Your settings live in `~/.hearo/config.json`. Delete it to reset to defaults.

## Getting the best direction

- **Left / Right + intensity** works on any normal stereo headset.
- **True front / back / side** direction needs a real multi-channel signal. In
  *Windows Sound settings* set your output device to **5.1 or 7.1**, and set the
  game's audio to surround too — Hear-O auto-detects the channel count and uses
  whatever is available. Note: "virtual surround" modes (Dolby Atmos / DTS
  Headphone:X) still send only 2 channels to Windows, so they stay left/right.

## Overlay not showing over your game?

Run the game in **Borderless / Windowed** mode. Exclusive-fullscreen can hide all
overlays (the same limitation Discord's overlay has).

## Known limitations

- **A single, isolated footstep** may not be recognised — the model's "footsteps"
  class is defined by the *rhythm* of several steps, so it detects *walking* well
  but not one lone step. Turn on **Boost soft sounds** and lower the threshold to
  catch as much as possible.
- **Crackling fire** is acoustically ambiguous (it overlaps with crackling wood,
  crunching, rain, etc.) and may be labelled inconsistently or missed. Lowering
  the detection threshold helps.
- Sound-type direction is **borrowed from the sound's frequency band**, so it is
  approximate — precise per-sound separation is a future goal.

## How it works

`app/audio_capture.py` grabs the output device's native channels via WASAPI
loopback. `app/analyzer.py` estimates a direction per frequency bin, builds a
smoothed angular histogram, and finds multiple peaks (so simultaneous sounds get
separate arcs). `app/classifier.py` runs the YAMNet TFLite model (bundled in
`app/models/`) to recognise sound types. `app/subtitles.py` transcribes speech
with faster-whisper, gated by the speech detector. `app/hud.py` draws the
transparent, click-through, always-on-top overlay. `app/main.py` wires it all
together with a tray icon and the global hotkey.

## Support / donate

Hear-O is free for personal and non-commercial use. If it helps you and you'd
like to support its development, you can buy me a coffee — it's genuinely
appreciated. ☕

**➡️ <https://buymeacoffee.com/jamiesandalls>**

## License

Copyright (c) 2026 Jamie Sandalls. Free for **personal, educational, and
non-commercial** use. Commercial use, redistribution for profit, resale,
sublicensing, or inclusion in a commercial product/service requires a separate
commercial license from the copyright holder. Provided "as is", without warranty
of any kind. See [LICENSE](LICENSE) for the full text.
