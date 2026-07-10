"""从源图显式重建多尺寸 favicon.ico。

构建流程只校验并使用仓库中的图标，不会自动运行本脚本。维护者需要更新图标时，优先
使用 favicon_src.png；源 PNG 不存在时，可从现有 ICO 的最大帧重新生成。
"""

import argparse
import os
import shutil
import tempfile

from PIL import Image


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(SCRIPT_DIR, 'favicon.ico')
SRC_PNG = os.path.join(SCRIPT_DIR, 'favicon_src.png')
NEEDED_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def load_source():
    """返回独立的 RGBA 图像、来源路径和原始尺寸。"""
    if os.path.isfile(SRC_PNG):
        with Image.open(SRC_PNG) as image:
            return image.convert('RGBA').copy(), SRC_PNG, image.size
    if not os.path.isfile(ICO_PATH):
        raise FileNotFoundError('找不到图标源：{} 或 {}'.format(SRC_PNG, ICO_PATH))

    with Image.open(ICO_PATH) as image:
        sizes = image.info.get('sizes') or {image.size}
        largest = max(sizes, key=lambda size: size[0] * size[1])
        if image.size != largest:
            image.size = largest
        image.load()
        return image.convert('RGBA').copy(), ICO_PATH, largest


def rebuild_icon(backup=False):
    source, source_path, source_size = load_source()
    if source.width != source.height:
        raise ValueError('图标源必须是正方形，当前为 {}x{}'.format(*source.size))

    descriptor, temporary_path = tempfile.mkstemp(
        prefix='.favicon-',
        suffix='.ico',
        dir=SCRIPT_DIR,
    )
    os.close(descriptor)
    try:
        source.save(temporary_path, format='ICO', sizes=NEEDED_SIZES)
        with Image.open(temporary_path) as generated:
            generated_sizes = set(generated.info.get('sizes') or {generated.size})
        missing = set(NEEDED_SIZES) - generated_sizes
        if missing:
            raise ValueError('生成的 ICO 缺少尺寸：{}'.format(sorted(missing)))

        if backup and os.path.isfile(ICO_PATH):
            shutil.copy2(ICO_PATH, ICO_PATH + '.bak')
        os.replace(temporary_path, ICO_PATH)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)

    print('来源：{}（{}x{}）'.format(os.path.basename(source_path), *source_size))
    print('输出：{}'.format(ICO_PATH))
    print('尺寸：{}'.format(sorted(generated_sizes)))


def main():
    parser = argparse.ArgumentParser(description='重建 SeavoExplorer 多尺寸 ICO')
    parser.add_argument(
        '--backup',
        action='store_true',
        help='覆盖前另存 favicon.ico.bak；默认依靠 Git 管理历史',
    )
    args = parser.parse_args()
    rebuild_icon(backup=args.backup)


if __name__ == '__main__':
    main()
