# -*- coding: utf-8 -*-
"""Optional real-window GUI smoke for occupancy analysis, path copy and undo.

Not part of the default unittest or release gate. Run manually:

    python gui_smoke.py
    python gui_smoke.py --shots D:\\tmp\\seavo-gui-smoke
    python gui_smoke.py --real-explorer

Uses an isolated sidecar directory, temporary project data, and never reads
the developer's seavoexplorer.json. Creating a ZIP and undoing it will send
that temp archive to the Recycle Bin.
"""
from __future__ import print_function

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import main
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

TEST_TMP_ROOT = r'D:\tmp' if os.path.isdir(r'D:\tmp') else None


def log(message):
    print(message, flush=True)


def pump(ms=50):
    QApplication.processEvents()
    QTest.qWait(ms)


def pump_until(pred, timeout=12.0, step=50):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if pred():
            return True
        QTest.qWait(step)
    return False


def write_bytes(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'wb') as stream:
        stream.write(data)


def close_window(window):
    for _ in range(25):
        window.close()
        pump(120)
        if not window.isVisible():
            return True
    window.hide()
    pump(100)
    return not window.isVisible()


def table_paths(table):
    found = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is None:
            found.append(('', None))
        else:
            found.append((item.text(), item.data(Qt.UserRole)))
    return found


def run_smoke(shot_dir=None, real_explorer=False):
    failures = []
    boxes = []
    occupancy_state = {}
    popen_cmds = []
    about_state = {}
    temps = []

    def fail(message):
        failures.append(message)
        log('FAIL: ' + message)

    def ok(message):
        log('OK: ' + message)

    def grab(widget, name):
        if not shot_dir:
            return None
        os.makedirs(shot_dir, exist_ok=True)
        path = os.path.join(shot_dir, name)
        widget.grab().save(path, 'PNG')
        log('shot ' + path)
        return path

    app_dir = tempfile.mkdtemp(prefix='seavo-gui-app-', dir=TEST_TMP_ROOT)
    data_dir = tempfile.mkdtemp(prefix='seavo-gui-data-', dir=TEST_TMP_ROOT)
    temps.extend([app_dir, data_dir])
    log('app_dir ' + app_dir)
    log('data_dir ' + data_dir)

    project = os.path.join(data_dir, 'S100_GUI测试')
    daughter = os.path.join(data_dir, 'M200_子卡')
    huge = os.path.join(project, 'BOM', 'huge.bin')
    notes = os.path.join(project, 'BOM', 'notes.txt')
    dsn = os.path.join(project, '原理图 资料', 'S100 (1).dsn')
    tiny = os.path.join(project, 'tiny.bin')
    write_bytes(huge, b'H' * 4000)
    write_bytes(notes, u'占用分析测试\n'.encode('utf-8'))
    write_bytes(dsn, b'D' * 800)
    write_bytes(tiny, b't' * 20)
    write_bytes(os.path.join(daughter, 'card.txt'), b'm' * 40)

    with open(os.path.join(app_dir, 'seavoexplorer.json'), 'w', encoding='utf-8') as stream:
        json.dump({
            'project_paths': [['GUI测试根', data_dir]],
            'include_subfolders': False,
            'wizard_shown': True,
            'window_geometry': [60, 40, 1280, 820],
            'window_maximized': False,
            'show_hidden': False,
        }, stream, ensure_ascii=False, indent=2)

    def rec_warning(_parent, title, text, *args, **kwargs):
        boxes.append(('warning', str(title), str(text)))
        log('QMessageBox.warning %s: %s' % (title, text))
        return QMessageBox.Ok

    def rec_info(_parent, title, text, *args, **kwargs):
        boxes.append(('info', str(title), str(text)))
        log('QMessageBox.information %s: %s' % (title, text))
        return QMessageBox.Ok

    def occupancy_exec(self):
        occupancy_state['title'] = self.windowTitle()
        occupancy_state['rows'] = self.table.rowCount()
        occupancy_state['items'] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            occupancy_state['items'].append(item.text() if item else '')
        labels = self.findChildren(QLabel)
        occupancy_state['summary'] = labels[0].text() if labels else ''
        self.show()
        pump(80)
        grab(self, '02-occupancy.png')
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
            self._copy_full_path()
            occupancy_state['full'] = QApplication.clipboard().text()
            self._copy_relative_path()
            occupancy_state['rel'] = QApplication.clipboard().text()
        self.close()
        return QDialog.Accepted

    class FakePopen(object):
        def __init__(self, cmd, *args, **kwargs):
            popen_cmds.append(list(cmd) if not isinstance(cmd, str) else cmd)

        def wait(self, timeout=None):
            return 0

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = None
    try:
        with mock.patch.object(main, '_get_app_dir', return_value=app_dir), \
                mock.patch.object(QMessageBox, 'warning', rec_warning), \
                mock.patch.object(QMessageBox, 'information', rec_info), \
                mock.patch.object(main.LargestFilesDialog, 'exec_', occupancy_exec), \
                mock.patch.object(main, '_sh_open_folder_and_select_item', return_value=False), \
                mock.patch.object(main.subprocess, 'Popen', FakePopen):
            window = main.MainWindow()
            window.show()
            window.raise_()
            window.activateWindow()
            pump(200)
            grab(window, '01-main-before-scan.png')

            if window.windowTitle() != u'主板项目文件浏览器':
                fail('window title is %r' % window.windowTitle())
            else:
                ok('main window title')

            menus = window.menuBar().actions()
            menu_titles = [action.text() for action in menus]
            if menu_titles[:4] != [u'文件', u'编辑', u'设置', u'帮助']:
                fail('menu order is %s' % menu_titles)
            else:
                ok('edit menu between file and settings')
            file_actions = menus[0].menu().actions()
            file_texts = [action.text() for action in file_actions]
            if u'占用分析' not in file_texts:
                fail('file menu missing occupancy: %s' % file_texts)
            else:
                ok('file menu has occupancy')
            if any(text.startswith(u'撤回') for text in file_texts):
                fail('undo still in file menu: %s' % file_texts)
            else:
                ok('undo moved out of file menu')
            refresh_actions = [action for action in file_actions if action.text() == u'刷新']
            if len(refresh_actions) != 1 or refresh_actions[0].shortcut().toString() != 'F5':
                fail('refresh shortcut is %s' % [
                    (action.text(), action.shortcut().toString()) for action in file_actions
                ])
            else:
                ok('refresh shortcut is F5')
            edit_actions = menus[1].menu().actions()
            edit_texts = [action.text() for action in edit_actions]
            if any(u'快捷键' in text for text in file_texts + edit_texts):
                fail('verbose shortcut label: %s' % (file_texts + edit_texts))
            else:
                ok('menu shortcuts are keys only')
            if not any(text.startswith(u'撤回') for text in edit_texts):
                fail('edit menu missing undo: %s' % edit_texts)
            else:
                ok('edit menu has undo')
            if window.undo_action.shortcut() != QKeySequence.Undo:
                fail('undo shortcut is %r' % window.undo_action.shortcut().toString())
            else:
                ok('undo shortcut is QKeySequence.Undo')
            if window.undo_action.isEnabled():
                fail('undo enabled at startup')
            else:
                ok('undo disabled at startup')
            edit_by_text = {}
            for action in edit_actions:
                edit_by_text.setdefault(action.text(), action)
            expected_shortcuts = (
                (u'复制', 'Ctrl+C'),
                (u'粘贴副本', 'Ctrl+V'),
                (u'重命名', 'F2'),
                (u'移入回收站', ('Del', 'Delete')),
            )
            for label, shortcut in expected_shortcuts:
                action = edit_by_text.get(label)
                shown = action.shortcut().toString() if action is not None else None
                allowed = shortcut if isinstance(shortcut, tuple) else (shortcut,)
                if action is None or shown not in allowed:
                    fail('edit shortcut %s is %s' % (label, shown))
                else:
                    ok('edit shortcut %s' % label)
            for label in (u'复制完整路径', u'复制相对路径'):
                action = edit_by_text.get(label)
                if action is None or not action.shortcut().isEmpty():
                    fail('path copy action missing or has shortcut: %s' % label)
                else:
                    ok('edit menu has %s' % label)

            if not pump_until(lambda: window.motherboard_table.rowCount() >= 1, timeout=15):
                fail('scan did not find motherboard project')
            else:
                ok('scan completed mb=%s db=%s' % (
                    window.motherboard_table.rowCount(),
                    window.daughterboard_table.rowCount(),
                ))

            mb_paths = [path for _text, path in table_paths(window.motherboard_table)]
            db_paths = [path for _text, path in table_paths(window.daughterboard_table)]
            if not any(path and os.path.basename(path).startswith('S100') for path in mb_paths):
                fail('S100 not in motherboard table: %s' % mb_paths)
            else:
                ok('found S100')
            if not any(path and os.path.basename(path).startswith('M200') for path in db_paths):
                fail('M200 not in daughterboard table: %s' % db_paths)
            else:
                ok('found M200')

            project_path = next(
                path for path in mb_paths
                if path and os.path.basename(path).startswith('S100')
            )
            window.motherboard_table.selectRow(0)
            window._select_project_path(project_path)
            pump(200)
            if not window.current_folder or os.path.basename(window.current_folder) != u'S100_GUI测试':
                fail('current_folder is %r' % window.current_folder)
            else:
                ok('selected S100_GUI测试')

            if not pump_until(lambda: window.file_model.index(huge).isValid(), timeout=10):
                fail('file model did not expose huge.bin')
            else:
                ok('file tree model has huge.bin')

            pump_until(lambda: bool(window.folder_stats_label.text()), timeout=8)
            stats_text = window.folder_stats_label.text()
            if not stats_text:
                fail('folder stats label empty')
            else:
                ok('stats label: ' + stats_text)
            grab(window, '03-main-project.png')

            window.show_occupancy_analysis()
            if not pump_until(lambda: 'rows' in occupancy_state, timeout=12):
                fail('occupancy dialog did not open')
            else:
                items = occupancy_state.get('items') or []
                ok('occupancy title=%s items=%s' % (occupancy_state.get('title'), items))
                if occupancy_state.get('rows', 0) < 3:
                    fail('occupancy rows too few: %s' % occupancy_state.get('rows'))
                if not items or items[0] != 'huge.bin':
                    fail('largest file is not huge.bin: %s' % items)
                else:
                    ok('largest file is huge.bin')
                if os.path.normpath(occupancy_state.get('full') or '') != os.path.normpath(huge):
                    fail('copied full path mismatch: %r' % occupancy_state.get('full'))
                else:
                    ok('copied full path')
                rel = occupancy_state.get('rel') or ''
                if 'BOM' not in rel or 'huge.bin' not in rel:
                    fail('copied relative path mismatch: %r' % rel)
                else:
                    ok('copied relative path ' + rel)

            window.clipboard_paths = ['keep-me']
            window.clipboard_path = 'keep-me'
            window._copy_path_texts_to_clipboard([dsn], u'完整路径')
            clip = QApplication.clipboard().text()
            if os.path.normpath(clip) != os.path.normpath(dsn):
                fail('file-tree copy full path mismatch: %r' % clip)
            else:
                ok('file-tree copied dsn path')
            if window.clipboard_paths != ['keep-me'] or window.clipboard_path != 'keep-me':
                fail('copy path mutated file clipboard')
            else:
                ok('file clipboard unchanged')

            window._copy_path_texts_to_clipboard(
                [main._relative_path_for_display(window.current_folder, dsn)],
                u'相对路径',
            )
            rel_clip = QApplication.clipboard().text()
            if u'原理图 资料' not in rel_clip or 'S100 (1).dsn' not in rel_clip:
                fail('relative copy mismatch: %r' % rel_clip)
            else:
                ok('copied relative dsn ' + rel_clip)

            popen_cmds[:] = []
            shown = window._reveal_paths_in_explorer([dsn])
            if not shown:
                fail('reveal returned False')
            if not popen_cmds:
                fail('explorer Popen not used')
            else:
                cmd = popen_cmds[0]
                ok('explorer cmd=%r' % cmd)
                if (
                    len(cmd) != 3
                    or os.path.basename(cmd[0]).lower() != 'explorer.exe'
                    or cmd[1] != '/select,'
                    or os.path.normpath(cmd[2]) != os.path.normpath(dsn)
                    or cmd[2] in cmd[1]
                ):
                    fail('explorer argv is unsafe: %r' % cmd)
                else:
                    ok('explorer argv keeps path separate')

            class FakeRename(object):
                def __init__(self, file_path, parent=None):
                    self._name = 'notes.renamed.txt'

                def exec_(self):
                    return True

                def get_new_name(self):
                    return self._name

            renamed = os.path.join(project, 'BOM', 'notes.renamed.txt')
            with mock.patch.object(main, 'RenameDialog', FakeRename):
                window.rename_item(notes)
            pump(100)
            if not os.path.exists(renamed) or os.path.exists(notes):
                fail('rename did not swap notes.txt -> notes.renamed.txt')
            else:
                ok('renamed notes.txt')
            if not window.undo_action.isEnabled():
                fail('undo not enabled after rename')
            else:
                ok('undo enabled after rename: ' + window.undo_action.text())
            grab(window, '04-after-rename.png')
            window.undo_action.trigger()
            pump(150)
            if not os.path.exists(notes) or os.path.exists(renamed):
                fail('undo rename did not restore notes.txt')
            else:
                ok('undo restored notes.txt')

            window.add_to_zip(tiny)
            pump(150)
            zips = [name for name in os.listdir(project) if name.lower().endswith('.zip')]
            if not zips:
                fail('zip not created')
            else:
                zip_path = os.path.join(project, zips[0])
                ok('zip created ' + zips[0])
                # QTest synthesized Ctrl+Z does not reliably hit QAction
                # shortcuts; the product path is the 撤回 action.
                window.undo_action.trigger()
                pump(400)
                if os.path.exists(zip_path):
                    fail('undo did not recycle zip: ' + zip_path)
                else:
                    ok('zip recycled via undo')

            occupy_src = os.path.join(project, 'tiny.bin')
            os.rename(occupy_src, occupy_src + '.moved')
            window._push_undo(main._make_undo_rename(occupy_src + '.moved', occupy_src, u'重命名'))
            write_bytes(occupy_src, b'occupied')
            if window.undo_last_action():
                fail('undo overwrite was allowed')
            else:
                ok('undo refused when original occupied')
            if not os.path.exists(occupy_src + '.moved'):
                fail('moved file disappeared after refused undo')
            else:
                ok('moved file kept after refused undo')
            occupied_box = [
                item for item in boxes
                if u'无法撤回' in item[1] or u'无法撤回' in item[2] or u'占用' in item[2]
            ]
            if not occupied_box:
                fail('no warning box for occupied undo: %s' % boxes)
            else:
                ok('occupied undo warned')

            def about_exec(self):
                about_state['title'] = self.windowTitle()
                about_state['text'] = self.text()
                self.show()
                pump(80)
                grab(self, '05-about.png')
                self.close()
                return QMessageBox.Ok

            with mock.patch.object(QMessageBox, 'exec_', about_exec):
                window.show_about()
                pump(100)
            text = about_state.get('text') or ''
            if main.APP_VERSION not in text:
                fail('about missing %s: %r' % (main.APP_VERSION, text[:240]))
            else:
                ok('about shows ' + main.APP_VERSION)
            if u'占用分析' not in text and u'撤回' not in text:
                fail('about missing occupancy/undo blurb')
            else:
                ok('about mentions new features')

            grab(window, '07-main-final.png')
    except Exception:
        fail('exception\n' + traceback.format_exc())
        if window is not None:
            try:
                grab(window, '99-exception.png')
            except Exception:
                pass
    finally:
        if window is not None:
            try:
                close_window(window)
            except Exception:
                log('close failed\n' + traceback.format_exc())
        pump(200)

    if real_explorer:
        try:
            target = dsn if os.path.exists(dsn) else notes
            shown = main._reveal_path_in_explorer(target)
            ok('real explorer reveal: ' + shown)
        except Exception as exc:
            fail('real explorer reveal failed: %s' % exc)

    if shot_dir:
        os.makedirs(shot_dir, exist_ok=True)
        report = os.path.join(shot_dir, 'report.txt')
        with open(report, 'w', encoding='utf-8') as stream:
            stream.write('failures=%d\n' % len(failures))
            for item in failures:
                stream.write('FAIL: %s\n' % item)
            stream.write('occupancy=%s\n' % occupancy_state)
            stream.write('popen=%s\n' % popen_cmds)
        log('report ' + report)

    for path in temps:
        shutil.rmtree(path, ignore_errors=True)

    if failures:
        log('RESULT FAIL %d' % len(failures))
        return 1
    log('RESULT PASS')
    return 0


def main_cli(argv=None):
    parser = argparse.ArgumentParser(
        description='Optional SeavoExplorer GUI smoke; not part of release tests.',
    )
    parser.add_argument(
        '--shots',
        help='Directory for PNG screenshots and report.txt',
    )
    parser.add_argument(
        '--real-explorer',
        action='store_true',
        help='Also call the real Explorer select API once (extra desktop side effect)',
    )
    args = parser.parse_args(argv)
    return run_smoke(shot_dir=args.shots, real_explorer=args.real_explorer)


if __name__ == '__main__':
    sys.exit(main_cli())