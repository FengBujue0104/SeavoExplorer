"""SeavoExplorer 的可复现构建公共逻辑。

`main.spec` 是 PyInstaller 配置的唯一事实来源；两个构建入口只负责前置检查、调用
spec、审计产物并生成校验信息。本模块仅使用 Python 标准库，以便 spec 在 Analysis
开始前直接导入。
"""

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import site
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = 'SeavoExplorer'
ENTRY_SCRIPT = 'main.py'
SPEC_FILE = 'main.spec'
BUILD_REQUIREMENTS = 'requirements-build.txt'

DATA_FILES = [
    ('favicon.ico', '.'),
    ('favicon_src.png', '.'),
]

HIDDEN_IMPORTS = [
    'PyQt5.QtWidgets',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtSvg',
    'PyPDF2',
    'openpyxl',
    'docx',
    'xlrd',
    'olefile',
    'cv2',
    'numpy',
    'PIL',
    'send2trash.win.modern',
    'send2trash.win.IFileOperationProgressSink',
    'pythoncom',
    'pywintypes',
    'win32com.shell.shell',
    'win32com.shell.shellcon',
]

EXCLUDED_MODULES = [
    'rarfile',
    'py7zr',
    'PyQt5.QtWebEngine',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtMultimedia',
    'PyQt5.QtMultimediaWidgets',
    'PyQt5.QtSql',
    'PyQt5.QtBluetooth',
    'PyQt5.QtNetwork',
    'PyQt5.QtXml',
    'PyQt5.QtTest',
    'PyQt5.QtDBus',
    'PyQt5.QtQml',
    'PyQt5.QtQuick',
    'PyQt5.QtQuickWidgets',
    'matplotlib',
    'scipy',
    'tornado',
    'notebook',
    'IPython',
    'jupyter',
]

REQUIRED_ICO_SIZES = {
    (16, 16),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}

BUILD_TARGETS = {
    'onefile': {
        'label': '单文件',
        'kind': 'file',
        'artifact': os.path.join('dist', APP_NAME + '.exe'),
        'entrypoint': os.path.join('dist', APP_NAME + '.exe'),
        'manifest': os.path.join('dist', APP_NAME + '.build.json'),
        'checksum': os.path.join('dist', APP_NAME + '.exe.sha256'),
    },
    'onedir': {
        'label': '单目录',
        'kind': 'directory',
        'artifact': os.path.join('dist', APP_NAME),
        'entrypoint': os.path.join('dist', APP_NAME, APP_NAME + '.exe'),
        'manifest': os.path.join('dist', APP_NAME, APP_NAME + '.build.json'),
        'checksum': os.path.join('dist', APP_NAME, APP_NAME + '.directory.sha256'),
    },
}

VERIFIED_PYTHON = '3.13.2'
VERIFIED_ARCHITECTURE = '64bit'
RELEASE_REQUIRED_CHECKS = (
    'python38_grammar',
    'py_compile',
    'setuptools_pyproject_validation',
    'unittest_test_safety',
    'unittest_tooling',
    'pyinstaller',
    'binary_source_audit',
    'isolated_exe_smoke',
)


class BuildError(RuntimeError):
    """构建前检、构建或产物审计失败。"""


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _display_command(command):
    try:
        return subprocess.list2cmdline(command)
    except (TypeError, ValueError):
        return ' '.join(str(part) for part in command)


def run_command(command, *, capture=False, check=True, env=None, cwd=ROOT_DIR):
    print('>', _display_command(command), flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=capture,
        text=capture,
        encoding='utf-8' if capture else None,
        errors='replace' if capture else None,
    )
    if check and result.returncode != 0:
        details = ''
        if capture:
            details = (result.stderr or result.stdout or '').strip()
        message = '命令失败（退出码 {}）：{}'.format(
            result.returncode,
            _display_command(command),
        )
        if details:
            message += '\n' + details
        raise BuildError(message)
    return result


def git_output(*arguments, check=True):
    result = run_command(
        ['git'] + list(arguments),
        capture=True,
        check=check,
    )
    return (result.stdout or '').strip()


def _app_version_from_source(source, filename='<source>'):
    tree = ast.parse(source, filename=filename)
    assignments = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == 'APP_VERSION'
            for target in node.targets
        ):
            continue
        assignments.append(node.value)
    if len(assignments) != 1:
        raise BuildError('APP_VERSION 必须且只能在顶层定义一次')
    value = assignments[0]
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise BuildError('APP_VERSION 必须是字符串字面量')
    version = value.value.strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise BuildError('APP_VERSION 必须是 X.Y.Z 三段数字：{}'.format(version))
    return version


def read_app_version():
    """从运行时源码读取 APP_VERSION，避免导入 GUI 及其依赖。"""
    source_path = os.path.join(ROOT_DIR, ENTRY_SCRIPT)
    with open(source_path, encoding='utf-8') as stream:
        return _app_version_from_source(stream.read(), source_path)


def _project_version_from_toml(text):
    current_section = None
    versions = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        section_match = re.fullmatch(r'\[([^\]]+)\]', line)
        if section_match:
            current_section = section_match.group(1).strip()
            continue
        if current_section != 'project' or not line or line.startswith('#'):
            continue
        version_match = re.fullmatch(r'version\s*=\s*"([^"]+)"\s*(?:#.*)?', line)
        if version_match:
            versions.append(version_match.group(1))
    if len(versions) != 1:
        raise BuildError('pyproject.toml 的 [project] 必须且只能定义一个 version')
    return versions[0]


def validate_version_consistency():
    version = read_app_version()
    pyproject_path = os.path.join(ROOT_DIR, 'pyproject.toml')
    with open(pyproject_path, encoding='utf-8') as stream:
        project_version = _project_version_from_toml(stream.read())
    readme_path = os.path.join(ROOT_DIR, 'README.md')
    with open(readme_path, encoding='utf-8') as stream:
        readme_matches = re.findall(
            r'(?m)^\*\*版本\s+([0-9]+\.[0-9]+\.[0-9]+)\*\*\s*$',
            stream.read(),
        )
    if len(readme_matches) != 1:
        raise BuildError('README.md 必须且只能包含一个顶部版本标记')
    for label, candidate in (
        ('pyproject.toml', project_version),
        ('README.md', readme_matches[0]),
    ):
        if candidate != version:
            raise BuildError(
                '版本不一致：main.py={}，{}={}'.format(version, label, candidate)
            )
    return version


def _four_part_version(version):
    parts = [int(part) for part in version.split('.')]
    file_version = tuple((parts + [0, 0, 0, 0])[:4])
    if any(part < 0 or part > 65535 for part in file_version):
        raise BuildError('Windows 版本号的每一段必须在 0..65535：{}'.format(version))
    return file_version


def write_version_info_file():
    """按 APP_VERSION 生成 Windows PE 版本资源，返回绝对路径。"""
    version = read_app_version()
    file_version = _four_part_version(version)
    dotted_version = '.'.join(str(part) for part in file_version)
    build_dir = os.path.join(ROOT_DIR, 'build')
    os.makedirs(build_dir, exist_ok=True)
    output_path = os.path.join(build_dir, APP_NAME + '-version-info.txt')
    content = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={file_version!r},
    prodvers={file_version!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [StringStruct('CompanyName', 'FengBujue0104'),
         StringStruct('FileDescription', 'SeavoExplorer 主板项目文件浏览器'),
         StringStruct('FileVersion', '{dotted_version}'),
         StringStruct('InternalName', '{app_name}'),
         StringStruct('OriginalFilename', '{app_name}.exe'),
         StringStruct('ProductName', '{app_name}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""".format(
        file_version=file_version,
        dotted_version=dotted_version,
        app_name=APP_NAME,
        version=version,
    )
    with open(output_path, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    return output_path


def _existing_path_value(candidates):
    result = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen or not os.path.isdir(candidate):
            continue
        seen.add(normalized)
        result.append(candidate)
    return os.pathsep.join(result)


def _windows_system_path_candidates():
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    return [
        os.path.join(system_root, 'System32'),
        system_root,
        os.path.join(system_root, 'System32', 'Wbem'),
        os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0'),
    ]


def sanitized_windows_runtime_path():
    """生成只包含 Windows 系统目录的分发包冒烟 PATH。"""
    return _existing_path_value(_windows_system_path_candidates())


def sanitized_windows_path():
    """生成仅包含 Python 与 Windows 系统目录的构建 PATH。"""
    candidates = []
    for prefix in (sys.prefix, sys.base_prefix, os.path.dirname(sys.executable)):
        if not prefix:
            continue
        candidates.extend([
            prefix,
            os.path.join(prefix, 'Scripts'),
            os.path.join(prefix, 'DLLs'),
        ])
    candidates.extend(_windows_system_path_candidates())
    return _existing_path_value(candidates)


def configure_spec_environment():
    """供 spec 在 Analysis 前调用，避免外部 PATH/Qt/Python 设置污染构建。"""
    if sys.platform == 'win32':
        os.environ['PATH'] = sanitized_windows_path()
    os.environ['PYTHONNOUSERSITE'] = '1'
    for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        os.environ.pop(name, None)
    user_site = site.getusersitepackages()
    user_sites = [user_site] if isinstance(user_site, str) else list(user_site)
    sys.path[:] = [
        path for path in sys.path
        if not any(_is_within(path, root) for root in user_sites if root)
    ]


def build_subprocess_environment(build_mode=None):
    env = os.environ.copy()
    if sys.platform == 'win32':
        env['PATH'] = sanitized_windows_path()
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONUTF8'] = '1'
    for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        env.pop(name, None)
    if build_mode is not None:
        env['SEAVO_BUILD_MODE'] = build_mode
    return env


def runtime_subprocess_environment():
    env = build_subprocess_environment()
    if sys.platform == 'win32':
        env['PATH'] = sanitized_windows_runtime_path()
    return env


def _exact_build_requirements():
    path = os.path.join(ROOT_DIR, BUILD_REQUIREMENTS)
    requirements = {}
    pattern = re.compile(r'^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^;\s]+)')
    with open(path, encoding='utf-8') as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            match = pattern.match(line)
            if not match:
                raise BuildError(
                    '{} 必须只包含精确的 == 版本约束：{}'.format(
                        BUILD_REQUIREMENTS,
                        line,
                    )
                )
            requirements[match.group(1)] = match.group(2)
    return requirements


def _normalize_distribution_name(name):
    return re.sub(r'[-_.]+', '-', str(name)).casefold()


def installed_distribution_versions():
    """在与 PyInstaller 相同的隔离环境中枚举全部发行包。"""
    script = (
        'import importlib.metadata as m, json; '
        "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions() "
        "if d.metadata.get('Name')}, sort_keys=True))"
    )
    result = run_command(
        [sys.executable, '-c', script],
        capture=True,
        env=build_subprocess_environment(),
    )
    try:
        data = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise BuildError('无法读取构建环境的发行包列表') from error
    if not isinstance(data, dict):
        raise BuildError('构建环境发行包列表格式错误')
    return data


def _isolated_venv_status():
    if sys.prefix == sys.base_prefix:
        return False, '当前解释器不是虚拟环境'
    config_path = os.path.join(sys.prefix, 'pyvenv.cfg')
    try:
        with open(config_path, encoding='utf-8') as stream:
            config_text = stream.read()
    except OSError:
        return False, '虚拟环境缺少 pyvenv.cfg'
    match = re.search(
        r'(?im)^include-system-site-packages\s*=\s*(true|false)\s*$',
        config_text,
    )
    if not match or match.group(1).casefold() != 'false':
        return False, '虚拟环境启用了 system-site-packages'
    return True, ''


def verify_build_environment(strict=True):
    if sys.platform != 'win32':
        raise BuildError('Windows EXE 必须在 Windows 上构建，PyInstaller 不支持跨平台打包')
    architecture = platform.architecture()[0]
    if architecture != VERIFIED_ARCHITECTURE or struct.calcsize('P') * 8 != 64:
        raise BuildError('官方构建要求 64 位 Python，当前为 {}'.format(architecture))

    issues = []
    isolated, isolation_issue = _isolated_venv_status()
    if not isolated:
        issues.append(isolation_issue)
    current_python = platform.python_version()
    if current_python != VERIFIED_PYTHON:
        issues.append('Python：当前 {}，已验证 {}'.format(current_python, VERIFIED_PYTHON))

    expected = _exact_build_requirements()
    installed_all = installed_distribution_versions()
    expected_normalized = {
        _normalize_distribution_name(name): (name, version)
        for name, version in expected.items()
    }
    installed_normalized = {
        _normalize_distribution_name(name): (name, version)
        for name, version in installed_all.items()
    }
    installed = {}
    missing = []
    for normalized, (distribution, expected_version) in expected_normalized.items():
        installed_entry = installed_normalized.get(normalized)
        if installed_entry is None:
            missing.append(distribution)
            installed[distribution] = None
            continue
        current = installed_entry[1]
        installed[distribution] = current
        if current != expected_version:
            issues.append(
                '{}：当前 {}，已验证 {}'.format(
                    distribution,
                    current,
                    expected_version,
                )
            )

    allowed_bootstrap = {'pip', 'wheel'}
    extra_normalized = set(installed_normalized) - set(expected_normalized) - allowed_bootstrap
    if extra_normalized:
        extras = [
            '{}=={}'.format(*installed_normalized[name])
            for name in sorted(extra_normalized)
        ]
        issues.append('存在锁文件之外的发行包：{}'.format(', '.join(extras)))

    if missing:
        raise BuildError(
            '缺少构建依赖：{}\n请删除并重建专用虚拟环境，然后运行：\n'
            'python -m pip install -r {}'.format(', '.join(missing), BUILD_REQUIREMENTS)
        )
    if issues:
        message = '构建环境与已验证基线不一致：\n- ' + '\n- '.join(issues)
        if strict:
            raise BuildError(
                message
                + '\n正式构建必须使用无额外包、未启用 system-site-packages 的专用 venv。'
            )
        print('[警告] ' + message.replace('\n', '\n[警告] '), flush=True)

    probe = (
        'import PyInstaller, PyQt5, PyPDF2, openpyxl, docx, xlrd, olefile, cv2, numpy, PIL; '
        'from send2trash.win.modern import send2trash; '
        'import pythoncom, pywintypes, win32com.shell.shell'
    )
    run_command(
        [sys.executable, '-c', probe],
        env=build_subprocess_environment(),
    )
    return installed, bool(strict and not issues and isolated)


def install_build_dependencies():
    if sys.prefix == sys.base_prefix:
        raise BuildError(
            '--install-deps 只允许在虚拟环境中使用，避免修改全局 Python。\n'
            '请先运行：python -m venv .venv-build'
        )
    run_command([
        sys.executable,
        '-m',
        'pip',
        'install',
        '--requirement',
        BUILD_REQUIREMENTS,
    ])


def validate_resources():
    required_files = {
        ENTRY_SCRIPT,
        SPEC_FILE,
        BUILD_REQUIREMENTS,
        'favicon.ico',
        'favicon_src.png',
        'README.md',
        'pyproject.toml',
        'test_safety.py',
        'test_tooling.py',
    }
    missing = [
        name for name in sorted(required_files)
        if not os.path.isfile(os.path.join(ROOT_DIR, name))
    ]
    if missing:
        raise BuildError('缺少构建必需文件：{}'.format(', '.join(missing)))

    from PIL import Image

    png_path = os.path.join(ROOT_DIR, 'favicon_src.png')
    with Image.open(png_path) as image:
        if image.width != image.height or image.width < 256:
            raise BuildError('favicon_src.png 必须是至少 256x256 的正方形图片')
    ico_path = os.path.join(ROOT_DIR, 'favicon.ico')
    with Image.open(ico_path) as image:
        sizes = set(image.info.get('sizes') or {image.size})
    missing_sizes = sorted(REQUIRED_ICO_SIZES - sizes)
    if missing_sizes:
        raise BuildError('favicon.ico 缺少尺寸：{}'.format(missing_sizes))


def validate_python38_syntax():
    for name in sorted(os.listdir(ROOT_DIR)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(ROOT_DIR, name)
        with open(path, encoding='utf-8') as stream:
            source = stream.read()
        try:
            ast.parse(source, filename=path, feature_version=(3, 8))
        except SyntaxError as error:
            raise BuildError('{} 不兼容 Python 3.8 语法：{}'.format(name, error)) from error


def run_source_checks(skip_tests=False):
    validate_version_consistency()
    validate_python38_syntax()
    python_env = build_subprocess_environment()
    python_files = [
        os.path.join(ROOT_DIR, name)
        for name in sorted(os.listdir(ROOT_DIR))
        if name.endswith('.py')
    ]
    run_command(
        [sys.executable, '-m', 'py_compile'] + python_files,
        env=python_env,
    )
    run_command([
        sys.executable,
        '-c',
        (
            'from setuptools.config.pyprojecttoml import read_configuration; '
            "read_configuration('pyproject.toml')"
        ),
    ], env=python_env)
    if not skip_tests:
        test_env = python_env.copy()
        test_env['QT_QPA_PLATFORM'] = 'offscreen'
        run_command(
            [
                sys.executable,
                '-m',
                'unittest',
                '-q',
                'test_safety.py',
                'test_tooling.py',
            ],
            env=test_env,
        )
    if os.path.isdir(os.path.join(ROOT_DIR, '.git')):
        run_command(['git', 'diff', '--check'])
        run_command(['git', 'diff', '--cached', '--check'])


def _is_within(path, root):
    try:
        normalized_path = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        normalized_root = os.path.normcase(os.path.realpath(os.path.abspath(root)))
        return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
    except (OSError, ValueError):
        return False


def _allowed_binary_roots():
    roots = [ROOT_DIR, sys.prefix, sys.base_prefix]
    system_root = os.environ.get('SystemRoot')
    if system_root:
        roots.append(system_root)
    return [root for root in roots if root]


def audit_binary_entries(entries):
    """供 spec 直接审计 Analysis.binaries。"""
    external = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            raise BuildError('Analysis 包含格式错误的二进制条目：{!r}'.format(entry))
        destination, source, kind = entry
        if not all(isinstance(value, str) for value in (destination, source, kind)):
            raise BuildError('Analysis 二进制条目必须全部是字符串：{!r}'.format(entry))
        if kind not in ('BINARY', 'EXTENSION'):
            raise BuildError('Analysis 二进制条目类型异常：{!r}'.format(entry))
        if not os.path.isabs(source):
            raise BuildError('二进制来源必须是绝对路径：{!r}'.format(source))
        if not any(_is_within(source, root) for root in _allowed_binary_roots()):
            external.append((destination, source, kind))
    if external:
        details = '\n'.join(
            '- {} <- {}'.format(destination, source)
            for destination, source, _kind in external[:20]
        )
        if len(external) > 20:
            details += '\n- ... 另有 {} 项'.format(len(external) - 20)
        raise BuildError('检测到来自未授权目录的二进制依赖：\n{}'.format(details))
    return len(entries)


def audit_analysis_toc():
    """构建后再次审计 TOC，并检查关键资源/Windows 回收站组件。"""
    toc_path = os.path.join(ROOT_DIR, 'build', 'main', 'Analysis-00.toc')
    if not os.path.isfile(toc_path):
        raise BuildError('未找到 PyInstaller Analysis 清单：{}'.format(toc_path))
    with open(toc_path, encoding='utf-8') as stream:
        analysis = ast.literal_eval(stream.read())

    entries = []

    def visit(value):
        if isinstance(value, (list, tuple)):
            if (
                len(value) == 3
                and isinstance(value[1], str)
                and value[2] in ('BINARY', 'EXTENSION', 'DATA', 'PYMODULE', 'PYSOURCE')
            ):
                entries.append(value)
                return
            for item in value:
                visit(item)

    visit(analysis)
    binary_entries = [entry for entry in entries if entry[2] in ('BINARY', 'EXTENSION')]
    audit_binary_entries(binary_entries)

    destinations = {str(entry[0]).replace('/', '\\').casefold() for entry in entries}
    required_destinations = {
        'favicon.ico',
        'favicon_src.png',
        'pythoncom',
        'pywintypes',
        'send2trash.win.modern',
        'send2trash.win.ifileoperationprogresssink',
        'pyi_rth_pythoncom',
        'pyi_rth_pywintypes',
    }
    missing = sorted(required_destinations - destinations)
    if missing:
        raise BuildError('Analysis 清单缺少关键资源：{}'.format(', '.join(missing)))

    required_fragments = (
        'win32com\\shell\\shell',
        'pywin32_system32\\pythoncom',
        'pywin32_system32\\pywintypes',
    )
    for fragment in required_fragments:
        if not any(fragment in destination for destination in destinations):
            raise BuildError('Analysis 清单缺少关键组件：{}'.format(fragment))
    return {
        'toc': os.path.relpath(toc_path, ROOT_DIR),
        'binary_count': len(binary_entries),
        'external_binary_count': 0,
    }


def _is_smoke_directory(path, smoke_root):
    parent = os.path.normcase(os.path.realpath(os.path.dirname(path)))
    expected_parent = os.path.normcase(os.path.realpath(smoke_root))
    return parent == expected_parent and os.path.basename(path).startswith(
        'seavo-build-smoke-'
    )


def _remove_smoke_directory(path, smoke_root, timeout=10.0):
    if not _is_smoke_directory(path, smoke_root):
        raise BuildError('拒绝清理意外的冒烟路径：{}'.format(path))
    deadline = time.monotonic() + timeout
    while os.path.exists(path):
        try:
            shutil.rmtree(path)
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)
    return True


def _cleanup_stale_smoke_directories(smoke_root):
    if not os.path.isdir(smoke_root):
        return
    for name in os.listdir(smoke_root):
        path = os.path.join(smoke_root, name)
        if os.path.isdir(path) and name.startswith('seavo-build-smoke-'):
            if not _remove_smoke_directory(path, smoke_root, timeout=2.0):
                print('[警告] 旧冒烟目录仍被占用：{}'.format(path))


def _stop_smoke_process(process, smoke_directory, smoke_root):
    """按可执行路径终止冒烟进程及其 PyInstaller onefile 子进程。"""
    if sys.platform == 'win32':
        if not _is_smoke_directory(smoke_directory, smoke_root):
            raise BuildError('拒绝终止意外目录中的进程：{}'.format(smoke_directory))
        system_root = os.environ.get('SystemRoot', r'C:\Windows')
        powershell = os.path.join(
            system_root,
            'System32',
            'WindowsPowerShell',
            'v1.0',
            'powershell.exe',
        )
        if not os.path.isfile(powershell):
            raise BuildError('无法找到 Windows PowerShell：{}'.format(powershell))
        script = (
            "$root = [IO.Path]::GetFullPath($env:SEAVO_SMOKE_ROOT).TrimEnd('\\') + '\\'; "
            '$comparison = [StringComparison]::OrdinalIgnoreCase; '
            'function Get-SmokeProcesses { '
            '  @(Get-Process -Name SeavoExplorer -ErrorAction SilentlyContinue | '
            '    Where-Object { '
            '      try { '
            '        [IO.Path]::GetFullPath($_.Path).StartsWith($root, $comparison) '
            '      } catch { $false } '
            '    }) '
            '}; '
            '$matches = @(Get-SmokeProcesses); '
            'if ($matches.Count -gt 0) { '
            '  $matches | Stop-Process -Force -ErrorAction Stop '
            '}; '
            'Start-Sleep -Milliseconds 250; '
            'if (@(Get-SmokeProcesses).Count -ne 0) { exit 3 }'
        )
        cleanup_env = runtime_subprocess_environment()
        cleanup_env['SEAVO_SMOKE_ROOT'] = smoke_directory
        try:
            result = subprocess.run(
                [powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                env=cleanup_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BuildError('无法终止隔离冒烟进程树') from error
        if result.returncode != 0:
            raise BuildError(
                'Windows 进程树终止失败，退出码 {}'.format(result.returncode)
            )
        if process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as error:
                raise BuildError('隔离冒烟进程树未在超时前退出') from error
        return

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def smoke_test_distribution(target_name):
    target = BUILD_TARGETS[target_name]
    entrypoint = os.path.join(ROOT_DIR, target['entrypoint'])
    smoke_root = os.path.join(ROOT_DIR, 'build')
    os.makedirs(smoke_root, exist_ok=True)
    _cleanup_stale_smoke_directories(smoke_root)
    temp_dir = tempfile.mkdtemp(
        prefix='seavo-build-smoke-',
        dir=smoke_root,
    )
    try:
        if target_name == 'onefile':
            smoke_exe = os.path.join(temp_dir, APP_NAME + '.exe')
            shutil.copy2(entrypoint, smoke_exe)
        else:
            source_dir = os.path.join(ROOT_DIR, target['artifact'])
            smoke_dir = os.path.join(temp_dir, APP_NAME)
            shutil.copytree(source_dir, smoke_dir)
            smoke_exe = os.path.join(smoke_dir, APP_NAME + '.exe')

        env = runtime_subprocess_environment()
        env['QT_QPA_PLATFORM'] = 'offscreen'
        process = subprocess.Popen(
            [smoke_exe],
            cwd=os.path.dirname(smoke_exe),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    raise BuildError(
                        '隔离启动冒烟失败：程序提前退出，退出码 {}'.format(return_code)
                    )
                time.sleep(0.25)
        finally:
            _stop_smoke_process(process, temp_dir, smoke_root)
    finally:
        # Windows Defender/杀毒软件可能在进程退出后短暂锁定刚生成的 EXE。冒烟结果
        # 不应因临时副本无法立即清理而变成失败；本次退避重试，后续冒烟也会清旧目录。
        if not _remove_smoke_directory(temp_dir, smoke_root):
            print('[警告] 冒烟临时目录仍被占用，后续冒烟将再次清理：{}'.format(temp_dir))


def _sanitize_remote_for_manifest(url):
    """移除 remote 中的用户名、令牌和本地路径，只保留公开主机/仓库标识。"""
    value = (url or '').strip()
    if not value:
        return None
    if re.match(r'^[A-Za-z]:[\\/]', value) or value.startswith(('\\\\', '//')):
        return None
    if '://' in value:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in ('https', 'ssh') or not parsed.hostname:
            return None
        path = parsed.path.rstrip('/')
        if path.casefold().endswith('.git'):
            path = path[:-4]
        return '{}://{}{}'.format(parsed.scheme.casefold(), parsed.hostname.casefold(), path)
    scp_match = re.fullmatch(r'(?:[^@/:]+@)?([^:/]+):(.+)', value)
    if scp_match:
        host, path = scp_match.groups()
        path = path.rstrip('/')
        if path.casefold().endswith('.git'):
            path = path[:-4]
        return 'ssh://{}/{}'.format(host.casefold(), path.lstrip('/'))
    return None


def _git_build_state():
    if not os.path.isdir(os.path.join(ROOT_DIR, '.git')):
        return {'commit': None, 'branch': None, 'origin': None, 'dirty': None}
    origin = git_output('remote', 'get-url', 'origin', check=False) or None
    return {
        'commit': git_output('rev-parse', 'HEAD'),
        'branch': git_output('branch', '--show-current'),
        'origin': _sanitize_remote_for_manifest(origin),
        'dirty': bool(git_output('status', '--porcelain')),
    }


def _input_hashes():
    names = [
        ENTRY_SCRIPT,
        SPEC_FILE,
        'build_support.py',
        'build_onefile.py',
        'build_onedir.py',
        BUILD_REQUIREMENTS,
        'requirements.txt',
        'pyproject.toml',
        'favicon.ico',
        'favicon_src.png',
    ]
    return {name: file_sha256(os.path.join(ROOT_DIR, name)) for name in names}


def _write_json_atomic(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
    os.replace(temporary, path)


def _directory_payload_records(directory, excluded_paths):
    excluded = {
        os.path.normcase(os.path.realpath(os.path.abspath(path)))
        for path in excluded_paths
    }
    records = []

    def fail_walk(error):
        raise BuildError('无法完整遍历 onedir 产物：{}'.format(error)) from error

    is_junction = getattr(os.path, 'isjunction', lambda _path: False)
    for current_root, directories, files in os.walk(
        directory,
        onerror=fail_walk,
        followlinks=False,
    ):
        for name in directories:
            path = os.path.join(current_root, name)
            if os.path.islink(path) or is_junction(path):
                raise BuildError('onedir 产物包含目录链接/联接点：{}'.format(path))
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            path = os.path.join(current_root, name)
            if os.path.islink(path) or is_junction(path):
                raise BuildError('onedir 产物包含文件链接/联接点：{}'.format(path))
            normalized = os.path.normcase(os.path.realpath(os.path.abspath(path)))
            if normalized in excluded:
                continue
            relative = os.path.relpath(path, directory).replace(os.sep, '/')
            records.append({
                'path': relative,
                'size': os.path.getsize(path),
                'sha256': file_sha256(path),
            })
    records.sort(key=lambda item: item['path'].casefold())
    if not records:
        raise BuildError('onedir 产物目录为空')
    return records


def _write_checksum_and_describe_artifact(target):
    artifact_path = os.path.join(ROOT_DIR, target['artifact'])
    entrypoint_path = os.path.join(ROOT_DIR, target['entrypoint'])
    checksum_path = os.path.join(ROOT_DIR, target['checksum'])
    manifest_path = os.path.join(ROOT_DIR, target['manifest'])

    if target['kind'] == 'file':
        digest = file_sha256(artifact_path)
        checksum_content = '{}  {}\n'.format(digest, os.path.basename(artifact_path))
        artifact = {
            'kind': 'file',
            'path': target['artifact'].replace(os.sep, '/'),
            'name': os.path.basename(artifact_path),
            'size': os.path.getsize(artifact_path),
            'sha256': digest,
            'checksum_file': target['checksum'].replace(os.sep, '/'),
        }
    else:
        records = _directory_payload_records(
            artifact_path,
            (checksum_path, manifest_path),
        )
        checksum_content = ''.join(
            '{}  {}\n'.format(record['sha256'], record['path'])
            for record in records
        )
        tree_digest = hashlib.sha256(checksum_content.encode('utf-8')).hexdigest().upper()
        entrypoint_relative = os.path.relpath(entrypoint_path, artifact_path).replace(os.sep, '/')
        entrypoint_record = next(
            (record for record in records if record['path'] == entrypoint_relative),
            None,
        )
        if entrypoint_record is None:
            raise BuildError('onedir 文件清单缺少启动器：{}'.format(entrypoint_relative))
        artifact = {
            'kind': 'directory',
            'path': target['artifact'].replace(os.sep, '/'),
            'name': os.path.basename(artifact_path),
            'size': sum(record['size'] for record in records),
            'file_count': len(records),
            'sha256': tree_digest,
            'sha256_kind': 'sha256-of-sorted-checksum-list-v1',
            'entrypoint': entrypoint_record,
            'checksum_file': target['checksum'].replace(os.sep, '/'),
        }

    os.makedirs(os.path.dirname(checksum_path), exist_ok=True)
    with open(checksum_path, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(checksum_content)
    return artifact


def write_build_outputs(
    target_name,
    version,
    started_at,
    source_state,
    installed_versions,
    audit,
    checks,
    environment_verified,
):
    target = BUILD_TARGETS[target_name]
    manifest_path = os.path.join(ROOT_DIR, target['manifest'])
    artifact = _write_checksum_and_describe_artifact(target)

    manifest = {
        'schema_version': 1,
        'application': {'name': APP_NAME, 'version': version},
        'build': {
            'type': target_name,
            'spec': SPEC_FILE,
            'started_at_utc': started_at,
            'finished_at_utc': utc_now(),
        },
        'source': source_state,
        'environment': {
            'python': platform.python_version(),
            'implementation': platform.python_implementation(),
            'architecture': platform.architecture()[0],
            'platform': platform.platform(),
            'distributions': installed_versions,
            'path_sanitized': True,
            'strict_environment': environment_verified,
        },
        'inputs_sha256': _input_hashes(),
        'checks': checks,
        'binary_source_audit': audit,
        'artifact': artifact,
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest


def _require_mapping(value, label):
    if not isinstance(value, dict):
        raise BuildError('{} 必须是 JSON object'.format(label))
    return value


def validate_release_artifacts(expected_version, expected_commit, require_clean=True):
    """Fail-closed 校验 onefile、checksum、manifest 和当前构建输入。"""
    target = BUILD_TARGETS['onefile']
    artifact_path = os.path.join(ROOT_DIR, target['artifact'])
    checksum_path = os.path.join(ROOT_DIR, target['checksum'])
    manifest_path = os.path.join(ROOT_DIR, target['manifest'])
    for path in (artifact_path, checksum_path, manifest_path):
        if not os.path.isfile(path):
            raise BuildError('缺少发布产物：{}'.format(os.path.relpath(path, ROOT_DIR)))

    try:
        with open(manifest_path, encoding='utf-8') as stream:
            manifest = json.load(stream)
        with open(checksum_path, encoding='ascii') as stream:
            checksum_text = stream.read()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BuildError('无法读取发布 manifest/checksum：{}'.format(error)) from error

    manifest = _require_mapping(manifest, 'manifest')
    application = _require_mapping(manifest.get('application'), 'manifest.application')
    build = _require_mapping(manifest.get('build'), 'manifest.build')
    source = _require_mapping(manifest.get('source'), 'manifest.source')
    environment = _require_mapping(manifest.get('environment'), 'manifest.environment')
    inputs = _require_mapping(manifest.get('inputs_sha256'), 'manifest.inputs_sha256')
    checks = _require_mapping(manifest.get('checks'), 'manifest.checks')
    audit = _require_mapping(manifest.get('binary_source_audit'), 'manifest.binary_source_audit')
    artifact = _require_mapping(manifest.get('artifact'), 'manifest.artifact')

    actual_digest = file_sha256(artifact_path)
    actual_size = os.path.getsize(artifact_path)
    expected_values = {
        'schema_version': (manifest.get('schema_version'), 1),
        '应用名称': (application.get('name'), APP_NAME),
        '应用版本': (application.get('version'), expected_version),
        '构建类型': (build.get('type'), 'onefile'),
        'spec': (build.get('spec'), SPEC_FILE),
        '源码 commit': (source.get('commit'), expected_commit),
        '源码分支': (source.get('branch'), 'main'),
        '产物类型': (artifact.get('kind'), 'file'),
        '产物路径': (artifact.get('path'), target['artifact'].replace(os.sep, '/')),
        '产物名称': (artifact.get('name'), os.path.basename(artifact_path)),
        'checksum 路径': (
            artifact.get('checksum_file'),
            target['checksum'].replace(os.sep, '/'),
        ),
        '产物 SHA-256': (artifact.get('sha256'), actual_digest),
        '产物大小': (artifact.get('size'), actual_size),
        'Python': (environment.get('python'), VERIFIED_PYTHON),
        '架构': (environment.get('architecture'), VERIFIED_ARCHITECTURE),
        'PATH 隔离': (environment.get('path_sanitized'), True),
        '严格环境': (environment.get('strict_environment'), True),
        '外部二进制数量': (audit.get('external_binary_count'), 0),
    }
    mismatches = [
        '{}：manifest={!r}，预期={!r}'.format(label, actual, expected)
        for label, (actual, expected) in expected_values.items()
        if actual != expected
    ]
    if require_clean and source.get('dirty') is not False:
        mismatches.append('manifest 显示构建时工作区不是干净状态')

    expected_distributions = _exact_build_requirements()
    distributions = environment.get('distributions')
    if not isinstance(distributions, dict) or distributions != expected_distributions:
        mismatches.append('manifest 的发行包集合/版本与 requirements-build.txt 不一致')

    for check_name in RELEASE_REQUIRED_CHECKS:
        if checks.get(check_name) is not True:
            mismatches.append('正式发布检查未通过：{}'.format(check_name))

    current_inputs = _input_hashes()
    if inputs != current_inputs:
        mismatches.append('manifest 的构建输入哈希与当前文件不一致')

    checksum_match = re.fullmatch(
        r'([0-9A-Fa-f]{64})  ([^\r\n]+)\r?\n?',
        checksum_text,
    )
    if not checksum_match:
        mismatches.append('checksum 必须只有一行“64位哈希  文件名”')
    else:
        if checksum_match.group(1).upper() != actual_digest:
            mismatches.append('checksum 与 EXE 的 SHA-256 不一致')
        if checksum_match.group(2) != os.path.basename(artifact_path):
            mismatches.append('checksum 中的文件名不正确')

    if mismatches:
        raise BuildError('发布产物校验失败：\n- ' + '\n- '.join(mismatches))
    return manifest


def build_distribution(
    target_name,
    *,
    install_deps=False,
    skip_tests=False,
    skip_smoke=False,
    strict_environment=True,
):
    if target_name not in BUILD_TARGETS:
        raise BuildError('未知构建类型：{}'.format(target_name))
    target = BUILD_TARGETS[target_name]
    os.chdir(ROOT_DIR)
    started_at = utc_now()

    print('=' * 56)
    print(' {} {}构建'.format(APP_NAME, target['label']))
    print('=' * 56)
    print('解释器：{} ({})'.format(sys.executable, platform.python_version()))

    if install_deps:
        install_build_dependencies()
    installed_versions, environment_verified = verify_build_environment(
        strict=strict_environment
    )
    validate_resources()
    run_source_checks(skip_tests=skip_tests)
    version = validate_version_consistency()
    source_state = _git_build_state()

    run_command([
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        SPEC_FILE,
    ], env=build_subprocess_environment(target_name))

    entrypoint = os.path.join(ROOT_DIR, target['entrypoint'])
    if not os.path.isfile(entrypoint) or os.path.getsize(entrypoint) == 0:
        raise BuildError('PyInstaller 未生成预期启动器：{}'.format(target['entrypoint']))

    audit = audit_analysis_toc()
    if not skip_smoke:
        smoke_test_distribution(target_name)

    checks = {
        'python38_grammar': True,
        'py_compile': True,
        'setuptools_pyproject_validation': True,
        'unittest_test_safety': None if skip_tests else True,
        'unittest_tooling': None if skip_tests else True,
        'pyinstaller': True,
        'binary_source_audit': True,
        'isolated_exe_smoke': None if skip_smoke else True,
    }
    manifest = write_build_outputs(
        target_name,
        version,
        started_at,
        source_state,
        installed_versions,
        audit,
        checks,
        environment_verified,
    )
    artifact_data = manifest['artifact']
    print()
    print('=' * 56)
    print(' 构建成功')
    print(' 产物：{}'.format(target['artifact']))
    print(' 大小：{:.1f} MiB'.format(artifact_data['size'] / 1024 / 1024))
    print(' SHA-256：{}'.format(artifact_data['sha256']))
    print(' Manifest：{}'.format(target['manifest']))
    print('=' * 56)
    return manifest


def build_cli(target_name):
    target = BUILD_TARGETS[target_name]
    parser = argparse.ArgumentParser(
        description='构建 {} {}分发包'.format(APP_NAME, target['label']),
    )
    parser.add_argument(
        '--install-deps',
        action='store_true',
        help='先在当前虚拟环境安装 requirements-build.txt；默认不联网、不改环境',
    )
    parser.add_argument(
        '--skip-tests',
        action='store_true',
        help='跳过 test_safety.py 和 test_tooling.py；正式发布不得使用',
    )
    parser.add_argument(
        '--skip-smoke',
        action='store_true',
        help='跳过隔离启动冒烟；正式发布不得使用',
    )
    parser.add_argument(
        '--allow-unverified-env',
        action='store_true',
        help='允许偏离已验证的 Python/依赖版本，仅适合本地试验',
    )
    args = parser.parse_args()
    try:
        build_distribution(
            target_name,
            install_deps=args.install_deps,
            skip_tests=args.skip_tests,
            skip_smoke=args.skip_smoke,
            strict_environment=not args.allow_unverified_env,
        )
    except (BuildError, OSError, ValueError) as error:
        print('\n构建失败：{}'.format(error), file=sys.stderr)
        return 1
    return 0
