import ast
import base64
import ctypes
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

    def test_project_regex_validation_contract(self):
        """自定义正则校验契约：默认规则与可选组可保存；嵌套重复量词（ReDoS 高危）被拒绝；组 1 非数字被拒绝。"""
        ok, err = main._validate_project_regex(main.DEFAULT_MB_RE_TEXT)
        self.assertTrue(ok, err)
        ok, err = main._validate_project_regex(main.DEFAULT_DB_RE_TEXT)
        self.assertTrue(ok, err)
        # 可选组（? 为 0/1 次，无组合爆炸）应放行
        ok, err = main._validate_project_regex(r'^S(\d{3,4})(-\d+)?$')
        self.assertTrue(ok, err)
        ok, err = main._validate_project_regex(r'^S(\d{3,4})(?:-(.*))?$')
        self.assertTrue(ok, err)
        # 嵌套重复量词：灾难性回溯高危，拒绝
        ok, err = main._validate_project_regex(r'^(a+)+$')
        self.assertFalse(ok)
        self.assertIn('回溯', err)
        ok, err = main._validate_project_regex(r'^(a|aa)+$')
        self.assertFalse(ok)
        ok, err = main._validate_project_regex(r'^(a.*)+$')
        self.assertFalse(ok)
        ok, err = main._validate_project_regex(r'^S([A-Za-z]+)$')
        self.assertFalse(ok)
        self.assertIn('纯数字', err)
        ok, err = main._validate_project_regex(r'^S(1000)$')
        self.assertTrue(ok, err)


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


class PersistedPathTests(unittest.TestCase):
    def test_slash_variants_share_a_windows_identity(self):
        with tempfile.TemporaryDirectory() as root:
            backslash = main._normalize_persisted_path(root)
            slash = backslash.replace('\\', '/')
            self.assertEqual(main._path_identity(backslash), main._path_identity(slash))
            self.assertTrue(main._same_path(backslash, slash))

    def test_persisted_path_lists_keep_first_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            slash = root.replace('\\', '/')
            self.assertEqual(
                main._normalize_named_paths([('首次名称', root), ('重复名称', slash)]),
                [('首次名称', main._normalize_persisted_path(root))],
            )
            self.assertEqual(
                main._normalize_quick_access_paths([('首次', root, True), ('重复', slash, False)]),
                [('首次', main._normalize_persisted_path(root), True)],
            )

    def test_comment_keys_are_normalized_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as root:
            slash = root.replace('\\', '/')
            comments = main._normalize_comments_map({root: '首次注释', slash: '重复注释'})
            self.assertEqual(comments, {main._normalize_persisted_path(root): '首次注释'})


class PreviewResourceTests(unittest.TestCase):
    def test_pdf_preview_closes_its_file_stream(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'sample.pdf')
            with open(path, 'wb') as stream:
                stream.write(b'%PDF-1.4\n')
            reader_factory = mock.Mock(return_value=SimpleNamespace(pages=[]))
            window = SimpleNamespace(preview_tab=mock.Mock())
            with mock.patch.object(main, 'PdfReader', reader_factory):
                main.MainWindow._preview_pdf(window, path)
            self.assertTrue(reader_factory.call_args.args[0].closed)

    def test_excel_preview_closes_workbook(self):
        workbook = mock.Mock(sheetnames=[])
        window = SimpleNamespace(preview_tab=mock.Mock())
        with mock.patch.object(main, 'load_workbook', return_value=workbook):
            main.MainWindow._preview_excel(window, 'sample.xlsx', '.xlsx')
        workbook.close.assert_called_once_with()

    def test_xls_preview_releases_resources(self):
        workbook = mock.Mock(nsheets=0)
        fake_xlrd = mock.Mock(open_workbook=mock.Mock(return_value=workbook))
        window = SimpleNamespace(preview_tab=mock.Mock())
        with mock.patch.object(main, 'xlrd', fake_xlrd):
            main.MainWindow._preview_excel(window, 'sample.xls', '.xls')
        workbook.release_resources.assert_called_once_with()

    def test_settings_dialog_default_path_area_fits_four_rows(self):
        app = main.QApplication.instance() or main.QApplication([])
        dialog = main.SettingsDialog([])
        expected = (
            dialog.path_list.horizontalHeader().height()
            + dialog.path_list.verticalHeader().defaultSectionSize() * 4
            + dialog.path_list.frameWidth() * 2
        )
        self.assertGreaterEqual(dialog.width(), 620)
        self.assertGreaterEqual(dialog.height(), 540)
        self.assertGreaterEqual(dialog.path_list.minimumHeight(), expected)
        dialog.deleteLater()
        app.processEvents()


class ExclusiveFileCopyTests(unittest.TestCase):
    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, 'source.txt')
            destination = os.path.join(root, 'destination.txt')
            with open(source, 'w', encoding='utf-8') as stream:
                stream.write('NEW')
            with open(destination, 'w', encoding='utf-8') as stream:
                stream.write('OLD')
            with self.assertRaises(FileExistsError):
                main._copy_file_exclusive(source, destination)
            self.assertEqual(read_text(destination), 'OLD')
            self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(root)))

class PersistenceSafetyTests(unittest.TestCase):
    def test_comments_save_is_blocked_after_read_failure(self):
        stub = SimpleNamespace(_comments_load_failed=True, comments={'a': 'b'})
        stub.safe_write_json = mock.Mock(return_value=True)
        stub.save_comments = main.MainWindow.save_comments.__get__(stub)
        with mock.patch.object(main.QMessageBox, 'warning') as warning:
            self.assertFalse(stub.save_comments())
        stub.safe_write_json.assert_not_called()
        warning.assert_called_once()

    def test_safe_write_json_leaves_no_predictable_temp_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'data.json')
            stub = SimpleNamespace(make_file_hidden=lambda *args: None)
            stub.safe_write_json = main.MainWindow.safe_write_json.__get__(stub)
            self.assertTrue(stub.safe_write_json(path, {'value': 1}))
            self.assertTrue(stub.safe_write_json(path, {'value': 2}))
            with open(path, encoding="utf-8") as stream:
                self.assertEqual(json.load(stream), {"value": 2})
            self.assertFalse(any(name.endswith('.tmp') for name in os.listdir(root)))

class PersistenceBackupFailureTests(unittest.TestCase):
    def test_comments_backup_failure_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'seavo_comments.json')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('{broken json')
            stub = SimpleNamespace(
                COMMENTS_FILE=path,
                _pending_load_warnings=[],
                _comments_load_failed=False,
            )
            stub._backup_corrupt_file = main.MainWindow._backup_corrupt_file.__get__(stub)
            stub.load_comments = main.MainWindow.load_comments.__get__(stub)
            with mock.patch.object(main.os, 'replace', side_effect=PermissionError('backup failed')):
                self.assertEqual(stub.load_comments(), {})
            self.assertTrue(stub._comments_load_failed)

    def test_settings_backup_failure_blocks_overwrite(self):
        class Harness:
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

        with tempfile.TemporaryDirectory() as root:
            config_file = os.path.join(root, 'seavoexplorer.json')
            with open(config_file, 'w', encoding='utf-8') as stream:
                stream.write('{broken json')
            harness = Harness(config_file)
            with mock.patch.object(main.os, 'replace', side_effect=PermissionError('backup failed')):
                harness.load_settings()
            self.assertTrue(harness._settings_load_failed)
            harness.safe_write_json = mock.Mock(return_value=True)
            with mock.patch.object(main.QMessageBox, 'warning'):
                self.assertFalse(harness.save_settings_to_file([], False))
            harness.safe_write_json.assert_not_called()


class ProxySupportTests(unittest.TestCase):
    def test_parse_proxy_list(self):
        proxies = main._parse_proxy_list('http=127.0.0.1:7897;https=127.0.0.1:7898')
        self.assertEqual(proxies['http'], 'http://127.0.0.1:7897')
        self.assertEqual(proxies['https'], 'http://127.0.0.1:7898')

    def test_rejects_non_http_network_url(self):
        with self.assertRaises(ValueError):
            main._urlopen_with_proxy(main.urllib.request.Request('file:///tmp/test'), timeout=1)

    def test_urlopen_uses_explicit_proxy_opener(self):
        request = main.urllib.request.Request('https://example.invalid/file')
        opener = mock.Mock()
        opener.open.return_value = SimpleNamespace()
        with mock.patch.object(main, '_get_proxy_map_for_url', return_value={'https': 'http://127.0.0.1:7897'}):
            with mock.patch.object(main.urllib.request, 'build_opener', return_value=opener) as build:
                main._urlopen_with_proxy(request, timeout=5)
        build.assert_called_once()
        opener.open.assert_called_once_with(request, timeout=5)

    def test_winhttp_autoproxy_options_matches_windows_abi(self):
        from ctypes import wintypes

        _ie_cls, options_cls, info_cls = main._winhttp_ctypes()
        self.assertEqual(
            [name for name, _typ in options_cls._fields_],
            [
                'dwFlags',
                'dwAutoDetectFlags',
                'lpszAutoConfigUrl',
                'fAutoLogonIfChallenged',
                'dwReserved',
            ],
        )
        fields = dict(options_cls._fields_)
        self.assertIs(fields['fAutoLogonIfChallenged'], wintypes.BOOL)
        self.assertIs(fields['dwReserved'], wintypes.DWORD)
        self.assertEqual(
            [name for name, _typ in info_cls._fields_],
            ['dwAccessType', 'lpszProxy', 'lpszProxyBypass'],
        )
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(options_cls), 24)
            self.assertEqual(options_cls.fAutoLogonIfChallenged.offset, 16)
            self.assertEqual(options_cls.dwReserved.offset, 20)

    def test_winhttp_autoproxy_options_keep_reserved_zero(self):
        _ie_cls, options_cls, _info_cls = main._winhttp_ctypes()
        pac = main._fill_winhttp_autoproxy_options(options_cls(), 'http://proxy.example/wpad.dat')
        self.assertEqual(pac.dwFlags, 0x00000002)
        self.assertEqual(pac.lpszAutoConfigUrl, 'http://proxy.example/wpad.dat')
        self.assertEqual(pac.dwAutoDetectFlags, 0)
        self.assertEqual(pac.dwReserved, 0)
        self.assertTrue(pac.fAutoLogonIfChallenged)
        detect = main._fill_winhttp_autoproxy_options(options_cls(), '')
        self.assertEqual(detect.dwFlags, 0x00000001)
        self.assertEqual(detect.dwAutoDetectFlags, 0x00000003)
        self.assertEqual(detect.dwReserved, 0)
        self.assertTrue(detect.fAutoLogonIfChallenged)

    def test_get_windows_proxy_passes_sdk_pac_options(self):
        if sys.platform != 'win32':
            self.skipTest('WinHTTP is Windows-only')
        ie_cls, options_cls, _info_cls = main._winhttp_ctypes()
        captured = {}

        def fake_ie(ptr):
            config = ctypes.cast(ptr, ctypes.POINTER(ie_cls)).contents
            config.fAutoDetect = 1
            return 1

        def fake_get_proxy(session, url, options_ptr, info_ptr):
            options = ctypes.cast(options_ptr, ctypes.POINTER(options_cls)).contents
            captured['names'] = [name for name, _typ in type(options)._fields_]
            captured['dwFlags'] = int(options.dwFlags)
            captured['dwAutoDetectFlags'] = int(options.dwAutoDetectFlags)
            captured['dwReserved'] = int(options.dwReserved)
            captured['fAutoLogonIfChallenged'] = bool(options.fAutoLogonIfChallenged)
            captured['size'] = ctypes.sizeof(type(options))
            return 0

        fake_winhttp = mock.Mock()
        fake_winhttp.WinHttpGetIEProxyConfigForCurrentUser.side_effect = fake_ie
        fake_winhttp.WinHttpOpen.return_value = 11
        fake_winhttp.WinHttpGetProxyForUrl.side_effect = fake_get_proxy
        fake_winhttp.WinHttpCloseHandle.return_value = 1
        fake_kernel32 = mock.Mock()
        fake_windll = SimpleNamespace(winhttp=fake_winhttp, kernel32=fake_kernel32)
        with mock.patch.object(main.ctypes, 'windll', fake_windll):
            result = main._get_windows_proxy_for_url('https://example.invalid/update')
        self.assertEqual(result, {})
        self.assertEqual(captured['names'][3], 'fAutoLogonIfChallenged')
        self.assertEqual(captured['dwFlags'], 0x00000001)
        self.assertEqual(captured['dwAutoDetectFlags'], 0x00000003)
        self.assertEqual(captured['dwReserved'], 0)
        self.assertTrue(captured['fAutoLogonIfChallenged'])
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(captured['size'], 24)


class SaveFileVersionTests(unittest.TestCase):
    def _save_version_with_files(self, filenames):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, 'board.dsn')
            with open(source, 'w', encoding='utf-8') as stream:
                stream.write('source')
            for filename in filenames:
                with open(os.path.join(root, filename), 'w', encoding='utf-8') as stream:
                    stream.write(filename)
            status = mock.Mock()
            window = SimpleNamespace(statusBar=lambda: status)
            main.MainWindow.save_file_version(window, source)
            messages = status.showMessage.call_args_list
            self.assertTrue(messages)
            return messages[-1].args[0], set(os.listdir(root))

    def test_only_c_version_continues_with_d(self):
        today = time.strftime('%Y%m%d')
        message, filenames = self._save_version_with_files([f'board_{today}c.dsn'])
        self.assertIn(f'board_{today}d.dsn', message)
        self.assertIn(f'board_{today}d.dsn', filenames)
        self.assertNotIn(f'board_{today}.dsn', filenames)
        self.assertNotIn(f'board_{today}a.dsn', filenames)
        self.assertNotIn(f'board_{today}b.dsn', filenames)

    def test_non_contiguous_versions_continue_after_maximum(self):
        today = time.strftime('%Y%m%d')
        message, filenames = self._save_version_with_files([
            f'board_{today}.dsn',
            f'board_{today}b.dsn',
            f'board_{today}d.dsn',
        ])
        self.assertIn(f'board_{today}e.dsn', message)
        self.assertIn(f'board_{today}e.dsn', filenames)
        self.assertNotIn(f'board_{today}a.dsn', filenames)
        self.assertNotIn(f'board_{today}c.dsn', filenames)

    def test_after_z_continues_with_double_letter(self):
        """a-z 用完后继续 aa-zz，绝不生成 '{'/'|' 等非法字符或静默覆盖（P0-1 回归）。"""
        today = time.strftime('%Y%m%d')
        existing = [f'board_{today}.dsn'] + [
            f'board_{today}{chr(ord("a") + i)}.dsn' for i in range(26)
        ]
        message, filenames = self._save_version_with_files(existing)
        self.assertIn(f'board_{today}aa.dsn', message)
        self.assertIn(f'board_{today}aa.dsn', filenames)
        self.assertFalse(any('{' in name for name in filenames))
        self.assertFalse(any('|' in name for name in filenames))

    @unittest.skipUnless(sys.platform == 'win32', '仅 Windows 文件系统大小写不敏感，行为与其他平台不同')
    def test_uppercase_variant_is_not_overwritten(self):
        """Windows 大小写不敏感：已有大写 A 版本时跳过 a，且原文件内容不被覆盖（P0-1 回归）。"""
        today = time.strftime('%Y%m%d')
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, 'board.dsn')
            with open(source, 'w', encoding='utf-8') as stream:
                stream.write('source')
            uppercase = f'board_{today}A.dsn'
            for filename in (f'board_{today}.dsn', uppercase):
                with open(os.path.join(root, filename), 'w', encoding='utf-8') as stream:
                    stream.write(filename)
            status = mock.Mock()
            window = SimpleNamespace(statusBar=lambda: status)
            main.MainWindow.save_file_version(window, source)
            message = status.showMessage.call_args_list[-1].args[0]
            self.assertIn(f'board_{today}b.dsn', message)
            self.assertEqual(read_text(os.path.join(root, uppercase)), uppercase)

    def test_version_limit_rejects_without_overwrite(self):
        """后缀全部占用（0-702）时明确提示且不产生新文件、不覆盖（P0-1 回归）。"""
        today = time.strftime('%Y%m%d')
        suffixes = [''] + [main._version_suffix_from_rank(r) for r in range(1, 703)]
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, 'board.dsn')
            with open(source, 'w', encoding='utf-8') as stream:
                stream.write('source')
            for suffix in suffixes:
                with open(os.path.join(root, f'board_{today}{suffix}.dsn'), 'w', encoding='utf-8') as stream:
                    stream.write('v')
            before = set(os.listdir(root))
            status = mock.Mock()
            window = SimpleNamespace(statusBar=lambda: status)
            with mock.patch.object(main.QMessageBox, 'warning') as warn_mock:
                main.MainWindow.save_file_version(window, source)
            warn_mock.assert_called()
            self.assertEqual(set(os.listdir(root)), before)


class ExternalClipboardTests(unittest.TestCase):
    def test_local_urls_from_system_clipboard_are_paste_sources(self):
        with tempfile.TemporaryDirectory() as root:
            source_file = os.path.join(root, 'external.txt')
            source_dir = os.path.join(root, 'external-folder')
            with open(source_file, 'w', encoding='utf-8') as stream:
                stream.write('external')
            os.makedirs(source_dir)
            mime_data = SimpleNamespace(
                hasUrls=lambda: True,
                urls=lambda: [
                    main.QUrl.fromLocalFile(source_file),
                    main.QUrl.fromLocalFile(source_dir),
                    main.QUrl('https://example.invalid/ignored.txt'),
                ],
            )
            clipboard = SimpleNamespace(mimeData=lambda: mime_data)
            window = SimpleNamespace(clipboard_paths=[], clipboard_path=None)
            with mock.patch.object(main.QApplication, 'clipboard', return_value=clipboard):
                sources = main.MainWindow._get_clipboard_source_paths(window)
            self.assertEqual(sources, [source_file, source_dir])

    def test_system_clipboard_takes_precedence_over_stale_internal_paths(self):
        with tempfile.TemporaryDirectory() as root:
            external = os.path.join(root, 'external.txt')
            internal = os.path.join(root, 'internal.txt')
            for path in (external, internal):
                with open(path, 'w', encoding='utf-8') as stream:
                    stream.write(path)
            mime_data = SimpleNamespace(
                hasUrls=lambda: True,
                urls=lambda: [main.QUrl.fromLocalFile(external)],
            )
            clipboard = SimpleNamespace(mimeData=lambda: mime_data)
            window = SimpleNamespace(clipboard_paths=[internal], clipboard_path=internal)
            with mock.patch.object(main.QApplication, 'clipboard', return_value=clipboard):
                sources = main.MainWindow._get_clipboard_source_paths(window)
            self.assertEqual(sources, [external])


class BreadcrumbNavigationTests(unittest.TestCase):
    def test_double_click_opens_root_or_child_without_tree_navigation(self):
        with tempfile.TemporaryDirectory() as root:
            child = os.path.join(root, 'child')
            os.makedirs(child)
            opened = mock.Mock()
            window = SimpleNamespace(
                current_folder=root,
                _open_with_shell=opened,
                _rebuild_breadcrumb=mock.Mock(),
            )
            main.MainWindow._on_breadcrumb_double_clicked(window, root)
            main.MainWindow._on_breadcrumb_double_clicked(window, child)
            self.assertEqual(opened.call_args_list, [mock.call(root), mock.call(child)])

    def test_double_click_rejects_directory_outside_current_project(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            opened = mock.Mock()
            window = SimpleNamespace(
                current_folder=root,
                _open_with_shell=opened,
                _rebuild_breadcrumb=mock.Mock(),
            )
            main.MainWindow._on_breadcrumb_double_clicked(window, outside)
            opened.assert_not_called()


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
    def test_terminal_failure_preserves_partial_for_resume(self):
        """网络类失败保留 .part 供下次续传（与取消路径语义一致）；失败消息含续传提示。"""
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

            self.assertTrue(os.path.exists(thread.part_path))
            self.assertIn('GitHub 返回错误：HTTP 404', failures[0])
            self.assertIn('自动续传', failures[0])

    def test_integrity_failure_removes_partial_file(self):
        """内容校验失败清理临时文件（内容错误续传无意义）。"""
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path)
            thread.MAX_RETRIES = 0
            with open(thread.part_path, 'wb') as stream:
                stream.write(b'partial')
            failures = []
            thread.download_failed.connect(failures.append)
            with mock.patch.object(thread, '_download_once', side_effect=main.UpdateDownloadIntegrityError('bad digest')):
                thread.run()

            self.assertFalse(os.path.exists(thread.part_path))
            self.assertIn('bad digest', failures[0])

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
        """内容校验失败路径：_reset_partial 清理异常必须被报告（网络类失败保留 .part 不清理）。"""
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path)
            thread.MAX_RETRIES = 0
            failures = []
            thread.download_failed.connect(failures.append)
            with mock.patch.object(thread, '_download_once', side_effect=main.UpdateDownloadIntegrityError('bad data')):
                with mock.patch.object(
                    thread,
                    '_reset_partial',
                    return_value=PermissionError(13, 'access denied'),
                ):
                    thread.run()

            self.assertEqual(len(failures), 1)
            self.assertIn('下载临时文件未能清理', failures[0])
            self.assertIn(thread.part_path, failures[0])

    def test_cancel_during_integrity_check_keeps_partial(self):
        """下载完成后的 SHA-256 校验阶段被取消：走 canceled 路径且保留 .part（不误报校验失败）。"""
        class FakeResponse(object):
            status = 200
            headers = {'Content-Length': '5'}
            def __init__(self, data):
                self._data = data
                self._pos = 0
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def getcode(self):
                return 200
            def read(self, n):
                if self._pos >= len(self._data):
                    return b''
                chunk = self._data[self._pos:self._pos + n]
                self._pos += len(chunk)
                return chunk

        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            save_path = os.path.join(root, 'update.exe')
            thread = main.UpdateDownloadThread('https://example.invalid/update.exe', save_path, expected_size=5, expected_sha256='0' * 64)
            canceled = []
            failed = []
            thread.download_canceled.connect(lambda p, s: canceled.append((p, s)))
            thread.download_failed.connect(lambda m: failed.append(m))
            counter = [0]
            def interrupt_late():
                # 前几次检查（下载循环/哈希计算）返回 False，校验完成后返回 True
                counter[0] += 1
                return counter[0] >= 4
            with mock.patch.object(thread, 'isInterruptionRequested', side_effect=interrupt_late):
                with mock.patch.object(main, '_urlopen_with_proxy', return_value=FakeResponse(b'hello')):
                    result = thread._download_once(1)

            self.assertFalse(result)
            self.assertEqual(len(canceled), 1)
            self.assertTrue(os.path.exists(thread.part_path))
            self.assertEqual(len(failed), 0)


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

class RegexSafetyRegressionTests(unittest.TestCase):
    def test_rejects_brace_quantifier_bypasses(self):
        patterns = [
            r'^S(\d{1,2})+$',
            r'^S(\d{1,3})+$',
            r'^S(\d{1,2})*$',
            r'^S(\d{1,2}){1,}$',
            r'^S(\d{1,2}){2,}$',
            r'^S(\d{3,4})+$',
        ]
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                ok, error = main._validate_project_regex(pattern)
                self.assertFalse(ok, pattern)
                self.assertIn('回溯', error)

    def test_rejects_adjacent_unbounded_repeats(self):
        pattern = r'^S(\d{3})(a*a*a*a*a*a*a*a*a*a*)b$'
        ok, error = main._validate_project_regex(pattern)
        self.assertFalse(ok)
        self.assertIn('回溯', error)

    def test_rejects_backreference_repeat(self):
        ok, error = main._validate_project_regex(r'^(a+)\1+$')
        self.assertFalse(ok)
        self.assertIn('回溯', error)

    def test_allows_common_safe_patterns(self):
        patterns = [
            main.DEFAULT_MB_RE_TEXT,
            main.DEFAULT_DB_RE_TEXT,
            r'^S(\d{3,4})(-\d+)?$',
            r'^S(\d{3,4})(?:-(.*))?$',
            r'^S(\d{2})+$',
            r'^S(\d{1,2}){2,10}$',
            r'^(ab)+$',
        ]
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                ok, error = main._validate_project_regex(pattern)
                self.assertTrue(ok, '%s: %s' % (pattern, error))

    def test_resolve_regex_falls_back_for_unsafe_custom(self):
        pattern, fallback = main._resolve_regex(
            'custom', r'^S(\d{1,2})+$', main.DEFAULT_MB_RE
        )
        self.assertIs(pattern, main.DEFAULT_MB_RE)
        self.assertTrue(fallback)
        pattern, fallback = main._resolve_regex(
            'custom', r'^S(\d{3,4})$', main.DEFAULT_MB_RE
        )
        self.assertEqual(pattern.pattern, r'^S(\d{3,4})$')
        self.assertFalse(fallback)

    def test_optional_backreference_is_not_rejected(self):
        safe, error = main._is_regex_safe(r'^(a)\1?$')
        self.assertTrue(safe, error)

    def test_conditional_group_fails_closed(self):
        ok, error = main._validate_project_regex(r'^(a)?(?(1)b|c)$')
        self.assertFalse(ok)
        self.assertIn('回溯', error)

    def test_load_settings_warns_for_unsafe_regex(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = os.path.join(root, 'seavoexplorer.json')
            with open(cfg, 'w', encoding='utf-8') as stream:
                json.dump({
                    'project_paths': [],
                    'regex_state': 'custom',
                    'custom_mb_regex': r'^S(\d{1,2})+$',
                    'custom_db_regex': main.DEFAULT_DB_RE_TEXT,
                }, stream)

            class Stub(object):
                pass

            stub = Stub()
            for name in (
                '_init_default_settings',
                'load_settings',
                '_backup_corrupt_file',
                '_get_default_quick_access_paths',
            ):
                setattr(stub, name, getattr(main.MainWindow, name).__get__(stub))
            stub.CONFIG_FILE = cfg
            stub.app_dir = root
            stub._pending_load_warnings = []
            stub.load_settings()
            self.assertTrue(any('自定义项目正则无效' in item for item in stub._pending_load_warnings))
            _pattern, fallback = main._resolve_regex(
                stub.regex_state, stub.custom_mb_regex, main.DEFAULT_MB_RE
            )
            self.assertTrue(fallback)


class TextPreviewEncodingTests(unittest.TestCase):
    def test_utf8_and_gbk_round_trip(self):
        text = '项目文件说明'
        self.assertEqual(main._decode_text_bytes(text.encode('utf-8')), text)
        self.assertEqual(main._decode_text_bytes(text.encode('gbk')), text)

    def test_utf8_bom_is_stripped(self):
        text = '中文内容'
        self.assertEqual(
            main._decode_text_bytes(b'\xef\xbb\xbf' + text.encode('utf-8')),
            text,
        )

    def test_gbk_ambiguous_common_characters_prefer_gbk(self):
        for text in ('一', '目录', '说明', '版本'):
            with self.subTest(text=text):
                self.assertEqual(main._decode_text_bytes(text.encode('gbk')), text)

    def test_utf8_chinese_is_not_misdetected(self):
        text = '说明文档项目版本'
        self.assertEqual(main._decode_text_bytes(text.encode('utf-8')), text)

    def test_preview_text_strips_bom_and_reports_truncation(self):
        class PreviewTab(object):
            def __init__(self):
                self.value = None

            def setPlainText(self, value):
                self.value = value

        class Stub(object):
            def __init__(self):
                self.preview_tab = PreviewTab()

            def format_file_size(self, size):
                return main.MainWindow.format_file_size(self, size)

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'bom.txt')
            with open(path, 'w', encoding='utf-8-sig') as stream:
                stream.write('中文')
            stub = Stub()
            main.MainWindow._preview_text(stub, path)
            self.assertEqual(stub.preview_tab.value, '中文')

            with mock.patch.object(main.os.path, 'getsize', return_value=2 * 1024 * 1024):
                main.MainWindow._preview_text(stub, path)
            self.assertIn('文件过大', stub.preview_tab.value)


class ZipCreationTests(unittest.TestCase):
    def _stub(self):
        class Stub(object):
            pass

        stub = Stub()
        stub._create_unique_zip_path = main.MainWindow._create_unique_zip_path.__get__(stub)
        stub._write_path_to_zip = main.MainWindow._write_path_to_zip.__get__(stub)
        return stub

    def test_directory_entries_are_unique(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, 'tree', 'inner'))
            with open(os.path.join(root, 'tree', 'inner', 'f.txt'), 'w', encoding='utf-8') as stream:
                stream.write('x')
            stub = self._stub()
            zip_path, _name = stub._create_unique_zip_path(root, 'tree')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                stub._write_path_to_zip(archive, os.path.join(root, 'tree'), root)
            names = zipfile.ZipFile(zip_path).namelist()
            self.assertEqual(names, ['tree/', 'tree/inner/', 'tree/inner/f.txt'])
            self.assertEqual(len(names), len(set(names)))

    def test_single_file_has_no_directory_entry(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, 'only.txt')
            with open(source, 'w', encoding='utf-8') as stream:
                stream.write('x')
            stub = self._stub()
            zip_path, _name = stub._create_unique_zip_path(root, 'only')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                stub._write_path_to_zip(archive, source, root)
            self.assertEqual(zipfile.ZipFile(zip_path).namelist(), ['only.txt'])


    def test_parent_and_child_selection_deduplicates_and_excludes_output(self):
        with tempfile.TemporaryDirectory() as root:
            tree = os.path.join(root, 'tree')
            inner = os.path.join(tree, 'inner')
            os.makedirs(inner)
            child = os.path.join(inner, 'f.txt')
            with open(child, 'w', encoding='utf-8') as stream:
                stream.write('x')
            stub = self._stub()
            stub.statusBar = lambda: SimpleNamespace(showMessage=lambda *args: None)
            stub.add_paths_to_zip = main.MainWindow.add_paths_to_zip.__get__(stub)
            stub.add_paths_to_zip([tree, child])
            zip_path = os.path.join(root, '选中文件.zip')
            names = zipfile.ZipFile(zip_path).namelist()
            self.assertEqual(names, ['tree/', 'tree/inner/', 'tree/inner/f.txt'])
            self.assertEqual(len(names), len(set(names)))

class FolderStructureNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_partial_dict_is_completed_consistently(self):
        parent = main.QWidget()
        parent.folder_structure = {'version': '03', 'selected_folders': {'BOM': True}}
        dialog = main.NewStructureDialog(project_folder=None, parent=parent)
        self.assertEqual(set(dialog.selected_folders), set(main.DEFAULT_STRUCTURE_FOLDERS))
        self.assertTrue(all(
            dialog.folder_checkboxes[name].isChecked()
            for name in main.DEFAULT_STRUCTURE_FOLDERS
        ))
        self.assertEqual(
            set(dialog.get_structure_info()['selected_folders']),
            set(main.DEFAULT_STRUCTURE_FOLDERS),
        )
        self.assertIn('SCH', dialog.preview_text.toPlainText())

    def test_list_and_non_dict_fall_back_to_defaults(self):
        normalized = main._normalize_folder_structure(['BOM'])
        self.assertEqual(
            set(normalized['selected_folders']),
            set(main.DEFAULT_STRUCTURE_FOLDERS),
        )
        parent = main.QWidget()
        parent.folder_structure = ['BOM']
        dialog = main.NewStructureDialog(project_folder=None, parent=parent)
        self.assertTrue(all(
            dialog.folder_checkboxes[name].isChecked()
            for name in main.DEFAULT_STRUCTURE_FOLDERS
        ))

    def test_custom_folders_filtered_and_version_normalized(self):
        normalized = main._normalize_folder_structure({
            'version': '7',
            'selected_folders': {'BOM': 'false'},
            'custom_folders': ['A', '', 1, ' B '],
        })
        self.assertEqual(normalized['version'], '07')
        self.assertFalse(normalized['selected_folders']['BOM'])
        self.assertEqual(normalized['custom_folders'], ['A', ' B '])

    def test_load_settings_normalizes_folder_structure(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = os.path.join(root, 'seavoexplorer.json')
            with open(cfg, 'w', encoding='utf-8') as stream:
                json.dump({'folder_structure': {'selected_folders': ['BOM']}}, stream)

            class Stub(object):
                pass

            stub = Stub()
            for name in (
                '_init_default_settings',
                'load_settings',
                '_backup_corrupt_file',
                '_get_default_quick_access_paths',
            ):
                setattr(stub, name, getattr(main.MainWindow, name).__get__(stub))
            stub.CONFIG_FILE = cfg
            stub.app_dir = root
            stub._pending_load_warnings = []
            stub.load_settings()
            self.assertIsInstance(stub.folder_structure, dict)
            self.assertEqual(
                set(stub.folder_structure['selected_folders']),
                set(main.DEFAULT_STRUCTURE_FOLDERS),
            )




class OccupancyAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_explorer_select_command_keeps_path_as_own_argument(self):
        path = os.path.join(r'D:\资料', 'file with space.dsn')
        cmd = main._explorer_select_command(path)
        self.assertEqual(len(cmd), 3)
        self.assertTrue(cmd[0].lower().endswith('explorer.exe'))
        self.assertEqual(os.path.basename(cmd[0]).lower(), 'explorer.exe')
        self.assertEqual(cmd[1], '/select,')
        self.assertEqual(cmd[2], os.path.normpath(os.path.abspath(path)))
        self.assertNotIn(cmd[2], cmd[1])
        self.assertFalse(cmd[1].startswith('/select,' + cmd[2][:3]))

    def test_explorer_select_command_preserves_spaces_chinese_and_unc(self):
        local = os.path.join(r'D:\原理图 资料', 'S1200 (1).dsn')
        cmd = main._explorer_select_command(local)
        self.assertEqual(cmd[1], '/select,')
        self.assertEqual(cmd[2], os.path.normpath(os.path.abspath(local)))
        self.assertIn('原理图 资料', cmd[2])
        self.assertIn('S1200 (1).dsn', cmd[2])

        unc = r'\\server\share\原理图\a.dsn'
        cmd = main._explorer_select_command(unc)
        self.assertEqual(cmd[1], '/select,')
        self.assertEqual(cmd[2], os.path.normpath(os.path.abspath(unc)))
        self.assertTrue(cmd[2].startswith('\\\\') or cmd[2].startswith('//'))
        self.assertIn('原理图', cmd[2])

    def test_relative_path_inside_root_and_different_drive(self):
        root = r'D:\proj\S1200'
        inside = os.path.join(root, 'BOM', 'a.txt')
        self.assertEqual(
            main._relative_path_for_display(root, inside),
            os.path.join('BOM', 'a.txt'),
        )
        self.assertEqual(
            main._relative_path_for_display(root, root),
            '.',
        )
        outside = r'E:\other\a.txt'
        self.assertEqual(
            main._relative_path_for_display(root, outside),
            os.path.normpath(os.path.abspath(outside)),
        )

    def test_collect_largest_files_returns_top_n_sorted(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            sizes = {
                'tiny.bin': 10,
                'small.bin': 20,
                'mid.bin': 40,
                'big.bin': 80,
                'huge.bin': 160,
            }
            os.makedirs(os.path.join(root, 'sub'))
            for name, size in sizes.items():
                target = os.path.join(root, 'sub' if name == 'huge.bin' else '', name)
                with open(target, 'wb') as stream:
                    stream.write(b'x' * size)
            payload = main._collect_largest_files(root, top_n=3)
            names = [os.path.basename(item['path']) for item in payload['items']]
            self.assertEqual(names, ['huge.bin', 'big.bin', 'mid.bin'])
            self.assertEqual(payload['count'], 5)
            self.assertEqual(payload['total'], 10 + 20 + 40 + 80 + 160)
            self.assertFalse(payload['truncated'])
            self.assertEqual(payload['items'][0]['rel'], os.path.join('sub', 'huge.bin'))

    def test_collect_largest_files_skips_reparse_dirs_and_files(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            keep = os.path.join(root, 'keep.bin')
            skip_dir = os.path.join(root, 'skipdir')
            os.makedirs(skip_dir)
            skipped_in_dir = os.path.join(skip_dir, 'nested.bin')
            skip_file = os.path.join(root, 'link.bin')
            with open(keep, 'wb') as stream:
                stream.write(b'a' * 10)
            with open(skipped_in_dir, 'wb') as stream:
                stream.write(b'b' * 100)
            with open(skip_file, 'wb') as stream:
                stream.write(b'c' * 80)

            def fake_reparse(path):
                name = os.path.basename(path)
                return name in ('skipdir', 'link.bin')

            with mock.patch.object(main, '_is_reparse_point', side_effect=fake_reparse):
                payload = main._collect_largest_files(root, top_n=10)
            names = [os.path.basename(item['path']) for item in payload['items']]
            self.assertEqual(names, ['keep.bin'])
            self.assertEqual(payload['count'], 1)

    def test_collect_largest_files_canceled_returns_none(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'a.bin')
            with open(path, 'wb') as stream:
                stream.write(b'x')
            self.assertIsNone(main._collect_largest_files(root, is_canceled=lambda: True))

    def test_copy_path_texts_does_not_update_file_clipboard(self):
        class Stub(object):
            clipboard_paths = ['keep-me']
            clipboard_path = 'keep-me'

            def statusBar(self):
                return SimpleNamespace(showMessage=lambda *args, **kwargs: None)

        stub = Stub()
        stub._copy_path_texts_to_clipboard = main.MainWindow._copy_path_texts_to_clipboard.__get__(stub)
        with mock.patch.object(main.QApplication, 'clipboard') as clipboard_factory:
            clipboard = mock.Mock()
            clipboard_factory.return_value = clipboard
            ok = stub._copy_path_texts_to_clipboard([r'D:\资料\a.dsn', r'D:\资料\b.dsn'], '完整路径')
        self.assertTrue(ok)
        clipboard.setText.assert_called_once_with(r'D:\资料\a.dsn' + '\n' + r'D:\资料\b.dsn')
        self.assertEqual(stub.clipboard_paths, ['keep-me'])
        self.assertEqual(stub.clipboard_path, 'keep-me')



class UndoActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def _window(self):
        class Stub(object):
            def __init__(self):
                self._undo_stack = []
                self.undo_action = None
                self.comments = {}
                self.pinned_folders = []
                self.hidden_folders = []
                self.current_folder = None
                self.last_project_path = None
                self.settings = {}
                self.include_subfolders = False
                self.messages = []

            def _reset_preview(self):
                pass

            def statusBar(self):
                return SimpleNamespace(showMessage=lambda *args, **kwargs: self.messages.append(args[0] if args else ''))

            def save_comments(self):
                pass

            def save_settings_to_file(self, settings, include_subfolders):
                pass

        stub = Stub()
        stub._push_undo = main.MainWindow._push_undo.__get__(stub)
        stub._refresh_undo_action = main.MainWindow._refresh_undo_action.__get__(stub)
        stub._retarget_persisted_path = main.MainWindow._retarget_persisted_path.__get__(stub)
        stub.undo_last_action = main.MainWindow.undo_last_action.__get__(stub)
        stub._apply_undo_record = main.MainWindow._apply_undo_record.__get__(stub)
        stub._paste_single = main.MainWindow._paste_single.__get__(stub)
        stub.archive_to_old_folder = main.MainWindow.archive_to_old_folder.__get__(stub)
        return stub

    def test_undo_rename_restores_original_name(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            original = os.path.join(root, 'a.txt')
            current = os.path.join(root, 'b.txt')
            with open(original, 'w', encoding='utf-8') as stream:
                stream.write('x')
            os.rename(original, current)
            window = self._window()
            window._push_undo(main._make_undo_rename(current, original, '重命名'))
            with mock.patch.object(main.QMessageBox, 'warning') as warning:
                ok = window.undo_last_action()
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(original))
            self.assertFalse(os.path.exists(current))
            self.assertEqual(window._undo_stack, [])
            warning.assert_not_called()

    def test_undo_rename_refuses_when_original_occupied(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            original = os.path.join(root, 'a.txt')
            current = os.path.join(root, 'b.txt')
            with open(original, 'w', encoding='utf-8') as stream:
                stream.write('keep')
            with open(current, 'w', encoding='utf-8') as stream:
                stream.write('new')
            window = self._window()
            window._push_undo(main._make_undo_rename(current, original, '重命名'))
            with mock.patch.object(main.QMessageBox, 'warning') as warning:
                ok = window.undo_last_action()
            self.assertFalse(ok)
            self.assertTrue(os.path.exists(original))
            self.assertTrue(os.path.exists(current))
            self.assertEqual(read_text(original), 'keep')
            self.assertEqual(read_text(current), 'new')
            warning.assert_called_once()

    def test_undo_create_uses_recycle_backend(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            created = os.path.join(root, 'copy.txt')
            with open(created, 'w', encoding='utf-8') as stream:
                stream.write('x')
            recycled = []

            def fake_backend(path):
                recycled.append(path)
                os.remove(path)

            window = self._window()
            window._push_undo(main._make_undo_create([created], '粘贴副本'))
            with mock.patch.object(main, '_load_strict_recycle_backend', return_value=fake_backend):
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    ok = window.undo_last_action()
            self.assertTrue(ok)
            self.assertEqual(recycled, [created])
            self.assertFalse(os.path.exists(created))
            warning.assert_not_called()

    def test_undo_create_keeps_file_when_recycle_fails(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            created = os.path.join(root, 'copy.txt')
            with open(created, 'w', encoding='utf-8') as stream:
                stream.write('keep-me')

            def fake_backend(path):
                raise OSError('recycle unavailable')

            window = self._window()
            window._push_undo(main._make_undo_create([created], '保存版本'))
            with mock.patch.object(main, '_load_strict_recycle_backend', return_value=fake_backend):
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    ok = window.undo_last_action()
            self.assertFalse(ok)
            self.assertTrue(os.path.exists(created))
            self.assertEqual(read_text(created), 'keep-me')
            warning.assert_called_once()

    def test_undo_archive_moves_file_back(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'a.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('x')
            window = self._window()
            with mock.patch.object(main.QMessageBox, 'information') as info:
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    window.archive_to_old_folder([path])
            archived = os.path.join(root, 'old', 'a.txt')
            self.assertTrue(os.path.exists(archived))
            self.assertFalse(os.path.exists(path))
            info.assert_not_called()
            warning.assert_not_called()
            with mock.patch.object(main.QMessageBox, 'warning') as warning:
                ok = window.undo_last_action()
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(archived))
            warning.assert_not_called()

    def test_undo_archive_refuses_when_original_occupied(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            original = os.path.join(root, 'a.txt')
            current = os.path.join(root, 'old', 'a.txt')
            os.makedirs(os.path.join(root, 'old'))
            with open(original, 'w', encoding='utf-8') as stream:
                stream.write('keep')
            with open(current, 'w', encoding='utf-8') as stream:
                stream.write('archived')
            window = self._window()
            window._push_undo(main._make_undo_move([(original, current)], '归档到 old/'))
            with mock.patch.object(main.QMessageBox, 'warning') as warning:
                ok = window.undo_last_action()
            self.assertFalse(ok)
            self.assertEqual(read_text(original), 'keep')
            self.assertEqual(read_text(current), 'archived')
            warning.assert_called_once()

    def test_undo_empty_stack_does_not_raise(self):
        window = self._window()
        with mock.patch.object(main.QMessageBox, 'warning') as warning:
            ok = window.undo_last_action()
        self.assertFalse(ok)
        warning.assert_not_called()

    def test_paste_single_returns_unique_destination(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            source = os.path.join(root, 'a.txt')
            with open(source, 'w', encoding='utf-8') as stream:
                stream.write('x')
            window = self._window()
            first = window._paste_single(source, root)
            self.assertTrue(first.endswith('_副本1.txt') or os.path.basename(first).endswith('_副本1.txt'))
            self.assertTrue(os.path.exists(first))
            self.assertTrue(os.path.exists(source))


class FolderThreadErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def test_walk_error_does_not_also_emit_success(self):
        def failing_walk(root, onerror=None):
            if onerror:
                onerror(PermissionError("injected traversal failure"))
            return iter(())

        with mock.patch.object(main.os, 'walk', side_effect=failing_walk):
            stats = main.FolderStatsThread('IN_MEMORY_ONLY', 9)
            events = []
            stats.stats_ready.connect(lambda *args: events.append(('ready', args)))
            stats.stats_error.connect(lambda *args: events.append(('error', args)))
            stats.run()
        self.assertEqual([event[0] for event in events], ['error'])

        with mock.patch.object(main.os, 'walk', side_effect=failing_walk):
            search = main.FileSearchThread('IN_MEMORY_ONLY', 10, '', None, None)
            events = []
            search.search_ready.connect(lambda *args: events.append(('ready', args)))
            search.search_error.connect(lambda *args: events.append(('error', args)))
            search.run()
        self.assertEqual([event[0] for event in events], ['error'])

        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            with mock.patch.object(main.os, 'walk', side_effect=failing_walk):
                largest = main.FolderLargestFilesThread(root, 11)
                events = []
                largest.result_ready.connect(lambda *args: events.append(('ready', args)))
                largest.result_error.connect(lambda *args: events.append(('error', args)))
                largest.run()
            self.assertEqual([event[0] for event in events], ['error'])

    def test_missing_root_emits_error_for_stats(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, 'missing')
            thread = main.FolderStatsThread(missing, 7)
            events = []
            thread.stats_ready.connect(lambda *args: events.append(('ready', args)))
            thread.stats_error.connect(lambda *args: events.append(('error', args)))
            thread.run()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0], 'error')
            self.assertEqual(events[0][1][0], 7)

    def test_missing_root_emits_error_for_search(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, 'missing')
            thread = main.FileSearchThread(missing, 8, '', None, None)
            events = []
            thread.search_ready.connect(lambda *args: events.append(('ready', args)))
            thread.search_error.connect(lambda *args: events.append(('error', args)))
            thread.run()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0], 'error')
            self.assertEqual(events[0][1][0], 8)

    def test_missing_root_emits_error_for_largest_files(self):
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, 'missing')
            thread = main.FolderLargestFilesThread(missing, 12)
            events = []
            thread.result_ready.connect(lambda *args: events.append(('ready', args)))
            thread.result_error.connect(lambda *args: events.append(('error', args)))
            thread.run()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0], 'error')
            self.assertEqual(events[0][1][0], 12)


class OldArchiveGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = main.QApplication.instance() or main.QApplication([])

    def _window(self):
        class Stub(object):
            def _reset_preview(self):
                pass

            def statusBar(self):
                return SimpleNamespace(showMessage=lambda *args: None)

        stub = Stub()
        stub.archive_to_old_folder = main.MainWindow.archive_to_old_folder.__get__(stub)
        return stub

    def test_file_inside_old_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            old_dir = os.path.join(root, 'old')
            os.makedirs(old_dir)
            path = os.path.join(old_dir, 'a.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('x')
            window = self._window()
            with mock.patch.object(main.QMessageBox, 'information') as info:
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    window.archive_to_old_folder([path])
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.isdir(os.path.join(old_dir, 'old')))
            info.assert_called_once()
            warning.assert_not_called()

    def test_directory_named_old_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            old_dir = os.path.join(root, 'old')
            os.makedirs(old_dir)
            window = self._window()
            with mock.patch.object(main.QMessageBox, 'information') as info:
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    window.archive_to_old_folder([old_dir])
            self.assertTrue(os.path.isdir(old_dir))
            self.assertFalse(os.path.isdir(os.path.join(old_dir, 'old')))
            info.assert_called_once()
            warning.assert_not_called()

    def test_normal_file_is_archived(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'a.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('x')
            window = self._window()
            with mock.patch.object(main.QMessageBox, 'information') as info:
                with mock.patch.object(main.QMessageBox, 'warning') as warning:
                    window.archive_to_old_folder([path])
            self.assertTrue(os.path.exists(os.path.join(root, 'old', 'a.txt')))
            self.assertFalse(os.path.exists(path))
            info.assert_not_called()
            warning.assert_not_called()


    def test_old_name_collision_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'a.txt')
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write('new')
            old_dir = os.path.join(root, 'old')
            os.makedirs(old_dir)
            existing = os.path.join(old_dir, 'a.txt')
            with open(existing, 'w', encoding='utf-8') as stream:
                stream.write('old')
            window = self._window()
            with mock.patch.object(main.QMessageBox, 'warning') as warning:
                window.archive_to_old_folder([path])
            self.assertEqual(read_text(existing), 'old')
            self.assertEqual(read_text(os.path.join(old_dir, 'a_1.txt')), 'new')
            warning.assert_not_called()

class ClipboardPrecedenceTests(unittest.TestCase):
    def test_non_local_url_ignores_stale_internal_paths(self):
        with tempfile.TemporaryDirectory() as root:
            internal = os.path.join(root, 'internal.txt')
            with open(internal, 'w', encoding='utf-8') as stream:
                stream.write('x')
            mime_data = SimpleNamespace(
                hasUrls=lambda: True,
                urls=lambda: [main.QUrl('https://example.invalid/page')],
            )
            clipboard = SimpleNamespace(mimeData=lambda: mime_data)
            window = SimpleNamespace(clipboard_paths=[internal], clipboard_path=internal)
            with mock.patch.object(main.QApplication, 'clipboard', return_value=clipboard):
                sources = main.MainWindow._get_clipboard_source_paths(window)
            self.assertEqual(sources, [])


class DocumentationConsistencyTests(unittest.TestCase):
    def test_help_headings_are_sequential_and_unique(self):
        source = read_text(os.path.abspath(main.__file__))
        headings = re.findall(r'<h3[^>]*>([^<]+)</h3>', source)
        section_headings = [heading for heading in headings if '、' in heading]
        prefixes = [heading.split('、', 1)[0] for heading in section_headings]
        self.assertEqual(
            prefixes,
            ['一', '二', '三', '四', '五', '六', '七', '八',
             '九', '十', '十一', '十二', '十三', '十四'],
        )

    def test_readme_regex_contract_matches_one_group_support(self):
        project_root = os.path.dirname(os.path.abspath(main.__file__))
        readme = read_text(os.path.join(project_root, 'README.md'))
        self.assertIn('至少提供 1 个捕获组', readme)
        ok, error = main._validate_project_regex(r'^S(\d{3,4})$')
        self.assertTrue(ok, error)

    def test_pdf_help_does_not_claim_pagination(self):
        source = read_text(os.path.abspath(main.__file__))
        self.assertIn('预览前 3 页文本', source)
        self.assertNotIn('多页预览，可翻页查看', source)

    def test_reserved_names_include_com_lpt_and_exclude_clock(self):
        self.assertIn('COM1', main._WINDOWS_RESERVED_NAMES)
        self.assertIn('LPT9', main._WINDOWS_RESERVED_NAMES)
        self.assertNotIn('CLOCK$', main._WINDOWS_RESERVED_NAMES)
        self.assertIsNone(main._validate_windows_filename('CLOCK$'))
        self.assertIsNotNone(main._validate_windows_filename('CON'))

class UpdateModeTests(unittest.TestCase):
    def test_parse_update_arguments(self):
        args = main._parse_update_arguments([
            '--apply-update',
            '--target', r'C:\app\SeavoExplorer.exe',
            '--pid', '123',
            '--sha256', 'ABC',
            '--no-relaunch',
            '--silent',
        ])
        self.assertTrue(args.apply_update)
        self.assertEqual(args.target, r'C:\app\SeavoExplorer.exe')
        self.assertEqual(args.pid, 123)
        self.assertEqual(args.sha256, 'ABC')
        self.assertTrue(args.no_relaunch)
        self.assertTrue(args.silent)

    def test_non_update_arguments_do_not_enter_update_mode(self):
        args = main._parse_update_arguments(['--foo'])
        self.assertFalse(args.apply_update)
        self.assertIsNone(main._run_update_mode(['--foo']))

    def test_update_mode_rejects_source_runtime(self):
        with mock.patch.object(main.sys, 'frozen', False, create=True):
            self.assertEqual(
                main._run_update_mode([
                    '--apply-update', '--target', 'target.exe', '--silent'
                ]),
                1,
            )

    def test_wait_for_process_exit_returns_after_exit(self):
        process = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(0.5)']
        )
        try:
            self.assertTrue(main._wait_for_process_exit(process.pid, 5))
        finally:
            process.wait(timeout=5)

    def test_replace_executable_with_backup(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, 'target.exe')
            source = os.path.join(root, 'source.exe')
            with open(target, 'wb') as stream:
                stream.write(b'OLD')
            with open(source, 'wb') as stream:
                stream.write(b'NEW')
            ok, error = main._replace_executable(target, source)
            self.assertTrue(ok, error)
            with open(target, 'rb') as stream:
                self.assertEqual(stream.read(), b'NEW')
            backups = [name for name in os.listdir(root) if '.old' in name]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(root, backups[0]), 'rb') as stream:
                self.assertEqual(stream.read(), b'OLD')

    def test_replace_executable_preserves_backup_if_rollback_fails(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, 'target.exe')
            source = os.path.join(root, 'source.exe')
            with open(target, 'wb') as stream:
                stream.write(b'OLD')
            with open(source, 'wb') as stream:
                stream.write(b'NEW')
            real_replace = main.os.replace
            calls = []

            def flaky_replace(src, dst):
                calls.append((os.path.basename(src), os.path.basename(dst)))
                if src == target:
                    return real_replace(src, dst)
                if dst == target and os.path.basename(src).startswith(".SeavoExplorer-update-"):
                    raise PermissionError("injected install failure")
                if dst == target and src.endswith(".old"):
                    raise PermissionError("injected rollback failure")
                return real_replace(src, dst)

            with mock.patch.object(main.sys, 'platform', 'linux'):
                with mock.patch.object(main.os, 'replace', side_effect=flaky_replace):
                    ok, error = main._replace_executable(target, source, retries=2)
            backup = target + ".old"
            self.assertFalse(ok, error)
            self.assertFalse(os.path.exists(target))
            self.assertTrue(os.path.isfile(backup))
            with open(backup, "rb") as stream:
                self.assertEqual(stream.read(), b'OLD')
            self.assertEqual(len(calls), 3)
            self.assertTrue(any(name.startswith(".SeavoExplorer-update-") for name in os.listdir(root)))

    def test_replace_executable_rejects_same_path(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'same.exe')
            with open(path, 'wb') as stream:
                stream.write(b'X')
            ok, error = main._replace_executable(path, path)
            self.assertFalse(ok)
            self.assertIn('相同', error)

    def test_can_update_in_place_false_for_source_mode(self):
        window = SimpleNamespace()
        with mock.patch.object(main.sys, 'frozen', False, create=True):
            can_update, reason = main.MainWindow._can_update_in_place(window)
        self.assertFalse(can_update)
        self.assertIn('源码', reason)


if __name__ == '__main__':
    unittest.main()
