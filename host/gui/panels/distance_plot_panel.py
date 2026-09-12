"""
Per-client distance trend panel.
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QSizePolicy, QSpinBox, QVBoxLayout


class DistancePlotPanel(QGroupBox):
    """Distance trend panel for one client."""

    def __init__(self, max_points=100, anchor_count=4):
        super().__init__("Distance Trend")
        self.max_points = max_points
        self.anchor_names = [f"A{index}" for index in range(1, max(1, int(anchor_count)) + 1)]
        self.client_label = "Client"
        self.source_addr_byte = None
        self._session_start_ts = None
        self._current_time = 0.0
        self.series = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 16, 8, 8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        header_layout = QHBoxLayout()
        self.lbl_client = QLabel("Client: --")
        self.lbl_client.setStyleSheet("font-weight: bold; color: black;")
        header_layout.addWidget(self.lbl_client)

        header_layout.addWidget(QLabel("History:"))
        self.spin_history = QSpinBox()
        self.spin_history.setRange(50, 1000)
        self.spin_history.setValue(self.max_points)
        self.spin_history.setSingleStep(50)
        self.spin_history.valueChanged.connect(self._update_history_length)
        header_layout.addWidget(self.spin_history)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_widget.setBackground("white")
        self.plot_widget.setMinimumHeight(180)
        self.plot_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plot = self.plot_widget.addPlot(title="")
        self.plot.setLabel("left", "Distance", "m", color="black")
        self.plot.setLabel("bottom", "Relative Time", "s", color="black")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.getAxis("left").setPen(pg.mkPen("black", width=1))
        self.plot.getAxis("left").setTextPen(pg.mkPen("black"))
        self.plot.getAxis("bottom").setPen(pg.mkPen("black", width=1))
        self.plot.getAxis("bottom").setTextPen(pg.mkPen("black"))
        self.plot.addLegend(offset=(10, 10))
        layout.addWidget(self.plot_widget, 1)

        self.lbl_current = QLabel("Current: --")
        self.lbl_current.setStyleSheet("color: black; font-size: 10px; font-weight: bold;")
        layout.addWidget(self.lbl_current)

        self.lbl_status = QLabel("Waiting for data...")
        self.lbl_status.setStyleSheet("color: #555555; font-size: 9px;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_status)

        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid black;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                color: black;
                background-color: #f9f9f9;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)

    def set_client_info(self, client_label=None, source_addr_byte=None):
        self.client_label = str(client_label or "Client")
        self.source_addr_byte = source_addr_byte
        title = self.client_label
        if source_addr_byte is not None:
            title = f"{title} (addr={source_addr_byte})"
        self.lbl_client.setText(f"Client: {title}")
        self.setTitle(f"Distance Trend - {self.client_label}")

    def set_preferred_plot_height(self, height):
        height = max(160, int(height))
        self.plot_widget.setMinimumHeight(height)

    def add_distance_data(self, distances, rssi_values=None, timestamp=None):
        rssi_values = rssi_values or []
        current_time = self._normalize_time(timestamp)
        latest_summary = []
        valid_count = 0

        for i, anchor in enumerate(self.anchor_names):
            value = self._normalize_distance(distances, i)
            rssi = rssi_values[i] if i < len(rssi_values) else None
            entry = self._ensure_series(anchor)

            entry["times"].append(current_time)
            entry["values"].append(value)
            entry["rssis"].append(rssi)

            if len(entry["times"]) > self.max_points:
                entry["times"] = entry["times"][-self.max_points:]
                entry["values"] = entry["values"][-self.max_points:]
                entry["rssis"] = entry["rssis"][-self.max_points:]

            if np.isfinite(value):
                valid_count += 1
                if rssi is None:
                    latest_summary.append(f"{anchor}:{value:.2f}m")
                else:
                    latest_summary.append(f"{anchor}:{value:.2f}m/{int(rssi)}dBm")

        self._update_plot()
        self.lbl_status.setText(f"Valid anchors: {valid_count} / {len(self.anchor_names)}")
        self.lbl_current.setText("Current: " + (", ".join(latest_summary) if latest_summary else "--"))

    def _normalize_distance(self, distances, index):
        if index >= len(distances):
            return float("nan")
        value = distances[index]
        if value is None:
            return float("nan")
        try:
            value = float(value)
        except (TypeError, ValueError):
            return float("nan")
        return value if value > 0 else float("nan")

    def _normalize_time(self, timestamp):
        if timestamp is None:
            self._current_time += 0.05
            return self._current_time
        ts = float(timestamp)
        if self._session_start_ts is None:
            self._session_start_ts = ts
        current_time = max(0.0, ts - self._session_start_ts)
        self._current_time = max(self._current_time, current_time)
        return current_time

    def _ensure_series(self, anchor):
        entry = self.series.get(anchor)
        if entry is not None:
            return entry

        color = pg.intColor(max(0, int(anchor[1:]) - 1), hues=max(8, len(self.anchor_names))).name()
        pen = pg.mkPen(color, width=2)
        curve = self.plot.plot([], [], pen=pen, name=anchor)
        label = pg.TextItem(text="", color=color, anchor=(0, 1))
        label.setZValue(10)
        self.plot.addItem(label)

        entry = {
            "curve": curve,
            "label": label,
            "times": [],
            "values": [],
            "rssis": [],
        }
        self.series[anchor] = entry
        return entry

    def _update_plot(self):
        for anchor, entry in self.series.items():
            times = np.array(entry["times"], dtype=float)
            values = np.array(entry["values"], dtype=float)
            entry["curve"].setData(times, values)

            if len(times) > 0 and len(values) > 0 and np.isfinite(values[-1]):
                latest_rssi = entry["rssis"][-1] if entry["rssis"] else None
                if latest_rssi is None:
                    text = f"{anchor}: {values[-1]:.2f}m"
                else:
                    text = f"{anchor}: {values[-1]:.2f}m/{int(latest_rssi)}dBm"
                entry["label"].setText(text)
                entry["label"].setPos(float(times[-1]), float(values[-1]))
                entry["label"].setVisible(True)
            else:
                entry["label"].setText("")
                entry["label"].setVisible(False)

    def _update_history_length(self, new_length):
        self.max_points = int(new_length)
        for entry in self.series.values():
            entry["times"] = entry["times"][-self.max_points:]
            entry["values"] = entry["values"][-self.max_points:]
            entry["rssis"] = entry["rssis"][-self.max_points:]
        self._update_plot()

    def set_anchor_count(self, count):
        """Use the active anchor count for subsequent samples."""
        count = max(1, int(count))
        self.anchor_names = [f"A{index}" for index in range(1, count + 1)]
        self.clear_plot()

    def clear_plot(self):
        self._session_start_ts = None
        self._current_time = 0.0
        for entry in self.series.values():
            entry["curve"].setData([], [])
            entry["label"].setText("")
            entry["label"].setVisible(False)
        self.series.clear()
        self.plot.clear()
        self.plot.addLegend(offset=(10, 10))
        self.lbl_current.setText("Current: --")
        self.lbl_status.setText("Waiting for data...")
