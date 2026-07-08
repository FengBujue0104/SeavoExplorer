import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def pause_before_exit():
    try:
        if sys.stdin.isatty():
            input("\n按回车键退出...")
    except EOFError:
        pass


def run_step(cmd, error_message):
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print()
        print("========================================")
        print(f" {error_message}")
        print("========================================")
        pause_before_exit()
        sys.exit(result.returncode)


print("========================================")
print(" SeavoExplorer 单目录打包")
print("========================================")
print()

run_step(
    [sys.executable, "-m", "pip", "install", "pyinstaller", "PyQt5", "PyPDF2", "openpyxl", "python-docx", "xlrd", "olefile", "Pillow", "opencv-python", "numpy"],
    "依赖安装失败，请检查错误信息",
)

print()
print("生成多尺寸图标...")
run_step([sys.executable, "make_ico.py"], "图标生成失败，请检查错误信息")

print()
print("开始打包...")
print()

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onedir", "--windowed",
    "--name", "SeavoExplorer",
    "--icon=favicon.ico",
    "--noconfirm", "--clean",
    "--add-data=favicon.ico;.",
    "--add-data=favicon_src.png;.",
    "--hidden-import=PyQt5.QtWidgets",
    "--hidden-import=PyQt5.QtCore",
    "--hidden-import=PyQt5.QtGui",
    "--hidden-import=PyQt5.QtSvg",
    "--hidden-import=PyPDF2",
    "--hidden-import=openpyxl",
    "--hidden-import=docx",
    "--hidden-import=xlrd",
    "--hidden-import=olefile",
    "--hidden-import=cv2",
    "--hidden-import=numpy",
    "--hidden-import=PIL",
    "--exclude-module=rarfile",
    "--exclude-module=py7zr",
    "--exclude-module=PyQt5.QtWebEngine",
    "--exclude-module=PyQt5.QtWebEngineWidgets",
    "--exclude-module=PyQt5.QtMultimedia",
    "--exclude-module=PyQt5.QtMultimediaWidgets",
    "--exclude-module=PyQt5.QtSql",
    "--exclude-module=PyQt5.QtBluetooth",
    "--exclude-module=PyQt5.QtNetwork",
    "--exclude-module=PyQt5.QtXml",
    "--exclude-module=PyQt5.QtTest",
    "--exclude-module=PyQt5.QtDBus",
    "--exclude-module=PyQt5.QtQml",
    "--exclude-module=PyQt5.QtQuick",
    "--exclude-module=PyQt5.QtQuickWidgets",
    "--exclude-module=matplotlib",
    "--exclude-module=scipy",
    "--exclude-module=tornado",
    "--exclude-module=notebook",
    "--exclude-module=IPython",
    "--exclude-module=jupyter",
    "main.py"
]

result = subprocess.run(cmd)

print()
if result.returncode == 0 and os.path.exists("dist/SeavoExplorer/SeavoExplorer.exe"):
    print("========================================")
    print(" 打包成功！")
    print(" 输出目录: dist/SeavoExplorer/")
    print(" 分发时将整个目录打包为zip即可")
    print("========================================")
    pause_before_exit()
    sys.exit(0)

print("========================================")
print(" 打包失败，请检查错误信息")
print("========================================")
pause_before_exit()
sys.exit(result.returncode or 1)
