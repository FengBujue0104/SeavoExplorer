import os
import sys
import traceback

from PyQt5.QtCore import QEventLoop, QPoint, QTimer, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit, QMenu, QMessageBox, QTreeView

import main

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_BASE = os.environ.get('VERIFY_FIXTURE_BASE', os.path.dirname(BASE_DIR))
PROJECT_DIR = os.path.join(FIXTURE_BASE, 'projects', 'root', 'S1001_alpha')
FILE_A = os.path.join(PROJECT_DIR, 'SubA', 'a.txt')
FILE_B = os.path.join(PROJECT_DIR, 'SubB', 'b.txt')
DIR_C = os.path.join(PROJECT_DIR, 'SubDir')
PASTE_TARGET = os.path.join(PROJECT_DIR, 'PasteTarget')
SOURCE_FILE = os.path.join(PROJECT_DIR, 'source.txt')
RENAMED_SOURCE = os.path.join(PROJECT_DIR, 'source_renamed.txt')
PASTED_COPY = os.path.join(PASTE_TARGET, 'source_renamed.txt')

results = []
message_calls = []
rename_dialog_opened = []
orig_warning = QMessageBox.warning
orig_information = QMessageBox.information
orig_critical = QMessageBox.critical
orig_exec = QMenu.exec_
orig_rename_exec = main.RenameDialog.exec_
orig_rename_get = main.RenameDialog.get_new_name


def log(name, ok, detail):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec_()


def wait_for(condition, timeout=8000, interval=50):
    deadline = timeout // interval
    for _ in range(deadline):
        QApplication.processEvents()
        if condition():
            return True
        wait(interval)
    QApplication.processEvents()
    return bool(condition())


def record_message(kind, title, text):
    message_calls.append((kind, title, text))
    print(f"MESSAGE {kind}: {title} | {text}")
    return QMessageBox.Ok


def warning_stub(parent, title, text, *args, **kwargs):
    return record_message('warning', title, text)


def information_stub(parent, title, text, *args, **kwargs):
    return record_message('information', title, text)


def critical_stub(parent, title, text, *args, **kwargs):
    return record_message('critical', title, text)


def rename_exec_stub(self):
    rename_dialog_opened.append(self.old_name)
    self.new_name = 'source_renamed.txt'
    return QDialog.Accepted


def rename_get_stub(self):
    return getattr(self, 'new_name', orig_rename_get(self))


def index_for_path(window, path):
    if not wait_for(lambda: window.file_model.index(path).isValid(), timeout=5000):
        raise RuntimeError(f'index not ready: {path}')
    return window.file_model.index(path)


def select_rows(window, paths):
    selection_model = window.file_tree.selectionModel()
    selection_model.clearSelection()
    first_index = None
    flags = selection_model.Select | selection_model.Rows
    for path in paths:
        index = index_for_path(window, path)
        if first_index is None:
            first_index = index
        selection_model.select(index, flags)
    if first_index is not None:
        # setCurrentIndex on the view would ClearAndSelect, wiping the multi-selection
        selection_model.setCurrentIndex(first_index, selection_model.NoUpdate)
        window.file_tree.scrollTo(first_index)
    QApplication.processEvents()


def clipboard_urls():
    mime = QApplication.clipboard().mimeData()
    if not mime or not mime.hasUrls():
        return []
    return [url.toLocalFile() for url in mime.urls()]


def norm_list(paths):
    return [os.path.normpath(p) for p in paths]


def send_shortcut(window, key, modifier=Qt.NoModifier):
    window.activateWindow()
    window.raise_()
    window.file_tree.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window, key, modifier)
    QApplication.processEvents()
    wait(200)


def show_context_menu_and_choose(window, path, choose_text):
    captured = {}

    def exec_stub(menu, *args, **kwargs):
        captured['actions'] = [action.text() for action in menu.actions()]
        for action in menu.actions():
            if action.text() == choose_text:
                return action
        return None

    QMenu.exec_ = exec_stub
    try:
        index = index_for_path(window, path)
        rect = window.file_tree.visualRect(index)
        if rect.isNull():
            window.file_tree.scrollTo(index)
            QApplication.processEvents()
            rect = window.file_tree.visualRect(index)
        point = rect.center()
        window.on_file_tree_context_menu(point)
        QApplication.processEvents()
        wait(200)
        return captured.get('actions', [])
    finally:
        QMenu.exec_ = orig_exec


def main_run():
    app = QApplication(sys.argv)
    QMessageBox.warning = warning_stub
    QMessageBox.information = information_stub
    QMessageBox.critical = critical_stub
    main.RenameDialog.exec_ = rename_exec_stub
    main.RenameDialog.get_new_name = rename_get_stub

    window = main.MainWindow()
    window.show()
    window.activateWindow()
    window.raise_()

    loaded = wait_for(lambda: window.motherboard_table.rowCount() > 0, timeout=12000)
    if not loaded:
        raise RuntimeError('project list did not load')

    window.motherboard_table.cellClicked.emit(0, 0)
    if not wait_for(lambda: os.path.normpath(window.file_model.rootPath()) == os.path.normpath(PROJECT_DIR), timeout=5000):
        raise RuntimeError('project root did not activate')
    if not wait_for(lambda: window.file_model.rowCount(window.file_tree.rootIndex()) >= 4, timeout=5000):
        raise RuntimeError('file tree did not populate')

    select_rows(window, [FILE_A, FILE_B])
    send_shortcut(window, Qt.Key_C, Qt.ControlModifier)
    copied_urls = clipboard_urls()
    copied_text = QApplication.clipboard().mimeData().text() if QApplication.clipboard().mimeData() else ''
    copy_ok = norm_list(copied_urls) == norm_list([FILE_A, FILE_B]) and os.path.normpath(FILE_A) in os.path.normpath(copied_text) and window.clipboard_path is None
    log('Ctrl+C multi-select copy', copy_ok, f'urls={copied_urls}, clipboard_path={window.clipboard_path}')

    select_rows(window, [FILE_A, FILE_B])
    send_shortcut(window, Qt.Key_Delete)
    delete_ok = wait_for(lambda: (not os.path.exists(FILE_A)) and (not os.path.exists(FILE_B)), timeout=5000)
    log('Delete multi-select recycle', delete_ok, f'exists_after={{a:{os.path.exists(FILE_A)}, b:{os.path.exists(FILE_B)}}}')

    select_rows(window, [DIR_C])
    actions = show_context_menu_and_choose(window, SOURCE_FILE, '复制')
    selected_after_menu = window._get_selected_file_paths()
    context_ok = norm_list(selected_after_menu) == norm_list([SOURCE_FILE]) and '粘贴副本' in actions and '重命名' in actions
    log('Context menu retargets unselected item', context_ok, f'actions={actions}, selected={selected_after_menu}')

    send_shortcut(window, Qt.Key_F2)
    rename_ok = wait_for(lambda: os.path.exists(RENAMED_SOURCE), timeout=3000) and rename_dialog_opened and rename_dialog_opened[-1] == 'source.txt'
    log('F2 single-item rename', rename_ok, f'rename_dialog_opened={rename_dialog_opened[-1:]}, renamed_exists={os.path.exists(RENAMED_SOURCE)}')

    window._copy_path_to_clipboard(RENAMED_SOURCE)
    select_rows(window, [PASTE_TARGET])
    send_shortcut(window, Qt.Key_V, Qt.ControlModifier)
    paste_ok = wait_for(lambda: os.path.exists(PASTED_COPY), timeout=3000)
    log('Ctrl+V targets selected directory', paste_ok, f'pasted_exists={os.path.exists(PASTED_COPY)} target={PASTE_TARGET}')

    # 程序内多选复制 + 粘贴副本（之前漏测的回归路径）
    multi_src_dir = os.path.join(PROJECT_DIR, 'MultiSrc')
    os.makedirs(multi_src_dir, exist_ok=True)
    src_x = os.path.join(multi_src_dir, 'x.txt')
    src_y = os.path.join(multi_src_dir, 'y.txt')
    with open(src_x, 'w', encoding='utf-8') as f:
        f.write('x content')
    with open(src_y, 'w', encoding='utf-8') as f:
        f.write('y content')
    multi_target = os.path.join(PROJECT_DIR, 'MultiPasteTarget')
    os.makedirs(multi_target, exist_ok=True)
    pasted_x = os.path.join(multi_target, 'x.txt')
    pasted_y = os.path.join(multi_target, 'y.txt')
    select_rows(window, [src_x, src_y])
    send_shortcut(window, Qt.Key_C, Qt.ControlModifier)
    in_app_state_ok = norm_list(window.clipboard_paths) == norm_list([src_x, src_y]) and window.clipboard_path is None
    select_rows(window, [multi_target])
    send_shortcut(window, Qt.Key_V, Qt.ControlModifier)
    multi_paste_ok = (
        wait_for(lambda: os.path.exists(pasted_x) and os.path.exists(pasted_y), timeout=3000)
        and in_app_state_ok
    )
    log('In-app multi-select copy+paste', multi_paste_ok,
        f'clipboard_paths={window.clipboard_paths}, pasted_x={os.path.exists(pasted_x)}, pasted_y={os.path.exists(pasted_y)}')

    window.close()
    app.processEvents()

    failed = [name for name, ok, _ in results if not ok]
    print('SUMMARY', 'PASS' if not failed else 'FAIL', failed)
    return 0 if not failed else 1


if __name__ == '__main__':
    try:
        sys.exit(main_run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        QMessageBox.warning = orig_warning
        QMessageBox.information = orig_information
        QMessageBox.critical = orig_critical
        QMenu.exec_ = orig_exec
        main.RenameDialog.exec_ = orig_rename_exec
        main.RenameDialog.get_new_name = orig_rename_get
