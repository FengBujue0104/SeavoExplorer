"""构建 SeavoExplorer 单目录 Windows 分发包。"""

import sys

from build_support import build_cli


if __name__ == '__main__':
    sys.exit(build_cli('onedir'))
