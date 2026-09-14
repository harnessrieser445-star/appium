#!/usr/bin/env python3
"""
生成模拟手机截图（登录界面）
bounds 与 element_service.py 中的模拟元素对应。
Phase 2: 使用PathManager管理路径，支持自定义输出路径。
"""

import os
import sys
from PIL import Image, ImageDraw, ImageFont

# 支持作为模块导入或独立运行
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.utils.paths import SCREENSHOTS_DIR

# 默认保存路径
DEFAULT_SAVE_PATH = os.path.join(str(SCREENSHOTS_DIR), 'current.png')

# 画布尺寸（模拟手机竖屏）
WIDTH, HEIGHT = 480, 800

# 模拟元素 bounds（与 element_service.py 一致）
ELEMENTS = [
    {'text': '欢迎登录', 'bounds': [120, 200, 360, 260], 'type': 'text'},
    {'text': '请输入用户名', 'bounds': [80, 300, 400, 360], 'type': 'input'},
    {'text': '请输入密码', 'bounds': [80, 380, 400, 440], 'type': 'input'},
    {'text': '登录', 'bounds': [140, 480, 340, 540], 'type': 'button'},
    {'text': '记住我', 'bounds': [80, 560, 240, 600], 'type': 'checkbox'},
]


def get_font(size):
    """尝试加载中文字体，失败则用默认字体"""
    if sys.platform == 'win32':
        font_paths = [
            'C:/Windows/Fonts/msyh.ttc',      # 微软雅黑
            'C:/Windows/Fonts/simhei.ttf',     # 黑体
            'C:/Windows/Fonts/simsun.ttc',     # 宋体
        ]
    else:
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate(save_path: str = None):
    """
    生成模拟截图

    Args:
        save_path: 保存路径，None则使用默认路径(SCREENSHOTS_DIR/current.png)

    Returns:
        保存的文件路径
    """
    if save_path is None:
        save_path = DEFAULT_SAVE_PATH

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    img = Image.new('RGB', (WIDTH, HEIGHT), '#F5F5F5')
    draw = ImageDraw.Draw(img)

    font_title = get_font(28)
    font_normal = get_font(18)
    font_button = get_font(20)

    for elem in ELEMENTS:
        x1, y1, x2, y2 = elem['bounds']
        text = elem['text']
        etype = elem['type']

        if etype == 'text':
            draw.text((x1, y1 + 5), text, fill='#333333', font=font_title)
        elif etype == 'input':
            draw.rectangle([x1, y1, x2, y2], outline='#999999', width=2, fill='#FFFFFF')
            draw.text((x1 + 10, y1 + 12), text, fill='#AAAAAA', font=font_normal)
        elif etype == 'button':
            draw.rounded_rectangle([x1, y1, x2, y2], radius=8, fill='#0e639c')
            bbox = draw.textbbox((0, 0), text, font=font_button)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x1 + (x2 - x1 - tw) // 2, y1 + (y2 - y1 - th) // 2 - 4), text, fill='#FFFFFF', font=font_button)
        elif etype == 'checkbox':
            draw.rectangle([x1, y1, x1 + 24, y1 + 24], outline='#666666', width=2, fill='#FFFFFF')
            draw.text((x1 + 32, y1), text, fill='#333333', font=font_normal)

    img.save(save_path, 'PNG')
    return save_path


if __name__ == '__main__':
    path = generate()
    print(f'模拟截图已生成: {path}')
