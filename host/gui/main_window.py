"""
定位系统可视化软件 - 主窗口
"""

import sys
import numpy as np
import re
import time
import csv
import os
import queue
import threading
import serial
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QFrame, QStatusBar, QMessageBox, QScrollArea,
    QFileDialog, QStackedWidget, QPushButton
)
from PyQt5.QtCore import Qt, QTimer

# 导入自定义组件
from .panels.control_panel import ControlPanel
from .panels.serial_panel import SerialPanel
from .panels.anchor_panel import AnchorPanel
from .panels.stats_panel import StatsPanel
from .panels.multi_client_distance_panel import MultiClientDistancePanel
from .panels.iq_page_panel import IQPagePanel
from .panels.dataset_collection_panel import DatasetCollectionPanel
from .panels.sensing_page_panel import SensingPagePanel
from .plotting.position_plot import PositionPlot
from .services.dataset_export_service import DatasetExportConfig, export_dataset
from .services.iq_mode3_service import IQMode3Service
from .services.iq_pair_store import IQPairStore
from .services.kalman_filter_service import ConstantVelocityKalmanService
from .services.link_activity_heatmap_service import LinkActivityHeatmapService
from .services.sensing_state_service import SensingStateService
from algorithm import GnUlsPositioning


class MainWindow(QMainWindow):
    """主窗口 - 定位系统可视化软件"""

    SERIAL_READ_MAX_LINES_PER_TICK = 2000
    IQ_UI_UPDATE_INTERVAL_FRAMES = 4
    DISTANCE_UI_UPDATE_INTERVAL_FRAMES = 3
    TABLE_UI_UPDATE_INTERVAL_FRAMES = 1
    SERIAL_COLLECT_META_RE = re.compile(
        r".*?COLLECT_SAMPLE_META\s+anchor=(\d+)\s+client=(\d+)\s+conn_id=(\d+)\s+"
        r"sdk_dist_mm=(\d+)\s+sdk_rssi=(-?\d+)\s+local_timestamp=(\d+)\s+remote_timestamp=(\d+)\s+"
        r"local_rssi=(\d+)\s+remote_rssi=(\d+)",
        re.IGNORECASE,
    )
    SERIAL_ACCESS_ERROR_TOKENS = (
        "ClearCommError failed",
        "拒绝访问",
        "Access is denied",
        "device disconnected",
        "returned no data",
    )

    def __init__(self):
        super().__init__()

        self.ui_scale = self._detect_ui_scale()

        self.setWindowTitle("星海无界定位系统 - 实时监控软件 v1.0")
        self.setMinimumSize(int(1400 * self.ui_scale), int(820 * self.ui_scale))
        self.resize(int(1800 * self.ui_scale), int(1000 * self.ui_scale))

        # 状态变量
        self.is_running = False
        self.current_mode = "serial"  # serial 或 simulation
        self.frame_count = 0
        self.export_data = []  # 存储导出数据

        # 定位算法
        self.solver_2d = None
        self.solver_3d = None
        self.last_pos_2d = None
        self.last_pos_3d = None
        self.last_pos_2d_by_client = {}
        self.last_pos_3d_by_client = {}

        # 真值与模拟运动状态
        self.true_position_serial = [25.0, 25.0, 1.5]
        self.sim_progress = 0.0
        self.sim_direction = 1.0
        self.sim_last_time = None
        self.serial_truth_progress = 0.0
        self.serial_truth_direction = 1.0
        self.serial_truth_last_time = None
        self._latest_serial_lines = []
        self._serial_client_states = {}
        self._serial_client_order = []
        self._serial_event_seq = 0
        self.iq_parse_enabled = True
        self.iq_ui_update_interval_frames = self.IQ_UI_UPDATE_INTERVAL_FRAMES
        self.distance_ui_update_interval_frames = self.DISTANCE_UI_UPDATE_INTERVAL_FRAMES
        self.table_ui_update_interval_frames = self.TABLE_UI_UPDATE_INTERVAL_FRAMES
        self.iq_mode3_service = IQMode3Service(max_history=200)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.iq_pair_store = IQPairStore(base_dir=os.path.join(root_dir, "data", "gui_sessions"))
        self._iq_write_queue = queue.Queue(maxsize=256)
        self._iq_writer_error = None
        self._dataset_group_counts = {}
        self._iq_writer_thread = threading.Thread(target=self._iq_writer_loop, name="IQJsonlWriter", daemon=True)
        self._iq_writer_thread.start()
        self._last_iq_snapshot_refresh_ts = 0.0
        self._last_distance_panel_refresh_ts = 0.0
        self.position_kf_enabled = True
        self.sensing_kf_enabled = True
        self.sensing_enabled = True
        self.collect_runtime_data_enabled = True
        self.position_kalman_service = ConstantVelocityKalmanService()
        self.link_activity_heatmap_service = LinkActivityHeatmapService()
        self.link_activity_heatmap_service.set_kalman_enabled(self.sensing_kf_enabled)
        self.sensing_state_service = SensingStateService(history_size=300)

        # 初始化UI
        self._init_ui()

        # 初始化定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._on_update)
        self.update_timer.setInterval(50)  # 50ms刷新间隔

        # 初始化算法
        self._init_solvers()

    def _detect_ui_scale(self):
        """检测UI缩放系数（用于高分屏自适应）"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1.0
        dpr = float(screen.devicePixelRatio())
        logical_dpi = float(screen.logicalDotsPerInch())
        dpi_scale = logical_dpi / 96.0
        return max(1.0, min(1.8, max(dpr, dpi_scale)))

    def _init_ui(self):
        """初始化用户界面"""
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 创建分割器
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)

        # === 左侧：绘图区域 ===
        left_panel = QFrame()
        left_panel.setFrameStyle(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # 顶部页面切换（网页风格）
        page_switch = QFrame()
        page_switch_layout = QHBoxLayout(page_switch)
        page_switch_layout.setContentsMargins(8, 8, 8, 0)
        page_switch_layout.setSpacing(8)

        self.page1_btn = QPushButton("页面1 定位")
        self.page2_btn = QPushButton("页面2 感知")
        self.page3_btn = QPushButton("页面3 IQ分析")
        self.page4_btn = QPushButton("页面4 数据采集")
        self.page1_btn.setCheckable(True)
        self.page2_btn.setCheckable(True)
        self.page3_btn.setCheckable(True)
        self.page4_btn.setCheckable(True)
        self.page1_btn.setChecked(True)
        self.page1_btn.clicked.connect(lambda: self._switch_page(0))
        self.page2_btn.clicked.connect(lambda: self._switch_page(1))
        self.page3_btn.clicked.connect(lambda: self._switch_page(2))
        self.page4_btn.clicked.connect(lambda: self._switch_page(3))

        page_switch_layout.addWidget(self.page1_btn)
        page_switch_layout.addWidget(self.page2_btn)
        page_switch_layout.addWidget(self.page3_btn)
        page_switch_layout.addWidget(self.page4_btn)
        page_switch_layout.addStretch()
        left_layout.addWidget(page_switch)

        self.page_stack = QStackedWidget()

        # 页面1：定位绘图组件
        self.position_plot = PositionPlot()
        self.position_plot.anchor_dragged.connect(self._on_anchor_dragged)
        self.position_plot.true_position_dragged.connect(self._on_true_position_dragged)

        page1_widget = QWidget()
        page1_layout = QVBoxLayout(page1_widget)
        page1_layout.setContentsMargins(0, 0, 0, 0)
        page1_layout.addWidget(self.position_plot)

        # 页面2：链路感知（独立于定位结果保存和展示评分）
        self.sensing_page_panel = SensingPagePanel(self.sensing_state_service)
        self.sensing_page_panel.metric_changed.connect(self._on_sensing_metric_changed)

        # 页面3：IQ与特征
        page3_widget = QWidget()
        page3_layout = QVBoxLayout(page3_widget)
        page3_layout.setContentsMargins(0, 0, 0, 0)
        self.iq_page_panel = IQPagePanel()
        self.iq_page_panel.anchor_changed.connect(self._on_iq_anchor_changed)
        self._connect_iq_parse_toggle_signal()
        page3_layout.addWidget(self.iq_page_panel)

        # 页面4：研究数据采集与标签
        self.dataset_collection_panel = DatasetCollectionPanel()
        self.dataset_collection_panel.export_dataset_clicked.connect(self._on_export_dataset)
        self.dataset_collection_panel.start_new_group_clicked.connect(self._on_start_new_dataset_group)
        self.dataset_collection_panel.collection_enabled_changed.connect(self._on_collection_enabled_changed)

        self.page_stack.addWidget(page1_widget)
        self.page_stack.addWidget(self.sensing_page_panel)
        self.page_stack.addWidget(page3_widget)
        self.page_stack.addWidget(self.dataset_collection_panel)
        left_layout.addWidget(self.page_stack)

        self.splitter.addWidget(left_panel)

        # === 右侧：数据栏（分两栏） ===
        right_panel = QFrame()
        right_panel.setFrameStyle(QFrame.StyledPanel)
        right_panel.setMinimumWidth(int(680 * self.ui_scale))

        # 使用滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        right_content = QWidget()
        right_layout = QHBoxLayout(right_content)
        right_layout.setContentsMargins(12, 5, 5, 5)
        right_layout.setSpacing(20)

        # === 左栏 ===
        left_column = QWidget()
        left_column.setMinimumWidth(int(260 * self.ui_scale))
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(5)

        # 1. 控制面板
        self.control_panel = ControlPanel()
        self.control_panel.start_clicked.connect(self._on_start)
        self.control_panel.stop_clicked.connect(self._on_stop)
        self.control_panel.reset_clicked.connect(self._on_reset)
        self.control_panel.export_clicked.connect(self._on_export)
        self.control_panel.mode_changed.connect(self._on_mode_changed)
        self.control_panel.iq_parse_toggled.connect(self._on_iq_parse_toggled)
        self.control_panel.position_kf_toggled.connect(self._on_position_kf_toggled)
        self.control_panel.sensing_toggled.connect(self._on_sensing_toggled)
        self.control_panel.sensing_kf_toggled.connect(self._on_sensing_kf_toggled)
        self.control_panel.client_selection_changed.connect(self._on_client_selection_changed)
        self.control_panel.set_iq_parse_enabled(self.iq_parse_enabled)
        self.iq_page_panel.set_iq_parse_enabled(self.iq_parse_enabled)
        left_column_layout.addWidget(self.control_panel)

        # 2. 串口配置面板
        self.serial_panel = SerialPanel()
        left_column_layout.addWidget(self.serial_panel)

        # 3. 锚点配置面板
        self.anchor_panel = AnchorPanel()
        self.anchor_panel.config_changed.connect(self._on_anchor_config_changed)
        self.anchor_panel.true_position_changed.connect(self._on_true_position_changed_from_panel)
        left_column_layout.addWidget(self.anchor_panel)

        left_column_layout.addStretch()

        # === 右栏 ===
        right_column = QWidget()
        right_column.setMinimumWidth(int(320 * self.ui_scale))
        right_column_layout = QVBoxLayout(right_column)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.setSpacing(8)

        # 1. 数据统计面板
        self.stats_panel = StatsPanel()
        right_column_layout.addWidget(self.stats_panel)

        # 2. 多 client 距离趋势图和表格
        self.multi_client_distance_panel = MultiClientDistancePanel(max_points=100, max_rows=100)
        self._sync_anchor_count(self._active_anchor_count())
        right_column_layout.addWidget(self.multi_client_distance_panel, 1)

        # 添加两栏到右侧布局
        right_layout.addWidget(left_column)
        right_layout.addWidget(right_column)

        scroll_area.setWidget(right_content)
        right_layout_scroll = QVBoxLayout(right_panel)
        right_layout_scroll.setContentsMargins(0, 0, 0, 0)
        right_layout_scroll.addWidget(scroll_area)

        self.splitter.addWidget(right_panel)

        # 设置分割比例
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 2)

        target_total = int(1800 * self.ui_scale)
        left_size = int(target_total * 0.66)
        right_size = max(int(640 * self.ui_scale), target_total - left_size)
        self.splitter.setSizes([left_size, right_size])

        # === 状态栏 ===
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("准备就绪 - 可在2D图中拖动绿色锚点调整位置")

        # 初始真值与模式
        self.true_position_serial = self.anchor_panel.get_true_position()
        self.position_plot.set_true_position(*self.true_position_serial)
        self._on_mode_changed(self.control_panel.get_mode())
        self._switch_page(0)

    def _switch_page(self, index):
        """切换左侧页面。"""
        self.page_stack.setCurrentIndex(index)
        self.page1_btn.setChecked(index == 0)
        self.page2_btn.setChecked(index == 1)
        self.page3_btn.setChecked(index == 2)
        self.page4_btn.setChecked(index == 3)
        self._update_page_tab_style()

    def _update_page_tab_style(self):
        """更新顶部页面按钮样式。"""
        checked_style = (
            "QPushButton { background-color: #1f6fae; color: white; border: 1px solid #15507d;"
            " border-radius: 4px; padding: 6px 10px; font-weight: bold; }"
        )
        normal_style = (
            "QPushButton { background-color: #eef4fa; color: #16344f; border: 1px solid #b8d1e8;"
            " border-radius: 4px; padding: 6px 10px; }"
            "QPushButton:hover { background-color: #dcebf7; }"
        )
        self.page1_btn.setStyleSheet(checked_style if self.page1_btn.isChecked() else normal_style)
        self.page2_btn.setStyleSheet(checked_style if self.page2_btn.isChecked() else normal_style)
        self.page3_btn.setStyleSheet(checked_style if self.page3_btn.isChecked() else normal_style)
        self.page4_btn.setStyleSheet(checked_style if self.page4_btn.isChecked() else normal_style)

    def _init_solvers(self):
        """初始化定位算法"""
        # 获取初始锚点配置
        anchors_2d = self.anchor_panel.get_anchors_2d()
        anchors_3d = self.anchor_panel.get_anchors_3d()

        self.solver_2d = GnUlsPositioning(anchors_2d)
        self.solver_3d = GnUlsPositioning(anchors_3d)

    def _on_start(self):
        """开始按钮点击"""
        # 获取模式选择
        self.current_mode = self.control_panel.get_mode()
        self.position_plot.set_mode(self.current_mode)

        if self.current_mode == "serial":
            if not self.serial_panel.is_serial_connected():
                self.status_bar.showMessage("请先连接串口")
                return
            self.status_bar.showMessage("已连接串口，开始接收数据...")
            self.update_timer.setInterval(50)
            self.position_plot.set_true_position(*self.true_position_serial)
            self._reset_serial_truth_motion_state()
            self._reset_serial_client_state()
        else:
            # 模拟模式
            self.status_bar.showMessage("启动模拟模式...")
            sim_cfg = self.control_panel.get_simulation_config()
            self.update_timer.setInterval(sim_cfg.get('refresh_ms', 50))
            self._reset_simulation_motion_state(sim_cfg)

        self.is_running = True
        self.position_kf_enabled = self.control_panel.is_position_kf_enabled()
        self.sensing_enabled = self.control_panel.is_spatial_sensing_enabled()
        self.sensing_kf_enabled = self.control_panel.is_sensing_kf_enabled()
        self.collect_runtime_data_enabled = self.dataset_collection_panel.is_collection_enabled()
        self.link_activity_heatmap_service.set_kalman_enabled(self.sensing_kf_enabled)
        self.position_kalman_service.reset()
        self.link_activity_heatmap_service.reset()
        self.sensing_state_service.reset()
        self.sensing_page_panel.reset()
        if self.current_mode == "serial":
            self.iq_page_panel.reset_view()
            if self.iq_parse_enabled:
                self.iq_mode3_service.reset()
                self._drain_iq_writer(timeout_s=1.0)
                self._dataset_group_counts = {anchor_id: 0 for anchor_id in self._active_anchor_ids()}
                self.dataset_collection_panel.set_dataset_sample_counts(self._dataset_group_counts)
                self.iq_pair_store.new_session()
                self.dataset_collection_panel.set_session_path(self.iq_pair_store.get_current_path())
                self.status_bar.showMessage(f"IQ配对记录写入: {self.iq_pair_store.get_current_path()}")
            else:
                self.status_bar.showMessage("IQ解析已关闭，仅页面1定位生效")
        self.control_panel.set_running_state(True)
        self.update_timer.start()

    def _on_stop(self):
        """停止按钮点击"""
        self.is_running = False
        self.update_timer.stop()
        self.control_panel.set_running_state(False)

        # 调用串口面板的断开方法
        self.serial_panel._on_disconnect()
        self._drain_iq_writer(timeout_s=2.5)
        self.iq_page_panel.reset_view()
        self._reset_serial_client_state()

        self.status_bar.showMessage("已停止")

    def _on_reset(self):
        """重置按钮点击"""
        self.frame_count = 0
        self.last_pos_2d = None
        self.last_pos_3d = None
        self.last_pos_2d_by_client = {}
        self.last_pos_3d_by_client = {}
        self.sim_last_time = None
        self.sim_progress = 0.0
        self.sim_direction = 1.0
        self.serial_truth_last_time = None
        self.serial_truth_progress = 0.0
        self.serial_truth_direction = 1.0
        self.position_plot.clear_plots()
        self.position_plot.set_true_position(*self.true_position_serial)
        self.stats_panel.reset_stats()
        self.multi_client_distance_panel.clear_all()
        self.iq_mode3_service.reset()
        self.sensing_state_service.reset()
        self._dataset_group_counts = {anchor_id: 0 for anchor_id in self._active_anchor_ids()}
        self.dataset_collection_panel.set_dataset_sample_counts(self._dataset_group_counts)
        self._reset_serial_client_state()
        self.link_activity_heatmap_service.reset()
        self.sensing_page_panel.reset()
        if self.iq_parse_enabled:
            self._drain_iq_writer(timeout_s=1.0)
            self.iq_pair_store.new_session()
        self.iq_page_panel.reset_view()
        self.export_data.clear()  # 清空导出数据
        self.status_bar.showMessage("已重置")

    def _on_iq_anchor_changed(self, anchor_id):
        """页面3切换anchor时刷新对应历史。"""
        if not self.iq_parse_enabled:
            return
        snapshot = self.iq_mode3_service.get_latest_anchor_snapshot(anchor_id, limit=200)
        self.iq_page_panel.update_snapshot(snapshot)

    def _connect_iq_parse_toggle_signal(self):
        """Keep the two IQ parsing controls synchronized."""
        self.iq_page_panel.iq_parse_toggled.connect(self._on_iq_parse_toggled)

    def _iq_writer_loop(self):
        """Serialize IQ file operations in FIFO order outside the GUI thread."""
        while True:
            command, payload = self._iq_write_queue.get()
            try:
                if command == "records":
                    self.iq_pair_store.append_records(payload)
                elif command == "flush":
                    self.iq_pair_store.flush()
                    payload.set()
                elif command == "stop":
                    self.iq_pair_store.flush()
                    payload.set()
                    return
            except (OSError, TypeError, ValueError) as error:
                self._iq_writer_error = error
                if command in {"flush", "stop"}:
                    payload.set()
            finally:
                self._iq_write_queue.task_done()

    def _enqueue_iq_records(self, records):
        if records and self.collect_runtime_data_enabled:
            target_counts = self._get_dataset_target_counts()
            reached_now = []
            for item in records:
                anchor_id = str(item.get("anchor_id") or "")
                if not anchor_id:
                    continue
                prev = int(self._dataset_group_counts.get(anchor_id, 0))
                curr = prev + 1
                self._dataset_group_counts[anchor_id] = curr
                target = int(target_counts.get(anchor_id) or 0)
                if target > 0 and prev < target <= curr:
                    reached_now.append(f"{anchor_id}({curr}/{target})")
            self.dataset_collection_panel.set_dataset_sample_counts(self._dataset_group_counts)
            if reached_now:
                self.status_bar.showMessage("已达到目标样本数: " + ", ".join(reached_now))
            try:
                self._iq_write_queue.put_nowait(("records", records))
            except queue.Full as error:
                raise RuntimeError("IQ write queue is full; acquisition stopped to prevent data loss") from error

    def _drain_iq_writer(self, timeout_s: float = 2.0):
        """Wait until every preceding record batch is durably flushed."""
        completed = threading.Event()
        timeout_s = max(0.2, float(timeout_s))
        try:
            self._iq_write_queue.put(("flush", completed), timeout=timeout_s)
        except queue.Full as error:
            raise TimeoutError("Timed out while scheduling the IQ flush") from error
        if not completed.wait(timeout_s):
            raise TimeoutError("Timed out while flushing IQ records")
        if self._iq_writer_error is not None:
            error = self._iq_writer_error
            self._iq_writer_error = None
            raise RuntimeError("IQ record writer failed") from error

    def _get_dataset_target_counts(self):
        cfg = self.dataset_collection_panel.get_dataset_export_config()
        anchor_cfg = dict(cfg.get("anchor_configs") or {})
        return {
            anchor_id: int((anchor_cfg.get(anchor_id) or {}).get("target_count") or 0)
            for anchor_id in self._active_anchor_ids()
        }

    def _on_iq_parse_toggled(self, enabled):
        """IQ解析开关回调。"""
        self.iq_parse_enabled = bool(enabled)
        self.control_panel.set_iq_parse_enabled(self.iq_parse_enabled)
        self.iq_page_panel.set_iq_parse_enabled(self.iq_parse_enabled)

        if not self.iq_parse_enabled:
            self.iq_page_panel.reset_view()
            self.sensing_state_service.reset()
            self.sensing_page_panel.reset()
            self.status_bar.showMessage("IQ解析已关闭，仅页面1定位生效")
            return

        self.iq_mode3_service.reset()
        self.sensing_state_service.reset()
        self.sensing_page_panel.reset()
        self._drain_iq_writer(timeout_s=1.0)
        self.iq_pair_store.new_session()
        self.dataset_collection_panel.set_session_path(self.iq_pair_store.get_current_path())
        self.iq_page_panel.reset_view()
        self.status_bar.showMessage(f"IQ解析已开启，记录写入: {self.iq_pair_store.get_current_path()}")

    def _on_position_kf_toggled(self, enabled):
        """Position Kalman toggle callback."""
        self.position_kf_enabled = bool(enabled)
        self.position_kalman_service.reset()
        self.status_bar.showMessage(
            f"Position Kalman filter {'enabled' if self.position_kf_enabled else 'disabled'}"
        )

    def _on_sensing_toggled(self, enabled):
        """Spatial sensing projection toggle callback."""
        self.sensing_enabled = bool(enabled)
        if not self.sensing_enabled:
            self.link_activity_heatmap_service.reset()
            self.sensing_page_panel.update_spatial_heatmap(None, "Spatial projection disabled")
            self.status_bar.showMessage("Spatial sensing projection disabled")
        else:
            self.status_bar.showMessage("Spatial sensing projection enabled")

    def _on_sensing_kf_toggled(self, enabled):
        """Sensing Kalman toggle callback."""
        self.sensing_kf_enabled = bool(enabled)
        self.link_activity_heatmap_service.set_kalman_enabled(self.sensing_kf_enabled)
        self.link_activity_heatmap_service.reset()
        self.status_bar.showMessage(
            f"Sensing Kalman filter {'enabled' if self.sensing_kf_enabled else 'disabled'}"
        )

    def _on_sensing_metric_changed(self, _metric):
        """Reset spatial normalization when switching score semantics."""
        self.link_activity_heatmap_service.reset()

    def _on_collection_enabled_changed(self, enabled):
        """Enable or pause persistence of research samples."""
        self.collect_runtime_data_enabled = bool(enabled)
        state = "enabled" if self.collect_runtime_data_enabled else "paused"
        self.status_bar.showMessage(f"Dataset collection {state}")

    def _on_start_new_dataset_group(self):
        """Start a fresh collection group for dataset export."""
        self._drain_iq_writer(timeout_s=1.0)
        self._dataset_group_counts = {anchor_id: 0 for anchor_id in self._active_anchor_ids()}
        self.dataset_collection_panel.set_dataset_sample_counts(self._dataset_group_counts)
        if self.iq_parse_enabled:
            self.iq_pair_store.new_session()
            self.dataset_collection_panel.set_session_path(self.iq_pair_store.get_current_path())
        self.status_bar.showMessage("新组采集已准备好：当前组样本已清零。接下来请点击“开始定位”启动真实采集。")

    def _on_export(self):
        """导出按钮点击"""
        if not self.export_data:
            QMessageBox.warning(self, "警告", "没有可导出的数据！")
            return

        # 弹出文件保存对话框
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存数据文件",
            f"positioning_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV文件 (*.csv);;所有文件 (*.*)"
        )

        if not file_path:
            return  # 用户取消

        try:
            export_truth = self.control_panel.should_export_true_position()

            # CSV列头
            anchor_count = self._active_anchor_count()
            fieldnames = ['Timestamp', 'ClientKey', 'ClientLabel', 'SourceAddrByte']
            fieldnames.extend(f'A{i}' for i in range(1, anchor_count + 1))
            fieldnames.extend(f'RSSI{i}' for i in range(1, anchor_count + 1))
            fieldnames.extend(['cost_ms', 'Valid_Anchors', 'X_2D', 'Y_2D', 'X_3D', 'Y_3D', 'Z_3D'])
            for i in range(1, anchor_count + 1):
                fieldnames.extend([f'Anchor{i}_X', f'Anchor{i}_Y', f'Anchor{i}_Z'])
            if export_truth:
                fieldnames.extend(['True_X', 'True_Y', 'True_Z'])

            rows_to_write = []
            for row in self.export_data:
                out = dict(row)
                if not export_truth:
                    out.pop('True_X', None)
                    out.pop('True_Y', None)
                    out.pop('True_Z', None)
                rows_to_write.append(out)

            # 写入CSV文件
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows_to_write)

            # 显示成功消息
            QMessageBox.information(
                self,
                "导出成功",
                f"数据已成功导出到：\n{file_path}\n\n共导出 {len(self.export_data)} 条记录。\n"
                f"IQ配对JSONL: {self.iq_pair_store.get_current_path()}"
            )

            self.status_bar.showMessage(f"数据已导出到: {os.path.basename(file_path)}")

        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出数据时发生错误：\n{str(e)}")
            print(f"导出CSV失败: {e}")
            import traceback
            traceback.print_exc()

    def _on_export_dataset(self):
        """Export current IQ records into dataset-style CSV files."""
        try:
            self._drain_iq_writer(timeout_s=3.0)
            records = self.iq_pair_store.read_records()
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            QMessageBox.critical(self, "读取失败", f"无法读取当前 IQ 会话：\n{error}")
            return

        if not records:
            QMessageBox.warning(self, "提示", "当前没有可导出的 IQ 配对记录，请先开始采集。")
            return

        cfg = self.dataset_collection_panel.get_dataset_export_config()
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_dir = os.path.join(root_dir, "data", "dataset_exports")
        os.makedirs(default_dir, exist_ok=True)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存数据集 RAW CSV",
            os.path.join(default_dir, "dataset_root.csv"),
            "CSV文件 (*.csv);;所有文件 (*.*)"
        )
        if not file_path:
            return

        try:
            export_dir = os.path.dirname(file_path)
            basename = os.path.basename(file_path)
            prefix = basename[:-8] if basename.lower().endswith("_raw.csv") else os.path.splitext(basename)[0]
            ds_cfg = DatasetExportConfig(
                scene_label=str(cfg.get("scene_label") or ""),
                anchor_configs=dict(cfg.get("anchor_configs") or {}),
            )
            outputs = export_dataset(
                records=records,
                output_dir=export_dir,
                prefix=prefix,
                config=ds_cfg,
                calibers=cfg.get("calibers"),
            )
            if not outputs:
                QMessageBox.warning(self, "提示", "当前记录里没有可导出的 anchor 数据。")
                return
            lines = []
            for anchor_id, raw_csv, feat_csv, time_csv in outputs:
                lines.append(f"{anchor_id}:")
                lines.append(raw_csv)
                lines.append(feat_csv)
                lines.append(time_csv)
            QMessageBox.information(
                self,
                "导出成功",
                "数据集已按 anchor 分别导出：\n" + "\n".join(lines)
            )
            self.status_bar.showMessage(f"数据集已按 anchor 导出: {len(outputs)} 组")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出数据集时发生错误：\n{str(e)}")
            print(f"导出数据集失败: {e}")
            import traceback
            traceback.print_exc()

    def _on_anchor_dragged(self, anchor_index, x, y):
        """anchor拖动回调"""
        # 更新锚点面板显示
        self.anchor_panel.update_anchor_position(anchor_index, x, y)

        # 更新算法中的锚点
        self._update_solver_anchors()

        self.status_bar.showMessage(f"Anchor {anchor_index + 1} 已移动到 ({x:.2f}, {y:.2f})")

    def _on_true_position_changed_from_panel(self, true_pos):
        """终端真实位置面板变更"""
        if not true_pos or len(true_pos) < 3:
            return
        self.true_position_serial = [float(true_pos[0]), float(true_pos[1]), float(true_pos[2])]
        if self.current_mode == "serial":
            self.position_plot.set_true_position(*self.true_position_serial)
        self.status_bar.showMessage(
            f"真值位置已更新: ({self.true_position_serial[0]:.2f}, {self.true_position_serial[1]:.2f}, {self.true_position_serial[2]:.2f})"
        )

    def _on_true_position_dragged(self, x, y, z):
        """2D图拖动真值点回调（串口模式）"""
        self.true_position_serial = [float(x), float(y), float(z)]
        self.anchor_panel.set_true_position(self.true_position_serial[0], self.true_position_serial[1], self.true_position_serial[2])
        self.status_bar.showMessage(
            f"真值点拖动到: ({self.true_position_serial[0]:.2f}, {self.true_position_serial[1]:.2f}, {self.true_position_serial[2]:.2f})"
        )

    def _on_mode_changed(self, mode):
        """数据源模式切换联动"""
        self.current_mode = mode
        self.position_plot.set_mode(mode)
        self.serial_panel.setVisible(mode == "serial")
        if mode == "serial":
            self.position_plot.set_true_position(*self.true_position_serial)
            self._reset_serial_truth_motion_state()
        else:
            sim_cfg = self.control_panel.get_simulation_config()
            self.position_plot.set_true_position(*sim_cfg.get('start_point', [25.0, 25.0, 1.5]))

    def _on_client_selection_changed(self, client_key):
        """Client display selection changed."""
        if str(client_key) == "__auto__":
            self.status_bar.showMessage("Client display: auto follow latest")
            return

        state = self._serial_client_states.get(str(client_key), {})
        label = state.get('client_label') or client_key
        self.status_bar.showMessage(f"Client display: {label} (refreshes on next frame)")

    def _reset_simulation_motion_state(self, sim_cfg=None):
        """重置模拟路径运动状态"""
        if sim_cfg is None:
            sim_cfg = self.control_panel.get_simulation_config()
        self.sim_progress = 0.0
        self.sim_direction = 1.0
        self.sim_last_time = time.time()
        start_point = sim_cfg.get('start_point', [25.0, 25.0, 1.5])
        self.position_plot.set_true_position(*start_point)

    def _reset_serial_truth_motion_state(self):
        """重置串口模式真值路径状态"""
        self.serial_truth_progress = 0.0
        self.serial_truth_direction = 1.0
        self.serial_truth_last_time = time.time()

    def _update_serial_truth_motion(self):
        """串口模式下按首尾点和速度更新真值位置（往返）"""
        cfg = self.anchor_panel.get_true_motion_config()
        if not cfg.get('enabled', False):
            return

        start_p = np.array(cfg.get('start_point', self.true_position_serial), dtype=float)
        end_p = np.array(cfg.get('end_point', self.true_position_serial), dtype=float)
        speed_mps = float(cfg.get('speed_mps', 1.5))

        now_ts = time.time()
        if self.serial_truth_last_time is None:
            self.serial_truth_last_time = now_ts
        dt = max(1e-3, now_ts - self.serial_truth_last_time)
        self.serial_truth_last_time = now_ts

        direction_vec = end_p - start_p
        path_length = float(np.linalg.norm(direction_vec))
        if path_length < 1e-6:
            pos = start_p
        else:
            delta_progress = (speed_mps * dt) / path_length
            self.serial_truth_progress += self.serial_truth_direction * delta_progress

            while self.serial_truth_progress > 1.0 or self.serial_truth_progress < 0.0:
                if self.serial_truth_progress > 1.0:
                    self.serial_truth_progress = 2.0 - self.serial_truth_progress
                    self.serial_truth_direction = -1.0
                elif self.serial_truth_progress < 0.0:
                    self.serial_truth_progress = -self.serial_truth_progress
                    self.serial_truth_direction = 1.0

            pos = start_p + self.serial_truth_progress * direction_vec

        self.true_position_serial = [float(pos[0]), float(pos[1]), float(pos[2])]
        self.anchor_panel.set_true_position(*self.true_position_serial)
        self.position_plot.set_true_position(*self.true_position_serial)

    def _on_anchor_config_changed(self, anchors_2d, anchors_3d):
        """锚点配置变更回调"""
        # 更新绘图中的锚点
        self.position_plot.update_anchors(anchors_2d, anchors_3d)

        # 更新算法中的锚点
        self._update_solver_anchors()
        self._sync_anchor_count(len(anchors_2d))

        self.status_bar.showMessage(f"锚点配置已更新：{len(anchors_2d)} 个")

    def _active_anchor_count(self):
        """Return the user-configured count; four is only the initial default."""
        return max(1, len(self.anchor_panel.get_anchors_2d()))

    def _active_anchor_ids(self):
        return tuple(f"A{index}" for index in range(1, self._active_anchor_count() + 1))

    def _sync_anchor_count(self, count):
        """Propagate an arbitrary configured anchor count across every view and service."""
        count = max(1, int(count))
        self.control_panel.set_anchor_count(count)
        self.dataset_collection_panel.set_anchor_count(count)
        self.sensing_page_panel.set_anchor_count(count)
        self.iq_page_panel.set_anchor_count(count)
        self.iq_mode3_service.set_anchor_count(count)
        self.multi_client_distance_panel.set_anchor_count(count)

        for state in self._serial_client_states.values():
            distances = list(state.get("distances") or [])[:count]
            rssis = list(state.get("rssi_values") or [])[:count]
            distances.extend([0.0] * (count - len(distances)))
            rssis.extend([None] * (count - len(rssis)))
            state["distances"] = distances
            state["rssi_values"] = rssis
            state["valid_count"] = sum(1 for value in distances if value and float(value) > 0)

    def _update_solver_anchors(self):
        """更新算法中的锚点配置"""
        anchors_2d = np.array(self.anchor_panel.get_anchors_2d())
        anchors_3d = np.array(self.anchor_panel.get_anchors_3d())

        if self.solver_2d:
            self.solver_2d.anchors = anchors_2d
            self.solver_2d.n_anchors = len(anchors_2d)

        if self.solver_3d:
            self.solver_3d.anchors = anchors_3d
            self.solver_3d.n_anchors = len(anchors_3d)

    def _build_online_anchor_subset(self, dists):
        """基于距离数组构建在线锚点子集（仅保留距离>0的锚点）"""
        anchors_2d_all = self.anchor_panel.get_anchors_2d()
        anchors_3d_all = self.anchor_panel.get_anchors_3d()

        online_indices = []
        for idx, dist in enumerate(dists):
            if idx >= len(anchors_2d_all) or idx >= len(anchors_3d_all):
                continue
            if dist is not None and float(dist) > 0:
                online_indices.append(idx)

        online_dists = [float(dists[i]) for i in online_indices]
        online_anchors_2d = [anchors_2d_all[i] for i in online_indices]
        online_anchors_3d = [anchors_3d_all[i] for i in online_indices]

        return online_indices, online_dists, online_anchors_2d, online_anchors_3d

    def _reset_serial_client_state(self):
        """Reset cached multi-client serial state."""
        self._serial_client_states = {}
        self._serial_client_order = []
        self._serial_event_seq = 0
        self.last_pos_2d_by_client = {}
        self.last_pos_3d_by_client = {}
        self.control_panel.update_client_choices([])

    def _get_serial_client_state(self, client_key, client_label=None):
        """Return persistent state bucket for one client."""
        client_key = str(client_key or "client")
        state = self._serial_client_states.get(client_key)
        if state is None:
            state = {
                'client_key': client_key,
                'client_label': client_label or client_key,
                'source_addr_byte': None,
                'distances': [0.0] * self._active_anchor_count(),
                'rssi_values': [None] * self._active_anchor_count(),
                'valid_count': 0,
                'cost_ms': None,
                'last_data_seq': 0,
                'last_rssi_seq': 0,
                'last_update_seq': 0,
                'last_emitted_signature': None,
                'last_timestamp': None,
            }
            self._serial_client_states[client_key] = state
            self._serial_client_order.append(client_key)
        elif client_label:
            state['client_label'] = client_label
        return state

    def _update_serial_client_selector(self):
        """Refresh client selector choices from discovered clients."""
        client_items = []
        for client_key in self._serial_client_order:
            state = self._serial_client_states.get(client_key) or {}
            label = state.get('client_label') or client_key
            addr = state.get('source_addr_byte')
            if addr is not None:
                label = f"{label} (addr={addr})"
            client_items.append((label, client_key))
        self.control_panel.update_client_choices(client_items)

    def _handle_serial_runtime_error(self, err: Exception):
        """Handle serial runtime failures and stop polling cleanly."""
        self._latest_serial_lines = []
        self.serial_panel._on_disconnect()

        self.is_running = False
        self.update_timer.stop()
        self.control_panel.set_running_state(False)

        msg = f"串口读取失败，已自动断开: {err}"
        print(msg)
        self.status_bar.showMessage(msg)

    def _should_refresh_iq_panel(self, loop_ts: float, iq_records_updated: bool) -> bool:
        if not self.iq_parse_enabled:
            return False
        if self.page_stack.currentIndex() != 2 and not iq_records_updated:
            return False

        backlog = self._iq_write_queue.qsize()
        min_interval_s = 0.20
        if backlog > 600:
            min_interval_s = 0.35
        if backlog > 1500:
            min_interval_s = 0.60

        if iq_records_updated and (loop_ts - self._last_iq_snapshot_refresh_ts) >= min_interval_s:
            self._last_iq_snapshot_refresh_ts = loop_ts
            return True

        if self.page_stack.currentIndex() == 2:
            due_by_frame = self.frame_count % max(1, int(self.iq_ui_update_interval_frames)) == 0
            if due_by_frame and (loop_ts - self._last_iq_snapshot_refresh_ts) >= min_interval_s:
                self._last_iq_snapshot_refresh_ts = loop_ts
                return True
        return False

    def _should_refresh_distance_panel(self, loop_ts: float, backlog: int) -> bool:
        min_interval_s = 0.08
        if backlog > 600:
            min_interval_s = 0.15
        if backlog > 1500:
            min_interval_s = 0.25
        if (loop_ts - self._last_distance_panel_refresh_ts) >= min_interval_s:
            self._last_distance_panel_refresh_ts = loop_ts
            return True
        return False

    def _snapshot_serial_client_state(self, state, timestamp):
        """Convert one cached client state to UI/algorithm data dict."""
        anchor_count = self._active_anchor_count()
        dists = list(state.get('distances') or [0.0] * anchor_count)[:anchor_count]
        rssis = list(state.get('rssi_values') or [None] * anchor_count)[:anchor_count]
        while len(dists) < anchor_count:
            dists.append(0.0)
        while len(rssis) < anchor_count:
            rssis.append(None)

        client_map = {
            'client_key': state.get('client_key'),
            'client_label': state.get('client_label'),
            'source_addr_byte': state.get('source_addr_byte'),
            'distances': list(dists),
            'rssi_values': list(rssis),
            'valid_count': int(state.get('valid_count') or 0),
            'cost_ms': state.get('cost_ms'),
            'timestamp': float(timestamp),
        }

        return {
            'client_key': state.get('client_key'),
            'client_label': state.get('client_label'),
            'source_addr_byte': state.get('source_addr_byte'),
            'distances': dists,
            'valid_count': int(state.get('valid_count') or 0),
            'timestamp': float(timestamp),
            'cost_ms': state.get('cost_ms'),
            'rssi_values': rssis,
            'clients': {
                state.get('client_key'): client_map,
            },
        }

    def _build_all_client_snapshot(self, timestamp):
        """Build lightweight snapshot for all known clients."""
        clients = {}
        for client_key, state in self._serial_client_states.items():
            clients[client_key] = {
                'client_key': state.get('client_key'),
                'client_label': state.get('client_label'),
                'source_addr_byte': state.get('source_addr_byte'),
                'distances': list(state.get('distances') or []),
                'rssi_values': list(state.get('rssi_values') or []),
                'valid_count': int(state.get('valid_count') or 0),
                'cost_ms': state.get('cost_ms'),
                'last_timestamp': state.get('last_timestamp'),
                'timestamp': float(timestamp),
            }
        return clients

    def _solve_position_for_distances(self, dists, client_key=None):
        """Solve one client's position and keep client-specific priors."""
        _, online_dists, online_anchors_2d, online_anchors_3d = self._build_online_anchor_subset(dists)
        valid_count = len(online_dists)

        est_p2 = None
        est_p3 = None
        client_key = str(client_key or "")

        if valid_count >= 3 and self.solver_2d:
            solver_2d = GnUlsPositioning(online_anchors_2d)
            if client_key:
                prior_2d = self.last_pos_2d_by_client.get(client_key)
            else:
                prior_2d = self.last_pos_2d
            if prior_2d is not None and len(prior_2d) != 2:
                prior_2d = None
            est_p2 = solver_2d.solve(online_dists, prior_pos=prior_2d)
            if client_key:
                self.last_pos_2d_by_client[client_key] = est_p2
            else:
                self.last_pos_2d = est_p2
        else:
            if client_key:
                self.last_pos_2d_by_client.pop(client_key, None)
            else:
                self.last_pos_2d = None

        if valid_count >= 4 and self.solver_3d:
            solver_3d = GnUlsPositioning(online_anchors_3d)
            if client_key:
                prior_3d = self.last_pos_3d_by_client.get(client_key)
            else:
                prior_3d = self.last_pos_3d
            if prior_3d is not None and len(prior_3d) != 3:
                prior_3d = None
            est_p3 = solver_3d.solve(online_dists, prior_pos=prior_3d)
            if client_key:
                self.last_pos_3d_by_client[client_key] = est_p3
            else:
                self.last_pos_3d = est_p3
        else:
            if client_key:
                self.last_pos_3d_by_client.pop(client_key, None)
            else:
                self.last_pos_3d = None

        if est_p2 is not None and est_p3 is not None:
            position = [est_p2[0], est_p2[1], est_p3[2]]
        elif est_p2 is not None:
            position = [est_p2[0], est_p2[1], 0]
        elif est_p3 is not None:
            position = [est_p3[0], est_p3[1], est_p3[2]]
        else:
            position = None

        return {
            'valid_count': valid_count,
            'est_p2': est_p2,
            'est_p3': est_p3,
            'position': position,
            'estimated_position': est_p2 if est_p2 is not None else est_p3,
        }

    def _get_client_cfr_map(self, client_key):
        cfr_map = {}
        for anchor_id in self._active_anchor_ids():
            record = self.iq_mode3_service.get_latest_link_record(anchor_id, client_key)
            if record is not None:
                cfr_map[anchor_id] = record["cfr"]
        return cfr_map

    def _build_link_activity_inputs(self, positions, loop_ts):
        anchors_2d = self.anchor_panel.get_anchors_2d()
        metric = self.sensing_page_panel.active_metric()
        inputs = []
        for client_key, item in (positions or {}).items():
            pos = item.get("position")
            if not pos or len(pos) < 2:
                continue
            cfr_map = self._get_client_cfr_map(client_key)
            for idx, anchor_pos in enumerate(anchors_2d):
                anchor_id = f"A{idx + 1}"
                cfr_info = (cfr_map or {}).get(anchor_id) or {}
                score = cfr_info.get(metric)
                if score is None:
                    continue
                inputs.append({
                    "client_key": str(client_key or ""),
                    "client_label": str(item.get("client_label") or client_key or ""),
                    "anchor_id": anchor_id,
                    "anchor_pos": (float(anchor_pos[0]), float(anchor_pos[1])),
                    "client_pos": (float(pos[0]), float(pos[1])),
                    "activity": float(score),
                    "timestamp": float(loop_ts),
                })
        return inputs

    def _update_link_activity_heatmap(self, data, loop_ts):
        anchors_2d = self.anchor_panel.get_anchors_2d()
        inputs = data.get("link_activity_inputs") or []
        heatmap_data = self.link_activity_heatmap_service.update(inputs, anchors_2d, loop_ts)
        data["link_activity_heatmap"] = heatmap_data

    def _filter_position_with_kalman(self, client_key, position, timestamp):
        if not self.position_kf_enabled:
            return None
        return self.position_kalman_service.update_position(str(client_key or ""), position, float(timestamp or 0.0))

    def _solve_all_client_positions(self, data):
        """Solve positions for every client present in the latest serial snapshot."""
        clients = data.get('clients') or {}
        positions = {}
        selected_key = data.get('client_key')

        for client_key, client_data in clients.items():
            dists = client_data.get('distances') or []
            solved = self._solve_position_for_distances(dists, client_key=client_key)
            client_data.update(solved)
            kf_position = self._filter_position_with_kalman(client_key, solved.get('position'), client_data.get('timestamp'))
            client_data['kf_position'] = kf_position
            if solved.get('position') is not None:
                positions[client_key] = {
                    'client_key': client_key,
                    'client_label': client_data.get('client_label') or client_key,
                    'source_addr_byte': client_data.get('source_addr_byte'),
                    'position': solved.get('position'),
                    'kf_position': kf_position,
                    'valid_count': solved.get('valid_count', 0),
                    'is_selected': client_key == selected_key,
                }

        selected_client = clients.get(selected_key) if selected_key else None
        if selected_client:
            data['valid_count'] = int(selected_client.get('valid_count') or 0)
            data['position'] = selected_client.get('position')
            data['kf_position'] = selected_client.get('kf_position')
            data['estimated_position'] = selected_client.get('estimated_position')
            data['kf_enabled'] = self.position_kf_enabled
            return (
                selected_client.get('distances') or data.get('distances', []),
                data['valid_count'],
                selected_client.get('est_p2'),
                selected_client.get('est_p3'),
                positions,
            )

        solved = self._solve_position_for_distances(data.get('distances', []), client_key=selected_key)
        data.update(solved)
        data['kf_position'] = self._filter_position_with_kalman(selected_key, solved.get('position'), data.get('timestamp'))
        data['kf_enabled'] = self.position_kf_enabled
        return (
            data.get('distances', []),
            int(data.get('valid_count') or 0),
            data.get('est_p2'),
            data.get('est_p3'),
            positions,
        )

    def _on_update(self):
        """定时更新回调"""
        try:
            if not self.is_running:
                return

            self.frame_count += 1

            # 获取数据
            if self.current_mode == "simulation":
                data = self._generate_simulation_data()
            else:
                loop_ts = time.time()
                self._update_serial_truth_motion()
                data = self._get_serial_data_multi(loop_ts=loop_ts)
                iq_records_updated = False

                if data:
                    for measurement in data.get('new_measurements') or []:
                        distances = measurement.get('distances') or []
                        rssis = measurement.get('rssi_values') or []
                        measurement_distances = {}
                        measurement_rssis = {}
                        for idx in range(self._active_anchor_count()):
                            anchor_id = f"A{idx + 1}"
                            if idx < len(distances):
                                dist_val = distances[idx]
                                if dist_val is not None and float(dist_val) > 0:
                                    measurement_distances[anchor_id] = float(dist_val)
                            if idx < len(rssis):
                                rssi_val = rssis[idx]
                                if rssi_val is not None:
                                    measurement_rssis[anchor_id] = int(rssi_val)

                        self.iq_mode3_service.push_measurement(
                            timestamp=float(loop_ts),
                            distances=measurement_distances,
                            rssis=measurement_rssis,
                            cost_ms=measurement.get('cost_ms', 0),
                            client_key=measurement.get('client_key'),
                            client_label=measurement.get('client_label'),
                            source_addr_byte=measurement.get('source_addr_byte'),
                        )

                if self.iq_parse_enabled:
                    new_records = self.iq_mode3_service.ingest_lines(self._latest_serial_lines, timestamp=float(loop_ts))
                    if new_records:
                        sensing_samples = self.sensing_state_service.ingest_records(new_records)
                        self.sensing_page_panel.ingest_samples(sensing_samples)
                        self._enqueue_iq_records(new_records)
                        iq_records_updated = True
                    # IQ页面按采样间隔刷新，降低主线程绘图开销；解析与落盘仍每帧执行。
                    if self._should_refresh_iq_panel(float(loop_ts), iq_records_updated):
                        snapshots = self.iq_mode3_service.get_multi_anchor_snapshots(limit=200)
                        self.iq_page_panel.update_multi_snapshots(snapshots)

            if data and data.get('skip_ui'):
                return

            if data:
                loop_ts = float(data.get('timestamp') or time.time())
                dists = data.get('distances', [])
                if self.current_mode == "serial":
                    data['true_position'] = list(self.true_position_serial)
                    dists, valid_count, est_p2, est_p3, client_positions = self._solve_all_client_positions(data)
                    data['client_positions'] = client_positions
                else:
                    solved = self._solve_position_for_distances(dists)
                    data.update(solved)
                    valid_count = solved['valid_count']
                    est_p2 = solved['est_p2']
                    est_p3 = solved['est_p3']

                backlog = self._iq_write_queue.qsize()
                position_interval = 1
                if backlog > 600:
                    position_interval = 2
                if backlog > 1500:
                    position_interval = 4

                # 定位图和统计是主线程最重部分，队列积压时主动降频，优先串口解析与落盘。
                if self.frame_count % position_interval == 0:
                    if self.current_mode == "serial" and self.sensing_enabled:
                        data['link_activity_inputs'] = self._build_link_activity_inputs(data.get('client_positions') or {}, loop_ts)
                        if data['link_activity_inputs']:
                            self._update_link_activity_heatmap(data, loop_ts)
                            self.sensing_page_panel.update_spatial_heatmap(
                                data['link_activity_heatmap'], "Spatial projection uses positioned links"
                            )
                        else:
                            self.sensing_page_panel.update_spatial_heatmap(
                                None, "Link scores are active; spatial projection is waiting for a client position"
                            )
                    self.position_plot.update_plot(data)
                    self.stats_panel.update_stats(data)

                distance_interval = max(1, int(self.distance_ui_update_interval_frames))
                table_interval = max(1, int(self.table_ui_update_interval_frames))
                if backlog > 600:
                    distance_interval = max(distance_interval, 6)
                    table_interval = max(table_interval, 2)
                if backlog > 1500:
                    distance_interval = max(distance_interval, 10)
                    table_interval = max(table_interval, 4)

                update_distance_plot = (self.frame_count % distance_interval == 0)
                update_distance_table = (self.frame_count % table_interval == 0)
                if update_distance_plot or update_distance_table:
                    if not self._should_refresh_distance_panel(float(loop_ts), backlog):
                        update_distance_plot = False
                        update_distance_table = False
                if update_distance_plot or update_distance_table:
                    try:
                        measurements = data.get('new_measurements') if self.current_mode == "serial" else None
                        if not measurements:
                            measurements = [data]
                        for item in measurements:
                            self.multi_client_distance_panel.add_measurement(
                                client_key=item.get('client_key'),
                                client_label=item.get('client_label') or item.get('client_key'),
                                source_addr_byte=item.get('source_addr_byte'),
                                distances=item.get('distances') or [],
                                rssi_values=item.get('rssi_values'),
                                timestamp=item.get('timestamp'),
                                valid_count=item.get('valid_count', 0),
                                cost_ms=item.get('cost_ms'),
                                update_plot=update_distance_plot,
                                update_table=update_distance_table,
                            )
                    except (TypeError, ValueError, IndexError) as error:
                        raise RuntimeError("距离面板更新失败") from error

                # 收集导出数据
                self._collect_export_data(data, dists, valid_count, est_p2, est_p3)
            else:
                return

        except Exception as error:
            self.is_running = False
            self.update_timer.stop()
            self.control_panel.set_running_state(False)
            self.status_bar.showMessage(f"运行已停止: {error}")
            print(f"ERROR: 运行已停止: {error}")
            import traceback
            traceback.print_exc()

    def _collect_export_data(self, data, dists, valid_count, est_p2, est_p3):
        """收集导出数据

        Args:
            data: 原始数据字典
            dists: 距离列表
            valid_count: 有效锚点数量
            est_p2: 2D估计位置 [x, y] 或 None
            est_p3: 3D估计位置 [x, y, z] 或 None
        """
        if not self.collect_runtime_data_enabled:
            return
        try:
            anchor_count = self._active_anchor_count()
            distances_fixed = [
                dists[index] if index < len(dists) and dists[index] > 0 else 0.0
                for index in range(anchor_count)
            ]

            # 获取时间戳
            timestamp = data.get('timestamp')
            if timestamp is None:
                timestamp = time.time()

            # 固定RSSI列表长度
            rssi_values = data.get('rssi_values') or []
            rssi_fixed = [
                rssi_values[index] if index < len(rssi_values) else None
                for index in range(anchor_count)
            ]

            # 格式化为datetime字符串
            time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            # 获取锚点坐标（2D模式下Z强制为0）
            anchors_3d = self.anchor_panel.get_anchors_3d()
            is_3d_mode = self.anchor_panel.is_3d_mode()

            anchor_xyz = []
            for i in range(anchor_count):
                if i < len(anchors_3d):
                    ax = float(anchors_3d[i][0])
                    ay = float(anchors_3d[i][1])
                    az = float(anchors_3d[i][2]) if is_3d_mode else 0.0
                else:
                    ax, ay, az = '', '', ''
                anchor_xyz.append((ax, ay, az))

            # 构建数据行
            export_row = {
                'Timestamp': time_str,
                'ClientKey': data.get('client_key', ''),
                'ClientLabel': data.get('client_label', ''),
                'SourceAddrByte': data.get('source_addr_byte', ''),
                'cost_ms': data.get('cost_ms', 0) or 0,  # 确保不为None
                'Valid_Anchors': valid_count,
                'X_2D': est_p2[0] if est_p2 is not None and len(est_p2) >= 2 else '',
                'Y_2D': est_p2[1] if est_p2 is not None and len(est_p2) >= 2 else '',
                'X_3D': est_p3[0] if est_p3 is not None and len(est_p3) >= 3 else '',
                'Y_3D': est_p3[1] if est_p3 is not None and len(est_p3) >= 3 else '',
                'Z_3D': est_p3[2] if est_p3 is not None and len(est_p3) >= 3 else '',
                'True_X': data.get('true_position', ['', '', ''])[0] if data.get('true_position') else '',
                'True_Y': data.get('true_position', ['', '', ''])[1] if data.get('true_position') else '',
                'True_Z': data.get('true_position', ['', '', ''])[2] if data.get('true_position') else ''
            }
            for index in range(anchor_count):
                number = index + 1
                export_row[f'A{number}'] = distances_fixed[index]
                export_row[f'RSSI{number}'] = rssi_fixed[index] if rssi_fixed[index] is not None else ''
                export_row[f'Anchor{number}_X'] = anchor_xyz[index][0]
                export_row[f'Anchor{number}_Y'] = anchor_xyz[index][1]
                export_row[f'Anchor{number}_Z'] = anchor_xyz[index][2]

            # 添加到导出数据列表
            self.export_data.append(export_row)

        except (TypeError, ValueError, IndexError) as error:
            raise RuntimeError("定位数据采集失败") from error

    def _generate_simulation_data(self):
        """生成模拟数据"""
        sim_cfg = self.control_panel.get_simulation_config()

        start_p = np.array(sim_cfg.get('start_point', [10.0, 10.0, 1.5]), dtype=float)
        end_p = np.array(sim_cfg.get('end_point', [40.0, 40.0, 1.5]), dtype=float)
        speed_mps = float(sim_cfg.get('speed_mps', 2.0))
        noise_std = float(sim_cfg.get('noise_std', 0.1))
        anchor_count = self._active_anchor_count()
        per_anchor_noise_ranges = sim_cfg.get('per_anchor_noise_ranges') or [
            [noise_std, noise_std] for _ in range(anchor_count)
        ]
        simulate_rssi = bool(sim_cfg.get('simulate_rssi', True))

        now_ts = time.time()
        if self.sim_last_time is None:
            self.sim_last_time = now_ts
        dt = max(1e-3, now_ts - self.sim_last_time)
        self.sim_last_time = now_ts

        direction_vec = end_p - start_p
        path_length = float(np.linalg.norm(direction_vec))

        if path_length < 1e-6:
            true_p3 = start_p.copy()
        else:
            delta_progress = (speed_mps * dt) / path_length
            self.sim_progress += self.sim_direction * delta_progress

            while self.sim_progress > 1.0 or self.sim_progress < 0.0:
                if self.sim_progress > 1.0:
                    self.sim_progress = 2.0 - self.sim_progress
                    self.sim_direction = -1.0
                elif self.sim_progress < 0.0:
                    self.sim_progress = -self.sim_progress
                    self.sim_direction = 1.0

            true_p3 = start_p + self.sim_progress * direction_vec

        x_true, y_true, z_true = float(true_p3[0]), float(true_p3[1]), float(true_p3[2])
        # 获取当前锚点配置
        anchors = self.anchor_panel.get_anchors_3d()

        # 计算到锚点的距离
        true_dists = [float(np.linalg.norm(true_p3 - np.array(a))) for a in anchors]

        # 各anchor独立噪声区间采样
        sampled_noise_std = []
        for i in range(len(anchors)):
            if i < len(per_anchor_noise_ranges):
                rng = per_anchor_noise_ranges[i]
                if isinstance(rng, (list, tuple)) and len(rng) >= 2:
                    nmin = float(rng[0])
                    nmax = float(rng[1])
                else:
                    nmin = noise_std
                    nmax = noise_std
            else:
                nmin = noise_std
                nmax = noise_std

            if nmin > nmax:
                nmin, nmax = nmax, nmin

            sampled_noise_std.append(float(np.random.uniform(nmin, nmax)))

        # 各anchor距离加噪
        dists = []
        for i, d in enumerate(true_dists):
            sigma_i = sampled_noise_std[i] if i < len(sampled_noise_std) else noise_std
            d_noisy = max(0.01, d + np.random.normal(0, sigma_i))
            dists.append(float(d_noisy))

        # 统计有效锚点数量
        valid_count = sum(1 for d in dists if d > 0)

        # RSSI模拟（与锚点编号无关）：由链路质量、噪声、距离、遮挡随机共同决定
        if simulate_rssi:
            # 链路质量分数：由每个anchor的噪声采样驱动，噪声越大质量越差
            noise_norm = [min(max(s / 1.0, 0.0), 1.5) for s in sampled_noise_std]
            rssi_values = []
            for i, d in enumerate(dists):
                sigma_i = sampled_noise_std[i] if i < len(sampled_noise_std) else noise_std

                # 质量分数 q∈[0,1]：1为高质量，0为低质量
                q = 1.0 - min(max(noise_norm[i], 0.0), 1.0)

                # 基线RSSI：高质量约-44dBm，低质量可到-66dBm
                base_rssi = -44.0 - 22.0 * (1.0 - q)

                # 距离影响（弱依赖，避免锚点编号固定好坏）
                dist_penalty = 4.0 * np.log10(max(d, 0.2) / 1.0)

                # 噪声惩罚（与定位质量相关）
                noise_penalty = 6.0 * sigma_i

                # 环境遮挡：随机发生，任意anchor都可能短时变差
                block_prob = 0.06 + 0.20 * (1.0 - q)
                block_penalty = np.random.uniform(5.0, 18.0) if np.random.rand() < block_prob else 0.0

                # 小尺度衰落
                fading = np.random.normal(0.0, 1.2 + 2.0 * (1.0 - q))

                rssi = base_rssi - dist_penalty - noise_penalty - block_penalty + fading

                # 链路失效哨兵（概率同样与质量相关）
                dropout_prob = 0.002 + 0.05 * (1.0 - q)
                if np.random.rand() < dropout_prob:
                    rssi_values.append(-128)
                else:
                    rssi_values.append(int(round(float(np.clip(rssi, -120.0, -35.0)))))
        else:
            rssi_values = [None] * len(anchors)

        return {
            'true_position': [x_true, y_true, z_true],  # 真值
            'distances': dists,
            'valid_count': valid_count,
            'timestamp': now_ts,
            'cost_ms': int(self.control_panel.get_simulation_config().get('refresh_ms', 50)),
            'rssi_values': rssi_values
        }

    def _get_serial_data_multi(self, loop_ts=None):
        """Read serial data with per-client pairing support."""
        if not self.serial_panel.is_serial_connected():
            self._latest_serial_lines = []
            return None

        serial_conn = self.serial_panel.get_serial_connection()
        if not serial_conn:
            self._latest_serial_lines = []
            return None

        received_lines = []
        ts = float(loop_ts if loop_ts is not None else time.time())
        new_measurements = []

        try:
            for _ in range(self.SERIAL_READ_MAX_LINES_PER_TICK):
                if serial_conn.in_waiting <= 0:
                    break

                line = serial_conn.readline()
                try:
                    text = line.decode('utf-8').strip()
                except UnicodeDecodeError:
                    text = line.decode('gbk', errors='ignore').strip()

                if text:
                    received_lines.append(text)

            for line in received_lines:
                if "COLLECT_SAMPLE_META" not in line:
                    continue

                collect_match = self.SERIAL_COLLECT_META_RE.match(line)
                if collect_match:
                    anchor_index = int(collect_match.group(1)) - 1
                    client_id = int(collect_match.group(2))
                    sdk_dist_mm = int(collect_match.group(4))
                    sdk_rssi = int(collect_match.group(5))

                    if 0 <= anchor_index < self._active_anchor_count() and client_id > 0:
                        client_key = f"client{client_id}"
                        client_label = client_key
                        state = self._get_serial_client_state(client_key, client_label)
                        state['source_addr_byte'] = client_id

                        anchor_count = self._active_anchor_count()
                        dists = list(state.get('distances') or [0.0] * anchor_count)[:anchor_count]
                        rssis = list(state.get('rssi_values') or [None] * anchor_count)[:anchor_count]
                        while len(dists) < anchor_count:
                            dists.append(0.0)
                        while len(rssis) < anchor_count:
                            rssis.append(None)

                        dists[anchor_index] = float(sdk_dist_mm) / 1000.0
                        rssis[anchor_index] = sdk_rssi

                        self._serial_event_seq += 1
                        state['distances'] = dists
                        state['rssi_values'] = rssis
                        state['valid_count'] = sum(1 for dist in dists if dist and float(dist) > 0)
                        state['cost_ms'] = state.get('cost_ms') or 0
                        state['last_data_seq'] = self._serial_event_seq
                        state['last_rssi_seq'] = self._serial_event_seq
                        state['last_update_seq'] = self._serial_event_seq
                        state['last_timestamp'] = ts
                    continue

            for state in self._serial_client_states.values():
                if int(state.get('valid_count') or 0) <= 0:
                    continue
                signature = (
                    tuple(state.get('distances') or []),
                    tuple(state.get('rssi_values') or []),
                    state.get('cost_ms'),
                    state.get('source_addr_byte'),
                    int(state.get('last_data_seq') or 0),
                    int(state.get('last_rssi_seq') or 0),
                )
                if signature == state.get('last_emitted_signature'):
                    continue
                state['last_emitted_signature'] = signature
                new_measurements.append(self._snapshot_serial_client_state(state, ts))

        except serial.SerialException as e:
            self._handle_serial_runtime_error(e)
            return None
        except OSError as e:
            err_text = str(e)
            if any(token.lower() in err_text.lower() for token in self.SERIAL_ACCESS_ERROR_TOKENS):
                self._handle_serial_runtime_error(e)
                return None
            print(f"Serial read error: {e}")
            import traceback
            traceback.print_exc()
        self._latest_serial_lines = received_lines
        self._update_serial_client_selector()

        if not new_measurements:
            return None

        selected_key = self.control_panel.get_selected_client_key()

        selected_measurement = None
        skip_ui = False
        if selected_key != "__auto__":
            for measurement in new_measurements:
                if measurement.get('client_key') == selected_key:
                    selected_measurement = measurement
                    break
            if selected_measurement is None:
                selected_measurement = max(
                    new_measurements,
                    key=lambda item: int(
                        (self._serial_client_states.get(item.get('client_key')) or {}).get('last_update_seq') or 0
                    ),
                )
                skip_ui = True
        else:
            selected_measurement = new_measurements[0] if new_measurements else None

        data = dict(selected_measurement)
        data['clients'] = self._build_all_client_snapshot(ts)
        data['new_measurements'] = new_measurements
        data['skip_ui'] = skip_ui
        return data

    def closeEvent(self, event):
        """关闭事件"""
        if self.is_running:
            reply = QMessageBox.question(
                self, "确认退出",
                "定位正在运行中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return

        self._on_stop()
        writer_stopped = threading.Event()
        self._iq_write_queue.put(("stop", writer_stopped), timeout=2.0)
        if not writer_stopped.wait(2.0):
            QMessageBox.critical(self, "关闭失败", "IQ 写入线程未能正常停止，请稍后重试。")
            event.ignore()
            return
        self._iq_writer_thread.join(timeout=2.0)
        self.iq_pair_store.close()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 高分屏自适应字体缩放
    screen = app.primaryScreen()
    if screen is not None:
        dpr = float(screen.devicePixelRatio())
        dpi_scale = float(screen.logicalDotsPerInch()) / 96.0
        ui_scale = max(1.0, min(1.8, max(dpr, dpi_scale)))
        base_font = app.font()
        base_size = float(base_font.pointSizeF())
        if base_size <= 0:
            base_size = 9.0
        base_font.setPointSizeF(base_size * min(ui_scale, 1.35))
        app.setFont(base_font)

    # 设置应用样式
    app.setStyle('Fusion')

    # 设置全局简洁样式表 - 白底黑框，重要按钮保留颜色
    simple_style = """
    /* 全局样式 */
    QMainWindow, QWidget {
        background-color: white;
        color: black;
        font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    }

    /* 分组框 */
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

    /* 按钮 - 默认黑白样式 */
    QPushButton {
        background-color: white;
        border: 1px solid black;
        border-radius: 3px;
        color: black;
        padding: 5px 10px;
        font-weight: normal;
    }
    QPushButton:hover {
        background-color: #f0f0f0;
        border-color: #333333;
    }
    QPushButton:pressed {
        background-color: #e0e0e0;
    }
    QPushButton:disabled {
        background-color: #f5f5f5;
        color: #999999;
        border-color: #cccccc;
    }

    /* 开始按钮特殊样式 - 保留绿色 */
    QPushButton[start="true"] {
        background-color: #4CAF50;
        border-color: #2E7D32;
        color: white;
        font-weight: bold;
    }
    QPushButton[start="true"]:hover {
        background-color: #45a049;
        border-color: #1B5E20;
    }

    /* 停止按钮特殊样式 - 保留红色 */
    QPushButton[stop="true"] {
        background-color: #f44336;
        border-color: #c62828;
        color: white;
        font-weight: bold;
    }
    QPushButton[stop="true"]:hover {
        background-color: #da190b;
        border-color: #b71c1c;
    }

    /* 下拉框 */
    QComboBox {
        background-color: white;
        color: black;
        border: 1px solid black;
        border-radius: 3px;
        padding: 3px;
        min-width: 80px;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid black;
    }
    QComboBox QAbstractItemView {
        background-color: white;
        color: black;
        border: 1px solid black;
        selection-background-color: #e0e0e0;
    }

    /* 标签 */
    QLabel {
        color: black;
    }
    QLabel[highlight="true"] {
        color: black;
        font-weight: bold;
    }

    /* 复选框 */
    QCheckBox {
        color: black;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
    }
    QCheckBox::indicator:unchecked {
        border: 1px solid #999999;
        background-color: white;
    }
    QCheckBox::indicator:checked {
        border: 1px solid black;
        background-color: #4CAF50;
    }
    QCheckBox::indicator:pressed {
        background-color: #d0d0d0;
    }

    /* 表格 */
    QTableWidget {
        background-color: white;
        alternate-background-color: #f9f9f9;
        gridline-color: #dddddd;
        color: black;
        border: 1px solid black;
        border-radius: 3px;
    }
    QTableWidget::item {
        padding: 3px;
    }
    QTableWidget::item:selected {
        background-color: #e0e0e0;
    }
    QHeaderView::section {
        background-color: #f0f0f0;
        color: black;
        padding: 4px;
        font-weight: bold;
        border: 1px solid #cccccc;
    }

    /* 状态栏 */
    QStatusBar {
        background-color: #f0f0f0;
        color: black;
        border-top: 1px solid black;
    }

    /* 滚动条 */
    QScrollBar:vertical {
        background-color: #f0f0f0;
        width: 12px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical {
        background-color: #cccccc;
        border-radius: 6px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #999999;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        background: none;
    }

    /* 分割器 */
    QSplitter::handle {
        background-color: #cccccc;
        border: 1px solid #999999;
    }
    QSplitter::handle:hover {
        background-color: #999999;
    }

    /* 框架 */
    QFrame {
        background-color: transparent;
    }
    """

    app.setStyleSheet(simple_style)

    # 创建主窗口
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
