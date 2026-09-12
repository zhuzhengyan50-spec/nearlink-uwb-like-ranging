"""Dedicated link sensing page for blockage, motion, and reliability scores."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from ..services.sensing_state_service import LinkScoreSample, SensingStateService
from .link_activity_heatmap_panel import LinkActivityHeatmapPanel


METRICS = {
    "dynamic_score": "Dynamic disturbance",
    "blockage_score": "Blockage risk",
    "link_reliability_score": "Link reliability",
}

MATRIX_METRICS = (
    ("blockage_score", "Blockage"),
    ("dynamic_score", "Dynamic"),
    ("link_reliability_score", "Reliability"),
)


class SensingPagePanel(QWidget):
    """Visualize link scores independently from positioning availability."""

    metric_changed = pyqtSignal(str)

    def __init__(self, state: SensingStateService):
        super().__init__()
        self.state = state
        self.anchor_ids = [f"A{index}" for index in range(1, 5)]
        self.selected_link = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QFrame()
        header_layout = QHBoxLayout(header)
        title = QLabel("NearLink Link Sensing")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1c3a5f;")
        header_layout.addWidget(title)
        header_layout.addWidget(QLabel("Spatial heatmap metric:"))
        self.metric_combo = QComboBox()
        for field, label in METRICS.items():
            self.metric_combo.addItem(label, field)
        self.metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        header_layout.addWidget(self.metric_combo)
        header_layout.addStretch()
        self.lbl_status = QLabel("Waiting for paired IQ samples")
        self.lbl_status.setStyleSheet("color: #35556f;")
        header_layout.addWidget(self.lbl_status)
        header.setStyleSheet(
            "QFrame { background-color: #eef6fd; border: 1px solid #bfd8ef; border-radius: 6px; }"
        )
        layout.addWidget(header)

        upper_splitter = QSplitter(Qt.Horizontal)

        matrix_box = QGroupBox("Anchor × Client sensing scores")
        matrix_layout = QVBoxLayout(matrix_box)
        matrix_hint = QLabel(
            "This matrix works with a single active link and does not depend on a positioning solution."
        )
        matrix_hint.setWordWrap(True)
        matrix_hint.setStyleSheet("color: #35556f;")
        matrix_layout.addWidget(matrix_hint)
        self.score_table = QTableWidget()
        self.score_table.verticalHeader().setVisible(False)
        self.score_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.score_table.cellClicked.connect(self._on_cell_clicked)
        self.score_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        matrix_layout.addWidget(self.score_table)
        upper_splitter.addWidget(matrix_box)

        current_box = QGroupBox("Selected link")
        current_layout = QVBoxLayout(current_box)
        self.lbl_selected = QLabel("Link: --")
        self.lbl_selected.setStyleSheet("font-size: 14px; font-weight: bold;")
        current_layout.addWidget(self.lbl_selected)
        self.lbl_blockage = QLabel("Blockage score: --")
        self.lbl_dynamic = QLabel("Dynamic score: --")
        self.lbl_reliability = QLabel("Reliability score: --")
        for label in (self.lbl_blockage, self.lbl_dynamic, self.lbl_reliability):
            label.setStyleSheet("font-size: 13px;")
            current_layout.addWidget(label)

        self.trend_plot = pg.PlotWidget(title="Score history")
        self.trend_plot.setBackground("w")
        self.trend_plot.setYRange(0.0, 1.0)
        self.trend_plot.showGrid(x=True, y=True, alpha=0.25)
        self.trend_plot.setLabel("left", "Score")
        self.trend_plot.setLabel("bottom", "Time", units="s")
        self.trend_plot.addLegend()
        self.blockage_curve = self.trend_plot.plot(pen=pg.mkPen("#d62728", width=2), name="Blockage")
        self.dynamic_curve = self.trend_plot.plot(pen=pg.mkPen("#1f77b4", width=2), name="Dynamic")
        self.reliability_curve = self.trend_plot.plot(pen=pg.mkPen("#2ca02c", width=2), name="Reliability")
        current_layout.addWidget(self.trend_plot, 1)
        upper_splitter.addWidget(current_box)
        upper_splitter.setSizes([560, 640])
        layout.addWidget(upper_splitter, 1)

        self.spatial_heatmap = LinkActivityHeatmapPanel()
        layout.addWidget(self.spatial_heatmap, 1)

    def set_anchor_count(self, count: int) -> None:
        self.anchor_ids = [f"A{index}" for index in range(1, max(1, int(count)) + 1)]
        self.refresh()

    def active_metric(self) -> str:
        return str(self.metric_combo.currentData())

    def ingest_samples(self, samples: list[LinkScoreSample]) -> None:
        if not samples:
            return
        latest = samples[-1]
        if self.selected_link not in self.state.link_keys():
            self.selected_link = (latest.anchor_id, latest.client_key)
        self.refresh()

    def refresh(self) -> None:
        clients = self.state.clients()
        self.score_table.setRowCount(len(self.anchor_ids))
        self.score_table.setColumnCount(1 + len(clients) * len(MATRIX_METRICS))
        headers = ["Anchor"]
        for _client_key, client_label in clients:
            headers.extend(f"{client_label}\n{label}" for _field, label in MATRIX_METRICS)
        self.score_table.setHorizontalHeaderLabels(headers)

        active_links = 0
        for row, anchor_id in enumerate(self.anchor_ids):
            anchor_item = QTableWidgetItem(anchor_id)
            anchor_item.setTextAlignment(Qt.AlignCenter)
            self.score_table.setItem(row, 0, anchor_item)
            for client_index, (client_key, _label) in enumerate(clients):
                sample = self.state.latest(anchor_id, client_key)
                if sample is not None:
                    active_links += 1
                for metric_index, (field, _metric_label) in enumerate(MATRIX_METRICS):
                    column = 1 + client_index * len(MATRIX_METRICS) + metric_index
                    value = None if sample is None else getattr(sample, field)
                    item = QTableWidgetItem("--" if value is None else f"{value:.3f}")
                    item.setTextAlignment(Qt.AlignCenter)
                    if value is not None:
                        item.setBackground(self._score_color(field, value))
                        item.setData(Qt.UserRole, (anchor_id, client_key))
                    self.score_table.setItem(row, column, item)

        self.lbl_status.setText(f"Active links: {active_links} | Anchors: {len(self.anchor_ids)} | Clients: {len(clients)}")
        self._refresh_selected_link()

    def reset(self) -> None:
        self.selected_link = None
        self.refresh()
        self.spatial_heatmap.update_heatmap(None, "Waiting for link scores and a client position")

    def update_spatial_heatmap(self, data, message: str) -> None:
        self.spatial_heatmap.set_metric_label(METRICS[self.active_metric()])
        self.spatial_heatmap.update_heatmap(data, message)

    def _on_metric_changed(self) -> None:
        metric = self.active_metric()
        self.refresh()
        self.metric_changed.emit(metric)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == 0:
            return
        item = self.score_table.item(row, column)
        link = item.data(Qt.UserRole) if item is not None else None
        if link is not None:
            self.selected_link = tuple(link)
            self._refresh_selected_link()

    def _refresh_selected_link(self) -> None:
        if self.selected_link is None:
            self.lbl_selected.setText("Link: --")
            self.lbl_blockage.setText("Blockage score: --")
            self.lbl_dynamic.setText("Dynamic score: --")
            self.lbl_reliability.setText("Reliability score: --")
            for curve in (self.blockage_curve, self.dynamic_curve, self.reliability_curve):
                curve.setData([], [])
            return

        anchor_id, client_key = self.selected_link
        history = self.state.history(anchor_id, client_key)
        if not history:
            self.selected_link = None
            self._refresh_selected_link()
            return

        latest = history[-1]
        self.lbl_selected.setText(f"Link: {anchor_id} ↔ {latest.client_label}")
        self.lbl_blockage.setText(f"Blockage score: {latest.blockage_score:.3f}")
        self.lbl_dynamic.setText(f"Dynamic score: {latest.dynamic_score:.3f}")
        self.lbl_reliability.setText(f"Reliability score: {latest.link_reliability_score:.3f}")
        t0 = history[0].timestamp
        times = [sample.timestamp - t0 for sample in history]
        self.blockage_curve.setData(times, [sample.blockage_score for sample in history])
        self.dynamic_curve.setData(times, [sample.dynamic_score for sample in history])
        self.reliability_curve.setData(times, [sample.link_reliability_score for sample in history])

    @staticmethod
    def _score_color(metric: str, value: float) -> QColor:
        value = min(max(float(value), 0.0), 1.0)
        risk = 1.0 - value if metric == "link_reliability_score" else value
        hue = 0.33 * (1.0 - risk)
        return QColor.fromHsvF(hue, 0.55, 1.0)
