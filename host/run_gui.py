"""
星海无界定位系统可视化软件 - 启动脚本

使用方法:
    python run_gui.py

功能:
    - 实时2D/3D定位显示
    - 串口数据接收
    - 数据统计
    - 锚点配置
"""

import sys
import os

# Allow direct startup from this source directory.
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

if __name__ == '__main__':
    from gui import main
    main()
