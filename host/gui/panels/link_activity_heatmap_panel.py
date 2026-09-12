"""Right-side panel for room-level link activity heatmap."""

from __future__ import annotations

import numpy as np

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame, QGroupBox, QLabel, QVBoxLayout

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class LinkActivityHeatmapPanel(QGroupBox):
    """Displays aggregated link activity as a 2D heatmap with top links."""

    def __init__(self):
        super().__init__("Link Activity Heatmap")
        self._heatmap_artist = None
        self._anchor_scatter = None
        self._anchor_labels = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.lbl_hint = QLabel("Spatial projection of the selected score along positioned links.")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: #35556f; font-size: 11px;")
        layout.addWidget(self.lbl_hint)

        frame = QFrame()
        frame.setStyleSheet("QFrame { background-color: white; border: 1px solid black; border-radius: 3px; }")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(6, 6, 6, 6)

        self.figure = Figure(figsize=(4.2, 3.2), facecolor="white")
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("Room Disturbance", fontsize=11, fontweight="bold")
        self.ax.set_xlabel("X (m)")
        self.ax.set_ylabel("Y (m)")
        self.ax.grid(True, linestyle="--", alpha=0.25)
        self.ax.set_aspect("equal")
        frame_layout.addWidget(self.canvas)
        layout.addWidget(frame, 1)

        self.lbl_top_links = QLabel("Top active links: --")
        self.lbl_top_links.setFont(QFont("Arial", 9, QFont.Bold))
        self.lbl_top_links.setWordWrap(True)
        layout.addWidget(self.lbl_top_links)

    def set_metric_label(self, label):
        self.ax.set_title(f"Spatial {label}", fontsize=11, fontweight="bold")

    def update_heatmap(self, data, message="Waiting for positioned links"):
        if not data:
            self._clear_plot()
            self.lbl_top_links.setText(message)
            return

        heatmap = np.asarray(data.get("heatmap")) if data.get("heatmap") is not None else np.asarray([])
        extent = data.get("extent") or (0.0, 50.0, 0.0, 50.0)
        anchors_2d = data.get("anchors_2d") or []
        top_links = data.get("top_links") or []

        if heatmap.size == 0:
            self._clear_plot()
        else:
            if self._heatmap_artist is None:
                self._heatmap_artist = self.ax.imshow(
                    heatmap,
                    extent=extent,
                    origin="lower",
                    cmap="jet",
                    alpha=0.68,
                    aspect="auto",
                    vmin=0.0,
                    vmax=1.0,
                    interpolation="bilinear",
                )
            else:
                self._heatmap_artist.set_data(heatmap)
                self._heatmap_artist.set_extent(extent)

            self.ax.set_xlim(extent[0], extent[1])
            self.ax.set_ylim(extent[2], extent[3])
            self._update_anchors(anchors_2d)

        if not top_links:
            self.lbl_top_links.setText("Top active links: --")
        else:
            lines = []
            for item in top_links[:4]:
                label = str(item.get("client_label") or item.get("client_key") or "")
                lines.append(f"{item.get('anchor_id')}-{label}: {float(item.get('score') or 0.0):.2f}")
            self.lbl_top_links.setText("Top active links:\n" + "\n".join(lines))

        self.canvas.draw_idle()

    def _update_anchors(self, anchors_2d):
        for text in self._anchor_labels:
            self._remove_artist(text)
        self._anchor_labels = []

        if anchors_2d:
            xs = [float(pt[0]) for pt in anchors_2d if len(pt) >= 2]
            ys = [float(pt[1]) for pt in anchors_2d if len(pt) >= 2]
            if self._anchor_scatter is None:
                self._anchor_scatter = self.ax.scatter(xs, ys, c="white", edgecolors="black", s=55, zorder=5)
            else:
                self._anchor_scatter.set_offsets(np.column_stack([xs, ys]))
            for idx, (x, y) in enumerate(zip(xs, ys), start=1):
                self._anchor_labels.append(
                    self.ax.text(x + 0.6, y + 0.6, f"A{idx}", fontsize=8, color="black", zorder=6)
                )
        elif self._anchor_scatter is not None:
            self._anchor_scatter.set_offsets(np.zeros((0, 2)))

    def _clear_plot(self):
        if self._heatmap_artist is not None:
            self._heatmap_artist.set_data(np.zeros((2, 2), dtype=float))
            self._heatmap_artist.set_extent((0.0, 1.0, 0.0, 1.0))
        if self._anchor_scatter is not None:
            self._anchor_scatter.set_offsets(np.zeros((0, 2)))
        for text in self._anchor_labels:
            self._remove_artist(text)
        self._anchor_labels = []
        self.ax.set_xlim(0.0, 50.0)
        self.ax.set_ylim(0.0, 50.0)
        self.canvas.draw_idle()

    @staticmethod
    def _remove_artist(artist):
        try:
            artist.remove()
        except (ValueError, NotImplementedError):
            pass
