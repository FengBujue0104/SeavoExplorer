import io

path = r"D:\Desktop\py-script\ohmypi\main.py"
with io.open(path, 'r', encoding='utf8') as f:
    src = f.read()

# 1. QAction import
old = "                                QCheckBox, QComboBox, QListWidget, QListWidgetItem)"
new = "                                QCheckBox, QComboBox, QListWidget, QListWidgetItem,\n                                QAction)"
src = src.replace(old, new, 1)

# 2. Insert show_hidden menu toggle into create_menu
old = "        settings_menu.addAction('恢复已隐藏项目', self.show_restore_hidden_projects_dialog)"
new = ("        self.show_hidden_action = QAction('显示隐藏文件', self, checkable=True)\n"
       "        self.show_hidden_action.setChecked(getattr(self, 'show_hidden', False))\n"
       "        self.show_hidden_action.triggered.connect(self._on_toggle_show_hidden)\n"
       "        settings_menu.addAction(self.show_hidden_action)\n"
       "        settings_menu.addAction('恢复已隐藏项目', self.show_restore_hidden_projects_dialog)")
src = src.replace(old, new, 1)

# 3. Insert _on_toggle_show_hidden + refresh_file_tree into init
old = "    def _init_default_settings(self):\n        \"\"\"初始化默认设置\"\"\""
new = ("    def _on_toggle_show_hidden(self, checked):\n"
       "        self.show_hidden = checked\n"
       "        self.save_settings_to_file(self.settings, self.include_subfolders)\n"
       "        if self.current_folder:\n"
       "            self._apply_hidden_files_filter()\n"
       "            self.refresh_file_tree()\n"
       "\n"
       "    def refresh_file_tree(self):\n"
       "        \"\"\"刷新文件树显示（重新应用过滤器）。\"\"\"\n"
       "        if not self.current_folder:\n"
       "            return\n"
       "        self.file_model.setRootPath(QDir().rootPath())\n"
       "        QApplication.processEvents()\n"
       "        self.file_model.setRootPath(self.current_folder)\n"
       "        self.file_tree.setRootIndex(self.file_model.index(self.current_folder))\n"
       "\n"
       "    def _init_default_settings(self):\n"
       "        \"\"\"初始化默认设置\"\"\"")
src = src.replace(old, new, 1)

with io.open(path, 'w', encoding='utf8') as f:
    f.write(src)

print("Patched. Test:  py main.py")
