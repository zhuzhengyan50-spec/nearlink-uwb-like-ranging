"""Main controls for acquisition, simulation, and optional visualization filters."""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


DEFAULT_ANCHOR_COUNT = 4


class ControlPanel(QGroupBox):
    """Controls needed while ranging and positioning are running."""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()
    export_clicked = pyqtSignal()
    mode_changed = pyqtSignal(str)
    iq_parse_toggled = pyqtSignal(bool)
    position_kf_toggled = pyqtSignal(bool)
    sensing_toggled = pyqtSignal(bool)
    sensing_kf_toggled = pyqtSignal(bool)
    client_selection_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__("系统控制")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        mode_label = QLabel("数据源模式:")
        mode_label.setFont(QFont("Arial", 9, QFont.Bold))
        layout.addWidget(mode_label)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["串口数据 (Serial)", "模拟数据 (Simulation)"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.chk_iq_parse = QCheckBox("解析 IQ（关闭后仅保留测距定位）")
        self.chk_iq_parse.setChecked(True)
        self.chk_iq_parse.toggled.connect(self.iq_parse_toggled.emit)
        layout.addWidget(self.chk_iq_parse)

        self.chk_position_kf = QCheckBox("位置轨迹 Kalman 平滑")
        self.chk_position_kf.setChecked(True)
        self.chk_position_kf.toggled.connect(self.position_kf_toggled.emit)
        layout.addWidget(self.chk_position_kf)

        self.chk_sensing = QCheckBox("空间感知投影热图")
        self.chk_sensing.setChecked(True)
        self.chk_sensing.toggled.connect(self.sensing_toggled.emit)
        layout.addWidget(self.chk_sensing)

        self.chk_sensing_kf = QCheckBox("空间热图 Kalman 平滑")
        self.chk_sensing_kf.setChecked(True)
        self.chk_sensing_kf.toggled.connect(self.sensing_kf_toggled.emit)
        layout.addWidget(self.chk_sensing_kf)

        client_layout = QHBoxLayout()
        client_layout.addWidget(QLabel("显示终端:"))
        self.client_combo = QComboBox()
        self.client_combo.addItem("自动（最新）", "__auto__")
        self.client_combo.currentIndexChanged.connect(self._on_client_selection_changed)
        client_layout.addWidget(self.client_combo)
        layout.addLayout(client_layout)

        self.btn_start = QPushButton("▶ 开始定位")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_clicked.emit)
        layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■ 停止定位")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_stop.setEnabled(False)
        layout.addWidget(self.btn_stop)

        self.btn_reset = QPushButton("↺ 重置")
        self.btn_reset.setFixedHeight(35)
        self.btn_reset.clicked.connect(self.reset_clicked.emit)
        layout.addWidget(self.btn_reset)

        self.sim_frame = QFrame()
        sim_layout = QVBoxLayout(self.sim_frame)
        sim_layout.setSpacing(6)
        sim_title = QLabel("模拟数据设置")
        sim_title.setFont(QFont("Arial", 9, QFont.Bold))
        sim_layout.addWidget(sim_title)
        sim_grid = QGridLayout()

        sim_grid.addWidget(QLabel("刷新率(ms):"), 0, 0)
        self.spin_refresh_ms = QSpinBox()
        self.spin_refresh_ms.setRange(20, 1000)
        self.spin_refresh_ms.setValue(50)
        sim_grid.addWidget(self.spin_refresh_ms, 0, 1)

        sim_grid.addWidget(QLabel("基础噪声σ(m):"), 1, 0)
        self.spin_noise_std = QDoubleSpinBox()
        self.spin_noise_std.setRange(0.0, 5.0)
        self.spin_noise_std.setSingleStep(0.01)
        self.spin_noise_std.setDecimals(2)
        self.spin_noise_std.setValue(0.10)
        sim_grid.addWidget(self.spin_noise_std, 1, 1)

        self.chk_simulate_rssi = QCheckBox("模拟各 Anchor RSSI")
        self.chk_simulate_rssi.setChecked(True)
        sim_grid.addWidget(self.chk_simulate_rssi, 2, 0, 1, 2)

        sim_grid.addWidget(QLabel("速度(m/s):"), 3, 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.1, 20.0)
        self.spin_speed.setSingleStep(0.1)
        self.spin_speed.setDecimals(2)
        self.spin_speed.setValue(2.0)
        sim_grid.addWidget(self.spin_speed, 3, 1)

        self.spin_start_x, self.spin_start_y, self.spin_start_z = self._add_point_row(
            sim_grid, 4, "起点X/Y/Z:", (10.0, 10.0, 1.5)
        )
        self.spin_end_x, self.spin_end_y, self.spin_end_z = self._add_point_row(
            sim_grid, 5, "终点X/Y/Z:", (40.0, 40.0, 1.5)
        )

        self._anchor_count = DEFAULT_ANCHOR_COUNT
        self._sim_grid = sim_grid
        self.anchor_noise_labels = []
        self.anchor_noise_ranges = []
        self._ensure_anchor_noise_rows(self._anchor_count)
        sim_layout.addLayout(sim_grid)
        layout.addWidget(self.sim_frame)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        self.btn_export = QPushButton("📥 导出定位数据")
        self.btn_export.setFixedHeight(35)
        self.btn_export.clicked.connect(self.export_clicked.emit)
        layout.addWidget(self.btn_export)
        self.chk_export_truth = QCheckBox("导出包含真值位置")
        self.chk_export_truth.setChecked(True)
        layout.addWidget(self.chk_export_truth)
        layout.addStretch()
        self._on_mode_changed(self.mode_combo.currentIndex())

    def _ensure_anchor_noise_rows(self, count):
        """Grow the simulation controls and show only the active anchor rows."""
        count = max(1, int(count))
        while len(self.anchor_noise_ranges) < count:
            idx = len(self.anchor_noise_ranges)
            label = QLabel(f"A{idx + 1}噪声σ区间:")
            range_layout = QHBoxLayout()
            spin_min = self._noise_spin(0.05)
            spin_max = self._noise_spin(0.20)
            range_layout.addWidget(spin_min)
            range_layout.addWidget(QLabel("~"))
            range_layout.addWidget(spin_max)
            range_layout.addStretch()
            row_widget = QWidget()
            row_widget.setLayout(range_layout)
            self._sim_grid.addWidget(label, 6 + idx, 0)
            self._sim_grid.addWidget(row_widget, 6 + idx, 1)
            self.anchor_noise_labels.append(label)
            self.anchor_noise_ranges.append((spin_min, spin_max))
            spin_min._range_row_widget = row_widget
        for idx, (spin_min, _spin_max) in enumerate(self.anchor_noise_ranges):
            visible = idx < count
            self.anchor_noise_labels[idx].setVisible(visible)
            spin_min._range_row_widget.setVisible(visible)

    def set_anchor_count(self, count):
        """Synchronize simulation controls with the configured anchor count."""
        self._anchor_count = max(1, int(count))
        self._ensure_anchor_noise_rows(self._anchor_count)

    @staticmethod
    def _noise_spin(value):
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 5.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.01)
        spin.setValue(value)
        spin.setFixedWidth(62)
        return spin

    @staticmethod
    def _add_point_row(grid, row, label, values):
        grid.addWidget(QLabel(label), row, 0)
        point_layout = QHBoxLayout()
        spins = []
        for value in values:
            spin = QDoubleSpinBox()
            spin.setRange(-1000.0, 1000.0)
            spin.setDecimals(2)
            spin.setValue(value)
            spin.setSingleStep(0.5)
            spin.setFixedWidth(62)
            point_layout.addWidget(spin)
            spins.append(spin)
        point_layout.addStretch()
        grid.addLayout(point_layout, row, 1)
        return tuple(spins)

    def _on_mode_changed(self, _index):
        mode = self.get_mode()
        self.sim_frame.setVisible(mode == "simulation")
        self.mode_changed.emit(mode)

    def get_mode(self):
        return ("serial", "simulation")[min(self.mode_combo.currentIndex(), 1)]

    def set_running_state(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.mode_combo.setEnabled(not running)
        self.sim_frame.setEnabled(not running)

    def should_export_true_position(self):
        return self.chk_export_truth.isChecked()

    def is_iq_parse_enabled(self):
        return self.chk_iq_parse.isChecked()

    def is_position_kf_enabled(self):
        return self.chk_position_kf.isChecked()

    def is_spatial_sensing_enabled(self):
        return self.chk_sensing.isChecked()

    def is_sensing_kf_enabled(self):
        return self.chk_sensing_kf.isChecked()

    def set_iq_parse_enabled(self, enabled: bool):
        self.chk_iq_parse.blockSignals(True)
        self.chk_iq_parse.setChecked(bool(enabled))
        self.chk_iq_parse.blockSignals(False)

    def _on_client_selection_changed(self, _index):
        self.client_selection_changed.emit(self.get_selected_client_key())

    def update_client_choices(self, client_items):
        current_key = self.get_selected_client_key()
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        self.client_combo.addItem("自动（最新）", "__auto__")
        for item in client_items or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                label, key = str(item[0]), str(item[1])
            else:
                label = key = str(item)
            self.client_combo.addItem(label, key)
        restore_index = self.client_combo.findData(current_key)
        self.client_combo.setCurrentIndex(max(restore_index, 0))
        self.client_combo.blockSignals(False)

    def get_selected_client_key(self):
        data = self.client_combo.currentData()
        return "__auto__" if data is None else str(data)

    def get_simulation_config(self):
        noise_ranges = []
        for spin_min, spin_max in self.anchor_noise_ranges[:self._anchor_count]:
            min_val, max_val = float(spin_min.value()), float(spin_max.value())
            noise_ranges.append([min(min_val, max_val), max(min_val, max_val)])
        return {
            "refresh_ms": int(self.spin_refresh_ms.value()),
            "noise_std": float(self.spin_noise_std.value()),
            "simulate_rssi": self.chk_simulate_rssi.isChecked(),
            "per_anchor_noise_ranges": noise_ranges,
            "speed_mps": float(self.spin_speed.value()),
            "start_point": [self.spin_start_x.value(), self.spin_start_y.value(), self.spin_start_z.value()],
            "end_point": [self.spin_end_x.value(), self.spin_end_y.value(), self.spin_end_z.value()],
        }
