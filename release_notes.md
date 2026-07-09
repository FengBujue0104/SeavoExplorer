# SeavoExplorer v0.4.2

## 新功能

- **保存版本**：右键文件选择「保存版本」，自动生成 `文件名_YYYYMMDD[后缀].ext` 的日期版本副本
- **归档到 old 文件夹**：右键将选中文件移入同目录下的 `old/` 子文件夹（自动创建），支持多选批量归档
- **显示隐藏文件**：菜单「设置」新增「显示隐藏文件」开关，勾选后显示以 `.` 开头的文件和系统隐藏属性的文件

## 修复

- 修复 zip 解压大文件 OOM 问题（改用分块读写）
- 修复图片预览大文件 OOM 问题（超 4096px 先缩放）
- 修复 F5 刷新文件树不更新问题
- 修复右键重命名失效问题
- 修复保存版本时无扩展名文件覆盖问题
- 修复 VideoCapture 泄漏问题
- 修复线程旧实例泄漏问题
- 修复 JSON 配置损坏回退问题

## 文档

- 新增 README.md（Markdown 格式）
- 新增 OHMYPI.md（项目指南）
- 更新所有版本号到 0.4.2
- 更新 GitHub 用户名（隐私保护）

## 下载

- `SeavoExplorer.exe` — 单文件可执行程序（约 93MB），无需安装 Python
- 支持 Python 3.8+
- 依赖：PyQt5、PyPDF2、openpyxl、xlrd、python-docx、olefile、opencv-python、numpy、Pillow、PyInstaller
