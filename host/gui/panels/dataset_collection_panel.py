"""Research dataset labeling, progress monitoring, and export controls."""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)


DEFAULT_ANCHOR_COUNT = 4


class DatasetCollectionPanel(QWidget):
    """Full-page workflow for collecting labeled paired-IQ datasets."""

    export_dataset_clicked = pyqtSignal()
    start_new_group_clicked = pyqtSignal()
    collection_enabled_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.anchor_dataset_config = {}
        self._last_dataset_counts = {}
        self._anchor_count = DEFAULT_ANCHOR_COUNT
        self._init_ui()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(14)

        title = QLabel("研究数据采集")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        description = QLabel(
            "为每个 Anchor 设置场景、真实距离和样本组。运行串口测距并开启 IQ 解析后，"
            "软件会配对双向 IQ、统计采集进度，并导出可复现的研究数据集。"
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #35556f;")
        layout.addWidget(description)

        session_group = QGroupBox("采集会话")
        session_layout = QGridLayout(session_group)
        self.chk_collect_data = QCheckBox("记录并保存当前会话的配对 IQ 数据")
        self.chk_collect_data.setChecked(True)
        self.chk_collect_data.toggled.connect(self.collection_enabled_changed.emit)
        session_layout.addWidget(self.chk_collect_data, 0, 0, 1, 2)
        session_layout.addWidget(QLabel("场景标签:"), 1, 0)
        self.edit_scene_label = QLineEdit("LOS")
        self.edit_scene_label.setPlaceholderText("例如 LOS、NLOS-wall、corridor")
        session_layout.addWidget(self.edit_scene_label, 1, 1)
        self.lbl_session_path = QLabel("会话文件：尚未开始采集")
        self.lbl_session_path.setWordWrap(True)
        self.lbl_session_path.setStyleSheet("color: #666666;")
        session_layout.addWidget(self.lbl_session_path, 2, 0, 1, 2)
        layout.addWidget(session_group)

        labels_group = QGroupBox("Anchor 标签与目标样本数")
        self._labels_layout = QGridLayout(labels_group)
        headers = ("Anchor", "距离标签", "样本组", "真实距离(m)", "目标样本数", "采集进度")
        for column, text in enumerate(headers):
            header = QLabel(text)
            header.setFont(QFont("Arial", 9, QFont.Bold))
            self._labels_layout.addWidget(header, 0, column)
        self._ensure_anchor_rows(self._anchor_count)
        layout.addWidget(labels_group)

        export_group = QGroupBox("导出内容")
        export_layout = QVBoxLayout(export_group)
        caliber_layout = QHBoxLayout()
        self.chk_export_raw = QCheckBox("Raw IQ")
        self.chk_export_raw.setChecked(True)
        self.chk_export_features = QCheckBox("CFR / MUSIC / 质量特征")
        self.chk_export_features.setChecked(True)
        self.chk_export_time = QCheckBox("时序特征")
        self.chk_export_time.setChecked(True)
        caliber_layout.addWidget(self.chk_export_raw)
        caliber_layout.addWidget(self.chk_export_features)
        caliber_layout.addWidget(self.chk_export_time)
        caliber_layout.addStretch()
        export_layout.addLayout(caliber_layout)

        hint = QLabel(
            "推荐流程：设置标签 → 新建采集组 → 返回定位页开始串口采集 → "
            "达到目标样本数后导出 CSV。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #35556f;")
        export_layout.addWidget(hint)
        button_layout = QHBoxLayout()
        self.btn_new_group = QPushButton("新建采集组")
        self.btn_new_group.setFixedHeight(38)
        self.btn_new_group.clicked.connect(self.start_new_group_clicked.emit)
        button_layout.addWidget(self.btn_new_group)
        self.btn_export_dataset = QPushButton("导出研究数据集 CSV")
        self.btn_export_dataset.setFixedHeight(38)
        self.btn_export_dataset.clicked.connect(self.export_dataset_clicked.emit)
        button_layout.addWidget(self.btn_export_dataset)
        export_layout.addLayout(button_layout)
        layout.addWidget(export_group)
        layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        self.edit_scene_label.editingFinished.connect(self._auto_fill_all_anchor_fields)

    def _ensure_anchor_rows(self, count):
        count = max(1, int(count))
        while len(self.anchor_dataset_config) < count:
            index = len(self.anchor_dataset_config) + 1
            anchor_id = f"A{index}"
            label = QLabel(anchor_id)
            distance_label = QLineEdit("5m")
            sample_group = QLineEdit(f"los_5m_{anchor_id.lower()}")
            reference_distance = QDoubleSpinBox()
            reference_distance.setRange(0.0, 1000.0)
            reference_distance.setDecimals(3)
            reference_distance.setSingleStep(0.1)
            reference_distance.setValue(5.0)
            target_count = QSpinBox()
            target_count.setRange(1, 1_000_000)
            target_count.setValue(500)
            progress = QProgressBar()
            progress.setRange(0, 500)
            progress.setFormat("0 / 500")
            progress.setMinimumWidth(150)
            widgets = {
                "label": label, "distance_label": distance_label,
                "sample_group": sample_group, "reference_distance": reference_distance,
                "target_count": target_count, "progress": progress,
            }
            self.anchor_dataset_config[anchor_id] = widgets
            row = index
            for column, widget in enumerate((label, distance_label, sample_group, reference_distance, target_count, progress)):
                self._labels_layout.addWidget(widget, row, column)
            distance_label.editingFinished.connect(
                lambda aid=anchor_id: self._auto_fill_anchor_fields(aid)
            )
            target_count.valueChanged.connect(
                lambda _value, aid=anchor_id: self._update_anchor_progress(aid)
            )
        for index, widgets in enumerate(self.anchor_dataset_config.values(), start=1):
            visible = index <= count
            for widget in widgets.values():
                widget.setVisible(visible)
            if visible:
                self._last_dataset_counts.setdefault(f"A{index}", 0)

    def set_anchor_count(self, count):
        self._anchor_count = max(1, int(count))
        self._ensure_anchor_rows(self._anchor_count)
        self.set_dataset_sample_counts({})

    def active_anchor_ids(self):
        return tuple(f"A{index}" for index in range(1, self._anchor_count + 1))

    def is_collection_enabled(self):
        return self.chk_collect_data.isChecked()

    def set_session_path(self, path):
        self.lbl_session_path.setText(f"会话文件：{path}" if path else "会话文件：尚未开始采集")

    def get_dataset_export_config(self):
        scene_label = self.edit_scene_label.text().strip() or "LOS"
        anchor_configs = {}
        for anchor_id in self.active_anchor_ids():
            widgets = self.anchor_dataset_config[anchor_id]
            distance_label = widgets["distance_label"].text().strip() or "5m"
            sample_group = widgets["sample_group"].text().strip() or f"{scene_label.lower()}_{distance_label}_{anchor_id.lower()}"
            anchor_configs[anchor_id] = {
                "distance_label_m": distance_label,
                "sample_group": sample_group,
                "reference_distance_m": float(widgets["reference_distance"].value()),
                "target_count": int(widgets["target_count"].value()),
            }
        return {
            "scene_label": scene_label,
            "anchor_configs": anchor_configs,
            "calibers": {
                "raw": self.chk_export_raw.isChecked(),
                "features": self.chk_export_features.isChecked(),
                "time_features": self.chk_export_time.isChecked(),
            },
        }

    @staticmethod
    def _parse_distance_label(text):
        raw = str(text or "").strip().lower().replace(" ", "")
        if raw.endswith("m"):
            raw = raw[:-1]
        try:
            return float(raw)
        except ValueError:
            return None

    def _auto_fill_anchor_fields(self, anchor_id, force_group=False):
        widgets = self.anchor_dataset_config.get(anchor_id) or {}
        if not widgets:
            return
        scene = self.edit_scene_label.text().strip() or "LOS"
        distance_label = widgets["distance_label"].text().strip() or "5m"
        distance_value = self._parse_distance_label(distance_label)
        if distance_value is not None:
            widgets["reference_distance"].setValue(distance_value)
        group = widgets["sample_group"]
        if force_group or not group.text().strip() or group.text().strip().endswith(anchor_id.lower()):
            group.setText(f"{scene.lower()}_{distance_label}_{anchor_id.lower()}")

    def _auto_fill_all_anchor_fields(self):
        for anchor_id in self.active_anchor_ids():
            self._auto_fill_anchor_fields(anchor_id, force_group=True)

    def _update_anchor_progress(self, anchor_id):
        widgets = self.anchor_dataset_config.get(anchor_id) or {}
        if not widgets:
            return
        current = int(self._last_dataset_counts.get(anchor_id, 0))
        target = int(widgets["target_count"].value())
        progress = widgets["progress"]
        progress.setRange(0, max(1, target))
        progress.setValue(min(current, target))
        progress.setFormat(f"{current} / {target}")

    def set_dataset_sample_counts(self, counts):
        self._last_dataset_counts.update(counts or {})
        for anchor_id in self.active_anchor_ids():
            self._update_anchor_progress(anchor_id)
