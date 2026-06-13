import sys
import os
import re
import json
import traceback
import ctypes
import shutil
from collections import namedtuple

# 尝试导入OpenCV用于视频缩略图生成
try:
    import cv2
    import numpy as np
    from PIL import Image
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

from PyQt5.QtWidgets import (QApplication, QMainWindow, QTreeView, QTextEdit,
                                QSplitter, QVBoxLayout, QHBoxLayout, QWidget,
                                QLineEdit, QLabel, QPushButton, QFileDialog, QScrollArea,
                                QMessageBox, QTabWidget, QFileSystemModel,
                                QGroupBox, QMenu, QAbstractItemView, QShortcut,
                                QDialog, QGridLayout, QTableWidget, QTableWidgetItem,
                                QHeaderView, QFormLayout,
                                QRadioButton, QButtonGroup, QInputDialog, QSplashScreen,
                                QToolBar, QToolButton, QSizePolicy)
from PyQt5.QtCore import QDir, Qt, QModelIndex, QThread, pyqtSignal, QRect, QUrl, QMimeData, QTimer
from PyQt5.QtGui import QFont, QPixmap, QImage, QIcon, QPainter, QColor, QPen, QKeySequence, QFontDatabase

_SPLASH_PIXMAP = None


def _first_available_font(candidates):
    """返回候选列表中系统已安装的第一个字体名，都没有则返回空串。"""
    try:
        families = set(QFontDatabase().families())
    except Exception:
        return ''
    for name in candidates:
        if name in families:
            return name
    return ''


# UI 字体候选：微软雅黑系列优先，其次思源/苹方，最后通用无衬线
_UI_FONT_CANDIDATES = [
    'Microsoft YaHei UI', 'Microsoft YaHei', '微软雅黑',
    'Source Han Sans SC', 'Noto Sans CJK SC', 'PingFang SC',
    'Segoe UI', 'Arial',
]
# 等宽字体候选：用于代码/文本/压缩包等预览
_MONO_FONT_CANDIDATES = ['Cascadia Mono', 'Consolas', 'Source Code Pro', 'Courier New']


def get_mono_font(size=10):
    """获取用于预览区的等宽字体。"""
    name = _first_available_font(_MONO_FONT_CANDIDATES) or 'Courier New'
    return QFont(name, size)


def apply_app_font(app):
    """为整个应用设置清晰的全局界面字体。"""
    name = _first_available_font(_UI_FONT_CANDIDATES)
    if not name:
        return
    font = QFont(name, 10)
    try:
        font.setStyleStrategy(QFont.PreferAntialias)
    except Exception:
        pass
    app.setFont(font)


def get_splash_pixmap():
    """预渲染启动画面，首次调用后缓存"""
    global _SPLASH_PIXMAP
    if _SPLASH_PIXMAP is not None:
        return _SPLASH_PIXMAP
    splash_pix = QPixmap(400, 300)
    splash_pix.fill(Qt.black)
    brand_color = QColor(233, 74, 22)
    painter = QPainter(splash_pix)
    painter.setFont(QFont("Arial", 36, QFont.Bold))
    painter.setPen(brand_color)
    painter.drawText(QRect(0, 100, 400, 50), Qt.AlignCenter, "SEAVO")
    painter.setPen(QPen(brand_color, 2, Qt.DashLine))
    painter.drawRoundedRect(50, 80, 300, 80, 10, 10)
    painter.end()
    _SPLASH_PIXMAP = splash_pix
    return _SPLASH_PIXMAP

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    import xlrd
except ImportError:
    xlrd = None

try:
    import olefile
except ImportError:
    olefile = None

FolderInfo = namedtuple('FolderInfo', ['sort_key', 'path', 'number', 'comment', 'source'])

class OpenWithDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.result = None
        self.setWindowTitle('打开方式')
        self.setGeometry(300, 300, 400, 150)
        
        layout = QVBoxLayout()
        label = QLabel(f'选择打开文件的方式：\n\n{os.path.basename(self.file_path)}')
        label.setWordWrap(True)
        layout.addWidget(label)
        
        button_layout = QHBoxLayout()
        direct_open_btn = QPushButton('直接打开')
        direct_open_btn.clicked.connect(self.direct_open)
        explorer_btn = QPushButton('在资源管理器中打开')
        explorer_btn.clicked.connect(self.explorer_open)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(direct_open_btn)
        button_layout.addWidget(explorer_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def direct_open(self):
        self.result = 'direct'
        self.accept()
        
    def explorer_open(self):
        self.result = 'explorer'
        self.accept()

class CommentEditDialog(QDialog):
    """注释编辑对话框"""
    def __init__(self, title, current_comment, parent=None):
        super().__init__(parent)
        self.current_comment = current_comment
        self.new_comment = current_comment
        self.setWindowTitle(title)
        self.initUI()
        
    def initUI(self):
        self.setGeometry(300, 300, 400, 150)
        
        layout = QVBoxLayout()
        
        self.comment_edit = QLineEdit(self.current_comment)
        self.comment_edit.setPlaceholderText('请输入注释内容')
        self.comment_edit.setMaxLength(200)  # 限制最大长度
        # 按Enter键保存
        self.comment_edit.returnPressed.connect(self.save)
        
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton('保存')
        save_btn.clicked.connect(self.save)
        
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addWidget(QLabel('注释内容：'))
        layout.addWidget(self.comment_edit)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        # 设置焦点到输入框
        self.comment_edit.setFocus()
        
    def save(self):
        self.new_comment = self.comment_edit.text().strip()
        self.accept()
        
    def get_comment(self):
        return self.new_comment

class RenameDialog(QDialog):
    """重命名对话框，将文件名和扩展名分开编辑"""
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.old_name = os.path.basename(file_path)
        self.is_file = os.path.isfile(file_path)
        
        if self.is_file:
            self.old_base_name, self.old_ext = os.path.splitext(self.old_name)
        else:
            self.old_base_name = self.old_name
            self.old_ext = ''
        
        self.setWindowTitle('重命名')
        self.initUI()
        
    def initUI(self):
        self.setGeometry(300, 300, 400, 150)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel(f'原名称：{self.old_name}'))
        
        self.name_edit = QLineEdit(self.old_base_name)
        self.name_edit.setPlaceholderText('文件名')
        self.name_edit.returnPressed.connect(self.save)
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel('名称：'))
        name_layout.addWidget(self.name_edit)
        
        if self.is_file:
            self.ext_edit = QLineEdit(self.old_ext)
            self.ext_edit.setPlaceholderText('扩展名')
            self.ext_edit.setFixedWidth(80)
            name_layout.addWidget(QLabel('扩展名：'))
            name_layout.addWidget(self.ext_edit)
        else:
            self.ext_edit = None
        
        layout.addLayout(name_layout)
        
        button_layout = QHBoxLayout()
        save_btn = QPushButton('确定')
        save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        
    def save(self):
        new_base = self.name_edit.text().strip()
        if not new_base:
            QMessageBox.warning(self, '警告', '名称不能为空')
            return
        
        if self.ext_edit:
            new_ext = self.ext_edit.text().strip()
            if not new_ext.startswith('.'):
                new_ext = '.' + new_ext if new_ext else ''
            self.new_name = new_base + new_ext
        else:
            self.new_name = new_base
        
        if self.new_name == self.old_name:
            self.reject()
            return
            
        self.accept()
        
    def get_new_name(self):
        return self.new_name

class FolderScanThread(QThread):
    """文件夹扫描线程，用于异步加载项目文件夹"""
    scan_completed = pyqtSignal(list, list)  # 发射(主板文件夹列表, 子卡文件夹列表)
    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(str)  # 发射当前扫描的目录
    
    def __init__(self, settings, include_subfolders, comments, sort_by_number=False):
        super().__init__()
        self.settings = settings
        self.include_subfolders = include_subfolders
        self.comments = comments
        self.sort_by_number = sort_by_number
        self.pattern = r'^([SM])(\d{3,4})(?:_(.*))?$'

    def _scan_directory(self, directory, dir_name, motherboard_folders, daughterboard_folders):
        """扫描单个目录，收集匹配的项目文件夹"""
        if not os.path.exists(directory):
            return
        try:
            items = os.listdir(directory)
            for item in items:
                item_path = os.path.join(directory, item)
                if os.path.isdir(item_path):
                    match = re.match(self.pattern, item)
                    if match:
                        prefix = match.group(1)
                        number = match.group(2)
                        folder_comment = match.group(3) if match.group(3) else ''
                        internal_comment = self.comments.get(item_path, folder_comment)
                        if prefix == 'S':
                            motherboard_folders.append((int(number), item_path, number, internal_comment, dir_name))
                        elif prefix == 'M':
                            daughterboard_folders.append((int(number), item_path, number, internal_comment, dir_name))
                    if self.include_subfolders:
                        self._scan_directory(item_path, dir_name, motherboard_folders, daughterboard_folders)
        except Exception as e:
            self.scan_progress.emit(f"扫描目录 {directory} 时出错: {str(e)}")

    def run(self):
        """线程运行方法"""
        root_dirs = self.settings or []
        dir_order = {name: idx for idx, (name, _) in enumerate(root_dirs)}
        motherboard_folders = []
        daughterboard_folders = []
        for dir_name, root_dir in root_dirs:
            self.scan_progress.emit(f"正在扫描: {root_dir}")
            self._scan_directory(root_dir, dir_name, motherboard_folders, daughterboard_folders)
        if self.sort_by_number:
            motherboard_folders.sort(key=lambda x: x[0])
            daughterboard_folders.sort(key=lambda x: x[0])
        else:
            motherboard_folders.sort(key=lambda x: (dir_order.get(x[4], 999), x[0]))
            daughterboard_folders.sort(key=lambda x: (dir_order.get(x[4], 999), x[0]))
        self.scan_completed.emit(motherboard_folders, daughterboard_folders)


class NewProjectDialog(QDialog):
    def __init__(self, parent=None, default_folder='D:\资料'):
        super().__init__(parent)
        self.project_type = '主板'
        self.pcb_number = ''
        self.comment = ''
        self.target_folder = default_folder  # 默认目标文件夹
        self.parent_window = parent
        self.setWindowTitle('新建项目文件夹')
        self.setGeometry(300, 300, 500, 300)
        
        layout = QVBoxLayout()
        
        # 目标文件夹选择
        folder_group = QGroupBox('目标文件夹')
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel(self.target_folder)
        self.folder_label.setStyleSheet('font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;')
        self.folder_label.setToolTip('点击更改目标文件夹')
        self.folder_label.setCursor(Qt.PointingHandCursor)
        self.folder_label.mousePressEvent = self.select_folder
        
        folder_btn = QPushButton('选择文件夹')
        folder_btn.clicked.connect(self.select_folder)
        
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(folder_btn)
        folder_group.setLayout(folder_layout)
        
        type_group = QGroupBox('项目类型')
        type_layout = QVBoxLayout()
        self.type_group = QButtonGroup()
        self.motherboard_radio = QRadioButton('主板 (S开头)')
        self.motherboard_radio.setChecked(True)
        self.motherboard_radio.toggled.connect(lambda: self.set_project_type('主板'))
        self.daughterboard_radio = QRadioButton('子卡 (M开头)')
        self.daughterboard_radio.toggled.connect(lambda: self.set_project_type('子卡'))
        self.type_group.addButton(self.motherboard_radio)
        self.type_group.addButton(self.daughterboard_radio)
        type_layout.addWidget(self.motherboard_radio)
        type_layout.addWidget(self.daughterboard_radio)
        type_group.setLayout(type_layout)
        
        info_group = QGroupBox('项目信息')
        info_layout = QFormLayout()
        self.number_edit = QLineEdit()
        self.number_edit.setPlaceholderText('请输入3-4位数字')
        self.number_edit.textChanged.connect(self.on_number_changed)
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText('请输入项目注释')
        self.comment_edit.textChanged.connect(self.on_comment_changed)
        self.preview_label = QLabel('')
        self.preview_label.setStyleSheet('font-weight: bold; color: blue;')
        info_layout.addRow('PCB编号：', self.number_edit)
        info_layout.addRow('项目注释：', self.comment_edit)
        info_layout.addRow('预览：', self.preview_label)
        info_group.setLayout(info_layout)
        
        button_layout = QHBoxLayout()
        self.create_btn = QPushButton('创建')
        self.create_btn.clicked.connect(self.create_project)
        self.create_btn.setEnabled(False)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.create_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addWidget(folder_group)
        layout.addWidget(type_group)
        layout.addWidget(info_group)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def set_project_type(self, project_type):
        self.project_type = project_type
        self.update_preview()
        
    def on_number_changed(self, text):
        self.pcb_number = text
        self.update_preview()
        
    def on_comment_changed(self, text):
        self.comment = text
        self.update_preview()
        
    def update_preview(self):
        if not self.pcb_number:
            self.preview_label.setText('')
            self.create_btn.setEnabled(False)
            return
        if not re.match(r'^\d{3,4}$', self.pcb_number):
            self.preview_label.setText('编号必须是3-4位数字')
            self.preview_label.setStyleSheet('font-weight: bold; color: red;')
            self.create_btn.setEnabled(False)
            return
        prefix = 'S' if self.project_type == '主板' else 'M'
        if self.comment:
            folder_name = f'{prefix}{self.pcb_number}_{self.comment}'
        else:
            folder_name = f'{prefix}{self.pcb_number}'
        self.preview_label.setText(folder_name)
        self.preview_label.setStyleSheet('font-weight: bold; color: blue;')
        self.create_btn.setEnabled(True)
        
    def select_folder(self, event=None):
        """选择目标文件夹"""
        folder_path = QFileDialog.getExistingDirectory(self, '选择目标文件夹', self.target_folder)
        if not folder_path:
            return
        self.target_folder = folder_path
        self.folder_label.setText(folder_path)
        if not self.parent_window:
            return
        self.parent_window.default_new_project_folder = folder_path
        settings = getattr(self.parent_window, 'settings', None) or []
        for name, path in settings:
            if path == folder_path:
                return
        folder_name = os.path.basename(folder_path) or "自定义路径"
        settings.append((folder_name, folder_path))
        self.parent_window.settings = settings
        self.parent_window.save_settings_to_file(
            self.parent_window.settings,
            self.parent_window.include_subfolders,
            folder_path
        )
    
    def create_project(self):
        if not re.match(r'^\d{3,4}$', self.pcb_number):
            QMessageBox.warning(self, '警告', 'PCB编号必须是3-4位数字')
            return
        prefix = 'S' if self.project_type == '主板' else 'M'
        if self.comment:
            folder_name = f'{prefix}{self.pcb_number}_{self.comment}'
        else:
            folder_name = f'{prefix}{self.pcb_number}'
        target_path = os.path.join(self.target_folder, folder_name)
        if os.path.exists(target_path):
            QMessageBox.warning(self, '警告', f'文件夹 {folder_name} 已存在')
            return
        try:
            os.makedirs(target_path)
            QMessageBox.information(self, '成功', f'项目文件夹 {folder_name} 已创建')
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, '错误', f'创建文件夹失败: {str(e)}')
            
    def get_project_info(self):
        prefix = 'S' if self.project_type == '主板' else 'M'
        if self.comment:
            folder_name = f'{prefix}{self.pcb_number}_{self.comment}'
        else:
            folder_name = f'{prefix}{self.pcb_number}'
        return {
            'type': self.project_type,
            'number': self.pcb_number,
            'comment': self.comment,
            'folder_name': folder_name,
            'full_path': os.path.join(self.target_folder, folder_name)
        }

class NewStructureDialog(QDialog):
    def __init__(self, project_folder=None, parent=None):
        super().__init__(parent)
        self.version = '00'
        self.selected_folders = {'BOM': True, 'SCH': True, '物料': True, '评审': True, '信号测试': True}
        self.custom_folders = []
        self.project_folder = project_folder
        self.parent_window = parent
        
        # 加载保存的文件夹结构设置
        if parent and hasattr(parent, 'folder_structure'):
            saved_structure = parent.folder_structure
            if 'version' in saved_structure:
                self.version = saved_structure['version']
            if 'selected_folders' in saved_structure:
                self.selected_folders = saved_structure['selected_folders']
            if 'custom_folders' in saved_structure:
                # 过滤掉空字符串
                self.saved_custom_folders = [f for f in saved_structure['custom_folders'] if f.strip()]
        
        # 设置窗口标题
        title = '新建文件夹内部结构'
        if self.project_folder:
            project_name = os.path.basename(self.project_folder)
            title += f' - 项目：{project_name}'
        self.setWindowTitle(title)
        self.setGeometry(300, 300, 450, 420)
        
        layout = QVBoxLayout()
        
        # 添加项目文件夹信息标签
        if self.project_folder:
            project_info_group = QGroupBox('项目信息')
            project_info_layout = QHBoxLayout()
            project_info_label = QLabel(f'当前项目文件夹：')
            project_path_label = QLabel(self.project_folder)
            project_path_label.setWordWrap(True)
            project_path_label.setToolTip(self.project_folder)
            project_info_layout.addWidget(project_info_label)
            project_info_layout.addWidget(project_path_label, 1)
            project_info_group.setLayout(project_info_layout)
            layout.addWidget(project_info_group)
        
        version_group = QGroupBox('版本选择')
        version_layout = QHBoxLayout()
        version_label = QLabel('版本号：V')
        self.version_edit = QLineEdit('00')
        self.version_edit.setMaxLength(2)
        self.version_edit.setFixedWidth(50)
        self.version_edit.textChanged.connect(self.on_version_changed)
        version_layout.addWidget(version_label)
        version_layout.addWidget(self.version_edit)
        version_layout.addStretch()
        version_group.setLayout(version_layout)
        
        folders_group = QGroupBox('常用文件夹（默认勾选）')
        folders_layout = QVBoxLayout()
        
        self.folder_names = ['BOM', 'SCH', '物料', '评审', '信号测试']
        self.folder_checkboxes = {}
        checkbox_layout = QGridLayout()
        for i, name in enumerate(self.folder_names):
            checkbox = QPushButton(name)
            checkbox.setCheckable(True)
            checkbox.setChecked(self.selected_folders.get(name, True))
            checkbox.toggled.connect(lambda c, n=name: self.on_folder_toggled(n, c))
            self.folder_checkboxes[name] = checkbox
            checkbox_layout.addWidget(checkbox, i // 2, i % 2)
        folders_layout.addLayout(checkbox_layout)
        
        # 添加全部恢复默认按钮
        reset_btn = QPushButton('全部恢复默认')
        reset_btn.clicked.connect(self.reset_to_defaults)
        folders_layout.addWidget(reset_btn, alignment=Qt.AlignRight)
        
        folders_group.setLayout(folders_layout)
        
        custom_group = QGroupBox('自定义文件夹')
        custom_layout = QVBoxLayout()
        self.custom_container = QWidget()
        self.custom_container_layout = QVBoxLayout(self.custom_container)
        self.custom_container_layout.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton('+ 添加自定义文件夹')
        add_btn.clicked.connect(self.add_custom_folder)
        custom_layout.addWidget(self.custom_container)
        custom_layout.addWidget(add_btn)
        custom_group.setLayout(custom_layout)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFixedHeight(100)
        
        button_layout = QHBoxLayout()
        create_btn = QPushButton('创建')
        create_btn.clicked.connect(self.create_structure)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(create_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addWidget(version_group)
        layout.addWidget(folders_group)
        layout.addWidget(custom_group)
        layout.addWidget(QLabel('文件夹结构预览：'))
        layout.addWidget(self.preview_text)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # 初始化UI控件状态
        self.version_edit.setText(self.version)
        
        # 添加保存的自定义文件夹
        if hasattr(self, 'saved_custom_folders'):
            for folder_name in self.saved_custom_folders:
                self.add_custom_folder_with_text(folder_name)
        
        self.update_preview()
        
    def on_version_changed(self, text):
        if text and len(text) <= 2:
            self.version = text.zfill(2)
        self.update_preview()
        
    def on_folder_toggled(self, folder_name, checked):
        self.selected_folders[folder_name] = checked
        self.update_preview()
    
    def reset_to_defaults(self):
        """将常用文件夹恢复为默认勾选状态，并删除所有自定义文件夹"""
        self.selected_folders = {name: True for name in self.folder_names}
        
        for name, checkbox in self.folder_checkboxes.items():
            checkbox.setChecked(True)
        
        if hasattr(self, 'custom_folders'):
            self.custom_folders.clear()
            while self.custom_container_layout.count() > 0:
                item = self.custom_container_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        
        self.update_preview()
        
    def add_custom_folder(self):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 5, 0, 5)
        edit = QLineEdit()
        edit.setPlaceholderText('输入文件夹名称')
        edit.textChanged.connect(self.update_preview)
        remove_btn = QPushButton('-')
        remove_btn.setFixedWidth(30)
        remove_btn.clicked.connect(lambda: self.remove_custom_folder(row_widget, edit))
        row_layout.addWidget(edit)
        row_layout.addWidget(remove_btn)
        self.custom_container_layout.addWidget(row_widget)
        self.custom_folders.append(edit)
        self.update_preview()
        
    def add_custom_folder_with_text(self, folder_name):
        """添加带有预设文本的自定义文件夹"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 5, 0, 5)
        edit = QLineEdit(folder_name)
        edit.textChanged.connect(self.update_preview)
        remove_btn = QPushButton('-')
        remove_btn.setFixedWidth(30)
        remove_btn.clicked.connect(lambda: self.remove_custom_folder(row_widget, edit))
        row_layout.addWidget(edit)
        row_layout.addWidget(remove_btn)
        self.custom_container_layout.addWidget(row_widget)
        self.custom_folders.append(edit)
        self.update_preview()
        
    def remove_custom_folder(self, widget, edit):
        widget.deleteLater()
        if edit in self.custom_folders:
            self.custom_folders.remove(edit)
        self.update_preview()
        
    def update_preview(self):
        preview = f'V{self.version}/\n'
        for folder_name, checked in self.selected_folders.items():
            if checked:
                preview += f'  - {folder_name}\n'
        for edit in self.custom_folders:
            folder_name = edit.text().strip()
            if folder_name:
                preview += f'  - {folder_name}\n'
        self.preview_text.setPlainText(preview)
        
    def create_structure(self):
        if not re.match(r'^\d{2}$', self.version):
            QMessageBox.warning(self, '警告', '版本号必须是两位数字')
            return
        self.save_folder_structure()
        self.accept()
        
    def save_folder_structure(self):
        """保存文件夹结构设置到主窗口"""
        if self.parent_window:
            # 收集当前设置
            custom_folders = [edit.text().strip() for edit in self.custom_folders if edit.text().strip()]
            
            # 更新主窗口的文件夹结构设置
            self.parent_window.folder_structure = {
                'version': self.version,
                'selected_folders': self.selected_folders,
                'custom_folders': custom_folders
            }
            
            # 保存到文件
            self.parent_window.save_settings_to_file(
                self.parent_window.settings,
                self.parent_window.include_subfolders,
                self.parent_window.default_new_project_folder
            )
    
    def reject(self):
        """重写取消方法，保存设置"""
        self.save_folder_structure()
        super().reject()
        
    def closeEvent(self, event):
        """重写关闭事件，保存设置"""
        self.save_folder_structure()
        super().closeEvent(event)
    
    def get_structure_info(self):
        selected_folders = [name for name, checked in self.selected_folders.items() if checked]
        custom_folders = [edit.text().strip() for edit in self.custom_folders if edit.text().strip()]
        return {
            'version': self.version,
            'selected_folders': selected_folders,
            'custom_folders': custom_folders
        }

class SettingsDialog(QDialog):
    def __init__(self, current_paths, include_subfolders=False, sort_by_number=False, parent=None):
        super().__init__(parent)
        self.current_paths = current_paths if current_paths is not None else []
        self.paths = list(self.current_paths)
        self.include_subfolders = include_subfolders
        self.sort_by_number = sort_by_number
        self.setWindowTitle('项目文件夹设置')
        self.setGeometry(300, 300, 550, 450)
        
        layout = QVBoxLayout()
        
        self.path_list = QTableWidget(0, 2)
        self.path_list.setHorizontalHeaderLabels(['名称', '路径'])
        self.path_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.path_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for name, path in self.current_paths:
            row = self.path_list.rowCount()
            self.path_list.insertRow(row)
            self.path_list.setItem(row, 0, QTableWidgetItem(name))
            self.path_list.setItem(row, 1, QTableWidgetItem(path))
        
        button_layout = QHBoxLayout()
        add_btn = QPushButton('+ 添加文件夹')
        add_btn.clicked.connect(self.add_path)
        remove_btn = QPushButton('- 删除选中')
        remove_btn.clicked.connect(self.remove_path)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(remove_btn)
        
        sort_layout = QHBoxLayout()
        up_btn = QPushButton('↑ 上移')
        up_btn.clicked.connect(self.move_up)
        down_btn = QPushButton('↓ 下移')
        down_btn.clicked.connect(self.move_down)
        sort_layout.addWidget(up_btn)
        sort_layout.addWidget(down_btn)
        sort_layout.addStretch()
        
        self.include_subfolders_checkbox = QPushButton('包含所有子文件夹(可能会导致一段时间卡顿无响应，请勿退出)')
        self.include_subfolders_checkbox.setCheckable(True)
        self.include_subfolders_checkbox.setChecked(self.include_subfolders)
        
        self.sort_by_number_checkbox = QPushButton('跨路径序号从小到大排序')
        self.sort_by_number_checkbox.setCheckable(True)
        self.sort_by_number_checkbox.setChecked(self.sort_by_number)
        
        save_btn = QPushButton('保存设置')
        save_btn.clicked.connect(self.save_settings)
        
        layout.addWidget(QLabel('项目文件路径（可调整顺序）：'))
        layout.addWidget(self.path_list)
        layout.addLayout(button_layout)
        layout.addLayout(sort_layout)
        layout.addWidget(self.include_subfolders_checkbox)
        layout.addWidget(self.sort_by_number_checkbox)
        layout.addWidget(save_btn)
        self.setLayout(layout)
        
    def add_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, '选择项目文件夹')
        if folder_path:
            default_name = os.path.basename(folder_path)
            name, ok = QInputDialog.getText(self, '输入名称', '请输入显示名称：', text=default_name)
            if ok:
                if not name.strip():
                    name = default_name
                row = self.path_list.rowCount()
                self.path_list.insertRow(row)
                self.path_list.setItem(row, 0, QTableWidgetItem(name))
                self.path_list.setItem(row, 1, QTableWidgetItem(folder_path))
        
    def remove_path(self):
        current_row = self.path_list.currentRow()
        if current_row >= 0:
            self.path_list.removeRow(current_row)
    
    def move_up(self):
        current_row = self.path_list.currentRow()
        if current_row > 0:
            self._swap_rows(current_row, current_row - 1)
            self.path_list.setCurrentCell(current_row - 1, 0)
    
    def move_down(self):
        current_row = self.path_list.currentRow()
        if current_row >= 0 and current_row < self.path_list.rowCount() - 1:
            self._swap_rows(current_row, current_row + 1)
            self.path_list.setCurrentCell(current_row + 1, 0)
    
    def _swap_rows(self, row1, row2):
        # 本对话框的表只有 2 列（名称、路径），不要访问第 3 列
        name1 = self.path_list.item(row1, 0).text()
        path1 = self.path_list.item(row1, 1).text()
        name2 = self.path_list.item(row2, 0).text()
        path2 = self.path_list.item(row2, 1).text()
        self.path_list.setItem(row1, 0, QTableWidgetItem(name2))
        self.path_list.setItem(row1, 1, QTableWidgetItem(path2))
        self.path_list.setItem(row2, 0, QTableWidgetItem(name1))
        self.path_list.setItem(row2, 1, QTableWidgetItem(path1))

    def save_settings(self):
        paths = []
        for row in range(self.path_list.rowCount()):
            name_item = self.path_list.item(row, 0)
            path_item = self.path_list.item(row, 1)
            if name_item and path_item:
                paths.append((name_item.text(), path_item.text()))
        if not paths:
            QMessageBox.warning(self, '警告', '至少需要保留一个项目文件夹')
            return
        self.paths = paths
        self.include_subfolders = self.include_subfolders_checkbox.isChecked()
        self.sort_by_number = self.sort_by_number_checkbox.isChecked()
        self.accept()
        
    def get_settings(self):
        return self.paths, self.include_subfolders, self.sort_by_number


class SevenZipSettingsDialog(QDialog):
    def __init__(self, current_path, parent=None):
        super().__init__(parent)
        self.current_path = current_path or ''
        self.archive_tool_path = self.current_path
        self.setWindowTitle('7-Zip路径设置')
        self.setGeometry(300, 300, 450, 120)
        
        layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel('7z.exe路径:'))
        self.path_edit = QLineEdit()
        self.path_edit.setText(self.current_path)
        self.path_edit.setPlaceholderText('自动检测7-Zip')
        browse_btn = QPushButton('浏览...')
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_btn)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton('保存设置')
        save_btn.clicked.connect(self.save_settings)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(path_layout)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def browse_path(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, '选择7z.exe', '', 
            '可执行文件 (*.exe);;所有文件 (*.*)'
        )
        if file_path:
            self.path_edit.setText(file_path)
    
    def save_settings(self):
        self.archive_tool_path = self.path_edit.text().strip()
        self.accept()
    
    def get_settings(self):
        return self.archive_tool_path


class QuickAccessSettingsDialog(QDialog):
    def __init__(self, current_paths, parent=None):
        super().__init__(parent)
        self.current_paths = current_paths if current_paths else []
        self.paths = list(self.current_paths)
        self.setWindowTitle('快捷访问设置')
        self.setGeometry(300, 300, 550, 400)
        
        layout = QVBoxLayout()
        
        self.path_list = QTableWidget(0, 3)
        self.path_list.setHorizontalHeaderLabels(['名称', '路径', '不显示预览'])
        self.path_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.path_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.path_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        for item in self.current_paths:
            if len(item) == 3:
                name, path, no_preview = item
            else:
                name, path = item
                no_preview = False
            row = self.path_list.rowCount()
            self.path_list.insertRow(row)
            self.path_list.setItem(row, 0, QTableWidgetItem(name))
            self.path_list.setItem(row, 1, QTableWidgetItem(path))
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Checked if no_preview else Qt.Unchecked)
            self.path_list.setItem(row, 2, check_item)
        
        button_layout = QHBoxLayout()
        add_btn = QPushButton('+ 添加文件夹')
        add_btn.clicked.connect(self.add_path)
        remove_btn = QPushButton('- 删除选中')
        remove_btn.clicked.connect(self.remove_path)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(remove_btn)
        
        sort_layout = QHBoxLayout()
        up_btn = QPushButton('↑ 上移')
        up_btn.clicked.connect(self.move_up)
        down_btn = QPushButton('↓ 下移')
        down_btn.clicked.connect(self.move_down)
        sort_layout.addWidget(up_btn)
        sort_layout.addWidget(down_btn)
        sort_layout.addStretch()
        
        reset_btn = QPushButton('恢复默认')
        reset_btn.clicked.connect(self.reset_to_default)
        
        save_btn = QPushButton('保存设置')
        save_btn.clicked.connect(self.save_settings)
        
        hint_label = QLabel('提示：大文件夹与网络文件夹建议勾选"不显示预览"')
        hint_label.setStyleSheet('color: gray; font-size: 11px;')
        
        layout.addWidget(QLabel('快捷访问路径（可调整顺序）：'))
        layout.addWidget(self.path_list)
        layout.addLayout(button_layout)
        layout.addLayout(sort_layout)
        layout.addWidget(reset_btn)
        layout.addWidget(save_btn)
        layout.addWidget(hint_label)
        self.setLayout(layout)
    
    def add_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, '选择文件夹')
        if folder_path:
            default_name = os.path.basename(folder_path)
            name, ok = QInputDialog.getText(self, '输入名称', '请输入显示名称：', text=default_name)
            if ok:
                if not name.strip():
                    name = default_name
                row = self.path_list.rowCount()
                self.path_list.insertRow(row)
                self.path_list.setItem(row, 0, QTableWidgetItem(name))
                self.path_list.setItem(row, 1, QTableWidgetItem(folder_path))
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Unchecked)
                self.path_list.setItem(row, 2, check_item)
    
    def remove_path(self):
        current_row = self.path_list.currentRow()
        if current_row >= 0:
            self.path_list.removeRow(current_row)
    
    def move_up(self):
        current_row = self.path_list.currentRow()
        if current_row > 0:
            self._swap_rows(current_row, current_row - 1)
            self.path_list.setCurrentCell(current_row - 1, 0)
    
    def move_down(self):
        current_row = self.path_list.currentRow()
        if current_row >= 0 and current_row < self.path_list.rowCount() - 1:
            self._swap_rows(current_row, current_row + 1)
            self.path_list.setCurrentCell(current_row + 1, 0)
    
    def _swap_rows(self, row1, row2):
        # 本对话框的表有 3 列，第 3 列是“不显示预览”勾选框，交换时必须一并搬运
        name1 = self.path_list.item(row1, 0).text()
        path1 = self.path_list.item(row1, 1).text()
        check1 = self.path_list.item(row1, 2).checkState()
        name2 = self.path_list.item(row2, 0).text()
        path2 = self.path_list.item(row2, 1).text()
        check2 = self.path_list.item(row2, 2).checkState()
        self.path_list.setItem(row1, 0, QTableWidgetItem(name2))
        self.path_list.setItem(row1, 1, QTableWidgetItem(path2))
        check_item1 = QTableWidgetItem()
        check_item1.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check_item1.setCheckState(check2)
        self.path_list.setItem(row1, 2, check_item1)
        self.path_list.setItem(row2, 0, QTableWidgetItem(name1))
        self.path_list.setItem(row2, 1, QTableWidgetItem(path1))
        check_item2 = QTableWidgetItem()
        check_item2.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check_item2.setCheckState(check1)
        self.path_list.setItem(row2, 2, check_item2)

    def reset_to_default(self):
        if hasattr(self.parent(), '_get_default_quick_access_paths'):
            default_paths = self.parent()._get_default_quick_access_paths()
            self.path_list.setRowCount(0)
            for item in default_paths:
                if len(item) == 3:
                    name, path, no_preview = item
                else:
                    name, path = item
                    no_preview = False
                row = self.path_list.rowCount()
                self.path_list.insertRow(row)
                self.path_list.setItem(row, 0, QTableWidgetItem(name))
                self.path_list.setItem(row, 1, QTableWidgetItem(path))
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Checked if no_preview else Qt.Unchecked)
                self.path_list.setItem(row, 2, check_item)
    
    def save_settings(self):
        paths = []
        for row in range(self.path_list.rowCount()):
            name_item = self.path_list.item(row, 0)
            path_item = self.path_list.item(row, 1)
            check_item = self.path_list.item(row, 2)
            if name_item and path_item:
                no_preview = check_item.checkState() == Qt.Checked if check_item else False
                paths.append((name_item.text(), path_item.text(), no_preview))
        self.paths = paths
        self.accept()
    
    def get_settings(self):
        return self.paths


class WizardDialog(QDialog):
    """新手向导：分页介绍几项核心功能，仅首次自动弹出，可随时跳过。"""

    # (标题, HTML 正文)
    PAGES = [
        (
            '欢迎使用 SeavoExplorer',
            '''
            <p>SeavoExplorer 是面向 S/M 主板项目的文件浏览器，帮你快速定位项目、
            预览工程文档、整理版本目录。</p>
            <p>下面用几步介绍几项核心功能。你可以随时点击<b>“跳过”</b>关闭向导，
            之后也能在菜单 <b>帮助 → 新手向导</b> 中重新打开。</p>
            '''
        ),
        (
            '一、配置并浏览项目',
            '''
            <p>首次使用请先在菜单 <b>设置 → 项目文件夹设置</b> 中添加包含项目的根目录。</p>
            <p>程序会自动扫描其中符合命名规则的文件夹（以 <code>S</code> 或 <code>M</code>
            开头 + 3~4 位数字，可选 <code>_注释</code>，如 <code>S1234_样机</code>）。</p>
            <ul>
            <li><b>单击</b>左侧项目行 → 在右侧文件树中查看该项目文件</li>
            <li><b>双击编号列</b> → 在资源管理器中打开</li>
            <li>顶部<b>搜索框</b> → 实时过滤项目列表</li>
            </ul>
            '''
        ),
        (
            '二、预览工程文档',
            '''
            <p>在右侧文件树中<b>单击</b>文件即可在下方预览区查看内容，无需打开外部程序：</p>
            <ul>
            <li>文本 / PDF / Excel / Word / 图片 / 视频缩略图</li>
            <li>压缩包（.zip/.rar/.7z）以树状结构显示内容</li>
            </ul>
            <p><b>双击</b>文件用系统默认程序打开；切换到<b>元数据</b>标签可查看文件详情。</p>
            '''
        ),
        (
            '三、文件操作（支持多选）',
            '''
            <p>文件树支持按住 <b>Ctrl</b> / <b>Shift</b> 多选，再进行批量操作：</p>
            <ul>
            <li><b>Ctrl+C / 右键复制</b>：复制到剪贴板，可在资源管理器粘贴，也保留程序内“粘贴副本”</li>
            <li><b>Ctrl+V / 右键粘贴副本</b>：粘贴到选中文件夹或当前项目（自动处理重名）</li>
            <li><b>F2</b>：重命名单个文件</li>
            <li><b>Delete</b>：移入回收站</li>
            <li>右键还可“添加到 zip 压缩包”“智能解压”</li>
            </ul>
            '''
        ),
        (
            '四、新建项目与版本结构',
            '''
            <p>左侧 <b>“新建项目文件夹”</b>：按规则创建新的 S/M 项目根目录。</p>
            <p>选中项目后的 <b>“新建文件夹内部结构”</b>：在项目内创建版本目录（如 <code>V01</code>）
            及 BOM / SCH / 物料 / 评审 / 信号测试 等标准子文件夹。</p>
            <p>更详细的说明请见菜单 <b>帮助 → 使用帮助</b>。祝使用愉快！</p>
            '''
        ),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('新手向导')
        self.setMinimumSize(560, 460)
        icon_path = parent._resource_path('favicon.ico') if parent and hasattr(parent, '_resource_path') else ''
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.current_page = 0

        layout = QVBoxLayout(self)

        self.title_label = QLabel()
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet('color: #2c3e50;')
        layout.addWidget(self.title_label)

        self.step_label = QLabel()
        self.step_label.setStyleSheet('color: #7f8c8d;')
        layout.addWidget(self.step_label)

        self.body = QTextEdit()
        self.body.setReadOnly(True)
        layout.addWidget(self.body, 1)

        btn_layout = QHBoxLayout()
        self.skip_btn = QPushButton('跳过')
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)
        btn_layout.addStretch()
        self.prev_btn = QPushButton('上一步')
        self.prev_btn.clicked.connect(self.go_prev)
        btn_layout.addWidget(self.prev_btn)
        self.next_btn = QPushButton('下一步')
        self.next_btn.clicked.connect(self.go_next)
        btn_layout.addWidget(self.next_btn)
        layout.addLayout(btn_layout)

        self._render_page()

    def _render_page(self):
        title, html = self.PAGES[self.current_page]
        self.title_label.setText(title)
        self.step_label.setText(f'第 {self.current_page + 1} / {len(self.PAGES)} 步')
        self.body.setHtml(html)
        self.prev_btn.setEnabled(self.current_page > 0)
        is_last = self.current_page == len(self.PAGES) - 1
        self.next_btn.setText('完成' if is_last else '下一步')
        self.skip_btn.setVisible(not is_last)

    def go_prev(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def go_next(self):
        if self.current_page < len(self.PAGES) - 1:
            self.current_page += 1
            self._render_page()
        else:
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 确定配置文件的保存位置
        # 对于打包后的程序，使用EXE文件所在目录
        import sys
        if hasattr(sys, '_MEIPASS'):
            # 打包后的程序
            self.app_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            # 开发环境
            self.app_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 初始化配置和注释文件路径
        self.CONFIG_FILE = os.path.join(self.app_dir, 'seavoexplorer.json')
        self.COMMENTS_FILE = os.path.join(self.app_dir, 'seavo_comments.json')
        
        # 确保app_dir目录存在
        os.makedirs(self.app_dir, exist_ok=True)
        
        self.current_folder = None
        self.filtered_folders = {'主板': [], '子卡': []}
        self.include_subfolders = False
        self.sort_by_number = False
        self.archive_tool_path = ''
        self.pinned_folders = []
        self.comments = self.load_comments() or {}
        self.clipboard_path = None
        self.clipboard_paths = []

        self.settings = self.load_settings()
        
        self.initUI()
        # 异步加载文件夹，提高启动速度
        self.load_filtered_folders_async()
        # 首次运行自动弹出新手向导（窗口显示后再弹，避免阻塞启动）
        if not getattr(self, 'wizard_shown', False):
            QTimer.singleShot(0, self.show_wizard)

    def initUI(self):
        self.setWindowTitle('主板项目文件浏览器')
        self.setGeometry(100, 100, 1400, 900)
        
        icon_path = self._resource_path('favicon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 0, 5, 5)
        
        # 快捷访问工具栏
        self.quick_access_toolbar = QWidget()
        quick_access_layout = QHBoxLayout(self.quick_access_toolbar)
        quick_access_layout.setContentsMargins(5, 0, 5, 0)
        quick_access_layout.setSpacing(2)
        self.quick_access_toolbar.setFixedHeight(28)
        quick_access_label = QLabel('快捷访问:')
        quick_access_layout.addWidget(quick_access_label)
        
        self.quick_access_buttons = []
        self._create_quick_access_buttons(quick_access_layout)
        quick_access_layout.addStretch()
        
        main_layout.addWidget(self.quick_access_toolbar)
        
        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        folder_search_layout = QHBoxLayout()
        folder_search_label = QLabel('文件夹搜索:')
        self.folder_search_edit = QLineEdit()
        self.folder_search_edit.textChanged.connect(self.filter_folders)
        folder_search_layout.addWidget(folder_search_label)
        folder_search_layout.addWidget(self.folder_search_edit)
        
        self.motherboard_group = QGroupBox('主板')
        motherboard_layout = QVBoxLayout(self.motherboard_group)
        self.motherboard_table = QTableWidget(0, 2)
        self.motherboard_table.setHorizontalHeaderLabels(['编号', '注释'])
        self.motherboard_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.motherboard_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.motherboard_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.motherboard_table.setSelectionMode(QTableWidget.SingleSelection)
        self.motherboard_table.cellClicked.connect(self.on_folder_cell_clicked)
        self.motherboard_table.cellDoubleClicked.connect(self.on_folder_cell_double_clicked)
        self.motherboard_table.verticalHeader().setVisible(False)
        self.motherboard_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.motherboard_table.customContextMenuRequested.connect(lambda pos: self._show_folder_context_menu(self.motherboard_table, pos))
        motherboard_layout.addWidget(self.motherboard_table)
        
        self.daughterboard_group = QGroupBox('子卡')
        daughterboard_layout = QVBoxLayout(self.daughterboard_group)
        self.daughterboard_table = QTableWidget(0, 2)
        self.daughterboard_table.setHorizontalHeaderLabels(['编号', '注释'])
        self.daughterboard_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.daughterboard_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.daughterboard_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.daughterboard_table.setSelectionMode(QTableWidget.SingleSelection)
        self.daughterboard_table.cellClicked.connect(self.on_folder_cell_clicked)
        self.daughterboard_table.cellDoubleClicked.connect(self.on_folder_cell_double_clicked)
        self.daughterboard_table.verticalHeader().setVisible(False)
        self.daughterboard_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.daughterboard_table.customContextMenuRequested.connect(lambda pos: self._show_folder_context_menu(self.daughterboard_table, pos))
        daughterboard_layout.addWidget(self.daughterboard_table)
        
        button_layout = QHBoxLayout()
        self.new_project_btn = QPushButton('新建项目文件夹')
        self.new_project_btn.clicked.connect(self.new_project)
        button_layout.addWidget(self.new_project_btn)
        self.new_structure_btn = QPushButton('新建文件夹内部结构')
        self.new_structure_btn.clicked.connect(self.new_folder_structure)
        self.new_structure_btn.setEnabled(False)
        button_layout.addWidget(self.new_structure_btn)
        
        left_layout.addLayout(folder_search_layout)
        left_layout.addWidget(self.motherboard_group)
        left_layout.addWidget(self.daughterboard_group)
        left_layout.addLayout(button_layout)
        
        right_layout = QVBoxLayout()
        
        self.file_tree = QTreeView()
        self.file_model = QFileSystemModel()
        self.file_model.setFilter(QDir.NoDotAndDotDot | QDir.AllEntries)
        self.file_tree.setModel(self.file_model)
        self.file_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_tree.setColumnWidth(0, 300)
        self.file_tree.setSortingEnabled(True)
        self.file_tree.sortByColumn(0, Qt.AscendingOrder)
        self.file_tree.clicked.connect(self.on_file_clicked)
        self.file_tree.doubleClicked.connect(self.on_file_double_clicked)
        self.file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.on_file_tree_context_menu)
        self.copy_shortcut = QShortcut(QKeySequence.Copy, self)
        self.copy_shortcut.activated.connect(self.copy_selected_items)
        self.paste_shortcut = QShortcut(QKeySequence.Paste, self)
        self.paste_shortcut.activated.connect(self.paste_to_selected_target)

        self.tabs = QTabWidget()
        
        # 文件预览容器
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        
        # 文本预览
        self.preview_tab = QTextEdit()
        self.preview_tab.setReadOnly(True)
        self.preview_tab.setFont(get_mono_font(10))
        self.preview_layout.addWidget(self.preview_tab)
        
        # 图片预览
        self.image_scroll_area = QScrollArea()
        self.image_scroll_area.setAlignment(Qt.AlignCenter)
        self.image_scroll_area.setWidgetResizable(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setCursor(Qt.PointingHandCursor)  # 点击手势
        self.image_label.mousePressEvent = self.show_full_image  # 点击事件
        self.image_scroll_area.setWidget(self.image_label)
        self.preview_layout.addWidget(self.image_scroll_area)
        self.image_scroll_area.hide()  # 初始隐藏图片预览
        
        self.tabs.addTab(self.preview_container, '文件预览')
        
        # 元数据预览
        self.metadata_tab = QTextEdit()
        self.metadata_tab.setReadOnly(True)
        self.tabs.addTab(self.metadata_tab, '元数据')
        
        # 右侧面板（文件树+预览）
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        right_layout.addWidget(self.file_tree)
        right_layout.addWidget(self.tabs)
        right_layout.setStretch(0, 2)
        right_layout.setStretch(1, 1)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 3)
        content_layout.addWidget(splitter)
        
        # 在状态栏右侧添加回收站按钮
        self.statusBar().addPermanentWidget(self._create_recycle_btn())
        
        self.create_menu()
    
    def create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('文件')
        file_menu.addAction('新建项目', self.new_project)
        file_menu.addAction('新建文件夹内部结构', self.new_folder_structure)
        file_menu.addAction('刷新(快捷键F5)', self.load_filtered_folders)
        file_menu.addAction('退出', self.close)
        settings_menu = menubar.addMenu('设置')
        settings_menu.addAction('项目文件夹设置', self.show_settings_dialog)
        settings_menu.addAction('快捷访问设置', self.show_quick_access_settings_dialog)
        settings_menu.addAction('7-Zip路径设置', self.show_7zip_settings_dialog)
        help_menu = menubar.addMenu('帮助')
        help_menu.addAction('新手向导', self.show_wizard)
        help_menu.addAction('使用帮助', self.show_help)
        help_menu.addAction('关于', self.show_about)
    
    def _init_default_settings(self):
        """初始化默认设置"""
        self.project_paths = []
        self.include_subfolders = False
        self.sort_by_number = False
        self.default_new_project_folder = os.path.expanduser("~")
        self.folder_structure = {
            'version': '00',
            'selected_folders': {'BOM': True, 'SCH': True, '物料': True, '评审': True, '信号测试': True},
            'custom_folders': []
        }
        self.quick_access_paths = self._get_default_quick_access_paths()
        self.wizard_shown = False

    def _get_default_quick_access_paths(self):
        """获取默认快捷访问路径"""
        import ctypes
        from ctypes import wintypes
        
        default_paths = []
        
        # 获取系统特殊文件夹路径
        CSIDL_DESKTOP = 0x00
        CSIDL_MYPICTURES = 0x27
        CSIDL_DOWNLOADS = 0x28
        
        def get_special_folder(csidl):
            try:
                buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
                ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf)
                return buf.value if buf.value else None
            except Exception:
                return None
        
        # 桌面
        desktop = get_special_folder(CSIDL_DESKTOP)
        if desktop and os.path.exists(desktop):
            default_paths.append(('桌面', desktop, False))
        
        pictures = get_special_folder(CSIDL_MYPICTURES)
        if pictures and os.path.exists(pictures):
            default_paths.append(('图片', pictures, False))
        
        for letter in ['C', 'D', 'E']:
            drive_path = f'{letter}:\\'
            if os.path.exists(drive_path):
                default_paths.append((f'{letter}:', drive_path, True))
        
        return default_paths

    def load_settings(self):
        self._init_default_settings()
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                if 'project_paths' in config_data and config_data['project_paths']:
                    self.project_paths = config_data['project_paths']
                if 'include_subfolders' in config_data:
                    self.include_subfolders = config_data['include_subfolders']
                if 'sort_by_number' in config_data:
                    self.sort_by_number = config_data['sort_by_number']
                if 'default_new_project_folder' in config_data:
                    self.default_new_project_folder = config_data['default_new_project_folder']
                if 'folder_structure' in config_data:
                    self.folder_structure = config_data['folder_structure']
                if 'archive_tool_path' in config_data:
                    self.archive_tool_path = config_data['archive_tool_path']
                if 'quick_access_paths' in config_data:
                    self.quick_access_paths = config_data['quick_access_paths']
                if 'pinned_folders' in config_data:
                    self.pinned_folders = config_data['pinned_folders']
                if 'wizard_shown' in config_data:
                    self.wizard_shown = config_data['wizard_shown']
        except Exception:
            self._init_default_settings()
        return self.project_paths
    
    def make_file_hidden(self, file_path):
        """将文件设置为隐藏属性"""
        try:
            if sys.platform == 'win32':
                ctypes.windll.kernel32.SetFileAttributesW(file_path, 0x02)
        except Exception:
            pass

    def safe_write_json(self, file_path, data, make_hidden=True):
        """安全地写入JSON文件（先删除再写入）"""
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            if os.path.exists(file_path):
                try:
                    os.chmod(file_path, 0o777)
                    os.remove(file_path)
                except Exception:
                    pass
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.chmod(file_path, 0o644)
            if make_hidden:
                self.make_file_hidden(file_path)
            return True
        except Exception:
            return False

    def save_settings_to_file(self, paths, include_subfolders=False, default_new_project_folder=None):
        try:
            config_data = {
                'project_paths': paths,
                'include_subfolders': include_subfolders,
                'sort_by_number': getattr(self, 'sort_by_number', False),
                'archive_tool_path': getattr(self, 'archive_tool_path', ''),
                'quick_access_paths': getattr(self, 'quick_access_paths', []),
                'pinned_folders': getattr(self, 'pinned_folders', []),
                'wizard_shown': getattr(self, 'wizard_shown', False)
            }
            if hasattr(self, 'folder_structure'):
                config_data['folder_structure'] = self.folder_structure
            if default_new_project_folder:
                config_data['default_new_project_folder'] = default_new_project_folder
            elif hasattr(self, 'default_new_project_folder'):
                config_data['default_new_project_folder'] = self.default_new_project_folder
            else:
                config_data['default_new_project_folder'] = 'D:\资料'
            if self.safe_write_json(self.CONFIG_FILE, config_data):
                return True
            else:
                QMessageBox.critical(self, '错误', '保存设置失败')
                return False
        except Exception as e:
            QMessageBox.critical(self, '错误', f'保存设置失败: {str(e)}')
            return False

    def load_comments(self):
        """加载项目注释"""
        try:
            if os.path.exists(self.COMMENTS_FILE):
                with open(self.COMMENTS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            return {}

    def save_comments(self):
        """保存项目注释"""
        if self.safe_write_json(self.COMMENTS_FILE, self.comments):
            return True
        else:
            QMessageBox.warning(self, '警告', '保存注释失败，但不影响程序使用')
            return False
    
    def show_settings_dialog(self):
        dialog = SettingsDialog(self.settings, self.include_subfolders, self.sort_by_number, self)
        if dialog.exec_():
            new_paths, new_include_subfolders, new_sort_by_number = dialog.get_settings()
            self.sort_by_number = new_sort_by_number
            if self.save_settings_to_file(new_paths, new_include_subfolders):
                self.settings = new_paths
                self.include_subfolders = new_include_subfolders
                QMessageBox.information(self, '成功', '设置已保存')
                self.load_filtered_folders()
    
    def show_7zip_settings_dialog(self):
        """显示7-Zip设置对话框"""
        dialog = SevenZipSettingsDialog(self.archive_tool_path, self)
        if dialog.exec_():
            new_path = dialog.get_settings()
            self.archive_tool_path = new_path
            self.save_settings_to_file(self.settings, self.include_subfolders)
            QMessageBox.information(self, '成功', '7-Zip路径设置已保存')
    
    def _create_quick_access_buttons(self, layout):
        for btn in self.quick_access_buttons:
            btn.deleteLater()
        self.quick_access_buttons.clear()
        
        for item in self.quick_access_paths:
            if len(item) == 3:
                name, path, no_preview = item
            else:
                name, path = item
                no_preview = False
            btn = QPushButton(name)
            btn.setToolTip(path)
            btn.setFixedHeight(22)
            btn.setMinimumWidth(btn.fontMetrics().width('000000') + 16)
            if no_preview:
                btn.setStyleSheet(
                    "QPushButton { background-color: #e8e8e8; border: 1px solid #bbb; border-radius: 3px; "
                    "color: #555; font-style: italic; }"
                    "QPushButton:hover { background-color: #d8d8d8; }"
                )
                btn.clicked.connect(lambda checked, p=path: self._open_quick_access_external(p))
            else:
                btn.clicked.connect(lambda checked, p=path: self._open_quick_access_path(p))
            layout.addWidget(btn)
            self.quick_access_buttons.append(btn)
    
    def _open_quick_access_external(self, path):
        try:
            path = os.path.normpath(path)
            if os.path.exists(path):
                os.startfile(path)
            else:
                QMessageBox.warning(self, '警告', f'路径不存在: {path}')
        except Exception as e:
            QMessageBox.warning(self, '错误', f'无法打开文件夹: {str(e)}')
    
    def _open_quick_access_path(self, path):
        if os.path.exists(path):
            self.current_folder = path
            self.file_model.setRootPath(path)
            self.file_tree.setRootIndex(self.file_model.index(path))
            self.new_structure_btn.setEnabled(False)
            self._update_folder_status_bar()
        else:
            QMessageBox.warning(self, '警告', f'路径不存在: {path}')

    def _get_selected_file_paths(self):
        selection_model = self.file_tree.selectionModel()
        if not selection_model:
            return []

        paths = []
        seen = set()
        for index in selection_model.selectedRows(0):
            file_path = self.file_model.filePath(index)
            normalized_path = os.path.normpath(file_path)
            if os.path.exists(file_path) and normalized_path not in seen:
                seen.add(normalized_path)
                paths.append(file_path)
        return paths

    def _get_primary_selected_file_path(self):
        selected_paths = self._get_selected_file_paths()
        if selected_paths:
            return selected_paths[0]

        current_index = self.file_tree.currentIndex()
        if current_index.isValid():
            file_path = self.file_model.filePath(current_index)
            if os.path.exists(file_path):
                return file_path
        return None

    def _select_single_file_index(self, index):
        if not index.isValid():
            return

        selection_model = self.file_tree.selectionModel()
        if not selection_model:
            return

        selection_model.clearSelection()
        self.file_tree.setCurrentIndex(index)
        selection_model.select(index, selection_model.Select | selection_model.Rows)

    def _copy_paths_to_clipboard(self, file_paths):
        valid_paths = []
        seen = set()
        for file_path in file_paths:
            normalized_path = os.path.normpath(file_path)
            if os.path.exists(file_path) and normalized_path not in seen:
                seen.add(normalized_path)
                valid_paths.append(file_path)

        if not valid_paths:
            QMessageBox.warning(self, '警告', '没有可复制的文件或文件夹')
            return False

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in valid_paths])
        mime_data.setText('\n'.join(valid_paths))
        QApplication.clipboard().setMimeData(mime_data)

        self.clipboard_paths = list(valid_paths)
        if len(valid_paths) == 1:
            self.clipboard_path = valid_paths[0]
            self.statusBar().showMessage(f"已复制，可在资源管理器中粘贴: {os.path.basename(valid_paths[0])}")
        else:
            self.clipboard_path = None
            self.statusBar().showMessage(f"已复制 {len(valid_paths)} 个项目，可在资源管理器中粘贴")
        return True

    def _copy_path_to_clipboard(self, file_path):
        """复制文件到系统剪贴板，并保留程序内粘贴副本功能"""
        return self._copy_paths_to_clipboard([file_path])

    def copy_selected_items(self):
        selected_paths = self._get_selected_file_paths()
        if selected_paths:
            return self._copy_paths_to_clipboard(selected_paths)

        selected_path = self._get_primary_selected_file_path()
        if selected_path:
            return self._copy_path_to_clipboard(selected_path)
        return False

    def paste_to_selected_target(self):
        target = self.current_folder
        selected_paths = self._get_selected_file_paths()
        if len(selected_paths) == 1:
            selected_path = selected_paths[0]
            if os.path.isdir(selected_path):
                target = selected_path
            else:
                target = os.path.dirname(selected_path)
        elif len(selected_paths) > 1:
            self.statusBar().showMessage("已选择多个项目，将粘贴到当前项目文件夹")
        else:
            selected_path = self._get_primary_selected_file_path()
            if selected_path:
                if os.path.isdir(selected_path):
                    target = selected_path
                else:
                    target = os.path.dirname(selected_path)

        if target and os.path.exists(target):
            self.paste_copy(target)
            return True
        return False

    def _create_unique_zip_path(self, parent_dir, base_name):
        zip_name = base_name + '.zip'
        zip_path = os.path.join(parent_dir, zip_name)
        counter = 1
        while os.path.exists(zip_path):
            zip_name = f"{base_name} ({counter}).zip"
            zip_path = os.path.join(parent_dir, zip_name)
            counter += 1
        return zip_path, zip_name

    def _write_path_to_zip(self, zf, source_path, base_dir):
        if os.path.isfile(source_path):
            zf.write(source_path, os.path.relpath(source_path, base_dir))
            return

        folder_arcname = os.path.relpath(source_path, base_dir).replace('\\', '/') + '/'
        zf.writestr(folder_arcname, '')
        for root, dirs, files in os.walk(source_path):
            rel_root = os.path.relpath(root, base_dir)
            if rel_root != '.':
                dir_arcname = rel_root.replace('\\', '/') + '/'
                zf.writestr(dir_arcname, '')
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                dir_arcname = os.path.relpath(dir_path, base_dir).replace('\\', '/') + '/'
                zf.writestr(dir_arcname, '')
            for file_name in files:
                file_path = os.path.join(root, file_name)
                arcname = os.path.relpath(file_path, base_dir)
                zf.write(file_path, arcname)

    def _move_paths_to_recycle(self, file_paths):
        valid_paths = []
        seen = set()
        for file_path in file_paths:
            normalized_path = os.path.normpath(file_path)
            if os.path.exists(file_path) and normalized_path not in seen:
                seen.add(normalized_path)
                valid_paths.append(os.path.abspath(file_path))

        if not valid_paths:
            QMessageBox.warning(self, '警告', '没有可移入回收站的文件或文件夹')
            return False

        try:
            from ctypes import wintypes

            class SHFILEOPSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p),
                    ("fFlags", wintypes.WORD),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", ctypes.c_wchar_p)
                ]

            SHFileOperation = ctypes.windll.shell32.SHFileOperationW
            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040
            FOF_NOCONFIRMATION = 0x0010
            FOF_SILENT = 0x0004

            p_from = '\x00'.join(valid_paths) + '\x00\x00'

            shfo = SHFILEOPSTRUCT()
            shfo.hwnd = int(self.winId())
            shfo.wFunc = FO_DELETE
            shfo.pFrom = p_from
            shfo.pTo = None
            shfo.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT

            result = SHFileOperation(ctypes.byref(shfo))
            if result == 0:
                if len(valid_paths) == 1:
                    self.statusBar().showMessage(f"已移入回收站: {os.path.basename(valid_paths[0])}")
                else:
                    self.statusBar().showMessage(f"已移入回收站: {len(valid_paths)} 个项目")
                return True

            QMessageBox.warning(self, "错误", f"移入回收站失败，错误码: {result}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"移入回收站失败: {str(e)}")
        return False

    def _create_recycle_btn(self):
        """创建回收站按钮"""
        btn = QPushButton('🗑')
        btn.setFixedSize(30, 22)
        btn.setToolTip('打开回收站')
        btn.clicked.connect(self.open_recycle_bin)
        return btn
    
    def show_quick_access_settings_dialog(self):
        """显示快捷访问设置对话框"""
        dialog = QuickAccessSettingsDialog(self.quick_access_paths, self)
        if dialog.exec_():
            new_paths = dialog.get_settings()
            self.quick_access_paths = new_paths
            # 保存设置
            self.save_settings_to_file(self.settings, self.include_subfolders)
            # 更新工具栏
            quick_access_layout = self.quick_access_toolbar.layout()
            # 移除旧按钮
            while quick_access_layout.count() > 1:
                item = quick_access_layout.takeAt(1)
                if item.widget() and item.widget() != self.quick_access_toolbar:
                    item.widget().deleteLater()
            # 重新创建按钮
            self.quick_access_buttons.clear()
            self._create_quick_access_buttons(quick_access_layout)
            QMessageBox.information(self, '成功', '快捷访问设置已保存')
    
    def open_recycle_bin(self):
        """打开回收站"""
        try:
            os.startfile('shell:RecycleBinFolder')
        except Exception as e:
            QMessageBox.warning(self, '错误', f'无法打开回收站: {str(e)}')
    
    def load_filtered_folders_async(self):
        """异步加载过滤后的文件夹"""
        # 清空表格
        self.motherboard_table.setRowCount(0)
        self.daughterboard_table.setRowCount(0)
        self.filtered_folders = {'主板': [], '子卡': []}
        
        # 在状态栏显示加载信息
        self.statusBar().showMessage("正在扫描文件夹...")
        
        # 创建并启动扫描线程
        self.scan_thread = FolderScanThread(self.settings, self.include_subfolders, self.comments, self.sort_by_number)
        self.scan_thread.scan_completed.connect(self.on_scan_completed)
        self.scan_thread.scan_progress.connect(self.on_scan_progress)
        self.scan_thread.start()
    
    def on_scan_progress(self, message):
        """处理扫描进度更新"""
        self.statusBar().showMessage(message)
    
    def on_scan_completed(self, motherboard_folders, daughterboard_folders):
        """处理扫描完成信号"""
        # 清空现有表格数据
        self.motherboard_table.setRowCount(0)
        self.daughterboard_table.setRowCount(0)
        self.filtered_folders = {'主板': [], '子卡': []}
        
        # 填充主板表格
        for folder in motherboard_folders:
            row_position = self.motherboard_table.rowCount()
            self.motherboard_table.insertRow(row_position)
            number_item = QTableWidgetItem(folder[2])
            number_item.setData(Qt.UserRole, folder[1])
            number_item.setData(Qt.UserRole + 1, folder[4])
            self.motherboard_table.setItem(row_position, 0, number_item)
            comment_item = QTableWidgetItem(folder[3])
            self.motherboard_table.setItem(row_position, 1, comment_item)
            self.filtered_folders['主板'].append(FolderInfo(*folder))
        
        # 填充子卡表格
        for folder in daughterboard_folders:
            row_position = self.daughterboard_table.rowCount()
            self.daughterboard_table.insertRow(row_position)
            number_item = QTableWidgetItem(folder[2])
            number_item.setData(Qt.UserRole, folder[1])
            number_item.setData(Qt.UserRole + 1, folder[4])
            self.daughterboard_table.setItem(row_position, 0, number_item)
            comment_item = QTableWidgetItem(folder[3])
            self.daughterboard_table.setItem(row_position, 1, comment_item)
            self.filtered_folders['子卡'].append(FolderInfo(*folder))
        
        # 更新状态栏
        self.statusBar().showMessage(
            f"共找到 {len(motherboard_folders)} 个主板文件夹，{len(daughterboard_folders)} 个子卡文件夹"
        )
        
        if self.pinned_folders:
            self._apply_pin_order(self.motherboard_table)
            self._apply_pin_order(self.daughterboard_table)
    
    def load_filtered_folders(self):
        """同步加载过滤后的文件夹（保留接口兼容）"""
        self.load_filtered_folders_async()
    
    def filter_folders(self, text):
        for row in range(self.motherboard_table.rowCount()):
            number = self.motherboard_table.item(row, 0).text()
            comment = self.motherboard_table.item(row, 1).text()
            show = text.lower() in number.lower() or text.lower() in comment.lower()
            self.motherboard_table.setRowHidden(row, not show)
        for row in range(self.daughterboard_table.rowCount()):
            number = self.daughterboard_table.item(row, 0).text()
            comment = self.daughterboard_table.item(row, 1).text()
            show = text.lower() in number.lower() or text.lower() in comment.lower()
            self.daughterboard_table.setRowHidden(row, not show)
    
    def _show_folder_context_menu(self, table, pos):
        row = table.rowAt(pos.y())
        if row < 0:
            return
        folder_path = table.item(row, 0).data(Qt.UserRole)
        if not folder_path:
            return
        menu = QMenu(self)
        if folder_path in self.pinned_folders:
            action = menu.addAction('取消置顶')
        else:
            action = menu.addAction('置顶')
        action_pos = table.viewport().mapToGlobal(pos)
        chosen = menu.exec_(action_pos)
        if chosen == action:
            if folder_path in self.pinned_folders:
                self.pinned_folders.remove(folder_path)
            else:
                self.pinned_folders.append(folder_path)
            self._apply_pin_order(table)
            self.save_settings_to_file(self.settings, self.include_subfolders)

    def _apply_pin_order(self, table):
        pinned_rows = []
        normal_rows = []
        for row in range(table.rowCount()):
            folder_path = table.item(row, 0).data(Qt.UserRole)
            if folder_path in self.pinned_folders:
                pinned_rows.append(row)
            else:
                normal_rows.append(row)
        pinned_rows.sort(key=lambda r: self.pinned_folders.index(table.item(r, 0).data(Qt.UserRole)), reverse=True)
        new_order = pinned_rows + normal_rows
        items_data = []
        for row in range(table.rowCount()):
            row_data = []
            for col in range(table.columnCount()):
                item = table.takeItem(row, col)
                row_data.append(item)
            items_data.append(row_data)
        table.setRowCount(0)
        for row_idx in new_order:
            row_position = table.rowCount()
            table.insertRow(row_position)
            for col, item in enumerate(items_data[row_idx]):
                if item:
                    table.setItem(row_position, col, item)
        for row in range(table.rowCount()):
            folder_path = table.item(row, 0).data(Qt.UserRole)
            font = table.item(row, 0).font()
            if folder_path in self.pinned_folders:
                font.setBold(True)
                table.item(row, 0).setFont(font)
                table.item(row, 1).setFont(font)
            else:
                font.setBold(False)
                table.item(row, 0).setFont(font)
                table.item(row, 1).setFont(font)

    def on_folder_cell_clicked(self, row, column):
        table = self.sender()
        folder_path = table.item(row, 0).data(Qt.UserRole)
        if folder_path and os.path.exists(folder_path):
            self.current_folder = folder_path
            self.file_model.setRootPath(folder_path)
            self.file_tree.setRootIndex(self.file_model.index(folder_path))
            self.preview_tab.clear()
            self.metadata_tab.clear()
            self.new_structure_btn.setEnabled(True)
            self._update_folder_status_bar()
    
    def on_folder_cell_double_clicked(self, row, column):
        """双击表格项：根据列执行不同操作"""
        table = self.sender()
        folder_path = table.item(row, 0).data(Qt.UserRole)
        
        if not folder_path or not os.path.exists(folder_path):
            return
        
        # 根据列执行不同操作
        if column == 0:  # 双击编号列：打开文件夹
            os.startfile(folder_path)
        elif column == 1:  # 双击注释列：修改注释
            # 从内部存储获取当前注释
            current_comment = self.comments.get(folder_path, '')
            
            # 弹出对话框编辑注释
            folder_name = os.path.basename(folder_path)
            dialog = CommentEditDialog(f'编辑项目注释 - {folder_name}', current_comment, self)
            if dialog.exec_():
                new_comment = dialog.get_comment()
                # 如果注释有变化，更新内部存储
                if new_comment != current_comment:
                    if new_comment:
                        self.comments[folder_path] = new_comment
                    else:
                        # 如果注释为空，从存储中删除
                        self.comments.pop(folder_path, None)
                    # 保存注释
                    self.save_comments()
                    # 刷新文件夹列表
                    self.load_filtered_folders()
                    # 定位回原来的文件夹
                    self.locate_new_folder(folder_path)
    

    
    def on_file_clicked(self, index):
        file_path = self.file_model.filePath(index)
        file_info = self.file_model.fileInfo(index)
        if file_info.isFile():
            self.preview_file(file_path)
            self.extract_metadata(file_info)
        else:
            self.preview_tab.clear()
            self.metadata_tab.clear()
    
    def on_file_tree_context_menu(self, position):
        """文件树右键菜单"""
        index = self.file_tree.indexAt(position)
        menu = QMenu(self)

        if index.isValid():
            clicked_path = self.file_model.filePath(index)
            selected_paths = self._get_selected_file_paths()
            if clicked_path not in selected_paths:
                self._select_single_file_index(index)

            selected_paths = self._get_selected_file_paths()
            if not selected_paths:
                return

            multi_selected = len(selected_paths) > 1
            file_path = selected_paths[0]
            file_info = self.file_model.fileInfo(index)
            ext = os.path.splitext(file_path)[1].lower()
            is_archive = ext in ['.zip', '.rar', '.7z']

            copy_action = menu.addAction('复制')
            add_to_zip_action = menu.addAction('添加到zip压缩包')

            paste_copy_action = None
            rename_action = None
            extract_action = None
            recycle_action = None

            if not multi_selected:
                paste_copy_action = menu.addAction('粘贴副本')
                rename_action = menu.addAction('重命名')
                menu.addSeparator()
                if is_archive:
                    extract_action = menu.addAction('智能解压')
                menu.addSeparator()
                recycle_action = menu.addAction('移入回收站')
                paste_copy_action.setEnabled(self._has_pasteable_clipboard())
            else:
                menu.addSeparator()
                recycle_action = menu.addAction('移入回收站')

            action = menu.exec_(self.file_tree.viewport().mapToGlobal(position))

            if action == copy_action:
                self._copy_paths_to_clipboard(selected_paths)
            elif action == add_to_zip_action:
                if multi_selected:
                    self.add_paths_to_zip(selected_paths)
                else:
                    self.add_to_zip(file_path)
            elif not multi_selected and action == paste_copy_action:
                self.paste_copy(file_path)
            elif not multi_selected and action == rename_action:
                self.rename_item(file_path)
            elif not multi_selected and extract_action and action == extract_action:
                self.smart_extract(file_path)
            elif action == recycle_action:
                if multi_selected:
                    self._move_paths_to_recycle(selected_paths)
                else:
                    self.move_to_recycle(file_path)
        else:
            # 右键点击了空白区域
            paste_copy_action = menu.addAction('粘贴副本')
            paste_copy_action.setEnabled(self._has_pasteable_clipboard())

            action = menu.exec_(self.file_tree.viewport().mapToGlobal(position))

            if action == paste_copy_action:
                # 粘贴到当前文件夹
                if self.current_folder and os.path.exists(self.current_folder):
                    self.paste_copy(self.current_folder)
                else:
                    QMessageBox.warning(self, "警告", "请先选择一个项目文件夹")
    
    def _has_pasteable_clipboard(self):
        """剪贴板中是否有可粘贴的有效路径"""
        for p in (self.clipboard_paths or []):
            if os.path.exists(p):
                return True
        return bool(self.clipboard_path) and os.path.exists(self.clipboard_path)

    def paste_copy(self, target_path):
        """粘贴副本到目标路径，支持多选"""
        sources = [p for p in (self.clipboard_paths or []) if os.path.exists(p)]
        if not sources and self.clipboard_path and os.path.exists(self.clipboard_path):
            sources = [self.clipboard_path]
        if not sources:
            QMessageBox.warning(self, "警告", "剪贴板中没有有效的文件")
            return

        # 目标目录：若 target_path 是目录则用它，否则用其所在目录
        target_dir = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)

        pasted = 0
        errors = []
        for source in sources:
            try:
                self._paste_single(source, target_dir)
                pasted += 1
            except Exception as e:
                errors.append(f"{os.path.basename(source)}: {str(e)}")

        if errors:
            QMessageBox.warning(self, "错误", "粘贴副本失败:\n" + "\n".join(errors))
        if pasted == 1:
            self.statusBar().showMessage(f"已粘贴副本: {os.path.basename(sources[0])}")
        elif pasted > 1:
            self.statusBar().showMessage(f"已粘贴 {pasted} 个副本")

    def _paste_single(self, source_path, target_dir):
        """复制单个文件/文件夹到目标目录，处理重名"""
        base_name = os.path.basename(source_path)
        dest = os.path.join(target_dir, base_name)

        # 处理重名：如果目标已存在，则生成副本名称
        if os.path.exists(dest):
            name, ext = os.path.splitext(base_name)
            # 检查原文件名是否已以 "_副本数字" 结尾
            match = re.search(r'_副本(\d+)$', name)
            if match:
                # 原文件已经是副本，从该数字继续递增
                base_name_without_copy = name[:match.start()]
                counter = int(match.group(1)) + 1
            else:
                # 原文件不是副本，从1开始
                base_name_without_copy = name
                counter = 1
            while os.path.exists(dest):
                new_name = f"{base_name_without_copy}_副本{counter}{ext}"
                dest = os.path.join(target_dir, new_name)
                counter += 1

        if os.path.isdir(source_path):
            shutil.copytree(source_path, dest)
        else:
            shutil.copy2(source_path, dest)
    
    def rename_item(self, file_path):
        """重命名文件或文件夹"""
        try:
            old_name = os.path.basename(file_path)
            parent_dir = os.path.dirname(file_path)
            
            dialog = RenameDialog(file_path, self)
            if not dialog.exec_():
                return
            
            new_name = dialog.get_new_name()
            new_path = os.path.join(parent_dir, new_name)
            if os.path.exists(new_path):
                QMessageBox.warning(self, '警告', f'名称 "{new_name}" 已存在')
                return
            
            os.rename(file_path, new_path)
            self.statusBar().showMessage(f"已重命名: {old_name} -> {new_name}")
            
            # 如果重命名的是当前项目文件夹，更新current_folder
            if file_path == self.current_folder:
                self.current_folder = new_path
                self.file_model.setRootPath(new_path)
                self.file_tree.setRootIndex(self.file_model.index(new_path))
                self._update_folder_status_bar()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"重命名失败: {str(e)}")
    
    def add_to_zip(self, source_path):
        """将文件或文件夹添加到zip压缩包"""
        try:
            import zipfile

            parent_dir = os.path.dirname(source_path)
            base_name = os.path.basename(source_path)
            zip_path, zip_name = self._create_unique_zip_path(parent_dir, base_name)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                self._write_path_to_zip(zf, source_path, parent_dir)

            self.statusBar().showMessage(f"已创建压缩包: {zip_name}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"创建压缩包失败: {str(e)}")

    def add_paths_to_zip(self, source_paths):
        """将多个文件或文件夹添加到同一个zip压缩包"""
        valid_paths = []
        seen = set()
        for source_path in source_paths:
            normalized_path = os.path.normpath(source_path)
            if os.path.exists(source_path) and normalized_path not in seen:
                seen.add(normalized_path)
                valid_paths.append(source_path)

        if not valid_paths:
            QMessageBox.warning(self, "警告", "没有可压缩的文件或文件夹")
            return

        try:
            import zipfile

            parent_dirs = {os.path.dirname(path) for path in valid_paths}
            if len(parent_dirs) == 1:
                target_dir = parent_dirs.pop()
                base_dir = target_dir
            else:
                common_path = os.path.commonpath(valid_paths)
                base_dir = common_path if os.path.isdir(common_path) else os.path.dirname(common_path)
                target_dir = base_dir

            zip_path, zip_name = self._create_unique_zip_path(target_dir, '选中文件')

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for source_path in valid_paths:
                    self._write_path_to_zip(zf, source_path, base_dir)

            self.statusBar().showMessage(f"已创建压缩包: {zip_name}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"创建压缩包失败: {str(e)}")

    @staticmethod
    def _resource_path(relative_path):
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

    def _find_7z_tool(self):
        """查找7-Zip路径"""
        import os
        import sys
        
        # 优先使用用户指定的路径
        if hasattr(self, 'archive_tool_path') and self.archive_tool_path:
            if os.path.exists(self.archive_tool_path):
                return self.archive_tool_path
        
        # 7z.exe 可能的位置
        sevenzip_paths = []
        
        # 程序所在目录（支持打包后的exe）
        if hasattr(sys, '_MEIPASS'):
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
        sevenzip_paths.append(os.path.join(app_dir, '7z.exe'))
        
        # 7-Zip安装目录
        sevenzip_paths.extend([
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ])
        
        for path in sevenzip_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _extract_with_7z(self, archive_path, extract_dir):
        """使用7-Zip解压文件"""
        import subprocess
        
        sevenzip = self._find_7z_tool()
        if not sevenzip:
            raise Exception('未找到7-Zip，请在设置中指定7z.exe路径或安装7-Zip')
        
        cmd = [sevenzip, 'x', archive_path, f'-o{extract_dir}', '-y']
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='gbk', errors='ignore', startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
        
        if result.returncode != 0:
            raise Exception(f'7-Zip解压失败: {result.stderr or result.stdout}')
        
        return True
    
    def _list_archive_with_7z(self, archive_path):
        """使用7-Zip列出压缩包内容"""
        import subprocess
        import re
        
        sevenzip = self._find_7z_tool()
        if not sevenzip:
            raise Exception('未找到7-Zip')
        
        cmd = [sevenzip, 'l', '-slt', archive_path]
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='gbk', errors='ignore', startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
        
        if result.returncode != 0:
            raise Exception(f'读取压缩包失败: {result.stderr or result.stdout}')
        
        items = []
        lines = result.stdout.split('\n')
        current_item = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('Path = '):
                current_item['path'] = line[7:]
            elif line.startswith('Size = '):
                current_item['size'] = int(line[7:]) if line[7:].isdigit() else 0
            elif line.startswith('Attributes = '):
                attrs = line[13:]
                current_item['is_dir'] = 'D' in attrs
            elif line == '' and 'path' in current_item:
                # 排除压缩包本身
                if current_item['path'] != os.path.basename(archive_path):
                    items.append((current_item['path'], current_item.get('size', 0), current_item.get('is_dir', False)))
                current_item = {}
        
        return items
    
    def smart_extract(self, archive_path):
        """智能解压：单文件/单文件夹直接解压，多文件则创建同名文件夹"""
        try:
            ext = os.path.splitext(archive_path)[1].lower()
            parent_dir = os.path.dirname(archive_path)
            archive_name = os.path.splitext(os.path.basename(archive_path))[0]
            
            # 获取压缩包内容列表
            items = []
            if ext == '.zip':
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for info in zf.infolist():
                        try:
                            filename = info.filename.encode('cp437').decode('gbk')
                        except (UnicodeDecodeError, UnicodeEncodeError):
                            try:
                                filename = info.filename.encode('cp437').decode('utf-8')
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                filename = info.filename
                        items.append((filename, info.file_size, info.is_dir()))
            elif ext in ['.rar', '.7z']:
                # 使用7-Zip处理RAR和7z
                items = self._list_archive_with_7z(archive_path)
            
            if not items:
                QMessageBox.warning(self, '警告', '压缩包为空')
                return
            
            # 分析顶层项目
            top_items = set()
            for filename, size, is_dir in items:
                path = filename.replace('\\', '/')
                if path.endswith('/'):
                    top_items.add(path.rstrip('/').split('/')[0])
                else:
                    top_items.add(path.split('/')[0])
            
            # 决定解压路径
            if len(top_items) == 1:
                extract_dir = parent_dir
            else:
                extract_dir = os.path.join(parent_dir, archive_name)
                os.makedirs(extract_dir, exist_ok=True)
            
            # 执行解压
            if ext == '.zip':
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for info in zf.infolist():
                        try:
                            filename = info.filename.encode('cp437').decode('gbk')
                        except (UnicodeDecodeError, UnicodeEncodeError):
                            try:
                                filename = info.filename.encode('cp437').decode('utf-8')
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                filename = info.filename
                        
                        target_path = os.path.join(extract_dir, filename)

                        # 防 Zip-slip：归档内文件名可能含 ../，校验解压目标必须在 extract_dir 内
                        real_extract_dir = os.path.realpath(extract_dir)
                        real_target = os.path.realpath(target_path)
                        if real_target != real_extract_dir and not real_target.startswith(real_extract_dir + os.sep):
                            raise Exception(f'压缩包包含非法路径，已阻止解压: {filename}')

                        if info.is_dir():
                            os.makedirs(target_path, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            # 用 with 同时管理 source 与 target，确保异常时也释放读句柄
                            with zf.open(info) as source, open(target_path, 'wb') as target:
                                target.write(source.read())
            elif ext in ['.rar', '.7z']:
                self._extract_with_7z(archive_path, extract_dir)
            
            self.statusBar().showMessage(f"已解压到: {extract_dir}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"解压失败: {str(e)}")
    
    def _update_folder_status_bar(self):
        """更新状态栏显示当前项目文件夹信息"""
        if self.current_folder:
            folder_name = os.path.basename(self.current_folder)
            match = re.match(r'^([SM])(\d{3,4})(?:_(.*))?$', folder_name)
            if match:
                prefix = match.group(1)
                number = match.group(2)
                if prefix == 'S':
                    self.statusBar().showMessage(f"当前文件夹：S{number}")
                else:
                    self.statusBar().showMessage(f"当前文件夹：M{number}")
    
    def move_to_recycle(self, file_path):
        """移入回收站"""
        self._move_paths_to_recycle([file_path])
    
    def _open_with_shell(self, path):
        """用系统默认程序打开文件/文件夹，包含存在性检查与异常提示。
        os.path.exists 通过不保证 startfile 成功（无关联程序、权限、网络盘失联等仍会抛错）。"""
        if not os.path.exists(path):
            QMessageBox.warning(self, "警告", f"文件或文件夹不存在：{path}")
            return
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开：{os.path.basename(path)}\n{str(e)}")

    def on_file_double_clicked(self, index):
        """双击文件树项：直接打开文件或展开目录；双击空白区域打开当前文件夹"""
        if not index.isValid():
            # 双击空白区域：打开当前文件夹
            if self.current_folder:
                self._open_with_shell(self.current_folder)
        else:
            # 双击有效项：直接打开文件或文件夹
            file_path = self.file_model.filePath(index)
            self._open_with_shell(file_path)
    
    def new_project(self):
        # 获取默认新建项目文件夹
        # 1. 如果有项目文件路径，使用第一条的路径
        if hasattr(self, 'settings') and self.settings is not None and self.settings:
            # 默认使用项目文件路径的第一条的路径部分
            default_folder = self.settings[0][1]
        # 2. 否则使用用户主文件夹
        elif hasattr(self, 'default_new_project_folder') and self.default_new_project_folder:
            default_folder = self.default_new_project_folder
        else:
            default_folder = os.path.expanduser("~")
            
        dialog = NewProjectDialog(self, default_folder=default_folder)
        if dialog.exec_():
            project_info = dialog.get_project_info()
            self.load_filtered_folders()
            self.locate_new_folder(project_info['full_path'])
    
    def locate_new_folder(self, folder_path):
        folder_name = os.path.basename(folder_path)
        match = re.match(r'^([SM])(\d{3,4})(?:_(.*))?$', folder_name)
        if match:
            prefix = match.group(1)
            if prefix == 'S':
                table = self.motherboard_table
            else:
                table = self.daughterboard_table
            for row in range(table.rowCount()):
                row_path = table.item(row, 0).data(Qt.UserRole)
                if row_path == folder_path:
                    table.selectRow(row)
                    table.scrollToItem(table.item(row, 0))
                    self.current_folder = folder_path
                    self.file_tree.setRootIndex(self.file_model.index(folder_path))
                    self.new_structure_btn.setEnabled(True)
                    break
    
    def new_folder_structure(self):
        if not self.current_folder:
            QMessageBox.warning(self, '警告', '请先选择一个项目文件夹')
            return
        folder_name = os.path.basename(self.current_folder)
        match = re.match(r'^([SM])(\d{3,4})(?:_(.*))?$', folder_name)
        if not match:
            QMessageBox.warning(self, '警告', '当前选择的不是有效的项目文件夹')
            return
        try:
            dialog = NewStructureDialog(self.current_folder, self)
            if dialog.exec_():
                structure_info = dialog.get_structure_info()
                version = structure_info['version']
                all_folders = structure_info['selected_folders'] + structure_info['custom_folders']
                if not all_folders:
                    QMessageBox.warning(self, '警告', '请至少选择一个文件夹')
                    return
                version_folder = os.path.join(self.current_folder, f'V{version}')
                if not os.path.exists(version_folder):
                    os.makedirs(version_folder)
                created_count = 0
                for folder in all_folders:
                    folder_path = os.path.join(version_folder, folder)
                    if not os.path.exists(folder_path):
                        os.makedirs(folder_path)
                        created_count += 1
                if created_count > 0:
                    QMessageBox.information(self, '成功', f'已创建版本文件夹 V{version} 和 {created_count} 个子文件夹')
                else:
                    QMessageBox.information(self, '提示', f'版本文件夹 V{version} 已存在，所有子文件夹也已存在')
                self.file_tree.setRootIndex(self.file_model.index(self.current_folder))
        except Exception as e:
            QMessageBox.critical(self, '错误', f'创建子文件夹失败: {str(e)}')
    
    def _preview_text(self, file_path):
        # 先按 UTF-8 严格解码（不加 errors，否则非法字节被替换、永不抛异常，GBK 回退成死代码）；
        # 失败再尝试 GBK，最后兜底用 UTF-8 + replace 保证总能显示
        content = None
        for encoding in ('utf-8', 'gbk'):
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        self.preview_tab.setPlainText(content)

    def _preview_pdf(self, file_path):
        if not PdfReader:
            self.preview_tab.setPlainText('PDF文件预览功能需要安装PyPDF2库')
            return
        content = f'PDF文件: {os.path.basename(file_path)}\n\n'
        try:
            reader = PdfReader(file_path)
            content += f'页数: {len(reader.pages)}\n\n'
            for i, page in enumerate(reader.pages[:3]):
                content += f'第 {i+1} 页:\n{page.extract_text()}\n\n'
        except Exception as e:
            content += f'PDF读取错误: {str(e)}'
        self.preview_tab.setPlainText(content)

    def _get_preview_size(self):
        """获取预览区域可用尺寸"""
        container_size = self.preview_container.size()
        return container_size.width() - 20, container_size.height() - 20

    def _scale_image(self, image):
        """按预览区域缩放图片"""
        available_width, available_height = self._get_preview_size()
        return image.scaled(available_width, available_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _preview_image(self, file_path):
        try:
            self.preview_tab.hide()
            self.image_scroll_area.show()
            image = QImage(file_path)
            if image.isNull():
                self.preview_tab.show()
                self.image_scroll_area.hide()
                self.preview_tab.setPlainText(f'无法加载图片: {os.path.basename(file_path)}')
                return
            scaled_image = self._scale_image(image)
            pixmap = QPixmap.fromImage(scaled_image)
            self.image_label.setPixmap(pixmap)
            self.image_label.setToolTip(f'点击查看大图\n图片: {os.path.basename(file_path)}\n原始尺寸: {image.width()}x{image.height()}')
            self.current_image_path = file_path
        except Exception as e:
            self.preview_tab.show()
            self.image_scroll_area.hide()
            self.preview_tab.setPlainText(f'图片预览错误: {str(e)}')

    def _preview_video(self, file_path):
        try:
            self.preview_tab.hide()
            self.image_scroll_area.show()
            video_thumbnail = self.generate_video_thumbnail(file_path)
            if video_thumbnail:
                scaled_image = self._scale_image(video_thumbnail)
                pixmap = QPixmap.fromImage(scaled_image)
                self.image_label.setPixmap(pixmap)
                self.image_label.setToolTip(f'视频: {os.path.basename(file_path)}\n点击查看视频缩略图大图')
                self.current_image_path = file_path
            else:
                self.preview_tab.show()
                self.image_scroll_area.hide()
                if HAS_OPENCV:
                    self.preview_tab.setPlainText(f'视频: {os.path.basename(file_path)}\n无法生成视频缩略图')
                else:
                    self.preview_tab.setPlainText(f'视频: {os.path.basename(file_path)}\n视频缩略图功能需要安装OpenCV (pip install opencv-python numpy pillow)')
        except Exception as e:
            self.preview_tab.show()
            self.image_scroll_area.hide()
            self.preview_tab.setPlainText(f'视频预览错误: {str(e)}')

    def _build_file_tree(self, files):
        tree = {}
        for item in files:
            if hasattr(item, 'filename'):
                path = item.filename
                is_dir = path.endswith('/') or path.endswith('\\')
                size = item.file_size
            else:
                path = item.get('name', '')
                is_dir = item.get('folder', False)
                size = item.get('size', 0)
            path_parts = path.replace('\\', '/').rstrip('/').split('/')
            current = tree
            for i, part in enumerate(path_parts):
                if part not in current:
                    current[part] = {'_type': 'dir', '_children': {}, '_item': None}
                if i == len(path_parts) - 1:
                    if is_dir:
                        current[part]['_item'] = item
                    else:
                        current[part] = {'_type': 'file', '_size': size, '_item': item}
                else:
                    current = current[part]['_children']
        return tree

    def _build_file_tree_v2(self, files):
        """构建文件树（使用元组列表格式）"""
        tree = {}
        for filename, size, is_dir in files:
            path_parts = filename.replace('\\', '/').rstrip('/').split('/')
            current = tree
            for i, part in enumerate(path_parts):
                if not part:
                    continue
                if part not in current:
                    current[part] = {'_type': 'dir', '_children': {}, '_size': 0}
                if i == len(path_parts) - 1:
                    if is_dir:
                        current[part]['_type'] = 'dir'
                    else:
                        current[part] = {'_type': 'file', '_size': size, '_children': {}}
                else:
                    current = current[part]['_children']
        return tree

    def _print_tree(self, tree, prefix='', is_last=True):
        result = ''
        items = list(tree.items())
        for i, (name, node) in enumerate(items):
            is_last_item = i == len(items) - 1
            if node['_type'] == 'dir':
                result += f'{prefix}{"└── " if is_last_item else "├── "}{name}/\n'
                new_prefix = prefix + ("    " if is_last_item else "│   ")
                result += self._print_tree(node['_children'], new_prefix, is_last_item)
            else:
                result += f'{prefix}{"└── " if is_last_item else "├── "}{name} ({node["_size"] / 1024:.2f} KB)\n'
        return result

    def _preview_archive(self, file_path, ext):
        try:
            archive_info = f'压缩包: {os.path.basename(file_path)}\n\n'
            files_list = []
            total_size = 0
            if ext == '.zip':
                import zipfile
                with zipfile.ZipFile(file_path, 'r') as zf:
                    for item in zf.infolist():
                        try:
                            filename = item.filename.encode('cp437').decode('gbk')
                        except (UnicodeDecodeError, UnicodeEncodeError):
                            try:
                                filename = item.filename.encode('cp437').decode('utf-8')
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                filename = item.filename
                        files_list.append((filename, item.file_size, item.is_dir()))
                        total_size += item.file_size
            elif ext in ['.rar', '.7z']:
                items = self._list_archive_with_7z(file_path)
                for filename, size, is_dir in items:
                    files_list.append((filename, size, is_dir))
                    total_size += size
            
            file_tree = self._build_file_tree_v2(files_list)
            archive_info += f'文件总数: {len(files_list)}\n'
            archive_info += f'总大小: {total_size / 1024:.2f} KB\n\n'
            archive_info += '文件树结构:\n'
            archive_info += '=' * 60 + '\n'
            archive_info += self._print_tree(file_tree)
            self.preview_tab.setPlainText(archive_info)
        except Exception as e:
            self.preview_tab.setPlainText(f'压缩包预览错误: {str(e)}')

    def _preview_excel(self, file_path, ext):
        if ext == '.xlsx':
            if not load_workbook:
                self.preview_tab.setPlainText('Excel文件预览功能需要安装openpyxl库')
                return
            content = f'Excel文件: {os.path.basename(file_path)}\n\n'
            try:
                workbook = load_workbook(file_path, read_only=True)
                for sheet_name in workbook.sheetnames:
                    content += f'工作表: {sheet_name}\n'
                    worksheet = workbook[sheet_name]
                    for row in worksheet.iter_rows(min_row=1, max_row=10, values_only=True):
                        content += '\t'.join(str(cell) if cell is not None else '' for cell in row) + '\n'
                    content += '\n'
            except Exception as e:
                content += f'Excel读取错误: {str(e)}'
            self.preview_tab.setPlainText(content)
        elif ext == '.xlsm':
            if not load_workbook:
                self.preview_tab.setPlainText('Excel宏文件预览功能需要安装openpyxl库')
                return
            content = f'Excel宏文件: {os.path.basename(file_path)}\n\n'
            try:
                workbook = load_workbook(file_path, read_only=True, keep_vba=True)
                for sheet_name in workbook.sheetnames:
                    content += f'工作表: {sheet_name}\n'
                    worksheet = workbook[sheet_name]
                    for row in worksheet.iter_rows(min_row=1, max_row=10, values_only=True):
                        content += '\t'.join(str(cell) if cell is not None else '' for cell in row) + '\n'
                    content += '\n'
            except Exception as e:
                content += f'Excel宏文件读取错误: {str(e)}'
            self.preview_tab.setPlainText(content)
        elif ext == '.xls':
            if not xlrd:
                self.preview_tab.setPlainText('Excel 97-2003文件预览功能需要安装xlrd库')
                return
            content = f'Excel文件(97-2003): {os.path.basename(file_path)}\n\n'
            try:
                workbook = xlrd.open_workbook(file_path)
                for sheet_idx in range(workbook.nsheets):
                    sheet = workbook.sheet_by_index(sheet_idx)
                    content += f'工作表: {sheet.name}\n'
                    max_rows = min(sheet.nrows, 10)
                    for row_idx in range(max_rows):
                        row_data = [str(sheet.cell(row_idx, col_idx).value) for col_idx in range(sheet.ncols)]
                        content += '\t'.join(row_data) + '\n'
                    content += '\n'
            except Exception as e:
                content += f'Excel读取错误: {str(e)}'
            self.preview_tab.setPlainText(content)

    def _preview_word(self, file_path, ext):
        if ext == '.docx':
            if not Document:
                self.preview_tab.setPlainText('Word文件预览功能需要安装python-docx库')
                return
            content = f'Word文件: {os.path.basename(file_path)}\n\n'
            try:
                doc = Document(file_path)
                for para in doc.paragraphs[:20]:
                    content += para.text + '\n'
            except Exception as e:
                content += f'Word读取错误: {str(e)}'
            self.preview_tab.setPlainText(content)
        elif ext == '.doc':
            if not olefile:
                self.preview_tab.setPlainText('Word 97-2003文件预览功能需要安装olefile库')
                return
            content = f'Word文件(97-2003): {os.path.basename(file_path)}\n\n'
            try:
                ole = olefile.OleFileIO(file_path)
                if ole.exists('WordDocument'):
                    stream = ole.openstream('WordDocument')
                    data = stream.read()
                    text_parts = [chr(b) for b in data if 32 <= b < 127 or b in (10, 13, 9)]
                    text = ''.join(text_parts)
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    content += '\n'.join(lines[:50])
                ole.close()
            except Exception as e:
                content += f'Word 97-2003读取错误: {str(e)}'
            self.preview_tab.setPlainText(content)

    def _preview_binary(self, file_path, ext):
        content = f'文件: {os.path.basename(file_path)}\n\n不支持的文件格式: {ext}\n\n文件前1000字节:\n\n'
        with open(file_path, 'rb') as f:
            content += f.read(1000).hex(' ')
        self.preview_tab.setPlainText(content)

    def preview_file(self, file_path):
        try:
            ext = os.path.splitext(file_path)[1].lower()
            text_exts = ['.txt', '.csv', '.log', '.bom', '.drc', '.rep', '.rpt', '.md', '.json', '.xml', '.html', '.htm', '.ini', '.cfg']
            image_exts = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif', '.webp', '.svg']
            video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.webm', '.mpg', '.mpeg', '.3gp']
            archive_exts = ['.zip', '.rar', '.7z']

            self.preview_tab.show()
            self.image_scroll_area.hide()

            if ext in text_exts or ext in ['.bom', '.drc', '.rep', '.rpt']:
                self._preview_text(file_path)
            elif ext == '.pdf':
                self._preview_pdf(file_path)
            elif ext in image_exts:
                self._preview_image(file_path)
            elif ext in video_exts:
                self._preview_video(file_path)
            elif ext in archive_exts:
                self._preview_archive(file_path, ext)
            elif ext in ['.xlsx', '.xlsm', '.xls']:
                self._preview_excel(file_path, ext)
            elif ext in ['.docx', '.doc']:
                self._preview_word(file_path, ext)
            elif ext not in ['.opj', '.dsn', '.sch', '.brd', '.dbk', '.dsnlck']:
                self._preview_binary(file_path, ext)
            else:
                self.preview_tab.setPlainText(f'该文件类型（{ext}）涉及加密，无法预览')
        except Exception as e:
            self.preview_tab.setPlainText(f'预览文件时出错: {str(e)}')
    
    def extract_metadata(self, file_info):
        metadata = [
            f'文件名: {file_info.fileName()}',
            f'路径: {file_info.absoluteFilePath()}',
            f'大小: {self.format_file_size(file_info.size())}',
            f'创建时间: {file_info.created().toString()}',
            f'修改时间: {file_info.lastModified().toString()}',
            f'访问时间: {file_info.lastRead().toString()}',
            f'是否为文件: {file_info.isFile()}',
            f'是否为目录: {file_info.isDir()}',
            f'是否可读: {file_info.isReadable()}',
            f'是否可写: {file_info.isWritable()}',
        ]
        self.metadata_tab.setPlainText('\n'.join(metadata))
    
    def format_file_size(self, size):
        if size < 1024:
            return f'{size} B'
        elif size < 1024 * 1024:
            return f'{size / 1024:.2f} KB'
        elif size < 1024 * 1024 * 1024:
            return f'{size / (1024 * 1024):.2f} MB'
        else:
            return f'{size / (1024 * 1024 * 1024):.2f} GB'
    
    def show_about(self):
        about_text = 'SeavoExplorer - 主板项目文件浏览器\n\n版本 0.2'
        # 关于页 logo 优先用高清 PNG 源（清晰放大），回退到多尺寸 ico
        png_path = self._resource_path('favicon_src.png')
        ico_path = self._resource_path('favicon.ico')
        pixmap = None
        if os.path.exists(png_path):
            pixmap = QPixmap(png_path)
        elif os.path.exists(ico_path):
            pixmap = QIcon(ico_path).pixmap(128, 128)

        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            msg = QMessageBox(self)
            msg.setWindowTitle('关于')
            msg.setText(about_text)
            msg.setIconPixmap(scaled)
            msg.exec_()
        else:
            QMessageBox.about(self, '关于', about_text)
    
    def show_wizard(self):
        """打开新手向导，并标记为已显示。"""
        dialog = WizardDialog(self)
        dialog.exec_()
        if not getattr(self, 'wizard_shown', False):
            self.wizard_shown = True
            self.save_settings_to_file(self.settings, self.include_subfolders)

    def show_help(self):
        help_dialog = QDialog(self)
        help_dialog.setWindowTitle('使用帮助')
        help_dialog.setGeometry(200, 100, 700, 600)
        layout = QVBoxLayout(help_dialog)
        
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml('''
<h2 style="color: #2c3e50;">SeavoExplorer 使用帮助</h2>
<p style="color: #7f8c8d;">主板/子卡项目文件浏览器 —— 快速定位项目、预览工程文档、整理版本目录。
首次使用建议先看 <b>帮助 → 新手向导</b>。</p>

<h3 style="color: #2980b9;">一、项目文件夹管理</h3>
<p><b>1. 配置项目根目录</b></p>
<p>点击菜单 <b>设置 → 项目文件夹设置</b>，添加一个或多个包含项目文件夹的根目录。程序会自动扫描这些目录下符合命名规则的文件夹。</p>
<p>命名规则：以 <b>S</b>（主板）或 <b>M</b>（子卡）开头，后跟 <b>3~4 位数字</b>，可选 <code>_注释</code> 后缀。例如：<code>S001</code>、<code>M1234</code>、<code>S002_样机</code>、<code>M003_说明</code>。</p>
<ul>
<li>勾选<b>"包含子文件夹"</b>：递归扫描子目录中的项目文件夹</li>
<li>勾选<b>"按编号排序"</b>：忽略来源目录分组，所有项目统一按编号大小排序；不勾选时先按根目录添加顺序分组，组内再按编号排序</li>
</ul>

<p><b>2. 项目列表操作</b></p>
<ul>
<li><b>单击</b>项目行：在右侧文件树中显示该项目的文件</li>
<li><b>双击编号列</b>：在系统资源管理器中打开该项目文件夹</li>
<li><b>双击注释列</b>：编辑项目注释（自动保存到 <code>seavo_comments.json</code>）</li>
<li><b>右键项目行</b>：置顶 / 取消置顶。置顶项以加粗显示并排在列表前部</li>
<li><b>文件夹搜索框</b>：输入关键词实时过滤项目列表</li>
</ul>
<p style="color: #7f8c8d;">注释显示优先级：若 <code>seavo_comments.json</code> 中对该文件夹有注释则优先显示，否则使用文件夹名的 <code>_注释</code> 后缀。</p>

<h3 style="color: #2980b9;">二、文件浏览与操作</h3>
<p><b>1. 文件浏览</b></p>
<ul>
<li>单击文件：在下方<b>文件预览</b>区显示内容；<b>元数据</b>标签页显示大小、创建/修改时间等详情</li>
<li>双击文件：用系统默认程序打开</li>
<li>双击文件夹：在资源管理器中打开</li>
<li>双击空白区域：在资源管理器中打开当前项目文件夹</li>
</ul>

<p><b>2. 多选操作</b></p>
<p>文件树支持多选：按住 <b>Ctrl</b> 点选多个项目，或按住 <b>Shift</b> 选择连续范围。多选后可批量复制、删除、压缩。</p>

<p><b>3. 右键菜单</b></p>
<p>选中<b>单个</b>文件/文件夹时：</p>
<ul>
<li><b>复制</b>：复制到剪贴板，既可在资源管理器中粘贴，也可用程序内"粘贴副本"</li>
<li><b>粘贴副本</b>：把剪贴板中的内容复制到当前位置，自动处理重名（追加 <code>_副本N</code>）</li>
<li><b>重命名</b>：重命名文件或文件夹（也可按 F2）</li>
<li><b>添加到zip压缩包</b>：压缩为同名 .zip 文件</li>
<li><b>智能解压</b>：仅对 .zip/.rar/.7z 显示</li>
<li><b>移入回收站</b>：移入系统回收站</li>
</ul>
<p>选中<b>多个</b>项目时，菜单仅保留可批量执行的项：<b>复制</b>、<b>添加到zip压缩包</b>、<b>移入回收站</b>。</p>
<p>在<b>空白处</b>右键：仅显示<b>粘贴副本</b>，粘贴到当前项目文件夹。</p>

<p><b>4. 复制与粘贴的目标规则</b></p>
<ul>
<li>复制（单个或多个）后，"粘贴副本"会把<b>全部</b>已复制项粘到目标位置</li>
<li>粘贴时若<b>选中了一个文件夹</b>，粘贴到该文件夹内；若选中的是文件，则粘到其所在目录</li>
<li>若<b>选中了多个</b>项目，则粘贴到当前项目根文件夹</li>
</ul>

<h3 style="color: #2980b9;">三、文件预览</h3>
<p>单击文件树中的文件，下方预览区会自动显示内容：</p>
<table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #ecf0f1;"><th>文件类型</th><th>支持格式</th><th>说明</th></tr>
<tr><td>文本文件</td><td>.txt .csv .log .bom .drc .rep .rpt .md .json .xml .html .htm .ini .cfg</td><td>直接显示文本（UTF-8/GBK 自动识别）</td></tr>
<tr><td>PDF 文件</td><td>.pdf</td><td>多页预览，可翻页查看</td></tr>
<tr><td>Excel 文件</td><td>.xlsx .xlsm .xls</td><td>表格形式预览</td></tr>
<tr><td>Word 文件</td><td>.docx .doc</td><td>文档内容预览</td></tr>
<tr><td>图片文件</td><td>.jpg .jpeg .png .bmp .gif .tiff .tif .webp .svg</td><td>缩略图预览，点击查看大图</td></tr>
<tr><td>视频文件</td><td>.mp4 .avi .mov .mkv .flv .wmv .m4v .webm .mpg .mpeg .3gp</td><td>显示视频缩略图（需 OpenCV）</td></tr>
<tr><td>压缩包</td><td>.zip .rar .7z</td><td>树状结构显示内容</td></tr>
</table>
<p style="color: #7f8c8d;">加密工程文件（.opj .dsn .sch .brd .dbk .dsnlck）无法预览，会显示提示信息而非二进制内容；请用对应 EDA 软件打开。</p>

<h3 style="color: #2980b9;">四、压缩包操作</h3>
<p><b>1. 智能解压</b></p>
<p>右键压缩包选择"智能解压"，程序自动判断：</p>
<ul>
<li>包内只有一个顶层项目 → 直接解压到当前目录</li>
<li>包内有多个顶层项目 → 创建与压缩包同名的文件夹，解压到其中（避免文件散落）</li>
</ul>
<p>.zip 使用内置解压；.rar / .7z 需要 7-Zip 支持。</p>

<p><b>2. 添加到 zip 压缩包</b></p>
<ul>
<li>选中单个项目：在同目录下生成同名 .zip（重名时自动追加序号）</li>
<li>选中多个项目：一并打包为一个 .zip</li>
</ul>

<p><b>3. 7-Zip 路径设置</b></p>
<p>菜单 <b>设置 → 7-Zip路径设置</b> 可手动指定 7z.exe。程序按以下顺序自动查找：</p>
<ol>
<li>设置中手动指定的路径</li>
<li>程序所在目录下的 7z.exe</li>
<li>C:\\Program Files\\7-Zip\\7z.exe</li>
<li>C:\\Program Files (x86)\\7-Zip\\7z.exe</li>
</ol>

<h3 style="color: #2980b9;">五、快捷访问栏</h3>
<p>菜单栏下方的快捷访问栏提供常用文件夹的快速入口：</p>
<ul>
<li><b>普通按钮</b>（默认样式）：点击后在文件树中显示该文件夹内容</li>
<li><b>不显示预览按钮</b>（灰色斜体）：点击后直接在资源管理器中打开</li>
</ul>
<p style="color: #7f8c8d;">提示：磁盘根目录、网络文件夹等大目录建议设为"不显示预览"，避免文件树加载缓慢。</p>
<p>菜单 <b>设置 → 快捷访问设置</b> 可添加、删除、排序快捷项，并为每项设置名称、路径和是否不显示预览。</p>

<h3 style="color: #2980b9;">六、新建项目与版本结构</h3>
<p><b>1. 新建项目文件夹</b></p>
<p>点击左侧<b>"新建项目文件夹"</b>，选择类型（S/M）、输入编号和保存位置，程序自动创建符合命名规则的项目文件夹。</p>
<p><b>2. 新建文件夹内部结构</b></p>
<p>选中一个项目后，点击<b>"新建文件夹内部结构"</b>，可创建版本文件夹（如 V01）及标准子文件夹（BOM、SCH、物料、评审、信号测试），也可自定义子文件夹。上次选择的模板会被记住。</p>

<h3 style="color: #2980b9;">七、快捷键</h3>
<table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #ecf0f1;"><th>快捷键</th><th>功能</th></tr>
<tr><td>F5</td><td>刷新项目列表和文件树</td></tr>
<tr><td>F2</td><td>重命名文件树中选中的单个文件/文件夹</td></tr>
<tr><td>Ctrl+C</td><td>复制选中的文件/文件夹（支持多选）</td></tr>
<tr><td>Ctrl+V</td><td>粘贴副本到选中文件夹或当前项目</td></tr>
<tr><td>Delete</td><td>将选中的文件/文件夹移入回收站（支持多选）</td></tr>
</table>

<h3 style="color: #2980b9;">八、其他</h3>
<ul>
<li><b>回收站</b>：状态栏右侧的回收站按钮可快速打开系统回收站</li>
<li><b>新手向导</b>：菜单 <b>帮助 → 新手向导</b> 随时重新查看核心功能介绍</li>
<li><b>设置持久化</b>：所有设置（项目路径、快捷访问、7-Zip 路径、排序选项等）自动保存到配置文件，下次启动自动加载</li>
</ul>
''')
        
        layout.addWidget(help_text)
        
        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(help_dialog.close)
        layout.addWidget(close_btn)
        
        help_dialog.exec_()
    
    def show_full_image(self, event):
        """点击图片或视频缩略图时显示大图"""
        if not hasattr(self, 'current_image_path') or not self.current_image_path:
            return
        
        try:
            ext = os.path.splitext(self.current_image_path)[1].lower()
            image_exts = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif', '.webp', '.svg']
            video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.webm', '.mpg', '.mpeg', '.3gp']
            
            # 创建对话框
            dialog = QDialog(self)
            dialog.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMaximizeButtonHint)
            
            # 创建滚动区域
            scroll_area = QScrollArea(dialog)
            scroll_area.setWidgetResizable(True)
            
            if ext in image_exts:
                # 处理图片文件
                dialog.setWindowTitle(f'图片查看 - {os.path.basename(self.current_image_path)}')
                image = QImage(self.current_image_path)
                if image.isNull():
                    return
                pixmap = QPixmap.fromImage(image)
            elif ext in video_exts:
                # 处理视频文件（显示大图缩略图）
                dialog.setWindowTitle(f'视频缩略图 - {os.path.basename(self.current_image_path)}')
                video_thumbnail = self.generate_video_thumbnail(self.current_image_path)
                if not video_thumbnail:
                    return
                pixmap = QPixmap.fromImage(video_thumbnail)
            else:
                return
            
            # 显示图片/缩略图
            image_label = QLabel()
            image_label.setPixmap(pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            
            scroll_area.setWidget(image_label)
            
            # 设置布局
            layout = QVBoxLayout(dialog)
            layout.addWidget(scroll_area)
            layout.setContentsMargins(0, 0, 0, 0)
            
            # 设置初始大小为屏幕的70%
            screen_size = QApplication.desktop().screenGeometry()
            dialog.resize(int(screen_size.width() * 0.7), int(screen_size.height() * 0.7))
            
            dialog.exec_()
        except Exception as e:
            QMessageBox.warning(self, '警告', f'无法显示大图: {str(e)}')
    
    def generate_video_thumbnail(self, video_path, size=(320, 240)):
        """生成视频缩略图"""
        if not HAS_OPENCV:
            return None
            
        try:
            # 打开视频文件
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None
            
            # 获取视频总帧数
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 选择中间帧作为缩略图
            frame_to_capture = total_frames // 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_to_capture)
            
            # 读取帧
            ret, frame = cap.read()
            cap.release()
            
            if not ret:
                # 如果中间帧读取失败，尝试读取第一帧
                cap = cv2.VideoCapture(video_path)
                ret, frame = cap.read()
                cap.release()
                if not ret:
                    return None
            
            # 转换颜色空间（OpenCV使用BGR，Qt使用RGB）
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 转换为QImage
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)

            # copy() 让 QImage 拥有独立内存，否则它共享的 frame_rgb 缓冲在函数返回后被回收，
            # 留下悬空指针（缩略图花屏甚至崩溃）
            return q_image.copy()
        except Exception as e:
            return None
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F5:
            self.load_filtered_folders()
            if self.current_folder:
                self.file_model.setRootPath(self.current_folder)
                self.file_tree.setRootIndex(self.file_model.index(self.current_folder))
        elif event.key() == Qt.Key_F2:
            selected_paths = self._get_selected_file_paths()
            if len(selected_paths) == 1:
                self.rename_item(selected_paths[0])
            elif len(selected_paths) > 1:
                self.statusBar().showMessage("请选择单个文件或文件夹进行重命名")
            else:
                selected_path = self._get_primary_selected_file_path()
                if selected_path:
                    self.rename_item(selected_path)
        elif event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self.copy_selected_items()
        elif event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
            self.paste_to_selected_target()
        elif event.key() == Qt.Key_Delete:
            selected_paths = self._get_selected_file_paths()
            if len(selected_paths) > 1:
                self._move_paths_to_recycle(selected_paths)
            else:
                selected_path = self._get_primary_selected_file_path()
                if selected_path:
                    self.move_to_recycle(selected_path)
        else:
            super().keyPressEvent(event)

if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)

        # 设置全局界面字体：优先使用系统中可用的清晰字体
        apply_app_font(app)

        # 创建启动画面（使用预渲染缓存）
        splash = QSplashScreen(get_splash_pixmap())
        splash.setStyleSheet("""
            QSplashScreen {
                border: 2px solid #E94A16;
                border-radius: 10px;
                background-color: black;
            }
        """)
        splash.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint)
        splash.showMessage("正在初始化程序...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
        splash.show()

        # 显示启动画面
        app.processEvents()
        
        # 初始化主窗口（在后台进行）
        window = MainWindow()

        # 显示主窗口
        window.show()

        # 确保窗口获得焦点并显示在最前面
        window.raise_()
        window.activateWindow()
        if window.windowState() & Qt.WindowMinimized:
            window.setWindowState(window.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)

        # 关闭启动画面
        splash.finish(window)
        
        sys.exit(app.exec_())
    except Exception as e:
        error_msg = "程序异常退出: {}\n\n详细信息:\n{}".format(str(e), traceback.format_exc())
        print(error_msg)
        try:
            with open('error_details.log', 'w', encoding='utf-8') as f:
                f.write(error_msg)
        except:
            pass
        sys.exit(1)