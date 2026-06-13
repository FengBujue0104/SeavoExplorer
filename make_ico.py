"""从源图生成多尺寸 favicon.ico（供窗口图标、任务栏、关于页使用）。

源图查找顺序：
  1. 与本脚本同目录的 favicon_src.png（如存在，优先；建议放 256x256 高清图）
  2. 与本脚本同目录的 favicon.ico
脚本始终就地更新本仓库的 favicon.ico，不依赖任何外部路径。
"""
from PIL import Image
import os
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(SCRIPT_DIR, 'favicon.ico')
SRC_PNG = os.path.join(SCRIPT_DIR, 'favicon_src.png')

NEEDED_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def load_source():
    """优先用高清 PNG 源，否则回退到现有 ico 中最大的一帧。"""
    if os.path.exists(SRC_PNG):
        return Image.open(SRC_PNG).convert('RGBA')
    if not os.path.exists(ICO_PATH):
        raise FileNotFoundError(f'找不到源图：{SRC_PNG} 或 {ICO_PATH}')
    img = Image.open(ICO_PATH)
    # ico 可能内嵌多帧，挑面积最大的一帧作为源
    best = img
    try:
        sizes = img.info.get('sizes')
        if sizes:
            largest = max(sizes, key=lambda s: s[0] * s[1])
            img.size = largest  # 让 Pillow 解码该尺寸帧
            img.load()
            best = img
    except Exception:
        best = Image.open(ICO_PATH)
    return best.convert('RGBA')


def main():
    src = load_source()

    # 备份一次原 ico
    backup = ICO_PATH + '.bak'
    if os.path.exists(ICO_PATH) and not os.path.exists(backup):
        shutil.copy2(ICO_PATH, backup)

    # 传单张高清源 + sizes，由 Pillow 内部生成所有尺寸帧（可靠写入多帧）
    src.save(ICO_PATH, format='ICO', sizes=NEEDED_SIZES)

    verify = Image.open(ICO_PATH)
    print('OK - favicon.ico sizes:', verify.info.get('sizes', 'N/A'))


if __name__ == '__main__':
    main()
