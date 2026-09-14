"""
截图服务
Phase 2修复：
- 添加logger统一日志
- 添加线程锁保护文件读写并发
- save_screenshot()添加异常处理
- 默认目录切换到data/screenshots
- 高亮处理失败时记录日志
"""
import io
import os
import threading
import time
from typing import Optional, Tuple, Dict, Any

from PIL import Image, ImageDraw

from backend.utils.logger import get_logger
from backend.utils.paths import SCREENSHOTS_DIR

logger = get_logger(__name__)


class ScreenshotService:
    """截图处理服务，封装Pillow绘图操作"""

    # 高亮框参数
    HIGHLIGHT_BOX_PADDING = 8       # 高亮框向外扩展像素
    HIGHLIGHT_BOX_WIDTH = 8         # 边框宽度
    HIGHLIGHT_CORNER_LEN = 20       # 角标长度
    HIGHLIGHT_FILL_ALPHA = 80       # 填充透明度 (0-255)
    HIGHLIGHT_COLOR = '#FF0000'     # 高亮颜色（红色）

    def __init__(self, screenshot_dir: Optional[str] = None):
        # Phase 2: 默认使用data/screenshots目录
        self._screenshot_dir = screenshot_dir or str(SCREENSHOTS_DIR)
        os.makedirs(self._screenshot_dir, exist_ok=True)
        self._file_lock = threading.Lock()  # 保护文件读写

    @property
    def screenshot_dir(self) -> str:
        """获取截图目录路径"""
        return self._screenshot_dir

    def get_current_screenshot_path(self) -> str:
        """获取当前截图文件路径"""
        return os.path.join(self._screenshot_dir, 'current.png')

    def screenshot_exists(self) -> bool:
        """检查当前截图是否存在"""
        return os.path.exists(self.get_current_screenshot_path())

    def validate_bounds(self, bounds) -> Tuple[bool, str]:
        """
        校验bounds参数

        Args:
            bounds: [x1, y1, x2, y2]

        Returns:
            (is_valid, error_message)
        """
        if not bounds or len(bounds) != 4:
            return False, 'bounds 参数无效，需要 [x1,y1,x2,y2]'

        try:
            bounds = [int(v) for v in bounds]
        except (ValueError, TypeError):
            return False, 'bounds 值必须为整数'

        x1, y1, x2, y2 = bounds
        if x1 < 0 or y1 < 0 or x2 < 0 or y2 < 0:
            return False, 'bounds 坐标不能为负数'
        if x2 <= x1 or y2 <= y1:
            return False, 'bounds 坐标无效：x2须大于x1，y2须大于y1'

        return True, ''

    def highlight_element(self, bounds) -> Tuple[bool, Any, str]:
        """
        在截图上为指定元素绘制红色高亮框

        Args:
            bounds: [x1, y1, x2, y2]

        Returns:
            (success, image_bytes_io_or_None, error_message)
        """
        valid, msg = self.validate_bounds(bounds)
        if not valid:
            return False, None, msg

        x1, y1, x2, y2 = [int(v) for v in bounds]

        path = self.get_current_screenshot_path()
        if not os.path.exists(path):
            return False, None, '截图不存在，请先刷新截图'

        with self._file_lock:
            try:
                img = Image.open(path).convert('RGB')
                draw = ImageDraw.Draw(img)

                pad = self.HIGHLIGHT_BOX_PADDING
                w = self.HIGHLIGHT_BOX_WIDTH
                cl = self.HIGHLIGHT_CORNER_LEN
                color = self.HIGHLIGHT_COLOR

                # 绘制红色高亮框
                draw.rectangle(
                    [x1 - pad, y1 - pad, x2 + pad, y2 + pad],
                    outline=color, width=w
                )

                # 四角加粗标记（L形角标）
                # 左上
                draw.line([(x1 - pad, y1 - pad), (x1 - pad + cl, y1 - pad)], fill=color, width=w)
                draw.line([(x1 - pad, y1 - pad), (x1 - pad, y1 - pad + cl)], fill=color, width=w)
                # 右上
                draw.line([(x2 + pad, y1 - pad), (x2 + pad - cl, y1 - pad)], fill=color, width=w)
                draw.line([(x2 + pad, y1 - pad), (x2 + pad, y1 - pad + cl)], fill=color, width=w)
                # 左下
                draw.line([(x1 - pad, y2 + pad), (x1 - pad + cl, y2 + pad)], fill=color, width=w)
                draw.line([(x1 - pad, y2 + pad), (x1 - pad, y2 + pad - cl)], fill=color, width=w)
                # 右下
                draw.line([(x2 + pad, y2 + pad), (x2 + pad - cl, y2 + pad)], fill=color, width=w)
                draw.line([(x2 + pad, y2 + pad), (x2 + pad, y2 + pad - cl)], fill=color, width=w)

                # 半透明红色填充
                overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                overlay_draw.rectangle([x1, y1, x2, y2], fill=(255, 0, 0, self.HIGHLIGHT_FILL_ALPHA))
                img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

                buf = io.BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                logger.debug(f'[ScreenshotService] 高亮处理完成: bounds={bounds}')
                return True, buf, ''

            except Exception as e:
                logger.error(f'[ScreenshotService] 高亮处理失败: {e}', exc_info=True)
                return False, None, f'高亮处理失败: {str(e)}'

    def save_screenshot(self, image_data: bytes, filename: str = 'current.png') -> Dict[str, Any]:
        """
        保存截图数据到文件（原子写入：临时文件 + os.replace，避免读者拿到半张图）

        Returns:
            {'success': bool, 'filepath': str, 'message': str}
        """
        filepath = os.path.join(self._screenshot_dir, filename)
        tmp_path = filepath + '.tmp'
        with self._file_lock:
            try:
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(tmp_path, 'wb') as f:
                    f.write(image_data)
                # Windows 下目标文件被读取占用时 os.replace 可能抛 PermissionError，重试几次
                last_err = None
                for _ in range(5):
                    try:
                        os.replace(tmp_path, filepath)
                        last_err = None
                        break
                    except PermissionError as e:
                        last_err = e
                        time.sleep(0.05)
                if last_err:
                    raise last_err
                logger.debug(f'[ScreenshotService] 截图已保存: {filepath} ({len(image_data)} bytes)')
                return {'success': True, 'filepath': filepath, 'message': '截图保存成功'}
            except Exception as e:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
                logger.error(f'[ScreenshotService] 保存截图失败: {e}', exc_info=True)
                return {'success': False, 'filepath': filepath, 'message': f'保存截图失败: {str(e)}'}


# 全局单例
screenshot_service = ScreenshotService()
