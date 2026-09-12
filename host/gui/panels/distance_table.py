"""
Per-client distance table panel.
"""

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class DistanceTablePanel(QGroupBox):
    """Table showing measurement history for one client."""

    def __init__(self, max_rows=100, anchor_count=4):
        super().__init__("Distance Data")
        self.max_rows = max_rows
        self.client_label = "Client"
        self.source_addr_byte = None
        self.anchor_count = max(1, int(anchor_count))
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 16, 8, 8)

        self.lbl_client = QLabel("Client: --")
        self.lbl_client.setStyleSheet("font-weight: bold; color: black;")
        layout.addWidget(self.lbl_client)

        self.table = QTableWidget()
        self.table.setMinimumHeight(150)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self._configure_columns()
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border-radius: 3px;
                gridline-color: #dddddd;
                font-size: 10px;
                color: black;
                border: 1px solid black;
            }
            QTableWidget::item {
                padding: 3px;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                color: black;
                padding: 4px;
                font-weight: bold;
                border: 1px solid #cccccc;
            }
        """)

        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Table")
        self.btn_clear.setFixedHeight(30)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: black;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
                border-color: #333333;
            }
        """)
        self.btn_clear.clicked.connect(self.clear_table)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.lbl_status = QLabel("Waiting for data...")
        self.lbl_status.setStyleSheet("QLabel { color: #555555; font-size: 9px; }")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_status)

    def set_client_info(self, client_label=None, source_addr_byte=None):
        self.client_label = str(client_label or "Client")
        self.source_addr_byte = source_addr_byte
        title = self.client_label
        if source_addr_byte is not None:
            title = f"{title} (addr={source_addr_byte})"
        self.lbl_client.setText(f"Client: {title}")
        self.setTitle(f"Distance Data - {self.client_label}")

    def set_preferred_table_height(self, height):
        height = max(150, int(height))
        self.table.setMinimumHeight(height)

    def add_distance_data(
        self,
        distances,
        valid_count,
        timestamp=None,
        rssi_values=None,
        cost_ms=None,
    ):
        if timestamp is None:
            time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        else:
            time_str = datetime.fromtimestamp(float(timestamp)).strftime("%H:%M:%S.%f")[:-3]

        row = 0
        self.table.insertRow(row)
        self.table.setItem(row, 0, self._make_item(time_str))

        for i in range(self.anchor_count):
            d = distances[i] if i < len(distances) else None
            if d is not None and self._is_positive_number(d):
                item = self._make_item(f"{float(d):.3f}", Qt.AlignCenter)
            else:
                item = self._make_item("--", Qt.AlignCenter, color=Qt.gray)
            self.table.setItem(row, 1 + i, item)

        rssi_values = rssi_values or []
        for i in range(self.anchor_count):
            value = rssi_values[i] if i < len(rssi_values) else None
            if value is None:
                item = self._make_item("--", Qt.AlignCenter, color=Qt.gray)
            else:
                color = Qt.red
                if int(value) >= -55:
                    color = Qt.darkGreen
                elif int(value) >= -70:
                    color = Qt.blue
                item = self._make_item(str(int(value)), Qt.AlignCenter, color=color)
            self.table.setItem(row, 1 + self.anchor_count + i, item)

        valid_item = self._make_item(str(int(valid_count or 0)), Qt.AlignCenter)
        if int(valid_count or 0) >= 4:
            valid_item.setForeground(Qt.darkGreen)
        elif int(valid_count or 0) >= 3:
            valid_item.setForeground(Qt.blue)
        else:
            valid_item.setForeground(Qt.red)
        valid_column = 1 + 2 * self.anchor_count
        self.table.setItem(row, valid_column, valid_item)
        self.table.setItem(row, valid_column + 1, self._make_item("" if cost_ms is None else str(int(cost_ms)), Qt.AlignCenter))

        while self.table.rowCount() > self.max_rows:
            self.table.removeRow(self.table.rowCount() - 1)

        self.lbl_status.setText(f"Rows: {self.table.rowCount()}")

    def _is_positive_number(self, value):
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False

    def _make_item(self, text, align=Qt.AlignLeft, color=None):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        if color is not None:
            item.setForeground(color)
        return item

    def clear_table(self):
        self.table.setRowCount(0)
        self.lbl_status.setText("Cleared")

    def set_anchor_count(self, count):
        self.anchor_count = max(1, int(count))
        self.clear_table()
        self._configure_columns()

    def _configure_columns(self):
        headers = ["Time"]
        headers.extend(f"A{index}(m)" for index in range(1, self.anchor_count + 1))
        headers.extend(f"R{index}(dBm)" for index in range(1, self.anchor_count + 1))
        headers.extend(["Valid", "Cost(ms)"])
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        for column in range(len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
