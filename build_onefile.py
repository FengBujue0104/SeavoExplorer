import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("========================================")
print(" SeavoExplorer 单文件打包")
print("========================================")
print()

subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller", "PyQt5", "PyPDF2", "openpyxl", "python-docx", "xlrd", "olefile", "Pillow", "opencv-python", "numpy"], capture_output=True)

print()
print("生成多尺寸图标...")
subprocess.run([sys.executable, "make_ico.py"])

print()
print("开始打包...")
print()

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile", "--windowed",
    "--name", "SeavoExplorer",
    "--icon=favicon.ico",
    "--noconfirm", "--clean",
    # 资源：多尺寸图标 + 高清源图（关于页/窗口图标在运行时读取）
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
if os.path.exists("dist/SeavoExplorer.exe"):
    print("========================================")
    print(" 打包成功！")
    print(" 输出文件: dist/SeavoExplorer.exe")
    print("========================================")
else:
    print("========================================")
    print(" 打包失败，请检查错误信息")
    print("========================================")

input("\n按回车键退出...")
