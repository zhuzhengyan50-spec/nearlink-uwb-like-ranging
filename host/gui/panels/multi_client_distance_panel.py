"""
Responsive container for per-client distance panels.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .distance_plot_panel import DistancePlotPanel
from .distance_table import DistanceTablePanel


class CollapsibleSection(QWidget):
    """Small collapsible content block."""

    def __init__(self, title, content_widget, expanded=True):
        super().__init__()
        self.content_widget = content_widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.toggle_button = QPushButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.clicked.connect(self._apply_state)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                font-weight: bold;
                background-color: #ffffff;
                border: 1px solid #c8d8e6;
                border-radius: 5px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background-color: #eef5fb;
            }
        """)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content_widget)

        self._title = title
        self._apply_state()

    def _apply_state(self):
        expanded = self.toggle_button.isChecked()
        marker = "[-]" if expanded else "[+]"
        self.toggle_button.setText(f"{marker} {self._title}")
        self.content_widget.setVisible(expanded)
        self.content_widget.updateGeometry()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None:
            parent.updateGeometry()


class ClientDistanceCard(QFrame):
    """One card containing one client's plot and table."""

    def __init__(self, client_key, client_label=None, source_addr_byte=None, max_points=100, max_rows=100, anchor_count=4):
        super().__init__()
        self.client_key = client_key
        self.client_label = client_label or client_key
        self.source_addr_byte = source_addr_byte
        self._init_ui(max_points=max_points, max_rows=max_rows, anchor_count=anchor_count)
        self._apply_responsive_heights()
        self.set_client_info(self.client_label, self.source_addr_byte)

    def _init_ui(self, max_points, max_rows, anchor_count):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.header_label = QLabel()
        self.header_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #16344f;")
        layout.addWidget(self.header_label)

        self.distance_plot_panel = DistancePlotPanel(max_points=max_points, anchor_count=anchor_count)
        self.plot_section = CollapsibleSection("Distance Trend", self.distance_plot_panel, expanded=True)
        layout.addWidget(self.plot_section)

        self.distance_table_panel = DistanceTablePanel(max_rows=max_rows, anchor_count=anchor_count)
        self.table_section = CollapsibleSection("Distance Table", self.distance_table_panel, expanded=False)
        layout.addWidget(self.table_section)

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #f5f8fb;
                border: 1px solid #c8d8e6;
                border-radius: 8px;
            }
        """)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_client_info(self, client_label=None, source_addr_byte=None):
        self.client_label = client_label or self.client_key
        self.source_addr_byte = source_addr_byte
        title = self.client_label
        if source_addr_byte is not None:
            title = f"{title} (addr={source_addr_byte})"
        self.header_label.setText(title)
        self.distance_plot_panel.set_client_info(self.client_label, self.source_addr_byte)
        self.distance_table_panel.set_client_info(self.client_label, self.source_addr_byte)

    def add_measurement(
        self,
        distances,
        rssi_values=None,
        timestamp=None,
        valid_count=0,
        cost_ms=None,
        update_plot=True,
        update_table=True,
    ):
        if update_plot:
            self.distance_plot_panel.add_distance_data(
                distances=distances,
                rssi_values=rssi_values,
                timestamp=timestamp,
            )
        if update_table:
            self.distance_table_panel.add_distance_data(
                distances=distances,
                valid_count=valid_count,
                timestamp=timestamp,
                rssi_values=rssi_values,
                cost_ms=cost_ms,
            )

    def clear(self):
        self.distance_plot_panel.clear_plot()
        self.distance_table_panel.clear_table()

    def set_anchor_count(self, count):
        self.distance_plot_panel.set_anchor_count(count)
        self.distance_table_panel.set_anchor_count(count)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_heights()

    def _apply_responsive_heights(self):
        width = max(320, self.width())
        plot_height = min(520, max(220, int(width * 0.62)))
        table_height = min(380, max(170, int(width * 0.46)))
        self.distance_plot_panel.set_preferred_plot_height(plot_height)
        self.distance_table_panel.set_preferred_table_height(table_height)


class MultiClientDistancePanel(QWidget):
    """Adaptive grid of per-client distance cards."""

    def __init__(self, max_points=100, max_rows=100, anchor_count=4):
        super().__init__()
        self.max_points = max_points
        self.max_rows = max_rows
        self.anchor_count = max(1, int(anchor_count))
        self.client_cards = {}
        self._current_columns = 0
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.summary_label = QLabel("Distance panels will appear as clients stream data.")
        self.summary_label.setStyleSheet("font-weight: bold; color: #16344f;")
        layout.addWidget(self.summary_label)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(10)
        self.grid_layout.setVerticalSpacing(10)
        layout.addWidget(self.grid_widget)

    def add_measurement(
        self,
        client_key,
        client_label,
        source_addr_byte,
        distances,
        rssi_values=None,
        timestamp=None,
        valid_count=0,
        cost_ms=None,
        update_plot=True,
        update_table=True,
    ):
        card = self._ensure_card(client_key, client_label, source_addr_byte)
        card.add_measurement(
            distances=distances,
            rssi_values=rssi_values,
            timestamp=timestamp,
            valid_count=valid_count,
            cost_ms=cost_ms,
            update_plot=update_plot,
            update_table=update_table,
        )
        self.summary_label.setText(f"Active clients: {len(self.client_cards)}")

    def clear_all(self):
        for card in self.client_cards.values():
            card.clear()
        self.summary_label.setText("Distance panels will appear as clients stream data.")

    def set_anchor_count(self, count):
        self.anchor_count = max(1, int(count))
        for card in self.client_cards.values():
            card.set_anchor_count(self.anchor_count)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_cards()

    def _ensure_card(self, client_key, client_label, source_addr_byte):
        key = str(client_key or "client")
        card = self.client_cards.get(key)
        if card is None:
            card = ClientDistanceCard(
                client_key=key,
                client_label=client_label or key,
                source_addr_byte=source_addr_byte,
                max_points=self.max_points,
                max_rows=self.max_rows,
                anchor_count=self.anchor_count,
            )
            self.client_cards[key] = card
            self._relayout_cards()
        else:
            card.set_client_info(client_label or key, source_addr_byte)
        return card

    def _column_count_for_width(self):
        width = max(1, self.width())
        if width < 1400:
            return 1
        if width < 2200:
            return 2
        return 3

    def _relayout_cards(self):
        columns = self._column_count_for_width()
        if columns == self._current_columns and self.grid_layout.count() == len(self.client_cards):
            return

        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        ordered_keys = sorted(self.client_cards.keys())
        for index, key in enumerate(ordered_keys):
            row = index // columns
            column = index % columns
            self.grid_layout.addWidget(self.client_cards[key], row, column, alignment=Qt.AlignTop)

        for column in range(columns):
            self.grid_layout.setColumnStretch(column, 1)
        self.grid_layout.setRowStretch(max(0, (len(ordered_keys) - 1) // max(1, columns)) + 1, 1)
        self._current_columns = columns
