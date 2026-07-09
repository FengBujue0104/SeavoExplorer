import io

path = r"D:\Desktop\py-script\ohmypi\main.py"
with io.open(path, 'r', encoding='utf8') as f:
    content = f.read()

# Fix 1: Add MAX_FILES and MAX_MATCHES_WARNING constants to FolderScanThread
OLD = """class FolderScanThread(QThread):
    \"\"\"文件夹扫描线程，用于异步加载项目文件夹\"\"\"
    scan_completed = pyqtSignal(list, list)  # 发射(主板文件夹列表, 子卡文件夹列表)
    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(str)  # 发射当前扫描的目录
    
    def __init__(self, settings, include_subfolders, comments, sort_by_number=False, mb_regex=None, db_regex=None):"""
NEW = """class FolderScanThread(QThread):
    \"\"\"文件夹扫描线程，用于异步加载项目文件夹\"\"\"
    scan_completed = pyqtSignal(list, list)  # 发射(主板文件夹列表, 子卡文件夹列表)
    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(str)  # 发射当前扫描的目录

    MAX_FILES = 50000
    MAX_MATCHES_WARNING = 500

    def __init__(self, settings, include_subfolders, comments, sort_by_number=False, mb_regex=None, db_regex=None):"""
assert OLD in content, "Fix 1 pattern not found"
content = content.replace(OLD, NEW, 1)
print("OK Fix 1 - FolderScanThread constants added")

# Fix 2: Add _on_regex_mode_changed method and radio button signal connections
OLD = """    def _test_regex(self):
        \"\"\"实时验证两个自定义正则并更新状态标签。\"\"\"
        if self.regex_state == 'default':
            self.regex_status_label.setText(f'✅ 使用默认：主板 {DEFAULT_MB_RE_TEXT}，子卡 {DEFAULT_DB_RE_TEXT}')
            self.regex_status_label.setStyleSheet('color: #27ae60;')
            return
        mb_text = self.regex_mb_edit.text().strip()
        db_text = self.regex_db_edit.text().strip()
        errors = []
        if not mb_text:
            errors.append('主板正则不能为空')
        try:
            re.compile(mb_text)
        except re.error as e:
            errors.append(f'主板正则无效: {e}')
        if not db_text:
            errors.append('子卡正则不能为空')
        try:
            re.compile(db_text)
        except re.error as e:
            errors.append(f'子卡正则无效: {e}')
        if errors:
            self.regex_status_label.setText('❌ ' + '; '.join(errors) + '（保存后将回退到默认）')
            self.regex_status_label.setStyleSheet('color: #c0392b;')
        else:
            self.regex_status_label.setText(f'✅ 主板: {mb_text}  |  子卡: {db_text}')
            self.regex_status_label.setStyleSheet('color: #27ae60;')

    def add_path(self):"""
NEW = """    def _test_regex(self):
        \"\"\"实时验证两个自定义正则并更新状态标签。\"\"\"
        if self.regex_state == 'default':
            self.regex_status_label.setText(f'✅ 使用默认：主板 {DEFAULT_MB_RE_TEXT}，子卡 {DEFAULT_DB_RE_TEXT}')
            self.regex_status_label.setStyleSheet('color: #27ae60;')
            return
        mb_text = self.regex_mb_edit.text().strip()
        db_text = self.regex_db_edit.text().strip()
        errors = []
        if not mb_text:
            errors.append('主板正则不能为空')
        try:
            re.compile(mb_text)
        except re.error as e:
            errors.append(f'主板正则无效: {e}')
        if not db_text:
            errors.append('子卡正则不能为空')
        try:
            re.compile(db_text)
        except re.error as e:
            errors.append(f'子卡正则无效: {e}')
        if errors:
            self.regex_status_label.setText('❌ ' + '; '.join(errors) + '（保存后将回退到默认）')
            self.regex_status_label.setStyleSheet('color: #c0392b;')
        else:
            self.regex_status_label.setText(f'✅ 主板: {mb_text}  |  子卡: {db_text}')
            self.regex_status_label.setStyleSheet('color: #27ae60;')

    def _on_regex_mode_changed(self, state):
        \"\"\"Radio button clicked - update state and refresh UI.\"\"\"
        self.regex_state = state
        self._refresh_regex_ui()

    def add_path(self):"""
assert OLD in content, "Fix 2a pattern not found"
content = content.replace(OLD, NEW, 1)
print("OK Fix 2a - _on_regex_mode_changed method added")

# Fix 2b: Connect radio button signals
OLD = "        # 初始化 UI 状态\n        self._refresh_regex_ui()"
NEW = """        # 初始化 UI 状态
        self.regex_custom_rb.clicked.connect(lambda: self._on_regex_mode_changed('custom'))
        self.regex_default_rb.clicked.connect(lambda: self._on_regex_mode_changed('default'))
        self._refresh_regex_ui()"""
assert OLD in content, "Fix 2b pattern not found"
content = content.replace(OLD, NEW, 1)
print("OK Fix 2b - radio button signals connected")

# Fix 3: show_settings_dialog - assign regex values before save_settings_to_file
OLD = "            self.show_hidden = new_show_hidden\n            if self.save_settings_to_file(new_paths, new_include_subfolders):"
NEW = """            self.show_hidden = new_show_hidden
            self.regex_state = new_regex_state
            self.custom_mb_regex = new_custom_mb_regex
            self.custom_db_regex = new_custom_db_regex
            if self.save_settings_to_file(new_paths, new_include_subfolders):"""
assert OLD in content, "Fix 3 pattern not found"
content = content.replace(OLD, NEW, 1)
print("OK Fix 3 - show_settings_dialog assigns regex before save")

# Verify syntax
import ast
try:
    ast.parse(content)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")

with io.open(path, 'w', encoding='utf8') as f:
    f.write(content)
print("DONE")
