"""IQ mode3 page panel for multi-anchor paired IQ visualization."""

from typing import Dict

import pyqtgraph as pg
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.iq_quality_rules import get_quality_rules_table


DEFAULT_ANCHORS = ["A1", "A2", "A3", "A4"]


class AnchorOverviewCard(QFrame):
    """Compact chart card for one anchor."""

    clicked = pyqtSignal(str)

    def __init__(self, anchor_id: str):
        super().__init__()
        self.anchor_id = anchor_id
        self._build_ui()
        self.set_selected(False)

    def _build_ui(self) -> None:
        self.setObjectName(f"overview_{self.anchor_id}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.lbl_title = QLabel(self.anchor_id)
        self.lbl_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #13324c;")
        self.lbl_meta = QLabel("F:- D:- R:-")
        self.lbl_meta.setStyleSheet("font-size: 10px; color: #50657a;")

        self.plot = pg.PlotWidget()
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMaximumHeight(120)
        self.anchor_curve = self.plot.plot([], [], pen=pg.mkPen("#1f77b4", width=1.5))
        self.client_curve = self.plot.plot([], [], pen=pg.mkPen("#ff7f0e", width=1.5))

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_meta)
        layout.addWidget(self.plot)

        self.plot.scene().sigMouseClicked.connect(lambda _evt, aid=self.anchor_id: self.clicked.emit(aid))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.anchor_id)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(
                "QFrame { background-color: #edf6ff; border: 2px solid #1f6fae; border-radius: 6px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { background-color: #f8fbff; border: 1px solid #c3d9ed; border-radius: 6px; }"
            )

    def clear(self) -> None:
        self.lbl_meta.setText("F:- D:- R:-")
        self.anchor_curve.setData([], [])
        self.client_curve.setData([], [])

    def update_snapshot(self, snapshot: Dict) -> None:
        if not snapshot:
            self.clear()
            return

        latest = snapshot.get("latest_record") or {}
        if not latest:
            count = int(snapshot.get("record_count", 0))
            self.lbl_meta.setText(f"F:- D:- R:- ({count})")
            self.anchor_curve.setData([], [])
            self.client_curve.setData([], [])
            return

        frame = latest.get("frame_index", "-")
        dist = latest.get("distance")
        rssi = latest.get("rssi")
        cfr = latest.get("cfr", {}) or {}
        state = cfr.get("state_label", "-")
        blockage = _fmt_num(cfr.get("blockage_score"))
        dynamic = _fmt_num(cfr.get("dynamic_score"))
        self.lbl_meta.setText(f"F:{frame} D:{_fmt_num(dist)} R:{_fmt_num(rssi)} {state} Sb:{blockage} Sd:{dynamic}")

        anchor_i = ((latest.get("anchor_packet") or {}).get("i_values") or [])[:64]
        client_i = ((latest.get("client_packet") or {}).get("i_values") or [])[:64]
        xa = list(range(len(anchor_i)))
        xc = list(range(len(client_i)))
        self.anchor_curve.setData(xa, anchor_i)
        self.client_curve.setData(xc, client_i)


def _fmt_num(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


class IQPagePanel(QWidget):
    """Second page panel showing multi-anchor IQ overview and selected link details."""

    anchor_changed = pyqtSignal(str)
    iq_parse_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.anchor_ids = list(DEFAULT_ANCHORS)
        self._latest_snapshots: Dict[str, Dict] = {aid: {} for aid in self.anchor_ids}
        self._selected_anchor = "A1"
        self._init_ui()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)

        self.lbl_title = QLabel("IQ 成对分析 (Mode3)")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1c3a5f;")

        self.chk_parse = QCheckBox("解析IQ数据")
        self.chk_parse.setChecked(True)
        self.chk_parse.toggled.connect(self.iq_parse_toggled.emit)

        self.lbl_selected = QLabel("当前选中: A1")
        self.lbl_selected.setStyleSheet("font-size: 11px; color: #2d4b68;")
        self.lbl_client = QLabel("当前Client: -")
        self.lbl_client.setStyleSheet("font-size: 11px; color: #2d4b68;")
        self.lbl_state = QLabel("链路状态: -")
        self.lbl_state.setStyleSheet("font-size: 11px; color: #2d4b68; font-weight: bold;")

        self.btn_rules = QPushButton("评判标准")
        self.btn_rules.clicked.connect(self._show_rules_dialog)

        header_layout.addWidget(self.lbl_title)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.chk_parse)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.lbl_selected)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.lbl_client)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.lbl_state)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_rules)
        header.setStyleSheet("QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e9f4ff, stop:1 #f5fbff); border: 1px solid #bfd8ef; border-radius: 6px; }")
        root_layout.addWidget(header)

        self.overview_box = QGroupBox()
        self.overview_layout = QGridLayout(self.overview_box)
        self.overview_layout.setHorizontalSpacing(8)
        self.overview_layout.setVerticalSpacing(8)

        self.anchor_cards: Dict[str, AnchorOverviewCard] = {}
        for idx, anchor_id in enumerate(self.anchor_ids):
            card = AnchorOverviewCard(anchor_id)
            card.clicked.connect(self._on_card_clicked)
            self.overview_layout.addWidget(card, idx // 3, idx % 3)
            self.anchor_cards[anchor_id] = card

        self._update_overview_title()
        root_layout.addWidget(self.overview_box)

        basic_box = QGroupBox("帧详情（全Anchor距离/RSSI）")
        basic_layout = QHBoxLayout(basic_box)
        self.lbl_detail_frame = QLabel("Frame: -")
        self.lbl_detail_dist = QLabel("DistAll: -")
        self.lbl_detail_rssi = QLabel("RSSIAll: -")
        self.lbl_detail_time = QLabel("Time: -")
        self.lbl_detail_scores = QLabel("Sb:- Sd:- Rel:- State:-")
        self.lbl_detail_research = QLabel("MUSIC direct ratio: -")
        for w in [self.lbl_detail_frame, self.lbl_detail_dist, self.lbl_detail_rssi, self.lbl_detail_time, self.lbl_detail_scores, self.lbl_detail_research]:
            w.setStyleSheet("font-size: 12px; color: #16344f; padding: 2px 6px;")
            basic_layout.addWidget(w)
        basic_layout.addStretch()
        root_layout.addWidget(basic_box)

        cards_box = QGroupBox("关键指标（Anchor侧）")
        cards_layout = QGridLayout(cards_box)
        cards_layout.setHorizontalSpacing(10)
        cards_layout.setVerticalSpacing(8)

        self.metric_labels = {}
        metric_names = [
            ("snr_estimate", "SNR"),
            ("phase_jitter", "Phase Jitter"),
            ("constellation_spread", "Spread"),
            ("std_amplitude", "Std Amp"),
            ("iq_correlation", "IQ Corr"),
            ("mean_amplitude", "Mean Amp"),
        ]

        for idx, (key, title) in enumerate(metric_names):
            card = QFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            lbl_name = QLabel(title)
            lbl_name.setStyleSheet("font-size: 10px; color: #4f6378;")
            lbl_val = QLabel("-")
            lbl_val.setStyleSheet("font-size: 14px; font-weight: bold; color: #0f2f4d;")
            card_layout.addWidget(lbl_name)
            card_layout.addWidget(lbl_val)
            card.setStyleSheet("QFrame { background-color: #f7fbff; border: 1px solid #c6dff3; border-radius: 5px; }")
            cards_layout.addWidget(card, idx // 3, idx % 3)
            self.metric_labels[key] = lbl_val

        root_layout.addWidget(cards_box)

        plots_layout = QHBoxLayout()

        self.cfr_plot = pg.PlotWidget(title="互功率谱幅度 |H_k|")
        self.cfr_plot.setBackground("w")
        self.cfr_plot.showGrid(x=True, y=True, alpha=0.25)
        self.cfr_plot.addLegend(offset=(8, 8))
        self.cfr_plot.setLabel("left", "|H(f)|")
        self.cfr_plot.setLabel("bottom", "Freq (MHz)")
        self.cfr_mag_curve = self.cfr_plot.plot([], [], pen=pg.mkPen("#1f77b4", width=2), name="|H(f)|")
        self.cfr_phase_curve = self.cfr_plot.plot([], [], pen=pg.mkPen("#d62728", width=2), name="phase")

        plots_layout.addWidget(self.cfr_plot, 1)
        root_layout.addLayout(plots_layout)

        trend_box = QGroupBox("历史趋势")
        trend_layout = QVBoxLayout(trend_box)
        self.trend_plot = pg.PlotWidget()
        self.trend_plot.setBackground("w")
        self.trend_plot.showGrid(x=True, y=True, alpha=0.2)
        self.trend_plot.addLegend(offset=(8, 8))
        self.trend_anchor_snr = self.trend_plot.plot([], [], pen=pg.mkPen("#2ca02c", width=2), name="A-SNR")
        self.trend_client_snr = self.trend_plot.plot([], [], pen=pg.mkPen("#9467bd", width=2), name="C-SNR")
        trend_layout.addWidget(self.trend_plot)
        root_layout.addWidget(trend_box, 1)

        self.features_table = QTableWidget(0, 5)
        self.features_table.setHorizontalHeaderLabels(["指标", "Anchor", "Anchor结论", "Client", "Client结论"])
        self.features_table.verticalHeader().setVisible(False)
        self.features_table.horizontalHeader().setStretchLastSection(True)
        self.features_table.setAlternatingRowColors(True)
        self.features_table.setMaximumHeight(240)
        root_layout.addWidget(self.features_table)

        self._apply_selected_style()

    def set_anchor_count(self, count: int) -> None:
        """Synchronize overview cards with the configured anchor count."""
        count = max(1, int(count))
        self.anchor_ids = [f"A{index}" for index in range(1, count + 1)]
        for anchor_id in self.anchor_ids:
            if anchor_id not in self.anchor_cards:
                card = AnchorOverviewCard(anchor_id)
                card.clicked.connect(self._on_card_clicked)
                self.anchor_cards[anchor_id] = card
            self._latest_snapshots.setdefault(anchor_id, {})
        for anchor_id, card in self.anchor_cards.items():
            card.setVisible(anchor_id in self.anchor_ids)
        for index, anchor_id in enumerate(self.anchor_ids):
            self.overview_layout.addWidget(self.anchor_cards[anchor_id], index // 3, index % 3)
        if self._selected_anchor not in self.anchor_ids:
            self._selected_anchor = self.anchor_ids[0]
        self._update_overview_title()
        self._apply_selected_style()
        self._refresh_selected_detail()

    def _update_overview_title(self) -> None:
        self.overview_box.setTitle(
            f"Anchor 概览（{len(self.anchor_ids)} 图同时展示，点击切换详情）"
        )

    def _on_card_clicked(self, anchor_id: str) -> None:
        if anchor_id not in self.anchor_ids:
            return
        self._selected_anchor = anchor_id
        self._apply_selected_style()
        self.anchor_changed.emit(anchor_id)
        self._refresh_selected_detail()

    def _apply_selected_style(self) -> None:
        for anchor_id, card in self.anchor_cards.items():
            card.set_selected(anchor_id == self._selected_anchor)
        self.lbl_selected.setText(f"当前选中: {self._selected_anchor}")

    def is_iq_parse_enabled(self) -> bool:
        return self.chk_parse.isChecked()

    def set_iq_parse_enabled(self, enabled: bool) -> None:
        self.chk_parse.blockSignals(True)
        self.chk_parse.setChecked(enabled)
        self.chk_parse.blockSignals(False)

    def reset_view(self) -> None:
        self.lbl_detail_frame.setText("Frame: -")
        self.lbl_detail_dist.setText("DistAll: -")
        self.lbl_detail_rssi.setText("RSSIAll: -")
        self.lbl_detail_time.setText("Time: -")
        self.lbl_client.setText("当前Client: -")
        self.lbl_state.setText("链路状态: -")
        self.lbl_detail_scores.setText("Sb:- Sd:- Rel:- State:-")
        self.lbl_detail_research.setText("MUSIC direct ratio: -")

        for anchor_id in self.anchor_ids:
            self._latest_snapshots[anchor_id] = {}
            self.anchor_cards[anchor_id].clear()

        for label in self.metric_labels.values():
            label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0f2f4d;")
            label.setText("-")
        self.cfr_mag_curve.setData([], [])
        self.cfr_phase_curve.setData([], [])
        self.trend_anchor_snr.setData([], [])
        self.trend_client_snr.setData([], [])
        self.features_table.setRowCount(0)

    def update_snapshot(self, snapshot: Dict) -> None:
        if not snapshot:
            return
        anchor_id = snapshot.get("anchor_id")
        if anchor_id in self.anchor_ids:
            self._latest_snapshots[anchor_id] = snapshot
            self.anchor_cards[anchor_id].update_snapshot(snapshot)
            if anchor_id == self._selected_anchor:
                self._render_selected_snapshot(snapshot)

    def update_multi_snapshots(self, snapshots: Dict[str, Dict]) -> None:
        for anchor_id in self.anchor_ids:
            snap = snapshots.get(anchor_id, {})
            self._latest_snapshots[anchor_id] = snap
            self.anchor_cards[anchor_id].update_snapshot(snap)
        self._refresh_selected_detail()

    def _refresh_selected_detail(self) -> None:
        snapshot = self._latest_snapshots.get(self._selected_anchor, {})
        self._render_selected_snapshot(snapshot)

    def _render_selected_snapshot(self, snapshot: Dict) -> None:
        if not snapshot:
            self.lbl_detail_frame.setText("Frame: -")
            self.lbl_detail_dist.setText("DistAll: -")
            self.lbl_detail_rssi.setText("RSSIAll: -")
            self.lbl_detail_time.setText("Time: -")
            self.lbl_client.setText("当前Client: -")
            self.lbl_state.setText("链路状态: -")
            self.lbl_detail_scores.setText("Sb:- Sd:- Rel:- State:-")
            self.lbl_detail_research.setText("MUSIC direct ratio: -")
            self.cfr_mag_curve.setData([], [])
            self.cfr_phase_curve.setData([], [])
            self.trend_anchor_snr.setData([], [])
            self.trend_client_snr.setData([], [])
            self.features_table.setRowCount(0)
            for label in self.metric_labels.values():
                label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0f2f4d;")
                label.setText("-")
            return

        latest = snapshot.get("latest_record")
        history = snapshot.get("history", [])
        count = int(snapshot.get("record_count", 0))

        if not latest:
            self.lbl_detail_frame.setText("Frame: -")
            self.lbl_detail_dist.setText("DistAll: -")
            self.lbl_detail_rssi.setText("RSSIAll: -")
            self.lbl_detail_time.setText(f"Time: records={count}")
            self.lbl_client.setText("当前Client: -")
            self.lbl_state.setText("链路状态: -")
            self.lbl_detail_scores.setText("Sb:- Sd:- Rel:- State:-")
            self.lbl_detail_research.setText("MUSIC direct ratio: -")
            self.cfr_mag_curve.setData([], [])
            self.cfr_phase_curve.setData([], [])
            self.trend_anchor_snr.setData([], [])
            self.trend_client_snr.setData([], [])
            self.features_table.setRowCount(0)
            for label in self.metric_labels.values():
                label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0f2f4d;")
                label.setText("-")
            return

        self.lbl_detail_frame.setText(f"Frame: {latest.get('frame_index', '-')}")
        client_label = latest.get("client_label") or latest.get("client_key") or "-"
        source_addr = latest.get("source_addr_byte")
        if source_addr is None:
            self.lbl_client.setText(f"当前Client: {client_label}")
        else:
            self.lbl_client.setText(f"当前Client: {client_label} (addr={source_addr})")
        dist_map = latest.get("distances") or {}
        rssi_map = latest.get("rssis") or {}
        dist_text = " ".join(f"{aid}={_fmt_num(dist_map.get(aid))}" for aid in self.anchor_ids)
        rssi_text = " ".join(f"{aid}={_fmt_num(rssi_map.get(aid))}" for aid in self.anchor_ids)
        self.lbl_detail_dist.setText(f"DistAll: {dist_text}")
        self.lbl_detail_rssi.setText(f"RSSIAll: {rssi_text}")
        self.lbl_detail_time.setText(f"Time: {_fmt_num(latest.get('timestamp'))}")
        cfr = latest.get("cfr", {}) or {}
        state_label = cfr.get("state_label", "-")
        blockage_score = cfr.get("blockage_score")
        dynamic_score = cfr.get("dynamic_score")
        reliability = cfr.get("link_reliability_score")
        self.lbl_state.setText(f"链路状态: {state_label}")
        self.lbl_detail_scores.setText(
            f"Sb:{_fmt_num(blockage_score)} Sd:{_fmt_num(dynamic_score)} "
            f"Rel:{_fmt_num(reliability)} State:{state_label}"
        )
        self.lbl_detail_research.setText(
            f"MUSIC direct ratio: {_fmt_num(cfr.get('music_direct_ratio'))}"
        )

        anchor_features = latest.get("anchor_features", {}) or {}
        quality = latest.get("quality", {}) or {}
        metric_levels = quality.get("metrics", {}) or {}

        for key, label in self.metric_labels.items():
            val = anchor_features.get(key)
            level = metric_levels.get(key, {}).get("anchor_level", "-")
            if val is None:
                label.setStyleSheet("font-size: 14px; font-weight: bold; color: #0f2f4d;")
                label.setText("-")
                continue
            color = self._level_color(level)
            label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
            label.setText(f"{float(val):.3f} ({level})")

        freq_mhz = cfr.get("freq_mhz") or []
        cfr_mag = cfr.get("cfr_mag") or []
        cfr_phase = cfr.get("cfr_phase") or []
        self.cfr_mag_curve.setData(freq_mhz, cfr_mag)
        self.cfr_phase_curve.setData(freq_mhz, cfr_phase)

        xh = [int(item.get("frame_index", 0)) for item in history]
        a_snr = [float((item.get("anchor_features", {}) or {}).get("snr_estimate", 0.0) or 0.0) for item in history]
        c_snr = [float((item.get("client_features", {}) or {}).get("snr_estimate", 0.0) or 0.0) for item in history]
        self.trend_anchor_snr.setData(xh, a_snr)
        self.trend_client_snr.setData(xh, c_snr)

        self._update_features_table(latest)

    def _update_features_table(self, latest: Dict) -> None:
        quality = latest.get("quality", {}) or {}
        metrics = quality.get("metrics", {}) or {}
        rows = sorted(metrics.items(), key=lambda kv: kv[0])
        self.features_table.setRowCount(len(rows))

        for row, (name, item) in enumerate(rows):
            a_val = float(item.get("anchor_value", 0.0) or 0.0)
            c_val = float(item.get("client_value", 0.0) or 0.0)
            a_level = item.get("anchor_level", "-")
            c_level = item.get("client_level", "-")

            self.features_table.setItem(row, 0, QTableWidgetItem(name))
            self.features_table.setItem(row, 1, QTableWidgetItem(f"{a_val:.6f}"))
            a_level_item = QTableWidgetItem(a_level)
            a_level_item.setForeground(self._level_brush(a_level))
            self.features_table.setItem(row, 2, a_level_item)
            self.features_table.setItem(row, 3, QTableWidgetItem(f"{c_val:.6f}"))
            c_level_item = QTableWidgetItem(c_level)
            c_level_item.setForeground(self._level_brush(c_level))
            self.features_table.setItem(row, 4, c_level_item)

    def _show_rules_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("IQ 质量评判标准")
        dlg.resize(860, 420)
        layout = QVBoxLayout(dlg)

        tbl = QTableWidget(0, 6)
        tbl.setHorizontalHeaderLabels(["指标", "显示名", "Good阈值", "Warn阈值", "方向", "说明"])
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.verticalHeader().setVisible(False)
        rows = get_quality_rules_table()
        tbl.setRowCount(len(rows))
        for i, row in enumerate(rows):
            tbl.setItem(i, 0, QTableWidgetItem(str(row["metric"])))
            tbl.setItem(i, 1, QTableWidgetItem(str(row["display"])))
            tbl.setItem(i, 2, QTableWidgetItem(str(row["good_threshold"])))
            tbl.setItem(i, 3, QTableWidgetItem(str(row["warn_threshold"])))
            tbl.setItem(i, 4, QTableWidgetItem(str(row["direction"])))
            tbl.setItem(i, 5, QTableWidgetItem(str(row["tip"])))

        layout.addWidget(tbl)
        dlg.exec_()

    def _level_color(self, level: str) -> str:
        if level == "good":
            return "#2e7d32"
        if level == "warn":
            return "#e65100"
        if level == "bad":
            return "#b71c1c"
        return "#0f2f4d"

    def _level_brush(self, level: str):
        return QBrush(QColor(self._level_color(level)))
