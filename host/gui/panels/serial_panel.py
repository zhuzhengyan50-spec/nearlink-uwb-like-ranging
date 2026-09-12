"""
串口配置面板 - 串口参数配置和状态显示
"""

import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QLabel, QGridLayout
)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer


class SerialPanel(QGroupBox):
    """串口配置面板"""

    # 信号定义
    connected = pyqtSignal(bool)
    status_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__("串口配置")
        self._init_ui()

        # 串口状态
        self.serial_conn = None
        self.is_connected = False

        # 扫描定时器
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self._scan_ports)

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # === 串口配置网格 ===
        config_layout = QGridLayout()
        config_layout.setSpacing(8)

        # 串口
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(120)
        config_layout.addWidget(QLabel("串口:"), 0, 0)
        config_layout.addWidget(self.port_combo, 0, 1)

        # 波特率
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud_combo.setCurrentText("921600")
        config_layout.addWidget(QLabel("波特率:"), 1, 0)
        config_layout.addWidget(self.baud_combo, 1, 1)

        # 数据位
        self.databits_combo = QComboBox()
        self.databits_combo.addItems(["7", "8"])
        self.databits_combo.setCurrentText("8")
        config_layout.addWidget(QLabel("数据位:"), 2, 0)
        config_layout.addWidget(self.databits_combo, 2, 1)

        # 停止位
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1", "1.5", "2"])
        self.stopbits_combo.setCurrentText("1")
        config_layout.addWidget(QLabel("停止位:"), 3, 0)
        config_layout.addWidget(self.stopbits_combo, 3, 1)

        # 校验位
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["None", "Odd", "Even"])
        self.parity_combo.setCurrentText("None")
        config_layout.addWidget(QLabel("校验位:"), 4, 0)
        config_layout.addWidget(self.parity_combo, 4, 1)

        layout.addLayout(config_layout)

        # === 操作按钮 ===
        btn_layout = QHBoxLayout()

        self.btn_scan = QPushButton("🔍 扫描")
        self.btn_scan.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: white;
                padding: 5px;
                border-radius: 3px;
                border: 1px solid black;
            }
            QPushButton:hover {
                background-color: #0097a7;
                border-color: #333333;
            }
        """)
        self.btn_scan.clicked.connect(self._on_scan)

        self.btn_connect = QPushButton("🔌 连接")
        self.btn_connect.setStyleSheet("""
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
            QPushButton:disabled {
                background-color: #cccccc;
                border-color: #999999;
            }
        """)
        self.btn_connect.clicked.connect(self._on_connect)

        self.btn_disconnect = QPushButton("🔌 断开")
        self.btn_disconnect.setStyleSheet("""
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
            QPushButton:disabled {
                background-color: #cccccc;
                border-color: #999999;
            }
        """)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        self.btn_disconnect.setEnabled(False)

        btn_layout.addWidget(self.btn_scan)
        btn_layout.addWidget(self.btn_connect)
        btn_layout.addWidget(self.btn_disconnect)
        layout.addLayout(btn_layout)

        # === 状态显示 ===
        status_layout = QVBoxLayout()

        self.lbl_status = QLabel("状态: 未连接")
        self.lbl_status.setStyleSheet("QLabel { color: black; font-size: 10px; }")
        status_layout.addWidget(self.lbl_status)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("QLabel { color: #555555; font-size: 9px; }")
        status_layout.addWidget(self.lbl_info)

        layout.addLayout(status_layout)

        # === 串口状态指示灯 ===
        self.indicator = QLabel("●")
        self.indicator.setStyleSheet("""
            QLabel {
                background-color: #cccccc;
                border-radius: 8px;
                font-size: 16px;
            }
        """)
        self.indicator.setAlignment(Qt.AlignCenter)
        self.indicator.setFixedSize(16, 16)

        layout.addWidget(self.indicator, 0, Qt.AlignCenter)

        # 初始扫描
        self._scan_ports()

    def _scan_ports(self):
        """扫描可用串口"""
        self.port_combo.clear()

        # 获取所有可用串口
        available_ports = []
        try:
            # 使用pyserial的list_ports获取实际存在的端口
            ports = list(serial.tools.list_ports.comports())
            for port_info in ports:
                available_ports.append(port_info.device)
        except Exception as e:
            print(f"扫描串口时出错: {e}")
            # 备用方案：扫描常见Windows COM端口
            for i in range(1, 21):
                available_ports.append(f'COM{i}')

        # 排序端口（COM号数字排序）
        def port_key(port):
            if port.startswith('COM'):
                try:
                    return int(port[3:])
                except ValueError:
                    return 9999
            return port
        available_ports.sort(key=port_key)

        # 添加到下拉框
        for port in available_ports:
            self.port_combo.addItem(port)

        # 如果有COM7，设置为默认
        index = self.port_combo.findText("COM7")
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

    def _on_scan(self):
        """扫描按钮点击"""
        self._scan_ports()
        self.lbl_info.setText(f"已扫描，找到 {self.port_combo.count()} 个串口")

    def _on_connect(self):
        """连接按钮点击"""
        port = self.port_combo.currentText()
        if not port:
            return

        try:
            # 获取校验位
            parity_map = {"None": serial.PARITY_NONE, "Odd": serial.PARITY_ODD, "Even": serial.PARITY_EVEN}
            parity = parity_map.get(self.parity_combo.currentText(), serial.PARITY_NONE)

            # 获取停止位
            stopbits_map = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}
            stopbits = stopbits_map.get(self.stopbits_combo.currentText(), serial.STOPBITS_ONE)

            # 先关闭现有连接
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()

            baudrate = int(self.baud_combo.currentText())
            if baudrate > 921600:
                raise ValueError("波特率上限为 921600")

            self.serial_conn = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=0.5,
                bytesize=int(self.databits_combo.currentText()),
                parity=parity,
                stopbits=stopbits
            )

            self.is_connected = True
            self._update_status(True)
            self.connected.emit(True)

        except Exception as e:
            self.is_connected = False
            self._update_status(False)
            self.lbl_info.setText(f"连接失败: {str(e)}")

    def _on_disconnect(self):
        """断开按钮点击"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

        self.is_connected = False
        self._update_status(False)
        self.connected.emit(False)

    def _update_status(self, connected):
        """更新状态显示"""
        if connected:
            self.lbl_status.setText("状态: 已连接")
            self.lbl_status.setStyleSheet("QLabel { color: #4CAF50; font-weight: bold; font-size: 10px; }")
            self.indicator.setStyleSheet("""
                QLabel {
                    background-color: #4CAF50;
                    border-radius: 8px;
                    font-size: 16px;
                }
            """)
            self.btn_connect.setEnabled(False)
            self.btn_disconnect.setEnabled(True)
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)
        else:
            self.lbl_status.setText("状态: 未连接")
            self.lbl_status.setStyleSheet("QLabel { color: black; font-size: 10px; }")
            self.indicator.setStyleSheet("""
                QLabel {
                    background-color: #cccccc;
                    border-radius: 8px;
                    font-size: 16px;
                }
            """)
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            self.port_combo.setEnabled(True)
            self.baud_combo.setEnabled(True)

    def is_serial_connected(self):
        """是否已连接"""
        return self.is_connected and self.serial_conn and self.serial_conn.is_open

    def get_serial_connection(self):
        """获取串口连接对象"""
        return self.serial_conn

    def closeEvent(self, event):
        """关闭事件"""
        if self.is_connected:
            self._on_disconnect()
        event.accept()
