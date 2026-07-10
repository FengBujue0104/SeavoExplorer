import ast
import base64
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import zipfile
from types import SimpleNamespace
from unittest import mock

import main


TEST_TMP_ROOT = r'D:\tmp' if os.path.isdir(r'D:\tmp') else None


def read_text(path):
    with open(path, encoding='utf-8') as stream:
        return stream.read()


class ProjectVersionTests(unittest.TestCase):
    def test_runtime_version_matches_project_metadata_and_readme(self):
        project_root = os.path.dirname(os.path.abspath(main.__file__))
        pyproject = read_text(os.path.join(project_root, 'pyproject.toml'))
        readme = read_text(os.path.join(project_root, 'README.md'))

        project_match = re.search(
            r'(?ms)^\[project\]\s*$.*?^version\s*=\s*"([^"]+)"\s*$',
            pyproject,
        )
        readme_match = re.search(
            r'(?m)^\*\*版本\s+([0-9]+\.[0-9]+\.[0-9]+)\*\*\s*$',
            readme,
        )
        self.assertIsNotNone(project_match)
        self.assertIsNotNone(readme_match)
        self.assertEqual(main.APP_VERSION, project_match.group(1))
        self.assertEqual(main.APP_VERSION, readme_match.group(1))

    def test_main_has_no_bare_except_handlers(self):
        source = read_text(os.path.abspath(main.__file__))
        tree = ast.parse(source, filename=main.__file__)
        bare_handlers = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and node.type is None
        ]
        self.assertEqual(bare_handlers, [])


class NewProjectDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_dialog_and_config_fallback_use_user_home(self):
        expected_home = os.path.expanduser('~')
        dialog = main.NewProjectDialog(default_folder=None)
        self.assertEqual(dialog.target_folder, expected_home)
        dialog.deleteLater()

        captured = {}

        def capture_settings(path, data, make_hidden=True):
            captured['path'] = path
            captured['data'] = data
            return True

        window = SimpleNamespace(
            CONFIG_FILE=os.path.join(expected_home, 'unused-settings.json'),
            safe_write_json=capture_settings,
        )
        self.assertTrue(main.MainWindow.save_settings_to_file(window, []))
        self.assertEqual(
            captured['data']['default_new_project_folder'],
            expected_home,
        )


class TerminalSafetyTests(unittest.TestCase):
    def test_local_paths_are_not_embedded_in_powershell_or_cmd_commands(self):
        path = os.path.abspath(os.path.join(TEST_TMP_ROOT or os.getcwd(), "x'$(calc)&^% space"))
        candidates = main.MainWindow._terminal_launch_candidates(None, path)
        names = {name for name, _exe, _args, _cwd in candidates}
        self.assertIn('PowerShell', names)
        self.assertIn('命令提示符', names)

        for name, executable, args, working_directory in candidates:
            self.assertTrue(os.path.isabs(executable))
            if name == 'Windows 终端':
                self.assertEqual(args, ['-d', path])
                self.assertEqual(working_directory, path)
            elif name == 'PowerShell':
                self.assertNotIn('-Command', args)
                self.assertNotIn('-EncodedCommand', args)
                self.assertNotIn(path, subprocess.list2cmdline(args))
                self.assertEqual(working_directory, path)
            elif name == '命令提示符':
                self.assertEqual(args, ['/D'])
                self.assertNotIn(path, subprocess.list2cmdline(args))
                self.assertEqual(working_directory, path)

    def test_unc_path_is_encoded_for_powershell(self):
        path = "\\\\server\\share\\folder'$(calc)&^%"
        candidates = main.MainWindow._terminal_launch_candidates(None, path)
        powershell = next(item for item in candidates if item[0] == 'PowerShell')
        _name, _executable, args, _working_directory = powershell
        self.assertIn('-EncodedCommand', args)
        self.assertNotIn(path, ' '.join(args))
        script = base64.b64decode(args[-1]).decode('utf-16le')
        match = re.search(r"FromBase64String\('([^']+)'\)", script)
        self.assertIsNotNone(match)
        decoded_path = base64.b64decode(match.group(1)).decode('utf-8')
        self.assertEqual(decoded_path, path)
        self.assertNotIn('命令提示符', {item[0] for item in candidates})

    def test_powershell_and_cmd_inherit_selected_working_directory(self):
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        powershell = os.path.join(
            system_root,
            'System32',
            'WindowsPowerShell',
            'v1.0',
            'powershell.exe',
        )
        cmd = os.path.join(system_root, 'System32', 'cmd.exe')
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            selected = os.path.join(root, "x'$(calc)&^% space")
            os.mkdir(selected)
            ps_result = subprocess.run(
                [powershell, '-NoLogo', '-NoProfile', '-Command', '(Get-Location).Path'],
                cwd=selected,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=20,
            )
            cmd_result = subprocess.run(
                [cmd, '/D', '/C', 'cd'],
                cwd=selected,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=20,
            )
            self.assertEqual(ps_result.returncode, 0, ps_result.stderr)
            self.assertEqual(cmd_result.returncode, 0, cmd_result.stderr)
            self.assertEqual(os.path.normcase(ps_result.stdout.strip()), os.path.normcase(selected))
            self.assertEqual(os.path.normcase(cmd_result.stdout.strip()), os.path.normcase(selected))


class RecycleSafetyTests(unittest.TestCase):
    def test_backend_failure_never_deletes_source(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'keep.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('keep')

            def failing_backend(_path):
                raise OSError('simulated recycle failure')

            with self.assertRaises(OSError):
                main._send_path_to_recycle_strict(path, backend=failing_backend)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(read_text(path), 'keep')

    def test_modern_backend_is_available(self):
        self.assertTrue(callable(main._load_strict_recycle_backend()))

    def test_os_error_is_classified_and_source_is_retained(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'keep.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('keep')

            def denied_backend(_path):
                raise PermissionError(13, 'access denied')

            window = SimpleNamespace()
            with mock.patch.object(
                main.QMessageBox,
                'question',
                return_value=main.QMessageBox.Yes,
            ):
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    with mock.patch.object(
                        main,
                        '_load_strict_recycle_backend',
                        return_value=denied_backend,
                    ):
                        result = main.MainWindow._move_paths_to_recycle(window, [path])

            self.assertFalse(result)
            self.assertTrue(os.path.exists(path))
            message = warning.call_args.args[2]
            self.assertIn('系统错误 13', message)
            self.assertIn('access denied', message)


class SevenZipSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_dialog_round_trip_and_path_validation(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            missing = os.path.join(root, 'missing', '7z.exe')
            disabled = main.SevenZipSettingsDialog(missing, False)
            disabled.save_settings()
            saved_path, enabled = disabled.get_settings()
            self.assertEqual(saved_path, os.path.abspath(missing))
            self.assertFalse(enabled)
            disabled.deleteLater()

            invalid = main.SevenZipSettingsDialog(missing, True)
            with mock.patch.object(main.QMessageBox, 'warning') as warning:
                invalid.save_settings()
            warning.assert_called_once()
            self.assertEqual(invalid.result(), main.QDialog.Rejected)
            invalid.deleteLater()

            sevenzip = os.path.join(root, '7z.exe')
            with open(sevenzip, 'wb') as stream:
                stream.write(b'test')
            valid = main.SevenZipSettingsDialog(sevenzip, True)
            valid.save_settings()
            self.assertEqual(valid.get_settings(), (sevenzip, True))
            self.assertEqual(valid.result(), main.QDialog.Accepted)
            valid.deleteLater()

    def test_enable_setting_is_fail_closed_and_persisted(self):
        class SettingsHarness:
            _init_default_settings = main.MainWindow._init_default_settings
            load_settings = main.MainWindow.load_settings
            save_settings_to_file = main.MainWindow.save_settings_to_file

            def __init__(self, config_file):
                self.CONFIG_FILE = config_file
                self._pending_load_warnings = []

            def _get_default_quick_access_paths(self):
                return []

            def _backup_corrupt_file(self, _path):
                return None

        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            config_file = os.path.join(root, 'settings.json')
            harness = SettingsHarness(config_file)
            self.assertEqual(harness.load_settings(), [])
            self.assertFalse(harness.enable_7zip)

            old_path = os.path.join(root, 'old', '7z.exe')
            with open(config_file, 'w', encoding='utf-8') as stream:
                json.dump({'archive_tool_path': old_path}, stream)
            harness = SettingsHarness(config_file)
            harness.load_settings()
            self.assertEqual(harness.archive_tool_path, old_path)
            self.assertFalse(harness.enable_7zip)

            for stored_value, expected in ((True, True), (False, False), ('true', False), (1, False)):
                with self.subTest(stored_value=stored_value):
                    with open(config_file, 'w', encoding='utf-8') as stream:
                        json.dump({'enable_7zip': stored_value}, stream)
                    harness = SettingsHarness(config_file)
                    harness.load_settings()
                    self.assertIs(harness.enable_7zip, expected)

            harness = SettingsHarness(config_file)
            harness._init_default_settings()
            harness.enable_7zip = True
            captured = {}

            def capture_settings(path, data, make_hidden=True):
                captured['path'] = path
                captured['data'] = data
                return True

            harness.safe_write_json = capture_settings
            self.assertTrue(harness.save_settings_to_file([]))
            self.assertTrue(captured['data']['enable_7zip'])

    def test_settings_dialog_commits_only_after_successful_save(self):
        class WindowHarness:
            def __init__(self, save_result):
                self.archive_tool_path = 'old-path'
                self.enable_7zip = False
                self.settings = []
                self.include_subfolders = False
                self.save_result = save_result

            def save_settings_to_file(self, _settings, _include_subfolders):
                return self.save_result

        dialog = mock.Mock()
        dialog.exec_.return_value = True
        dialog.get_settings.return_value = ('new-path', True)
        window = WindowHarness(False)
        with mock.patch.object(main, 'SevenZipSettingsDialog', return_value=dialog):
            main.MainWindow.show_7zip_settings_dialog(window)
        self.assertEqual(window.archive_tool_path, 'old-path')
        self.assertFalse(window.enable_7zip)

        window = WindowHarness(True)
        with mock.patch.object(main, 'SevenZipSettingsDialog', return_value=dialog):
            with mock.patch.object(main.QMessageBox, 'information') as information:
                main.MainWindow.show_7zip_settings_dialog(window)
        self.assertEqual(window.archive_tool_path, 'new-path')
        self.assertTrue(window.enable_7zip)
        information.assert_called_once()

    def test_preview_gate_covers_rar_7z_and_keeps_zip_enabled(self):
        for ext in ('.rar', '.7z'):
            with self.subTest(ext=ext):
                hint = mock.Mock()
                archive_preview = mock.Mock()
                window = SimpleNamespace(
                    preview_button=mock.Mock(),
                    preview_tab=mock.Mock(),
                    image_scroll_area=mock.Mock(),
                    _preview_7z_disabled_hint=hint,
                    _preview_archive=archive_preview,
                )
                main.MainWindow._do_preview(window, 'sample' + ext)
                hint.assert_called_once_with('sample' + ext)
                archive_preview.assert_not_called()

        archive_preview = mock.Mock()
        enabled_window = SimpleNamespace(
            enable_7zip=True,
            preview_button=mock.Mock(),
            preview_tab=mock.Mock(),
            image_scroll_area=mock.Mock(),
            _preview_7z_disabled_hint=mock.Mock(),
            _preview_archive=archive_preview,
        )
        main.MainWindow._do_preview(enabled_window, 'sample.rar')
        archive_preview.assert_called_once_with('sample.rar', '.rar')

        zip_preview = mock.Mock()
        zip_window = SimpleNamespace(
            preview_button=mock.Mock(),
            preview_tab=mock.Mock(),
            image_scroll_area=mock.Mock(),
            _preview_7z_disabled_hint=mock.Mock(),
            _preview_archive=zip_preview,
        )
        main.MainWindow._do_preview(zip_window, 'sample.zip')
        zip_preview.assert_called_once_with('sample.zip', '.zip')

    def test_manual_preview_button_cannot_bypass_gate(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            archive = os.path.join(root, 'sample.rar')
            with open(archive, 'wb') as stream:
                stream.write(b'not opened by the preview gate')
            hint = mock.Mock()
            archive_preview = mock.Mock()
            window = SimpleNamespace(
                _manual_preview_path=archive,
                preview_button=mock.Mock(),
                preview_tab=mock.Mock(),
                image_scroll_area=mock.Mock(),
                _preview_7z_disabled_hint=hint,
                _preview_archive=archive_preview,
            )
            window._do_preview = lambda path: main.MainWindow._do_preview(window, path)
            main.MainWindow._on_preview_button_clicked(window)
            hint.assert_called_once_with(archive)
            archive_preview.assert_not_called()

    def test_disabled_hint_and_list_helper_do_not_start_7zip(self):
        preview_tab = mock.Mock()
        window = SimpleNamespace(preview_tab=preview_tab)
        main.MainWindow._preview_7z_disabled_hint(window, r'C:\unsafe\sample.rar')
        text = preview_tab.setPlainText.call_args.args[0]
        self.assertIn('尚未读取', text)
        self.assertIn('设置 → 7-Zip路径设置', text)
        self.assertIn('来源可信', text)

        blocked = SimpleNamespace(enable_7zip=False)
        with self.assertRaises(main.ArchiveSafetyError):
            main.MainWindow._list_archive_with_7z(blocked, 'sample.rar')

    def test_tool_lookup_never_executes_an_arbitrary_configured_exe(self):
        configured_path = os.path.abspath('not-7zip.exe')
        window = SimpleNamespace(archive_tool_path=configured_path)

        def only_arbitrary_exe_exists(path):
            return os.path.normcase(path) == os.path.normcase(configured_path)

        with mock.patch.object(main.os.path, 'isfile', side_effect=only_arbitrary_exe_exists):
            self.assertIsNone(main.MainWindow._find_7z_tool(window))


class PreviewButtonFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_delayed_disabled_preview_preserves_button_target(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'preview.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('preview content')

            do_preview = mock.Mock()
            window = SimpleNamespace(
                _scheduled_preview_path=path,
                _manual_preview_path=None,
                preview_text_enabled=False,
                preview_button=mock.Mock(),
                preview_tab=mock.Mock(),
                image_scroll_area=mock.Mock(),
                isVisible=lambda: True,
                _do_preview=do_preview,
            )
            window._preview_category = lambda ext: main.MainWindow._preview_category(window, ext)
            window._show_preview_button = (
                lambda file_path, type_name: main.MainWindow._show_preview_button(
                    window,
                    file_path,
                    type_name,
                )
            )
            window.preview_file = lambda file_path: main.MainWindow.preview_file(window, file_path)

            main.MainWindow._execute_pending_preview(window)

            self.assertIsNone(window._scheduled_preview_path)
            self.assertEqual(window._manual_preview_path, path)
            window.preview_button.show.assert_called_once()

            main.MainWindow._on_preview_button_clicked(window)

            self.assertIsNone(window._manual_preview_path)
            do_preview.assert_called_once_with(path)

    def test_cancel_pending_preview_stops_owned_timer(self):
        timer = mock.Mock()
        timer.isActive.return_value = True
        window = SimpleNamespace(
            _preview_timer=timer,
            _scheduled_preview_path='old-file.txt',
        )

        main.MainWindow._cancel_pending_preview(window)

        timer.stop.assert_called_once()
        self.assertIsNone(window._scheduled_preview_path)

    def test_real_qtimer_and_button_click_load_preview(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'preview.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('preview content')

            parent = main.QWidget()
            button = main.QPushButton(parent)
            preview_tab = main.QTextEdit(parent)
            image_area = main.QWidget(parent)
            loaded = []
            timer = main.QTimer(parent)
            timer.setSingleShot(True)
            timer.setInterval(1)
            window = SimpleNamespace(
                _scheduled_preview_path=path,
                _manual_preview_path=None,
                _preview_timer=timer,
                preview_text_enabled=False,
                preview_button=button,
                preview_tab=preview_tab,
                image_scroll_area=image_area,
                isVisible=lambda: True,
                _do_preview=loaded.append,
            )
            window._preview_category = lambda ext: main.MainWindow._preview_category(window, ext)
            window._show_preview_button = (
                lambda file_path, type_name: main.MainWindow._show_preview_button(
                    window,
                    file_path,
                    type_name,
                )
            )
            window.preview_file = lambda file_path: main.MainWindow.preview_file(window, file_path)
            window._execute_pending_preview = (
                lambda: main.MainWindow._execute_pending_preview(window)
            )
            window._on_preview_button_clicked = (
                lambda: main.MainWindow._on_preview_button_clicked(window)
            )
            timer.timeout.connect(window._execute_pending_preview)
            button.clicked.connect(window._on_preview_button_clicked)

            timer.start()
            deadline = time.monotonic() + 1
            while timer.isActive() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)

            self.assertFalse(timer.isActive())
            self.assertEqual(window._manual_preview_path, path)
            button.click()
            self.app.processEvents()
            self.assertEqual(loaded, [path])
            self.assertIsNone(window._manual_preview_path)
            parent.deleteLater()


class UpdateDownloadSafetyTests(unittest.TestCase):
    def test_terminal_failure_removes_partial_file(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path)
            thread.MAX_RETRIES = 0
            with open(thread.part_path, 'wb') as stream:
                stream.write(b'partial')
            failures = []
            thread.download_failed.connect(failures.append)
            error = urllib.error.HTTPError(thread.url, 404, 'not found', None, None)
            with mock.patch.object(thread, '_download_once', side_effect=error):
                thread.run()

            self.assertFalse(os.path.exists(thread.part_path))
            self.assertEqual(failures, ['GitHub 返回错误：HTTP 404'])

    def test_partial_file_survives_between_automatic_retries(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path)
            thread.MAX_RETRIES = 1
            with open(thread.part_path, 'wb') as stream:
                stream.write(b'partial')
            observed = []

            def download_attempt(attempt):
                observed.append((attempt, os.path.exists(thread.part_path)))
                if attempt == 1:
                    raise urllib.error.URLError('temporary outage')
                os.replace(thread.part_path, thread.save_path)
                return True

            with mock.patch.object(thread, '_download_once', side_effect=download_attempt):
                with mock.patch.object(thread, '_sleep_with_cancel', return_value=True):
                    thread.run()

            self.assertEqual(observed, [(1, True), (2, True)])
            self.assertTrue(os.path.exists(save_path))
            self.assertFalse(os.path.exists(thread.part_path))

    def test_cancellation_preserves_partial_file(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path)
            with open(thread.part_path, 'wb') as stream:
                stream.write(b'partial')
            canceled = []
            thread.download_canceled.connect(lambda path, size: canceled.append((path, size)))
            with mock.patch.object(thread, 'isInterruptionRequested', return_value=True):
                thread.run()

            self.assertTrue(os.path.exists(thread.part_path))
            self.assertEqual(canceled, [(thread.part_path, 7)])

    def test_cleanup_failure_is_reported(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path)
            thread.MAX_RETRIES = 0
            failures = []
            thread.download_failed.connect(failures.append)
            with mock.patch.object(thread, '_download_once', side_effect=ValueError('bad data')):
                with mock.patch.object(
                    thread,
                    '_reset_partial',
                    return_value=PermissionError(13, 'access denied'),
                ):
                    thread.run()

            self.assertEqual(len(failures), 1)
            self.assertIn('下载临时文件未能清理', failures[0])
            self.assertIn(thread.part_path, failures[0])


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT)
        self.root = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def assert_no_staging(self):
        leftovers = [name for name in os.listdir(self.root) if name.startswith('.seavo-extract-')]
        self.assertEqual(leftovers, [])

    def test_existing_single_file_is_renamed_not_overwritten(self):
        existing = os.path.join(self.root, 'doc.txt')
        with open(existing, 'w', encoding='utf-8') as stream:
            stream.write('old')
        archive = os.path.join(self.root, 'sample.zip')
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('doc.txt', 'new')

        destination = main._transactional_extract_archive(archive)

        self.assertEqual(os.path.basename(destination), 'doc (1).txt')
        self.assertEqual(read_text(existing), 'old')
        self.assertEqual(read_text(destination), 'new')
        with zipfile.ZipFile(archive) as zf:
            self.assertIsNone(zf.testzip())
        self.assert_no_staging()

    def test_multiple_top_level_items_use_unique_directory(self):
        existing_dir = os.path.join(self.root, 'bundle')
        os.mkdir(existing_dir)
        with open(os.path.join(existing_dir, 'keep.txt'), 'w', encoding='utf-8') as stream:
            stream.write('keep')
        archive = os.path.join(self.root, 'bundle.zip')
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('a.txt', 'a')
            zf.writestr('dir/b.txt', 'b')

        destination = main._transactional_extract_archive(archive)

        self.assertEqual(os.path.basename(destination), 'bundle (1)')
        self.assertEqual(read_text(os.path.join(existing_dir, 'keep.txt')), 'keep')
        self.assertEqual(read_text(os.path.join(destination, 'a.txt')), 'a')
        self.assertEqual(read_text(os.path.join(destination, 'dir', 'b.txt')), 'b')
        self.assert_no_staging()

    def test_archive_cannot_overwrite_itself(self):
        archive = os.path.join(self.root, 'self.zip')
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('self.zip', 'payload')

        destination = main._transactional_extract_archive(archive)

        self.assertEqual(os.path.basename(destination), 'self (1).zip')
        with zipfile.ZipFile(archive) as zf:
            self.assertIsNone(zf.testzip())
        self.assertEqual(read_text(destination), 'payload')
        self.assert_no_staging()

    def test_traversal_and_case_collisions_are_rejected(self):
        traversal = os.path.join(self.root, 'traversal.zip')
        with zipfile.ZipFile(traversal, 'w') as zf:
            zf.writestr('../escape.txt', 'bad')
        with self.assertRaises(main.ArchiveSafetyError):
            main._transactional_extract_archive(traversal)

        collision = os.path.join(self.root, 'collision.zip')
        with zipfile.ZipFile(collision, 'w') as zf:
            zf.writestr('A.txt', 'a')
            zf.writestr('a.txt', 'b')
        with self.assertRaises(main.ArchiveSafetyError):
            main._transactional_extract_archive(collision)
        self.assert_no_staging()

    def test_zip_symlink_is_rejected(self):
        archive = os.path.join(self.root, 'link.zip')
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr(info, 'target.txt')
        with self.assertRaises(main.ArchiveSafetyError):
            main._transactional_extract_archive(archive)
        self.assert_no_staging()

    def test_cancel_after_validation_does_not_commit(self):
        archive = os.path.join(self.root, 'cancel.zip')
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('payload.txt', 'payload')
        canceled = {'value': False}
        original_validate = main._validate_staged_tree

        def validate_then_cancel(stage_dir, manifest, is_canceled):
            original_validate(stage_dir, manifest, is_canceled)
            canceled['value'] = True

        with mock.patch.object(main, '_validate_staged_tree', side_effect=validate_then_cancel):
            with self.assertRaises(main.ArchiveExtractionCanceled):
                main._transactional_extract_archive(
                    archive,
                    is_canceled=lambda: canceled['value'],
                )
        self.assertFalse(os.path.exists(os.path.join(self.root, 'payload.txt')))
        self.assert_no_staging()

    def test_manifest_path_resource_limits(self):
        raw_entries = [{
            'name': 'a/b.txt',
            'size': 0,
            'compressed_size': 0,
            'is_dir': False,
        }]
        with mock.patch.object(main, 'ARCHIVE_MAX_PATH_NODES', 2):
            with mock.patch.object(main, 'ARCHIVE_MAX_PATH_CHARS', 8):
                manifest, _total_size = main._build_archive_manifest(raw_entries, 1)
        self.assertEqual(len(manifest), 1)

        with mock.patch.object(main, 'ARCHIVE_MAX_PATH_NODES', 1):
            with self.assertRaises(main.ArchiveSafetyError):
                main._build_archive_manifest(raw_entries, 1)
        with mock.patch.object(main, 'ARCHIVE_MAX_PATH_CHARS', 7):
            with self.assertRaises(main.ArchiveSafetyError):
                main._build_archive_manifest(raw_entries, 1)

    def test_7z_parser_flushes_last_record_without_blank_line(self):
        output = 'Header\n----------\nPath = a.txt\nSize = 3\nPacked Size = 2'
        entries = main._parse_7z_slt_output(output)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['name'], 'a.txt')
        self.assertEqual(entries[0]['size'], 3)

    def test_7z_parser_rejects_entry_overflow_at_eof(self):
        output = (
            'Header\n----------\nPath = a.txt\nSize = 1\n\n'
            'Path = b.txt\nSize = 1'
        )
        with mock.patch.object(main, 'ARCHIVE_MAX_ENTRIES', 1):
            with self.assertRaises(main.ArchiveSafetyError):
                main._parse_7z_slt_output(output)

    def test_7z_process_caps_stdout_and_stderr(self):
        for stream_name in ('stdout', 'stderr'):
            with self.subTest(stream=stream_name):
                script = (
                    f"import sys; sys.{stream_name}.write('x' * 131072); "
                    f'sys.{stream_name}.flush()'
                )
                with self.assertRaises(main.ArchiveSafetyError):
                    main._run_7z_process(
                        [sys.executable, '-c', script],
                        timeout=10,
                        max_output_bytes=4096,
                    )

    def test_real_7z_transaction_when_available(self):
        sevenzip = r'C:\Program Files\7-Zip\7z.exe'
        if not os.path.isfile(sevenzip):
            self.skipTest('7-Zip is not installed')
        source_dir = os.path.join(self.root, 'payload')
        os.mkdir(source_dir)
        filename = '中文 file with space.txt'
        with open(os.path.join(source_dir, filename), 'w', encoding='utf-8') as stream:
            stream.write('7z content')
        archive = os.path.join(self.root, 'payload.7z')
        result = subprocess.run(
            [sevenzip, 'a', '-bd', '-bb0', archive, source_dir],
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        destination = main._transactional_extract_archive(archive, sevenzip=sevenzip)

        self.assertTrue(os.path.isdir(destination))
        self.assertEqual(read_text(os.path.join(destination, filename)), '7z content')
        self.assert_no_staging()


if __name__ == '__main__':
    unittest.main()
