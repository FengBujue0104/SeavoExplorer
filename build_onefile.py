"""构建 SeavoExplorer 单文件 Windows EXE。"""

import sys

from build_support import build_cli


if __name__ == '__main__':
    sys.exit(build_cli('onefile'))
