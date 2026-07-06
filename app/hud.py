"""The on-screen overlay: a transparent, always-on-top, click-through window
that draws one rotating direction indicator per frequency band.

Layout: concentric rings share a centre. Each enabled band owns a ring. On
each ring a glowing arc ("blip") swings around to point at the sound's
direction (top = front), and its colour shifts along the intensity gradient
from calm blue to loud red. A label naming the band sits next to the blip.
"""

import math

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QGuiApplication,
)
from PySide6.QtWidgets import QWidget


def _lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


def _gradient_color(stops, t):
    """Interpolate a colour along [[pos, '#hex'], ...] for t in 0..1."""
    t = max(0.0, min(1.0, t))
    pts = [(float(p), QColor(c)) for p, c in stops]
    pts.sort(key=lambda x: x[0])
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (p0, c0), (p1, c1) in zip(pts, pts[1:]):
        if p0 <= t <= p1:
            span = (p1 - p0) or 1.0
            return _lerp_color(c0, c1, (t - p0) / span)
    return pts[-1][1]


class HudOverlay(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._frame = None            # latest AudioFrame (bands + direction)
        self._detections = []         # latest list[Detection] from the classifier
        self._subtitle_text = ""      # latest transcribed speech
        self._subtitle_time = 0.0     # when it arrived (for fade-out)
        self._label_fade_state = {}   # label -> last position/level/time (fade-out)
        self._preview = False         # settings-window demo mode

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.apply_settings()
        self._fit_to_screen()

    # -- external API -------------------------------------------------------
    def set_frame(self, frame):
        self._frame = frame

    def set_detections(self, detections):
        self._detections = detections or []

    def set_subtitle(self, text):
        import time
        self._subtitle_text = text
        self._subtitle_time = time.time()

    def set_preview(self, on):
        self._preview = on

    def apply_settings(self):
        """Re-read window-level settings (opacity, click-through)."""
        self.setWindowOpacity(float(self.settings.get("overlay.opacity", 0.9)))
        click_through = bool(self.settings.get("overlay.click_through", True))
        self.setWindowFlag(Qt.WindowTransparentForInput, click_through)
        # Toggling a flag hides the window; re-show if we were visible.
        if self.isVisible():
            self.show()

    def _fit_to_screen(self):
        screen = QGuiApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

    # -- painting -----------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        ov = self.settings.data["overlay"]
        w, h = self.width(), self.height()
        cx = ov["center_x"] * w
        cy = ov["center_y"] * h
        base_r = float(ov["base_radius"])
        spacing = float(ov["ring_spacing"])
        gradient = self.settings.get("gradient", [[0.0, "#2b7bff"], [1.0, "#ff2020"]])

        rings = self._rings_to_draw()  # [(ring_index, [(label, angle, level), ...]), ...]

        # Faint centre dot so the user can position the HUD even when silent.
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 40)))
        p.drawEllipse(QPointF(cx, cy), 3, 3)

        if ov.get("show_compass", True):
            self._draw_compass(p, cx, cy, base_r + spacing * max(len(rings), 1))

        for ring_index, peaks in rings:
            ring_r = base_r + spacing * ring_index
            self._draw_ring_bg(p, cx, cy, ring_r)
            for angle, level in peaks:
                self._draw_arc(p, cx, cy, ring_r, angle, level, ov, gradient)

        # Labels are drawn separately so they can linger and fade after the
        # sound stops, instead of blinking out the instant it drops.
        if ov.get("show_labels", True):
            self._draw_labels_with_fade(p, cx, cy, base_r, spacing, rings, ov, gradient)

        self._draw_subtitle(p, w, h)

        p.end()

    def _draw_labels_with_fade(self, p, cx, cy, base_r, spacing, rings, ov, gradient):
        import time
        now = time.time()
        fade_dur = max(0.05, float(ov.get("label_fade", 1.5)))
        font_size = int(ov.get("label_font_size", 9))

        # Every label to show right now, each anchored to its band's peak.
        current = self._current_labels(base_r, spacing)
        for label, (ri, ring_r, angle, level) in current.items():
            st = self._label_fade_state.get(label)
            if st is None:
                st = {"born": now}          # first time we've seen this label
                self._label_fade_state[label] = st
            st.update({"ring_index": ri, "ring_r": ring_r,
                       "angle": angle, "level": level, "last": now})

        # Compute each label's fade; drop the fully-faded, draw fading arcs.
        drawable = []
        for label in list(self._label_fade_state.keys()):
            st = self._label_fade_state[label]
            if label in current:
                fade = 1.0
            else:
                fade = 1.0 - (now - st["last"]) / fade_dur
                if fade <= 0:
                    del self._label_fade_state[label]
                    continue
                self._draw_arc(p, cx, cy, st["ring_r"], st["angle"],
                               st["level"], ov, gradient, fade)
            drawable.append((label, st, fade))

        # Group labels that sit on the same arc (same ring + similar direction)
        # so they can be stacked instead of overprinting each other.
        groups = {}
        for label, st, fade in drawable:
            key = (st["ring_index"], round(math.degrees(st["angle"]) / 25.0))
            groups.setdefault(key, []).append((label, st, fade))

        p.setFont(QFont("Segoe UI", font_size, QFont.DemiBold))
        row_h = p.fontMetrics().height() + 3
        for members in groups.values():
            # Oldest at the base (row 0), newest stacked on top. When a label
            # fades out and is removed, the rows recompute and everyone drops
            # down to fill the gap.
            members.sort(key=lambda m: m[1]["born"])
            anchor = members[-1][1]                 # follow the newest arc
            label_r = anchor["ring_r"] + font_size + 9
            ax = cx + label_r * math.sin(anchor["angle"])
            ay = cy - label_r * math.cos(anchor["angle"])
            for r, (label, st, fade) in enumerate(members):
                color = _gradient_color(gradient, st["level"])
                self._blit_label(p, ax, ay - r * row_h, label, color, fade)

    def _blit_label(self, p, cx_text, baseline_y, text, color, fade):
        metrics = p.fontMetrics()
        tx = cx_text - metrics.horizontalAdvance(text) / 2
        ty = baseline_y + metrics.height() / 3
        # Subtle shadow for readability over bright game scenes.
        p.setPen(QColor(0, 0, 0, int(180 * fade)))
        p.drawText(QPointF(tx + 1, ty + 1), text)
        label_col = QColor(color)
        label_col.setAlpha(int(255 * max(0.0, min(1.0, fade))))
        p.setPen(label_col)
        p.drawText(QPointF(tx, ty), text)

    def _draw_subtitle(self, p, w, h):
        import time
        sub = self.settings.data.get("subtitles", {})
        text = self._subtitle_text
        if self._preview:
            text = "Subtitle preview - recognised speech appears here"
        if not text:
            return
        duration = float(sub.get("duration", 7.0))
        age = time.time() - self._subtitle_time
        if not self._preview and age > duration:
            return
        # Fade out over the last second.
        fade = 1.0 if self._preview else max(0.0, min(1.0, (duration - age) / 1.0))

        font = QFont("Segoe UI", int(sub.get("font_size", 18)), QFont.DemiBold)
        p.setFont(font)
        metrics = p.fontMetrics()

        max_w = int(w * 0.7)
        lines = self._wrap_text(text, metrics, max_w)
        line_h = metrics.height()
        block_h = line_h * len(lines)
        block_w = max(metrics.horizontalAdvance(ln) for ln in lines)

        cx = w / 2
        by = h * float(sub.get("position_y", 0.82))
        pad = 12
        box = QRectF(cx - block_w / 2 - pad, by - pad,
                     block_w + pad * 2, block_h + pad * 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, int(150 * fade))))
        p.drawRoundedRect(box, 8, 8)

        for i, line in enumerate(lines):
            tw = metrics.horizontalAdvance(line)
            tx = cx - tw / 2
            ty = by + line_h * (i + 1) - metrics.descent()
            p.setPen(QColor(0, 0, 0, int(200 * fade)))
            p.drawText(QPointF(tx + 1, ty + 1), line)
            p.setPen(QColor(255, 255, 255, int(255 * fade)))
            p.drawText(QPointF(tx, ty), line)

    @staticmethod
    def _wrap_text(text, metrics, max_w):
        words = text.split()
        lines, cur = [], ""
        for wd in words:
            trial = wd if not cur else cur + " " + wd
            if metrics.horizontalAdvance(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines or [text]

    def _rings_to_draw(self):
        """Directional arcs only: one ring per band, each with its peak(s).

        Returns [(ring_index, [(angle, level), ...]), ...]. Labels are handled
        separately (see _current_labels) so several sound types from the same
        direction can be stacked rather than fighting over one arc.
        """
        if self._preview:
            return self._demo_rings()
        frame = self._frame
        if frame is None:
            return []
        return [(i, list(b.peaks) if b.active else [])
                for i, b in enumerate(frame.bands)]

    def _demo_rings(self):
        import time
        t = time.time()
        def lvl(ph):
            return 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 1.2 + ph))
        return [
            (0, [((t * 0.4) % (2 * math.pi), lvl(0))]),
            (1, [((t * 0.5 + 2.0) % (2 * math.pi), lvl(2.5))]),
            # High ring: single arc that several demo labels will stack on.
            (2, [((t * 0.6 + 4.0) % (2 * math.pi), lvl(3.5))]),
        ]

    def _current_labels(self, base_r, spacing):
        """Map every active label to its band's peak: {label: (ring_i, ring_r,
        angle, level)}. Multiple labels can share one peak (they get stacked)."""
        if self._preview:
            return self._demo_labels(base_r, spacing)
        frame = self._frame
        if frame is None:
            return {}
        class_on = self.settings.get("classification.enabled", True)
        out = {}
        if class_on:
            det_by_band = {}
            for d in self._detections:
                det_by_band.setdefault(d.band, []).append(d)
            for i, b in enumerate(frame.bands):
                if not (b.active and b.peaks):
                    continue
                dets = sorted(det_by_band.get(b.name, []), key=lambda d: -d.score)
                for j, d in enumerate(dets):
                    # Spread across peaks when possible; extras stack on the last.
                    angle, level = b.peaks[min(j, len(b.peaks) - 1)]
                    out[d.name] = (i, base_r + spacing * i, angle, level)
        else:
            for i, b in enumerate(frame.bands):
                if b.active and b.peaks:
                    angle, level = b.peaks[0]
                    label = f"{b.name} - {b.hint}" if b.hint else b.name
                    out[label] = (i, base_r + spacing * i, angle, level)
        return out

    def _demo_labels(self, base_r, spacing):
        import time
        t = time.time()
        class_on = self.settings.get("classification.enabled", True)
        angle = (t * 0.6 + 4.0) % (2 * math.pi)          # the High demo arc
        ring_r = base_r + spacing * 2
        lvl = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 1.2 + 3.5))
        if class_on:
            # Three types cycling on one arc to show stacking + fade.
            labels = ["Gunfire", "Glass", "Siren/Alarm"]
            n = 1 + int(t / 1.5) % 3
            return {lab: (2, ring_r, angle, lvl) for lab in labels[:n]}
        return {"High - gunshots / clicks": (2, ring_r, angle, lvl)}

    def _draw_ring_bg(self, p, cx, cy, ring_r):
        pen = QPen(QColor(255, 255, 255, 22), 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

    def _draw_arc(self, p, cx, cy, ring_r, angle, level, ov, gradient, fade=1.0):
        if level <= 0.001 or fade <= 0.0:
            return

        color = _gradient_color(gradient, level)
        alpha = int((70 + 185 * min(1.0, level)) * fade)
        color.setAlpha(alpha)

        # Convert our angle (0 = front/up, + = clockwise) to Qt's angle system
        # (0 = 3 o'clock, counter-clockwise positive).
        deg = math.degrees(angle)
        qt_center = 90.0 - deg
        span = float(ov.get("blip_span_deg", 46))
        thickness = float(ov.get("thickness", 12))

        rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        pen = QPen(color, thickness)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Qt drawArc units are 1/16 degree.
        p.drawArc(rect, int((qt_center - span / 2) * 16), int(span * 16))

        # A pointed tip at the exact direction for a clear "this way" cue.
        tip_r = ring_r + thickness * 0.6
        tx = cx + tip_r * math.sin(angle)
        ty = cy - tip_r * math.cos(angle)
        p.setPen(Qt.NoPen)
        tip = QColor(color)
        tip.setAlpha(min(255, int((alpha + 40))))
        p.setBrush(QBrush(tip))
        p.drawEllipse(QPointF(tx, ty), thickness * 0.4, thickness * 0.4)

    def _draw_compass(self, p, cx, cy, outer_r):
        font = QFont("Segoe UI", 10, QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 120))
        r = outer_r + 6
        marks = [("F", 0), ("R", 90), ("B", 180), ("L", 270)]
        for label, deg in marks:
            a = math.radians(deg)
            x = cx + r * math.sin(a)
            y = cy - r * math.cos(a)
            p.drawText(QRectF(x - 10, y - 10, 20, 20), Qt.AlignCenter, label)
