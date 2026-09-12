"""
定位绘图组件 - 2D/3D实时定位显示
支持拖动锚点调整位置
"""

import numpy as np
import math
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QSlider, QFileDialog, QCheckBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Circle, Arc
import matplotlib.pyplot as plt

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


class PositionPlot(QWidget):
    """定位绘图组件"""

    # 信号定义 - 锚点拖动
    anchor_dragged = pyqtSignal(int, float, float)  # (anchor_index, x, y)
    true_position_dragged = pyqtSignal(float, float, float)  # (x, y, z)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ui_scale = max(1.0, min(1.8, float(self.logicalDpiX()) / 96.0))

        # 默认锚点
        self.anchors_2d = [[0, 0], [50, 0], [50, 50], [0, 50]]
        self.anchors_3d = [[0, 0, 0], [50, 0, 0], [50, 50, 4], [0, 50, 3]]

        # 拖动状态
        self.dragging_anchor = None
        self.dragging_true_position = False
        self.panning_2d = False
        self.drag_zooming = False
        self.pan_last_data = None
        self.zoom_last_y = None
        self.zoom_target_axes = None
        self.drag_radius = 15  # 拖动检测半径（像素）
        self.true_drag_radius = 14

        # 模式与真值位置
        self.current_mode = "serial"
        self.true_position = [25.0, 25.0, 1.5]

        # 背景图与地图绘制状态
        self.background_image = None
        self.background_image_artist = None
        self.background_opacity = 0.35
        self.draw_mode = "none"  # none / line / circle / arc
        self.draw_points = []
        self.map_artists = []
        self.map_labels = []

        # 显示配置
        self.show_2d = True
        self.show_3d = True
        self.show_trajectory = True
        self.show_true_pos = True

        # 轨迹缓冲
        self.history_len = 200
        self.smooth_alpha = 0.22
        self.traj_2d_x, self.traj_2d_y = [], []
        self.traj_3d_x, self.traj_3d_y, self.traj_3d_z = [], [], []
        self.kf_traj_2d_x, self.kf_traj_2d_y = [], []
        self.kf_traj_3d_x, self.kf_traj_3d_y, self.kf_traj_3d_z = [], [], []
        self.client_colors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
        ]
        self.client_color_map = {}
        self.client_artists = {}
        self._last_selected_key = None

        self._init_ui()
        self._init_plot_elements()

    def _build_smoothed_path_2d(self, xs, ys):
        xs = list(xs or [])
        ys = list(ys or [])
        n = min(len(xs), len(ys))
        if n <= 2:
            return xs[:n], ys[:n]
        alpha = float(min(max(self.smooth_alpha, 0.01), 0.95))
        smooth_x = [float(xs[0])]
        smooth_y = [float(ys[0])]
        for idx in range(1, n):
            smooth_x.append((1.0 - alpha) * smooth_x[-1] + alpha * float(xs[idx]))
            smooth_y.append((1.0 - alpha) * smooth_y[-1] + alpha * float(ys[idx]))
        return smooth_x, smooth_y

    def _build_smoothed_path_3d(self, xs, ys, zs):
        xs = list(xs or [])
        ys = list(ys or [])
        zs = list(zs or [])
        n = min(len(xs), len(ys), len(zs))
        if n <= 2:
            return xs[:n], ys[:n], zs[:n]
        smooth_x, smooth_y = self._build_smoothed_path_2d(xs[:n], ys[:n])
        alpha = float(min(max(self.smooth_alpha, 0.01), 0.95))
        smooth_z = [float(zs[0])]
        for idx in range(1, n):
            smooth_z.append((1.0 - alpha) * smooth_z[-1] + alpha * float(zs[idx]))
        return smooth_x, smooth_y, smooth_z

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 顶部工具栏
        toolbar_layout = QHBoxLayout()

        self.btn_import_image = QPushButton("导入场地图")
        self.btn_import_image.clicked.connect(self._import_background_image)
        toolbar_layout.addWidget(self.btn_import_image)

        self.btn_clear_image = QPushButton("清除图片")
        self.btn_clear_image.clicked.connect(self._clear_background_image)
        toolbar_layout.addWidget(self.btn_clear_image)

        lbl_opacity = QLabel("透明度")
        toolbar_layout.addWidget(lbl_opacity)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(10, 80)
        self.slider_opacity.setValue(int(self.background_opacity * 100))
        self.slider_opacity.setFixedWidth(120)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        toolbar_layout.addWidget(self.slider_opacity)

        lbl_mode = QLabel("地图绘制")
        toolbar_layout.addWidget(lbl_mode)

        self.combo_draw_mode = QComboBox()
        self.combo_draw_mode.addItems(["锚点拖动", "画直线", "画圆", "画弧线"])
        self.combo_draw_mode.currentTextChanged.connect(self._on_draw_mode_changed)
        toolbar_layout.addWidget(self.combo_draw_mode)

        self.btn_clear_map = QPushButton("清空地图")
        self.btn_clear_map.clicked.connect(self._clear_map_drawings)
        toolbar_layout.addWidget(self.btn_clear_map)

        self.chk_show_legend_2d = QCheckBox("2D图例")
        self.chk_show_legend_2d.setChecked(True)
        self.chk_show_legend_2d.stateChanged.connect(self._toggle_legend_visibility)
        toolbar_layout.addWidget(self.chk_show_legend_2d)

        self.chk_show_legend_3d = QCheckBox("3D图例")
        self.chk_show_legend_3d.setChecked(True)
        self.chk_show_legend_3d.stateChanged.connect(self._toggle_legend_visibility)
        toolbar_layout.addWidget(self.chk_show_legend_3d)

        toolbar_layout.addStretch()

        self.lbl_draw_hint = QLabel("模式: 锚点拖动")
        self.lbl_draw_hint.setStyleSheet("color: #333333; font-size: 11px;")
        toolbar_layout.addWidget(self.lbl_draw_hint)

        layout.addLayout(toolbar_layout)

        # 创建matplotlib图形
        self.figure = Figure(figsize=(14, 8), facecolor='white')
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        # 使用GridSpec创建子图布局 - 水平排列（左2D右3D）
        gs = GridSpec(1, 2, figure=self.figure, wspace=0.22)

        # 2D子图
        self.ax2d = self.figure.add_subplot(gs[0, 0])
        self.ax2d.set_title("2D Positioning (可拖动锚点)", fontsize=14 * self.ui_scale, fontweight='bold', color='black')
        self.ax2d.set_xlabel("X (m)")
        self.ax2d.set_ylabel("Y (m)")
        self.ax2d.grid(True, linestyle='--', alpha=0.3)
        self.ax2d.set_aspect('equal')

        # 3D子图
        self.ax3d = self.figure.add_subplot(gs[0, 1], projection='3d')
        self.ax3d.set_title("3D Positioning", fontsize=14 * self.ui_scale, fontweight='bold', color='black')
        self.ax3d.set_xlabel("X (m)")
        self.ax3d.set_ylabel("Y (m)")
        self.ax3d.set_zlabel("Z (m)")
        self.ax2d.tick_params(axis='both', labelsize=max(8, int(10 * self.ui_scale)))
        self.ax3d.tick_params(axis='both', labelsize=max(8, int(9 * self.ui_scale)))

        # 不使用tight_layout，因为3D subplot不兼容
        # self.figure.tight_layout()

        # 连接事件
        self.canvas.mpl_connect('button_press_event', self._on_press)
        self.canvas.mpl_connect('button_release_event', self._on_release)
        self.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.canvas.mpl_connect('scroll_event', self._on_scroll)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(1, self.width())
        height = max(1, self.height())
        ratio = width / float(height)
        if ratio < 1.4:
            self.figure.subplots_adjust(left=0.06, right=0.98, bottom=0.08, top=0.95, wspace=0.16)
        else:
            self.figure.subplots_adjust(left=0.05, right=0.98, bottom=0.08, top=0.95, wspace=0.22)
        self.canvas.draw_idle()

    def _init_plot_elements(self):
        """初始化绘图元素"""
        # === 2D绘图元素 ===
        # 锚点 (绿色三角形，可拖动)
        ax, ay = zip(*self.anchors_2d)
        self.scat_anchors_2d = self.ax2d.scatter(ax, ay, c='green', marker='^', s=150,
                                                  label='Anchors (拖动)', zorder=5,
                                                  edgecolors='darkgreen', linewidths=2, picker=True)

        self.scat_kf_2d = self.ax2d.scatter([], [], c='#00d5d5', marker='D', s=120,
                                            label='KF Estimated', zorder=13,
                                            edgecolors='white', linewidths=1.6)

        # 真值位置 (红色圆点)
        self.scat_true_2d = self.ax2d.scatter([], [], c='red', marker='o', s=80,
                                              label='True', zorder=8)

        # 轨迹线
        self.line_traj_2d, = self.ax2d.plot([], [], 'b-', alpha=0.6, linewidth=2)
        self.line_kf_traj_2d, = self.ax2d.plot([], [], color='#00a6a6', linestyle='--', alpha=0.85, linewidth=2)

        # 长度图例（比例尺）
        self.scale_bar_line, = self.ax2d.plot([], [], color='black', linewidth=3, zorder=6)
        self.scale_bar_text = self.ax2d.text(0, 0, "", fontsize=max(9, int(9 * self.ui_scale)), color='black', zorder=6)

        self.legend_2d = self.ax2d.legend(loc='upper right', fontsize=max(9, int(10 * self.ui_scale)))

        # === 3D绘图元素 ===
        ax, ay, az = zip(*self.anchors_3d)
        self.scat_anchors_3d = self.ax3d.scatter(ax, ay, az, c='green', marker='^', s=150,
                                                  label='Anchors', zorder=5, edgecolors='darkgreen')

        self.scat_kf_3d = self.ax3d.scatter([0], [0], [0], c='#00d5d5', marker='D', s=80,
                                            label='KF Estimated', zorder=13,
                                            edgecolors='white')

        # 真值位置
        self.scat_true_3d = self.ax3d.scatter([0], [0], [0], c='red', marker='o', s=80,
                                              label='True', zorder=8)

        # 轨迹线
        self.line_traj_3d, = self.ax3d.plot([], [], [], 'b-', alpha=0.6, linewidth=2)
        self.line_kf_traj_3d, = self.ax3d.plot([], [], [], color='#00a6a6', linestyle='--', alpha=0.85, linewidth=2)

        self.legend_3d = self.ax3d.legend(fontsize=max(9, int(10 * self.ui_scale)))

        # 设置坐标范围
        self._update_axes_limits()
        self._update_scale_bar()

        # 鼠标坐标提示（地图绘制辅助）
        self.cursor_coord_text = self.ax2d.text(0, 0, "", fontsize=max(9, int(9 * self.ui_scale)), color='#222222', zorder=9)
        self.cursor_coord_text.set_visible(False)

    def _zoom_2d(self, factor, center_x=None, center_y=None):
        """2D视图缩放"""
        if factor <= 0:
            return

        x_min, x_max = self.ax2d.get_xlim()
        y_min, y_max = self.ax2d.get_ylim()

        if center_x is None:
            center_x = (x_min + x_max) / 2.0
        if center_y is None:
            center_y = (y_min + y_max) / 2.0

        new_half_w = (x_max - x_min) * factor / 2.0
        new_half_h = (y_max - y_min) * factor / 2.0

        self.ax2d.set_xlim(center_x - new_half_w, center_x + new_half_w)
        self.ax2d.set_ylim(center_y - new_half_h, center_y + new_half_h)
        self._refresh_background_extent()
        self._update_scale_bar()

    def _zoom_3d(self, factor):
        """3D视图缩放（保持中心点）"""
        if factor <= 0:
            return

        x_min, x_max = self.ax3d.get_xlim3d()
        y_min, y_max = self.ax3d.get_ylim3d()
        z_min, z_max = self.ax3d.get_zlim3d()

        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        cz = (z_min + z_max) / 2.0

        half_x = (x_max - x_min) * factor / 2.0
        half_y = (y_max - y_min) * factor / 2.0
        half_z = (z_max - z_min) * factor / 2.0

        self.ax3d.set_xlim3d(cx - half_x, cx + half_x)
        self.ax3d.set_ylim3d(cy - half_y, cy + half_y)
        self.ax3d.set_zlim3d(max(0.0, cz - half_z), cz + half_z)

    def _on_scroll(self, event):
        """鼠标滚轮缩放：2D与3D分别缩放"""
        if event.inaxes not in (self.ax2d, self.ax3d):
            return

        factor = 0.9 if event.button == 'up' else 1.1

        if event.inaxes == self.ax2d:
            cx = float(event.xdata) if event.xdata is not None else None
            cy = float(event.ydata) if event.ydata is not None else None
            self._zoom_2d(factor, cx, cy)
        else:
            self._zoom_3d(factor)

        self.canvas.draw_idle()

    def _update_axes_limits(self):
        """更新坐标轴范围"""
        # 计算锚点边界
        if self.anchors_2d:
            all_x = [a[0] for a in self.anchors_2d]
            all_y = [a[1] for a in self.anchors_2d]
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)

            # 扩展范围
            margin = 10
            self.ax2d.set_xlim(min_x - margin, max_x + margin)
            self.ax2d.set_ylim(min_y - margin, max_y + margin)
            self._refresh_background_extent()
            self._update_scale_bar()

        if self.anchors_3d:
            all_x = [a[0] for a in self.anchors_3d]
            all_y = [a[1] for a in self.anchors_3d]
            all_z = [a[2] for a in self.anchors_3d]
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            min_z, max_z = min(all_z), max(all_z)

            margin = 10
            self.ax3d.set_xlim(min_x - margin, max_x + margin)
            self.ax3d.set_ylim(min_y - margin, max_y + margin)
            self.ax3d.set_zlim(max(0, min_z - margin), max_z + margin + 5)

    def _update_scale_bar(self):
        """更新2D比例尺图例（单位：米）"""
        x_min, x_max = self.ax2d.get_xlim()
        y_min, y_max = self.ax2d.get_ylim()
        span_x = max(1e-6, x_max - x_min)
        span_y = max(1e-6, y_max - y_min)

        # 比例尺长度取视图宽度约1/6，并量化为常见整数米
        raw_len = span_x / 6.0
        candidates = [1, 2, 5, 10, 20, 50, 100]
        scale_len = candidates[-1]
        for val in candidates:
            scale_len = val
            if raw_len <= val:
                break

        x0 = x_min + 0.05 * span_x
        y0 = y_min + 0.08 * span_y
        x1 = x0 + scale_len

        self.scale_bar_line.set_data([x0, x1], [y0, y0])
        self.scale_bar_text.set_position((x0, y0 + 0.03 * span_y))
        self.scale_bar_text.set_text(f"比例尺: {scale_len} m")

    def _toggle_legend_visibility(self, *args):
        """切换图例显示"""
        if self.legend_2d is not None:
            self.legend_2d.set_visible(self.chk_show_legend_2d.isChecked())
        if self.legend_3d is not None:
            self.legend_3d.set_visible(self.chk_show_legend_3d.isChecked())
        self.canvas.draw_idle()

    def _get_client_color(self, client_key):
        client_key = str(client_key or "client")
        color = self.client_color_map.get(client_key)
        if color is None:
            color = self.client_colors[len(self.client_color_map) % len(self.client_colors)]
            self.client_color_map[client_key] = color
        return color

    def _ensure_client_artist(self, client_key, client_label):
        client_key = str(client_key or "client")
        artist = self.client_artists.get(client_key)
        if artist is not None:
            return artist

        color = self._get_client_color(client_key)
        label = str(client_label or client_key)
        scat_2d = self.ax2d.scatter([], [], c=color, marker='o', s=95, label=label, zorder=11,
                                    edgecolors='white', linewidths=1.0)
        traj_2d, = self.ax2d.plot([], [], color=color, alpha=0.7, linewidth=1.8)
        text_2d = self.ax2d.text(0, 0, "", fontsize=max(8, int(9 * self.ui_scale)), color=color, zorder=12)

        scat_3d = self.ax3d.scatter([], [], [], c=color, marker='o', s=80, label=label, zorder=11)
        traj_3d, = self.ax3d.plot([], [], [], color=color, alpha=0.7, linewidth=1.8)

        artist = {
            'label': label,
            'scat_2d': scat_2d,
            'traj_2d': traj_2d,
            'text_2d': text_2d,
            'scat_3d': scat_3d,
            'traj_3d': traj_3d,
            'history_2d': [],
            'history_3d': [],
        }
        self.client_artists[client_key] = artist
        self._rebuild_client_legends()
        return artist

    def _rebuild_client_legends(self):
        self._remove_artist(self.legend_2d)
        self._remove_artist(self.legend_3d)

        self.legend_2d = self.ax2d.legend(loc='upper right', fontsize=max(9, int(10 * self.ui_scale)))
        self.legend_3d = self.ax3d.legend(fontsize=max(9, int(10 * self.ui_scale)))
        self._toggle_legend_visibility()

    def _set_client_visibility(self, client_key, visible):
        artist = self.client_artists.get(str(client_key or "client"))
        if not artist:
            return
        artist['scat_2d'].set_visible(visible)
        artist['traj_2d'].set_visible(visible and self.show_trajectory)
        artist['text_2d'].set_visible(visible)
        artist['scat_3d'].set_visible(visible)
        artist['traj_3d'].set_visible(visible and self.show_trajectory)

    def set_mode(self, mode):
        """设置数据模式"""
        self.current_mode = mode

    def set_true_position(self, x, y, z=0.0):
        """设置真值位置（用于串口模式手动真值或模拟真值轨迹）"""
        self.true_position = [float(x), float(y), float(z)]
        self.scat_true_2d.set_offsets([self.true_position[0], self.true_position[1]])
        self.scat_true_3d._offsets3d = ([self.true_position[0]], [self.true_position[1]], [self.true_position[2]])
        self.canvas.draw_idle()

    def _get_true_position_at_point(self, event):
        """判断鼠标是否点中真值点（2D）"""
        if event.inaxes != self.ax2d:
            return False
        tx, ty = self.true_position[0], self.true_position[1]
        tx_px, ty_px = self.ax2d.transData.transform((tx, ty))
        dist = ((tx_px - event.x) ** 2 + (ty_px - event.y) ** 2) ** 0.5
        return dist < self.true_drag_radius

    def _on_opacity_changed(self, value):
        """背景图透明度调节"""
        self.background_opacity = value / 100.0
        if self.background_image_artist is not None:
            self.background_image_artist.set_alpha(self.background_opacity)
            self.canvas.draw_idle()

    def _on_draw_mode_changed(self, mode_text):
        """切换绘图模式"""
        mode_map = {
            "锚点拖动": "none",
            "画直线": "line",
            "画圆": "circle",
            "画弧线": "arc"
        }
        self.draw_mode = mode_map.get(mode_text, "none")
        self.draw_points = []

        if self.draw_mode == "none":
            self.lbl_draw_hint.setText("模式: 锚点拖动")
            self.canvas.setCursor(Qt.ArrowCursor)
            self.cursor_coord_text.set_visible(False)
        elif self.draw_mode == "line":
            self.lbl_draw_hint.setText("模式: 画直线（点击2点）")
            self.canvas.setCursor(Qt.CrossCursor)
        elif self.draw_mode == "circle":
            self.lbl_draw_hint.setText("模式: 画圆（先圆心后边缘）")
            self.canvas.setCursor(Qt.CrossCursor)
        elif self.draw_mode == "arc":
            self.lbl_draw_hint.setText("模式: 画弧线（起点-中间点-终点）")
            self.canvas.setCursor(Qt.CrossCursor)

    def _import_background_image(self):
        """导入2D背景图（半透明，不阻挡交互）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择场地图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;所有文件 (*.*)"
        )
        if not file_path:
            return

        try:
            self.background_image = plt.imread(file_path)
            self._draw_background_image()
            self.lbl_draw_hint.setText(f"已导入图片: {os.path.basename(file_path)}")
        except Exception as e:
            self.lbl_draw_hint.setText(f"图片导入失败: {e}")

    def _draw_background_image(self):
        """绘制背景图"""
        if self.background_image is None:
            return

        if self.background_image_artist is not None:
            self._remove_artist(self.background_image_artist)

        x_min, x_max = self.ax2d.get_xlim()
        y_min, y_max = self.ax2d.get_ylim()
        self.background_image_artist = self.ax2d.imshow(
            self.background_image,
            extent=[x_min, x_max, y_min, y_max],
            origin='lower',
            alpha=self.background_opacity,
            zorder=0,
            interpolation='bilinear'
        )
        self.canvas.draw_idle()

    def _refresh_background_extent(self):
        """坐标范围变化时同步背景图范围"""
        if self.background_image_artist is None:
            return
        x_min, x_max = self.ax2d.get_xlim()
        y_min, y_max = self.ax2d.get_ylim()
        self.background_image_artist.set_extent([x_min, x_max, y_min, y_max])

    def _clear_background_image(self):
        """清除背景图"""
        self.background_image = None
        if self.background_image_artist is not None:
            self._remove_artist(self.background_image_artist)
            self.background_image_artist = None
            self.canvas.draw_idle()
        self.lbl_draw_hint.setText("背景图已清除")

    def _clear_map_drawings(self):
        """清空地图绘制元素"""
        for artist in self.map_artists:
            self._remove_artist(artist)
        for label in self.map_labels:
            self._remove_artist(label)

        self.map_artists = []
        self.map_labels = []
        self.draw_points = []
        self.lbl_draw_hint.setText("地图元素已清空")
        self.canvas.draw_idle()

    @staticmethod
    def _remove_artist(artist):
        if artist is None:
            return
        try:
            artist.remove()
        except (ValueError, NotImplementedError):
            pass

    def _handle_drawing_click(self, x, y):
        """处理绘图点击"""
        self.draw_points.append((x, y))

        if self.draw_mode == "line" and len(self.draw_points) >= 2:
            p1, p2 = self.draw_points[0], self.draw_points[1]
            self._draw_line_with_length(p1, p2)
            self.draw_points = []
        elif self.draw_mode == "circle" and len(self.draw_points) >= 2:
            center, edge = self.draw_points[0], self.draw_points[1]
            self._draw_circle_with_radius(center, edge)
            self.draw_points = []
        elif self.draw_mode == "arc" and len(self.draw_points) >= 3:
            p1, p2, p3 = self.draw_points[0], self.draw_points[1], self.draw_points[2]
            self._draw_arc_with_length(p1, p2, p3)
            self.draw_points = []

    def _draw_line_with_length(self, p1, p2):
        """绘制直线并标注长度（米）"""
        x1, y1 = p1
        x2, y2 = p2
        line_artist, = self.ax2d.plot([x1, x2], [y1, y2], color='#333333', linewidth=2.0, zorder=2)
        self.map_artists.append(line_artist)

        length = float(np.hypot(x2 - x1, y2 - y1))
        mid_x = (x1 + x2) / 2.0
        mid_y = (y1 + y2) / 2.0
        label = self.ax2d.text(mid_x, mid_y, f"{length:.2f}m", fontsize=9, color='#111111', zorder=3)
        self.map_labels.append(label)
        self.lbl_draw_hint.setText(f"直线长度: {length:.2f}m")
        self.canvas.draw_idle()

    def _draw_circle_with_radius(self, center, edge):
        """绘制圆并标注半径/周长（米）"""
        cx, cy = center
        ex, ey = edge
        radius = float(np.hypot(ex - cx, ey - cy))
        if radius <= 0:
            self.lbl_draw_hint.setText("圆半径无效")
            return

        circle = Circle((cx, cy), radius=radius, fill=False, edgecolor='#4444aa', linewidth=2.0, zorder=2)
        self.ax2d.add_patch(circle)
        self.map_artists.append(circle)

        circumference = 2.0 * math.pi * radius
        label = self.ax2d.text(cx + radius, cy, f"r={radius:.2f}m, C={circumference:.2f}m", fontsize=9,
                               color='#222266', zorder=3)
        self.map_labels.append(label)
        self.lbl_draw_hint.setText(f"圆半径: {radius:.2f}m")
        self.canvas.draw_idle()

    def _circle_from_3_points(self, p1, p2, p3):
        """由三点计算圆心和半径"""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3

        temp = x2 * x2 + y2 * y2
        bc = (x1 * x1 + y1 * y1 - temp) / 2.0
        cd = (temp - x3 * x3 - y3 * y3) / 2.0
        det = (x1 - x2) * (y2 - y3) - (x2 - x3) * (y1 - y2)

        if abs(det) < 1e-8:
            return None

        cx = (bc * (y2 - y3) - cd * (y1 - y2)) / det
        cy = ((x1 - x2) * cd - (x2 - x3) * bc) / det
        r = math.hypot(x1 - cx, y1 - cy)
        return cx, cy, r

    def _normalize_deg(self, angle):
        """角度归一化到[0, 360)"""
        return angle % 360.0

    def _is_between_ccw(self, start, end, test):
        """判断test是否在start到end的逆时针弧段上"""
        start = self._normalize_deg(start)
        end = self._normalize_deg(end)
        test = self._normalize_deg(test)
        span = (end - start) % 360.0
        offset = (test - start) % 360.0
        return offset <= span

    def _draw_arc_with_length(self, p1, p2, p3):
        """绘制弧线并标注弧长（米）"""
        circle_params = self._circle_from_3_points(p1, p2, p3)
        if circle_params is None:
            self.lbl_draw_hint.setText("弧线绘制失败：三点近似共线")
            return

        cx, cy, r = circle_params
        if r <= 0:
            self.lbl_draw_hint.setText("弧线半径无效")
            return

        a1 = self._normalize_deg(math.degrees(math.atan2(p1[1] - cy, p1[0] - cx)))
        am = self._normalize_deg(math.degrees(math.atan2(p2[1] - cy, p2[0] - cx)))
        a2 = self._normalize_deg(math.degrees(math.atan2(p3[1] - cy, p3[0] - cx)))

        # 选择经过中间点的弧
        if self._is_between_ccw(a1, a2, am):
            start_deg, end_deg = a1, a2
        else:
            start_deg, end_deg = a2, a1

        arc_patch = Arc(
            (cx, cy),
            2.0 * r,
            2.0 * r,
            angle=0,
            theta1=start_deg,
            theta2=end_deg,
            edgecolor='#aa4422',
            linewidth=2.0,
            zorder=2
        )
        self.ax2d.add_patch(arc_patch)
        self.map_artists.append(arc_patch)

        sweep_deg = (end_deg - start_deg) % 360.0
        arc_length = r * math.radians(sweep_deg)
        mid_deg = self._normalize_deg(start_deg + sweep_deg / 2.0)
        label_x = cx + r * math.cos(math.radians(mid_deg))
        label_y = cy + r * math.sin(math.radians(mid_deg))
        label = self.ax2d.text(label_x, label_y, f"L={arc_length:.2f}m", fontsize=9, color='#aa4422', zorder=3)
        self.map_labels.append(label)
        self.lbl_draw_hint.setText(f"弧长: {arc_length:.2f}m")
        self.canvas.draw_idle()

    def _get_anchor_at_point(self, event):
        """获取鼠标位置的锚点索引"""
        if event.inaxes != self.ax2d:
            return None

        # 计算每个锚点的距离
        for i, (ax, ay) in enumerate(self.anchors_2d):
            # 转换到像素坐标
            ax_px, ay_px = self.ax2d.transData.transform((ax, ay))
            x_px, y_px = event.x, event.y

            # 计算像素距离
            dist = ((ax_px - x_px) ** 2 + (ay_px - y_px) ** 2) ** 0.5
            if dist < self.drag_radius:
                return i

        return None

    def _on_press(self, event):
        """鼠标按下事件"""
        if event.inaxes not in (self.ax2d, self.ax3d):
            return

        # 中键拖拽平移（2D）
        if event.button == 2 and event.inaxes == self.ax2d and event.xdata is not None and event.ydata is not None:
            self.panning_2d = True
            self.pan_last_data = (float(event.xdata), float(event.ydata))
            self.canvas.setCursor(Qt.SizeAllCursor)
            return

        # 右键拖拽缩放（2D/3D）
        if event.button == 3:
            self.drag_zooming = True
            self.zoom_last_y = event.y
            self.zoom_target_axes = event.inaxes
            self.canvas.setCursor(Qt.SizeVerCursor)
            return

        if event.button != 1:
            return

        if event.inaxes != self.ax2d or event.xdata is None or event.ydata is None:
            return

        # 绘图模式下优先处理地图绘制
        if self.draw_mode != "none":
            self._handle_drawing_click(float(event.xdata), float(event.ydata))
            return

        # 串口模式允许拖动真值点
        if self.current_mode == "serial" and self._get_true_position_at_point(event):
            self.dragging_true_position = True
            self.canvas.setCursor(Qt.ClosedHandCursor)
            return

        anchor_idx = self._get_anchor_at_point(event)
        if anchor_idx is not None:
            self.dragging_anchor = anchor_idx
            self.canvas.setCursor(Qt.ClosedHandCursor)

    def _on_release(self, event):
        """鼠标释放事件"""
        if self.dragging_true_position:
            self.canvas.setCursor(Qt.ArrowCursor if self.draw_mode == "none" else Qt.CrossCursor)
            self.dragging_true_position = False

        if self.dragging_anchor is not None:
            self.canvas.setCursor(Qt.ArrowCursor if self.draw_mode == "none" else Qt.CrossCursor)
            self.dragging_anchor = None

        if self.panning_2d:
            self.panning_2d = False
            self.pan_last_data = None
            self.canvas.setCursor(Qt.ArrowCursor if self.draw_mode == "none" else Qt.CrossCursor)

        if self.drag_zooming:
            self.drag_zooming = False
            self.zoom_last_y = None
            self.zoom_target_axes = None
            self.canvas.setCursor(Qt.ArrowCursor if self.draw_mode == "none" else Qt.CrossCursor)

    def _on_motion(self, event):
        """鼠标移动事件"""
        if self.panning_2d and event.inaxes == self.ax2d and event.xdata is not None and event.ydata is not None:
            cur_x, cur_y = float(event.xdata), float(event.ydata)
            if self.pan_last_data is not None:
                last_x, last_y = self.pan_last_data
                dx = cur_x - last_x
                dy = cur_y - last_y

                x_min, x_max = self.ax2d.get_xlim()
                y_min, y_max = self.ax2d.get_ylim()
                self.ax2d.set_xlim(x_min - dx, x_max - dx)
                self.ax2d.set_ylim(y_min - dy, y_max - dy)
                self.pan_last_data = (cur_x, cur_y)
                self._refresh_background_extent()
                self._update_scale_bar()
                self.canvas.draw_idle()
            return

        if self.drag_zooming and self.zoom_last_y is not None:
            dy_px = event.y - self.zoom_last_y
            if abs(dy_px) >= 2:
                factor = 1.0 + (dy_px * 0.01)
                factor = min(max(factor, 0.85), 1.15)
                target_axes = self.zoom_target_axes

                if target_axes == self.ax2d:
                    cx = float(event.xdata) if event.xdata is not None else None
                    cy = float(event.ydata) if event.ydata is not None else None
                    self._zoom_2d(factor, cx, cy)
                elif target_axes == self.ax3d:
                    self._zoom_3d(factor)

                self.zoom_last_y = event.y
                self.canvas.draw_idle()
            return

        if event.inaxes == self.ax2d and event.xdata is not None and event.ydata is not None:
            if self.draw_mode != "none":
                self.cursor_coord_text.set_visible(True)
                self.cursor_coord_text.set_position((float(event.xdata) + 0.8, float(event.ydata) + 0.8))
                self.cursor_coord_text.set_text(f"({event.xdata:.2f}, {event.ydata:.2f})")
                self.canvas.draw_idle()
            else:
                if self.cursor_coord_text.get_visible():
                    self.cursor_coord_text.set_visible(False)
                    self.canvas.draw_idle()

        if self.dragging_true_position and event.inaxes == self.ax2d and event.xdata is not None and event.ydata is not None:
            x, y = float(event.xdata), float(event.ydata)
            self.true_position[0] = x
            self.true_position[1] = y
            self.scat_true_2d.set_offsets([x, y])
            self.scat_true_3d._offsets3d = ([x], [y], [self.true_position[2]])
            self.canvas.draw_idle()
            self.true_position_dragged.emit(x, y, self.true_position[2])
            return

        if self.dragging_anchor is None or event.inaxes != self.ax2d:
            return

        x, y = event.xdata, event.ydata

        # 更新锚点位置
        self.anchors_2d[self.dragging_anchor] = [x, y]
        self.anchors_3d[self.dragging_anchor][:2] = [x, y]  # 保持Z不变

        # 更新2D锚点显示
        ax, ay = zip(*self.anchors_2d)
        self.scat_anchors_2d.set_offsets(np.column_stack([ax, ay]))

        # 更新3D锚点显示
        ax3, ay3, az3 = zip(*self.anchors_3d)
        self.scat_anchors_3d._offsets3d = (ax3, ay3, az3)

        # 更新坐标范围（可选）
        # self._update_axes_limits()

        # 刷新画布
        self.canvas.draw_idle()

        # 发送信号
        self.anchor_dragged.emit(self.dragging_anchor, x, y)

    def update_anchors(self, anchors_2d=None, anchors_3d=None):
        """更新锚点配置"""
        if anchors_2d:
            self.anchors_2d = anchors_2d
            ax, ay = zip(*self.anchors_2d)
            self.scat_anchors_2d.set_offsets(np.column_stack([ax, ay]))

        if anchors_3d:
            self.anchors_3d = anchors_3d
            ax, ay, az = zip(*self.anchors_3d)
            self.scat_anchors_3d._offsets3d = (ax, ay, az)

        self._update_axes_limits()
        self.canvas.draw()
        self._toggle_legend_visibility()

    def update_plot(self, data):
        """更新绘图"""
        if not data:
            return

        position = data.get('position')
        kf_position = data.get('kf_position')
        true_pos = data.get('true_position')
        client_positions = data.get('client_positions') or {}
        if client_positions:
            selected_item = next((item for item in client_positions.values() if item.get('is_selected')), None)
            if selected_item is not None:
                position = selected_item.get('position')
                kf_position = selected_item.get('kf_position')
            else:
                position = data.get('position')
                kf_position = data.get('kf_position')
            selected_key = selected_item.get('client_key') if selected_item else None
            if selected_key != self._last_selected_key:
                self._last_selected_key = selected_key
                self.traj_2d_x, self.traj_2d_y = [], []
                self.traj_3d_x, self.traj_3d_y, self.traj_3d_z = [], [], []
                self.kf_traj_2d_x, self.kf_traj_2d_y = [], []
                self.kf_traj_3d_x, self.kf_traj_3d_y, self.kf_traj_3d_z = [], [], []
                self.line_traj_2d.set_data([], [])
                self.line_traj_3d.set_data([], [])
                self.line_traj_3d.set_3d_properties([])
                self.line_kf_traj_2d.set_data([], [])
                self.line_kf_traj_3d.set_data([], [])
                self.line_kf_traj_3d.set_3d_properties([])

        # === 更新2D图 ===
        if self.show_2d and position:
            x, y = position[0], position[1]

            # 更新轨迹
            if self.show_trajectory:
                self.traj_2d_x.append(x)
                self.traj_2d_y.append(y)
                if len(self.traj_2d_x) > self.history_len:
                    self.traj_2d_x.pop(0)
                    self.traj_2d_y.pop(0)
                smooth_x, smooth_y = self._build_smoothed_path_2d(self.traj_2d_x, self.traj_2d_y)
                self.line_traj_2d.set_data(smooth_x, smooth_y)

            # 更新真值
            if self.show_true_pos and true_pos and len(true_pos) >= 2:
                self.true_position[0], self.true_position[1] = float(true_pos[0]), float(true_pos[1])
                self.scat_true_2d.set_offsets([true_pos[0], true_pos[1]])

        if self.show_2d and kf_position:
            self.scat_kf_2d.set_offsets([kf_position[0], kf_position[1]])
            if self.show_trajectory:
                self.kf_traj_2d_x.append(kf_position[0])
                self.kf_traj_2d_y.append(kf_position[1])
                if len(self.kf_traj_2d_x) > self.history_len:
                    self.kf_traj_2d_x.pop(0)
                    self.kf_traj_2d_y.pop(0)
                smooth_x, smooth_y = self._build_smoothed_path_2d(self.kf_traj_2d_x, self.kf_traj_2d_y)
                self.line_kf_traj_2d.set_data(smooth_x, smooth_y)
        else:
            self.scat_kf_2d.set_offsets(np.zeros((0, 2)))
            self.line_kf_traj_2d.set_data([], [])

        # === 更新3D图 ===
        if self.show_3d and position and len(position) >= 3:
            x, y, z = position[0], position[1], position[2]

            # 更新轨迹
            if self.show_trajectory:
                self.traj_3d_x.append(x)
                self.traj_3d_y.append(y)
                self.traj_3d_z.append(z)
                if len(self.traj_3d_x) > self.history_len:
                    self.traj_3d_x.pop(0)
                    self.traj_3d_y.pop(0)
                    self.traj_3d_z.pop(0)
                smooth_x, smooth_y, smooth_z = self._build_smoothed_path_3d(self.traj_3d_x, self.traj_3d_y, self.traj_3d_z)
                self.line_traj_3d.set_data(smooth_x, smooth_y)
                self.line_traj_3d.set_3d_properties(smooth_z)

            # 更新真值
            if self.show_true_pos and true_pos and len(true_pos) >= 3:
                self.true_position[2] = float(true_pos[2])
                self.scat_true_3d._offsets3d = ([true_pos[0]], [true_pos[1]], [true_pos[2]])

        if self.show_3d and kf_position and len(kf_position) >= 3:
            self.scat_kf_3d._offsets3d = ([kf_position[0]], [kf_position[1]], [kf_position[2]])
            if self.show_trajectory:
                self.kf_traj_3d_x.append(kf_position[0])
                self.kf_traj_3d_y.append(kf_position[1])
                self.kf_traj_3d_z.append(kf_position[2])
                if len(self.kf_traj_3d_x) > self.history_len:
                    self.kf_traj_3d_x.pop(0)
                    self.kf_traj_3d_y.pop(0)
                    self.kf_traj_3d_z.pop(0)
                smooth_x, smooth_y, smooth_z = self._build_smoothed_path_3d(self.kf_traj_3d_x, self.kf_traj_3d_y, self.kf_traj_3d_z)
                self.line_kf_traj_3d.set_data(smooth_x, smooth_y)
                self.line_kf_traj_3d.set_3d_properties(smooth_z)
        else:
            self.scat_kf_3d._offsets3d = ([], [], [])
            self.line_kf_traj_3d.set_data([], [])
            self.line_kf_traj_3d.set_3d_properties([])

        # 刷新画布
        active_keys = set()
        for client_key, item in client_positions.items():
            pos = item.get('position')
            if not pos or len(pos) < 2:
                continue
            artist = self._ensure_client_artist(client_key, item.get('client_label'))
            active_keys.add(client_key)

            x = float(pos[0])
            y = float(pos[1])
            z = float(pos[2]) if len(pos) >= 3 else 0.0
            artist['scat_2d'].set_offsets([x, y])
            artist['text_2d'].set_position((x + 0.4, y + 0.4))
            artist['text_2d'].set_text(str(item.get('client_label') or client_key))

            hist2 = artist['history_2d']
            hist2.append((x, y))
            if len(hist2) > self.history_len:
                del hist2[0]
            if self.show_trajectory:
                smooth_x, smooth_y = self._build_smoothed_path_2d([p[0] for p in hist2], [p[1] for p in hist2])
                artist['traj_2d'].set_data(smooth_x, smooth_y)
            else:
                artist['traj_2d'].set_data([], [])

            artist['scat_3d']._offsets3d = ([x], [y], [z])
            hist3 = artist['history_3d']
            hist3.append((x, y, z))
            if len(hist3) > self.history_len:
                del hist3[0]
            if self.show_trajectory:
                smooth_x, smooth_y, smooth_z = self._build_smoothed_path_3d(
                    [p[0] for p in hist3],
                    [p[1] for p in hist3],
                    [p[2] for p in hist3],
                )
                artist['traj_3d'].set_data(smooth_x, smooth_y)
                artist['traj_3d'].set_3d_properties(smooth_z)
            else:
                artist['traj_3d'].set_data([], [])
                artist['traj_3d'].set_3d_properties([])

            self._set_client_visibility(client_key, True)

        for client_key in list(self.client_artists.keys()):
            if client_key not in active_keys:
                self._set_client_visibility(client_key, False)
                artist = self.client_artists[client_key]
                artist['traj_2d'].set_data([], [])
                artist['traj_3d'].set_data([], [])
                artist['traj_3d'].set_3d_properties([])
                artist['text_2d'].set_text("")

        # 鍒锋柊鐢诲竷
        self.canvas.draw_idle()

    def clear_plots(self):
        """清除绘图"""
        self.traj_2d_x, self.traj_2d_y = [], []
        self.traj_3d_x, self.traj_3d_y, self.traj_3d_z = [], [], []
        self.kf_traj_2d_x, self.kf_traj_2d_y = [], []
        self.kf_traj_3d_x, self.kf_traj_3d_y, self.kf_traj_3d_z = [], [], []

        self.scat_kf_2d.set_offsets(np.zeros((0, 2)))
        self.scat_true_2d.set_offsets(np.zeros((0, 2)))
        self.line_traj_2d.set_data([], [])
        self.line_kf_traj_2d.set_data([], [])

        self.scat_kf_3d._offsets3d = ([], [], [])
        self.scat_true_3d._offsets3d = ([], [], [])
        self.line_traj_3d.set_data([], [])
        self.line_traj_3d.set_3d_properties([])
        self.line_kf_traj_3d.set_data([], [])
        self.line_kf_traj_3d.set_3d_properties([])
        for artist in self.client_artists.values():
            artist['history_2d'].clear()
            artist['history_3d'].clear()
            artist['scat_2d'].set_offsets(np.zeros((0, 2)))
            artist['traj_2d'].set_data([], [])
            artist['text_2d'].set_text("")
            artist['scat_3d']._offsets3d = ([], [], [])
            artist['traj_3d'].set_data([], [])
            artist['traj_3d'].set_3d_properties([])
        self.cursor_coord_text.set_visible(False)

        self.canvas.draw()

        # 保留背景图与地图绘制
        self._refresh_background_extent()

