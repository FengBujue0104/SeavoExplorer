"""从源图生成多尺寸 favicon.ico（供窗口图标、任务栏、关于页使用）。

源图：与本脚本同目录的 favicon_src.png（256x256 高清源）
回退：与本脚本同目录的 favicon.ico（取最大一帧）
"""
from PIL import Image
import os
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(SCRIPT_DIR, 'favicon.ico')
SRC_PNG = os.path.join(SCRIPT_DIR, 'favicon_src.png')

NEEDED_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def load_source():
    """优先用 favicon_src.png，否则回退到现有 ico 中最大的一帧。"""
    if os.path.exists(SRC_PNG):
        return Image.open(SRC_PNG).convert('RGBA')
    if not os.path.exists(ICO_PATH):
        raise FileNotFoundError(f'找不到源图：{SRC_PNG} 或 {ICO_PATH}')
    img = Image.open(ICO_PATH)
    best = img
    try:
        sizes = img.info.get('sizes')
        if sizes:
            largest = max(sizes, key=lambda s: s[0] * s[1])
            img.size = largest
            img.load()
            best = img
    except Exception:
        best = Image.open(ICO_PATH)
    return best.convert('RGBA')


def main():
    src = load_source()

    # 备份一次原 ico（仅在 ico 存在且无备份时）
    ico_backup = ICO_PATH + '.bak'
    if os.path.exists(ICO_PATH) and not os.path.exists(ico_backup):
        shutil.copy2(ICO_PATH, ico_backup)

    # 源图已是 256x256，直接生成多尺寸 ICO
    src.save(ICO_PATH, format='ICO', sizes=NEEDED_SIZES)

    verify = Image.open(ICO_PATH)
    print('OK - favicon.ico sizes:', verify.info.get('sizes', 'N/A'))
    print('OK - favicon_src.png size:', Image.open(SRC_PNG).size)


if __name__ == '__main__':
    main()
