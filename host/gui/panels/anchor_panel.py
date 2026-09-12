"""
锚点配置面板 - 锚点坐标配置和显示
"""

import configparser
import os

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView,
    QComboBox, QDoubleSpinBox, QMessageBox, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class AnchorPanel(QGroupBox):
    """锚点配置面板"""

    # 信号定义
    config_changed = pyqtSignal(list, list)  # 2D锚点列表, 3D锚点列表
    true_position_changed = pyqtSignal(list)  # [x, y, z]

    def __init__(self):
        super().__init__("锚点配置")
        self._config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "anchor_layout.ini"))
        # 默认使用四锚点；表格仍允许用户按实验需要任意增减。
        self.default_anchors_2d = [[0, 0], [50, 0], [50, 50], [0, 50]]
        self.default_anchors_3d = [[0, 0, 0], [50, 0, 0], [50, 50, 4], [0, 50, 3]]

        self._init_ui()
        self._load_saved_or_default_config()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # === 维度选择 ===
        dim_layout = QHBoxLayout()
        dim_label = QLabel("配置维度:")
        dim_label.setFont(QFont("Arial", 9, QFont.Bold))
        self.dim_combo = QComboBox()
        self.dim_combo.addItems(["2D (平面)", "3D (空间)"])
        self.dim_combo.currentIndexChanged.connect(self._on_dimension_changed)
        dim_layout.addWidget(dim_label)
        dim_layout.addWidget(self.dim_combo)
        layout.addLayout(dim_layout)

        # === 锚点表格 ===
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "X (m)", "Y (m)", "Z (m)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setFixedHeight(200)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid black;
                border-radius: 3px;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #e0e0e0;
                color: black;
            }
        """)
        layout.addWidget(self.table)

        # === 操作按钮 ===
        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("+ 添加锚点")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 5px;
                border-radius: 3px;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #45a049;
                border-color: #333333;
            }
        """)
        self.btn_add.clicked.connect(self._on_add_anchor)

        self.btn_remove = QPushButton("- 删除锚点")
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 5px;
                border-radius: 3px;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #da190b;
                border-color: #333333;
            }
        """)
        self.btn_remove.clicked.connect(self._on_remove_anchor)

        self.btn_reset = QPushButton("↺ 恢复默认")
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                padding: 5px;
                border-radius: 3px;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #e68900;
                border-color: #333333;
            }
        """)
        self.btn_reset.clicked.connect(self._load_default_config)

        self.btn_apply = QPushButton("✓ 应用配置")
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 5px;
                border-radius: 3px;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #0b7dda;
                border-color: #333333;
            }
        """)
        self.btn_apply.clicked.connect(self._on_apply)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_reset)
        btn_layout.addWidget(self.btn_apply)
        layout.addLayout(btn_layout)

        # === 提示信息 ===
        hint_label = QLabel("提示: 2D定位需要≥3个锚点，3D定位需要≥4个锚点")
        hint_label.setStyleSheet("QLabel { color: #555555; font-size: 9px; font-style: italic; }")
        hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint_label)

        # === 终端真实位置 ===
        true_pos_title = QLabel("终端真实位置")
        true_pos_title.setFont(QFont("Arial", 9, QFont.Bold))
        layout.addWidget(true_pos_title)

        true_pos_layout = QHBoxLayout()
        true_pos_layout.addWidget(QLabel("X:"))
        self.spin_true_x = QDoubleSpinBox()
        self.spin_true_x.setRange(-1000.0, 1000.0)
        self.spin_true_x.setDecimals(2)
        self.spin_true_x.setSingleStep(0.2)
        self.spin_true_x.setValue(25.0)
        true_pos_layout.addWidget(self.spin_true_x)

        true_pos_layout.addWidget(QLabel("Y:"))
        self.spin_true_y = QDoubleSpinBox()
        self.spin_true_y.setRange(-1000.0, 1000.0)
        self.spin_true_y.setDecimals(2)
        self.spin_true_y.setSingleStep(0.2)
        self.spin_true_y.setValue(25.0)
        true_pos_layout.addWidget(self.spin_true_y)

        true_pos_layout.addWidget(QLabel("Z:"))
        self.spin_true_z = QDoubleSpinBox()
        self.spin_true_z.setRange(-1000.0, 1000.0)
        self.spin_true_z.setDecimals(2)
        self.spin_true_z.setSingleStep(0.2)
        self.spin_true_z.setValue(1.5)
        true_pos_layout.addWidget(self.spin_true_z)

        self.btn_apply_true_pos = QPushButton("✓ 应用真值")
        self.btn_apply_true_pos.setStyleSheet("""
            QPushButton {
                background-color: #607D8B;
                color: white;
                padding: 5px;
                border-radius: 3px;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #546E7A;
                border-color: #333333;
            }
        """)
        self.btn_apply_true_pos.clicked.connect(self._on_apply_true_position)
        true_pos_layout.addWidget(self.btn_apply_true_pos)

        layout.addLayout(true_pos_layout)

        # === 串口模式真值路径设定 ===
        path_title = QLabel("串口模式真值路径设定（首尾点）")
        path_title.setFont(QFont("Arial", 9, QFont.Bold))
        layout.addWidget(path_title)

        self.chk_true_motion_enabled = QCheckBox("启用真值沿路径移动")
        self.chk_true_motion_enabled.setChecked(False)
        layout.addWidget(self.chk_true_motion_enabled)

        path_speed_layout = QHBoxLayout()
        path_speed_layout.addWidget(QLabel("速度(m/s):"))
        self.spin_path_speed = QDoubleSpinBox()
        self.spin_path_speed.setRange(0.1, 20.0)
        self.spin_path_speed.setDecimals(2)
        self.spin_path_speed.setSingleStep(0.1)
        self.spin_path_speed.setValue(1.5)
        path_speed_layout.addWidget(self.spin_path_speed)
        path_speed_layout.addStretch()
        layout.addLayout(path_speed_layout)

        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("起点 X/Y/Z:"))
        self.spin_path_start_x = QDoubleSpinBox()
        self.spin_path_start_y = QDoubleSpinBox()
        self.spin_path_start_z = QDoubleSpinBox()
        for spin, val in [(self.spin_path_start_x, 10.0), (self.spin_path_start_y, 10.0), (self.spin_path_start_z, 1.5)]:
            spin.setRange(-1000.0, 1000.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setValue(val)
            spin.setFixedWidth(62)
            start_layout.addWidget(spin)
        start_layout.addStretch()
        layout.addLayout(start_layout)

        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("终点 X/Y/Z:"))
        self.spin_path_end_x = QDoubleSpinBox()
        self.spin_path_end_y = QDoubleSpinBox()
        self.spin_path_end_z = QDoubleSpinBox()
        for spin, val in [(self.spin_path_end_x, 40.0), (self.spin_path_end_y, 40.0), (self.spin_path_end_z, 1.5)]:
            spin.setRange(-1000.0, 1000.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setValue(val)
            spin.setFixedWidth(62)
            end_layout.addWidget(spin)
        end_layout.addStretch()
        layout.addLayout(end_layout)

        # 初始化表格
        self._init_table()

    def _init_table(self):
        """初始化表格"""
        self.table.setRowCount(len(self.default_anchors_2d))

        # 创建坐标输入框
        self.coord_inputs = []  # 存储所有坐标输入框的引用

        for row in range(len(self.default_anchors_2d)):
            # ID列
            id_item = QTableWidgetItem(f"A{row + 1}")
            id_item.setTextAlignment(Qt.AlignCenter)
            id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, id_item)

            # 坐标列
            row_inputs = []
            for col in range(1, 4):
                if col == 3 and self.dim_combo.currentIndex() == 0:
                    # 2D模式下Z列设为0且禁用
                    item = QTableWidgetItem("0")
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(Qt.lightGray)
                else:
                    item = QTableWidgetItem("0")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
                row_inputs.append(item)
            self.coord_inputs.append(row_inputs)

    def _on_dimension_changed(self):
        """维度切换"""
        is_3d = self.dim_combo.currentIndex() == 1

        # 更新表头
        self.table.setHorizontalHeaderLabels(["ID", "X (m)", "Y (m)", "Z (m)"])

        # 启用/禁用Z列
        for row_inputs in self.coord_inputs:
            z_item = row_inputs[2]
            if is_3d:
                z_item.setFlags(z_item.flags() | Qt.ItemIsEditable)
                z_item.setBackground(Qt.white)
            else:
                z_item.setFlags(z_item.flags() & ~Qt.ItemIsEditable)
                z_item.setText("0")
                z_item.setBackground(Qt.lightGray)

    def _on_add_anchor(self):
        """添加锚点"""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # ID
        id_item = QTableWidgetItem(f"A{row + 1}")
        id_item.setTextAlignment(Qt.AlignCenter)
        id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, id_item)

        # 坐标
        row_inputs = []
        for col in range(1, 4):
            item = QTableWidgetItem("0")
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, col, item)
            row_inputs.append(item)
        self.coord_inputs.append(row_inputs)

    def _on_remove_anchor(self):
        """删除锚点"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
            self.coord_inputs.pop(current_row)

            # 更新ID
            for row in range(self.table.rowCount()):
                self.table.item(row, 0).setText(f"A{row + 1}")

    def _load_default_config(self):
        """加载默认配置"""
        # 2D
        for row, anchor in enumerate(self.default_anchors_2d):
            if row < self.table.rowCount():
                self.coord_inputs[row][0].setText(str(anchor[0]))  # X
                self.coord_inputs[row][1].setText(str(anchor[1]))  # Y

        # 3D
        for row, anchor in enumerate(self.default_anchors_3d):
            if row < self.table.rowCount():
                self.coord_inputs[row][2].setText(str(anchor[2]))  # Z

    def _load_saved_or_default_config(self):
        if not os.path.exists(self._config_path):
            self._load_default_config()
            return

        parser = configparser.ConfigParser()
        try:
            parser.read(self._config_path, encoding="utf-8")
            saved_indices = []
            for section in parser.sections():
                if section.startswith("Anchor") and section[6:].isdigit():
                    saved_indices.append(int(section[6:]))
            saved_count = max(saved_indices, default=len(self.default_anchors_2d))
            while self.table.rowCount() < saved_count:
                self._on_add_anchor()
            while self.table.rowCount() > saved_count:
                row = self.table.rowCount() - 1
                self.table.removeRow(row)
                self.coord_inputs.pop(row)

            for row in range(self.table.rowCount()):
                section = f"Anchor{row + 1}"
                default_2d = self.default_anchors_2d[row] if row < len(self.default_anchors_2d) else [0.0, 0.0]
                default_3d = self.default_anchors_3d[row] if row < len(self.default_anchors_3d) else [0.0, 0.0, 0.0]
                if parser.has_section(section):
                    self.coord_inputs[row][0].setText(parser.get(section, "x", fallback=str(default_2d[0])))
                    self.coord_inputs[row][1].setText(parser.get(section, "y", fallback=str(default_2d[1])))
                    self.coord_inputs[row][2].setText(parser.get(section, "z", fallback=str(default_3d[2])))
                else:
                    self.coord_inputs[row][0].setText(str(default_2d[0]))
                    self.coord_inputs[row][1].setText(str(default_2d[1]))
                    self.coord_inputs[row][2].setText(str(default_3d[2]))

            if parser.has_section("TruePosition"):
                self.spin_true_x.setValue(parser.getfloat("TruePosition", "x", fallback=25.0))
                self.spin_true_y.setValue(parser.getfloat("TruePosition", "y", fallback=25.0))
                self.spin_true_z.setValue(parser.getfloat("TruePosition", "z", fallback=1.5))
            if parser.has_section("Path"):
                self.chk_true_motion_enabled.setChecked(parser.getboolean("Path", "enabled", fallback=False))
                self.spin_path_speed.setValue(parser.getfloat("Path", "speed_mps", fallback=1.5))
                self.spin_path_start_x.setValue(parser.getfloat("Path", "start_x", fallback=10.0))
                self.spin_path_start_y.setValue(parser.getfloat("Path", "start_y", fallback=10.0))
                self.spin_path_start_z.setValue(parser.getfloat("Path", "start_z", fallback=1.5))
                self.spin_path_end_x.setValue(parser.getfloat("Path", "end_x", fallback=40.0))
                self.spin_path_end_y.setValue(parser.getfloat("Path", "end_y", fallback=40.0))
                self.spin_path_end_z.setValue(parser.getfloat("Path", "end_z", fallback=1.5))
        except (OSError, ValueError, configparser.Error) as error:
            print(f"Anchor configuration ignored: {error}")
            self._load_default_config()

    def _save_current_config(self):
        parser = configparser.ConfigParser()
        for row in range(len(self.coord_inputs)):
            section = f"Anchor{row + 1}"
            parser[section] = {
                "x": self.coord_inputs[row][0].text(),
                "y": self.coord_inputs[row][1].text(),
                "z": self.coord_inputs[row][2].text(),
            }
        parser["TruePosition"] = {
            "x": str(self.spin_true_x.value()),
            "y": str(self.spin_true_y.value()),
            "z": str(self.spin_true_z.value()),
        }
        parser["Path"] = {
            "enabled": str(self.chk_true_motion_enabled.isChecked()),
            "speed_mps": str(self.spin_path_speed.value()),
            "start_x": str(self.spin_path_start_x.value()),
            "start_y": str(self.spin_path_start_y.value()),
            "start_z": str(self.spin_path_start_z.value()),
            "end_x": str(self.spin_path_end_x.value()),
            "end_y": str(self.spin_path_end_y.value()),
            "end_z": str(self.spin_path_end_z.value()),
        }
        with open(self._config_path, "w", encoding="utf-8") as f:
            parser.write(f)

    def _on_apply(self):
        """应用配置"""
        anchors_2d = []
        anchors_3d = []

        try:
            for row_inputs in self.coord_inputs:
                x = float(row_inputs[0].text())
                y = float(row_inputs[1].text())
                z = float(row_inputs[2].text())

                anchors_2d.append([x, y])
                anchors_3d.append([x, y, z])

            self.config_changed.emit(anchors_2d, anchors_3d)
            self._save_current_config()
            print(f"已应用锚点配置: 2D={len(anchors_2d)}, 3D={len(anchors_3d)}")

        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的数值！")

    def get_anchors_2d(self):
        """获取2D锚点列表"""
        anchors = []
        for row_inputs in self.coord_inputs:
            x = float(row_inputs[0].text())
            y = float(row_inputs[1].text())
            anchors.append([x, y])
        return anchors

    def get_anchors_3d(self):
        """获取3D锚点列表"""
        anchors = []
        for row_inputs in self.coord_inputs:
            x = float(row_inputs[0].text())
            y = float(row_inputs[1].text())
            z = float(row_inputs[2].text())
            anchors.append([x, y, z])
        return anchors

    def _on_apply_true_position(self):
        """应用终端真实位置"""
        true_pos = self.get_true_position()
        self._save_current_config()
        self.true_position_changed.emit(true_pos)

    def get_true_position(self):
        """获取终端真实位置"""
        return [
            float(self.spin_true_x.value()),
            float(self.spin_true_y.value()),
            float(self.spin_true_z.value())
        ]

    def set_true_position(self, x, y, z):
        """设置终端真实位置"""
        self.spin_true_x.setValue(float(x))
        self.spin_true_y.setValue(float(y))
        self.spin_true_z.setValue(float(z))

    def get_true_motion_config(self):
        """获取串口模式真值路径运动配置"""
        return {
            'enabled': self.chk_true_motion_enabled.isChecked(),
            'speed_mps': float(self.spin_path_speed.value()),
            'start_point': [
                float(self.spin_path_start_x.value()),
                float(self.spin_path_start_y.value()),
                float(self.spin_path_start_z.value())
            ],
            'end_point': [
                float(self.spin_path_end_x.value()),
                float(self.spin_path_end_y.value()),
                float(self.spin_path_end_z.value())
            ]
        }

    def is_3d_mode(self):
        """是否为3D模式"""
        return self.dim_combo.currentIndex() == 1

    def update_anchor_position(self, index, x, y):
        """更新单个锚点位置（响应拖动）"""
        if index < len(self.coord_inputs):
            self.coord_inputs[index][0].setText(f"{x:.2f}")  # X
            self.coord_inputs[index][1].setText(f"{y:.2f}")  # Y
            self._save_current_config()

            # 自动通知配置变更
            anchors_2d = self.get_anchors_2d()
            anchors_3d = self.get_anchors_3d()
            self.config_changed.emit(anchors_2d, anchors_3d)
