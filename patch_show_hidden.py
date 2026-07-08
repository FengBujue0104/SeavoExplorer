import sys

path = r'D:\Desktop\py-script\ohmypi\main.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

patches = [
    # 1. Add QAction import
    (
        'QCheckBox, QComboBox, QListWidget, QListWidgetItem)\nfrom PyQt5.QtGui',
        'QCheckBox, QComboBox, QListWidget, QListWidgetItem,\n                                QAction)\nfrom PyQt5.QtGui'
    ),
    # 2. Add menu toggle after 预览设置
    (
        "settings_menu.addAction('预览设置', self.show_preview_settings_dialog)\n        settings_menu.addAction('恢复已隐藏项目'",
        "settings_menu.addAction('预览设置', self.show_preview_settings_dialog)\n        self.show_hidden_action = QAction('显示隐藏文件', self, checkable=True)\n        self.show_hidden_action.setChecked(getattr(self, 'show_hidden', False))\n        self.show_hidden_action.triggered.connect(self._on_toggle_show_hidden)\n        settings_menu.addAction(self.show_hidden_action)\n        settings_menu.addAction('恢复已隐藏项目'"
    ),
    # 3. Insert methods before _init_default_settings
    (
        '    def _init_default_settings(self):\n        """初始化默认设置"""\n        self.project_paths = []\n        self.include_subfolders = False\n        self.sort_by_number = False',
        '    def _on_toggle_show_hidden(self, checked):\n        self.show_hidden = checked\n        self.save_settings_to_file(self.settings, self.include_subfolders)\n        if self.current_folder:\n            self._apply_hidden_files_filter()\n            self.refresh_file_tree()\n\n    def _apply_hidden_files_filter(self):\n        """根据 show_hidden 设置更新文件模型过滤器。"""\n        if getattr(self, \'show_hidden\', False):\n            self.file_model.setFilter(QDir.NoDotAndDotDot | QDir.AllEntries | QDir.Hidden)\n        else:\n            self.file_model.setFilter(QDir.NoDotAndDotDot | QDir.AllEntries)\n\n    def _init_default_settings(self):\n        """初始化默认设置"""\n        self.project_paths = []\n        self.include_subfolders = False\n        self.sort_by_number = False\n        self.show_hidden = False'
    ),
    # 4. Add apply filter after load_settings return
    (
        '        return self.project_paths\n\n    def make_file_hidden(self, file_path):',
        '        return self.project_paths\n\n        # 启动时应用隐藏文件过滤器\n        QTimer.singleShot(0, self._apply_hidden_files_filter)\n\n    def make_file_hidden(self, file_path):'
    ),
]

for old, new in patches:
    if old in content:
        content = content.replace(old, new)
        print(f"OK - patched: {old[:50]}...")
    else:
        print(f"NOT FOUND: {old[:50]}...")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
