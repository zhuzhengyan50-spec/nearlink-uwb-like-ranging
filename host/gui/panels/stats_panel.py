"""
Statistics panel for current selected client and per-client FPS.
"""

import time

from PyQt5.QtWidgets import QFrame, QGridLayout, QGroupBox, QLabel, QVBoxLayout
from PyQt5.QtGui import QFont


class StatsPanel(QGroupBox):
    """Realtime stats summary."""

    def __init__(self):
        super().__init__("Data Stats")
        self._last_timestamp_by_client = {}
        self._fps_by_client = {}
        self._last_update_ts = None
        self._avg_fps = 0.0
        self._fps_smooth = 0.08
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        current_frame = QFrame()
        current_frame.setStyleSheet("QFrame { background-color: white; border: 1px solid black; border-radius: 3px; }")
        current_layout = QGridLayout(current_frame)
        current_layout.setContentsMargins(10, 10, 10, 10)

        current_layout.addWidget(QLabel("Current Position:"), 0, 0)
        self.lbl_current_x = QLabel("X: --")
        current_layout.addWidget(self.lbl_current_x, 0, 1)
        self.lbl_current_y = QLabel("Y: --")
        current_layout.addWidget(self.lbl_current_y, 0, 2)
        self.lbl_kf_xy = QLabel("KF XY: --")
        current_layout.addWidget(self.lbl_kf_xy, 0, 3)

        current_layout.addWidget(QLabel(""), 1, 0)
        self.lbl_current_z = QLabel("Z: --")
        current_layout.addWidget(self.lbl_current_z, 1, 1)
        self.lbl_client = QLabel("Client: --")
        current_layout.addWidget(self.lbl_client, 1, 2)
        self.lbl_kf_z = QLabel("KF Z: --")
        current_layout.addWidget(self.lbl_kf_z, 1, 3)

        layout.addWidget(current_frame)

        valid_frame = QFrame()
        valid_frame.setStyleSheet("QFrame { background-color: white; border: 1px solid black; border-radius: 3px; }")
        valid_layout = QVBoxLayout(valid_frame)
        valid_layout.setContentsMargins(10, 10, 10, 10)

        self.lbl_valid_count = QLabel("Valid anchors: --")
        self.lbl_valid_count.setFont(QFont("Arial", 10, QFont.Bold))
        valid_layout.addWidget(self.lbl_valid_count)

        layout.addWidget(valid_frame)

        fps_frame = QFrame()
        fps_frame.setStyleSheet("QFrame { background-color: white; border: 1px solid black; border-radius: 3px; }")
        fps_layout = QVBoxLayout(fps_frame)
        fps_layout.setContentsMargins(10, 10, 10, 10)
        fps_layout.setSpacing(6)

        self.lbl_active_clients = QLabel("Active clients: 0")
        self.lbl_active_clients.setFont(QFont("Arial", 9, QFont.Bold))
        fps_layout.addWidget(self.lbl_active_clients)

        self.lbl_avg_fps = QLabel("Avg FPS: --")
        self.lbl_avg_fps.setFont(QFont("Arial", 10, QFont.Bold))
        self.lbl_avg_fps.setStyleSheet("color: #0B5394;")
        fps_layout.addWidget(self.lbl_avg_fps)

        self.lbl_client_fps = QLabel("FPS: --")
        self.lbl_client_fps.setWordWrap(True)
        self.lbl_client_fps.setStyleSheet("color: black;")
        fps_layout.addWidget(self.lbl_client_fps)

        layout.addWidget(fps_frame)
        layout.addStretch()

    def update_stats(self, data):
        """Update panel from latest UI-driving data."""
        if not data:
            return

        now = time.time()
        if self._last_update_ts is not None:
            instant_fps = 1.0 / max(1e-6, now - self._last_update_ts)
            self._avg_fps += self._fps_smooth * (instant_fps - self._avg_fps)
        self._last_update_ts = now
        self.lbl_avg_fps.setText(f"Avg FPS: {self._avg_fps:.1f}")

        position = data.get('position')
        kf_position = data.get('kf_position')
        if position:
            self.lbl_current_x.setText(f"X: {position[0]:.2f}")
            self.lbl_current_y.setText(f"Y: {position[1]:.2f}")
            self.lbl_current_z.setText(f"Z: {position[2]:.2f}" if len(position) > 2 else "Z: --")
        else:
            self.lbl_current_x.setText("X: --")
            self.lbl_current_y.setText("Y: --")
            self.lbl_current_z.setText("Z: --")

        if data.get('kf_enabled') and kf_position:
            self.lbl_kf_xy.setText(f"KF XY: {kf_position[0]:.2f}, {kf_position[1]:.2f}")
            self.lbl_kf_z.setText(f"KF Z: {kf_position[2]:.2f}" if len(kf_position) > 2 else "KF Z: --")
        else:
            self.lbl_kf_xy.setText("KF XY: --")
            self.lbl_kf_z.setText("KF Z: --")

        client_label = data.get('client_label') or data.get('client_key')
        source_addr_byte = data.get('source_addr_byte')
        if client_label and source_addr_byte is not None:
            self.lbl_client.setText(f"Client: {client_label} (addr={source_addr_byte})")
        elif client_label:
            self.lbl_client.setText(f"Client: {client_label}")
        else:
            self.lbl_client.setText("Client: --")

        valid_count = data.get('valid_count', 0)
        total_count = len(data.get('distances') or [])
        self.lbl_valid_count.setText(f"Valid anchors: {valid_count}/{total_count}")

        clients = data.get('clients') or {}
        self._update_client_fps(clients)

    def _update_client_fps(self, clients):
        active_clients = []
        for client_key, client_data in clients.items():
            label = client_data.get('client_label') or client_key
            addr = client_data.get('source_addr_byte')
            if addr is not None:
                label = f"{label} (addr={addr})"

            last_timestamp = client_data.get('last_timestamp')
            if last_timestamp is not None:
                try:
                    last_timestamp = float(last_timestamp)
                except (TypeError, ValueError):
                    last_timestamp = None

            prev_timestamp = self._last_timestamp_by_client.get(client_key)
            if last_timestamp is not None:
                if prev_timestamp is not None and last_timestamp > prev_timestamp:
                    self._fps_by_client[client_key] = 1.0 / max(1e-6, last_timestamp - prev_timestamp)
                self._last_timestamp_by_client[client_key] = last_timestamp

            fps = self._fps_by_client.get(client_key)
            fps_text = "--" if fps is None else f"{fps:.2f}"
            active_clients.append(f"{label}: {fps_text} fps")

        self.lbl_active_clients.setText(f"Active clients: {len(clients)}")
        self.lbl_client_fps.setText("FPS: --" if not active_clients else "FPS:\n" + "\n".join(active_clients))

    def reset_stats(self):
        """Reset panel state."""
        self._last_timestamp_by_client.clear()
        self._fps_by_client.clear()
        self._last_update_ts = None
        self._avg_fps = 0.0
        self.lbl_avg_fps.setText("Avg FPS: --")
        self.lbl_current_x.setText("X: --")
        self.lbl_current_y.setText("Y: --")
        self.lbl_current_z.setText("Z: --")
        self.lbl_kf_xy.setText("KF XY: --")
        self.lbl_kf_z.setText("KF Z: --")
        self.lbl_client.setText("Client: --")
        self.lbl_valid_count.setText("Valid anchors: --")
        self.lbl_active_clients.setText("Active clients: 0")
        self.lbl_client_fps.setText("FPS: --")
