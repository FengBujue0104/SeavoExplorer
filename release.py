"""构建、校验并发布 SeavoExplorer GitHub Release。

新发布默认从干净、已同步的 main 和严格构建 venv 重新构建。``--resume`` 只用于恢复
同一 commit 已存在的 annotated tag 或 draft；脚本绝不删除或覆盖远端状态。
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urlsplit

from build_support import (
    APP_NAME,
    BUILD_TARGETS,
    BuildError,
    ROOT_DIR,
    file_sha256,
    git_output,
    read_app_version,
    run_command,
    validate_release_artifacts,
)


REPOSITORY = 'FengBujue0104/SeavoExplorer'
MAIN_BRANCH = 'main'
MINIMUM_GH_VERSION = (2, 94, 0)


class ReleaseError(RuntimeError):
    """发布前检或远端状态不符合安全发布条件。"""


def normalize_version(value):
    version = value.strip()
    if not version.startswith('v'):
        version = 'v' + version
    if not re.fullmatch(r'v\d+\.\d+\.\d+', version):
        raise ReleaseError('版本号必须是 vX.Y.Z，例如 v0.6.0')
    return version


def _origin_matches_repository(url):
    value = (url or '').strip()
    expected_path = '/' + REPOSITORY.casefold()
    if '://' in value:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in ('https', 'ssh'):
            return False
        if (parsed.hostname or '').casefold() != 'github.com':
            return False
        if parsed.password:
            return False
        if parsed.scheme.casefold() == 'https' and parsed.username:
            return False
        if parsed.scheme.casefold() == 'ssh' and (parsed.username or 'git') != 'git':
            return False
        path = parsed.path.rstrip('/').casefold()
        if path.endswith('.git'):
            path = path[:-4]
        return path == expected_path
    scp_match = re.fullmatch(r'git@github\.com:(.+)', value, flags=re.IGNORECASE)
    if not scp_match:
        return False
    path = '/' + scp_match.group(1).rstrip('/').casefold()
    if path.endswith('.git'):
        path = path[:-4]
    return path == expected_path


def _require_gh_baseline():
    result = run_command(['gh', '--version'], capture=True)
    match = re.search(r'(?m)^gh version (\d+)\.(\d+)\.(\d+)', result.stdout or '')
    if not match:
        raise ReleaseError('无法识别 GitHub CLI 版本')
    version = tuple(int(part) for part in match.groups())
    if version < MINIMUM_GH_VERSION:
        raise ReleaseError(
            'GitHub CLI 至少需要 {}，当前为 {}'.format(
                '.'.join(map(str, MINIMUM_GH_VERSION)),
                '.'.join(map(str, version)),
            )
        )
    run_command(['gh', 'auth', 'status'])
    return version


def _require_clean_main(expected_version):
    branch = git_output('branch', '--show-current')
    if branch != MAIN_BRANCH:
        raise ReleaseError('只能从 main 发布，当前分支为 {}'.format(branch or '<detached>'))
    dirty = git_output('status', '--porcelain')
    if dirty:
        raise ReleaseError('工作区必须完全干净（包括未跟踪文件）：\n{}'.format(dirty))

    origin = git_output('remote', 'get-url', 'origin')
    if not _origin_matches_repository(origin):
        raise ReleaseError('origin 不是预期的 GitHub HTTPS/SSH 仓库：{}'.format(origin))
    source_version = read_app_version()
    if expected_version != 'v' + source_version:
        raise ReleaseError(
            '发布版本与源码不一致：参数={}，APP_VERSION={}'.format(
                expected_version,
                source_version,
            )
        )

    run_command([
        'git',
        'fetch',
        'origin',
        'refs/heads/{0}:refs/remotes/origin/{0}'.format(MAIN_BRANCH),
        '--tags',
    ])
    head = git_output('rev-parse', 'HEAD')
    origin_head = git_output('rev-parse', 'origin/' + MAIN_BRANCH)
    if head != origin_head:
        raise ReleaseError(
            'HEAD 必须与 origin/main 完全一致。请先单独完成 push/pull。\n'
            'HEAD={}\norigin/main={}'.format(head, origin_head)
        )
    return {
        'head': head,
        'origin': origin,
        'version': source_version,
    }


def _ensure_source_unchanged(initial_state):
    branch = git_output('branch', '--show-current')
    head = git_output('rev-parse', 'HEAD')
    origin = git_output('remote', 'get-url', 'origin')
    dirty = git_output('status', '--porcelain')
    remote_line = git_output('ls-remote', 'origin', 'refs/heads/' + MAIN_BRANCH)
    remote_head = remote_line.split()[0] if remote_line else ''
    if (
        branch != MAIN_BRANCH
        or head != initial_state['head']
        or remote_head != initial_state['head']
        or origin != initial_state['origin']
        or not _origin_matches_repository(origin)
        or dirty
    ):
        raise ReleaseError(
            '构建/确认期间源码或 origin 状态发生变化，已中止发布。\n'
            'branch={!r}, HEAD={}, origin/main={}, origin={!r}, dirty={!r}'.format(
                branch,
                head,
                remote_head,
                origin,
                dirty,
            )
        )


def _local_tag_state(tag):
    object_result = run_command(
        ['git', 'rev-parse', '--verify', 'refs/tags/' + tag],
        capture=True,
        check=False,
    )
    if object_result.returncode != 0:
        return None
    object_id = (object_result.stdout or '').strip()
    object_type = git_output('cat-file', '-t', object_id)
    commit = git_output('rev-list', '-n', '1', tag)
    return {
        'object_id': object_id,
        'commit': commit,
        'annotated': object_type == 'tag',
    }


def _parse_remote_tag_state(output, tag):
    direct_ref = 'refs/tags/' + tag
    peeled_ref = direct_ref + '^{}'
    values = {}
    for raw_line in (output or '').splitlines():
        parts = raw_line.split()
        if len(parts) != 2 or parts[1] not in (direct_ref, peeled_ref):
            raise ReleaseError('git ls-remote 返回了无法识别的 tag 数据')
        if parts[1] in values:
            raise ReleaseError('git ls-remote 返回了重复的 tag ref')
        values[parts[1]] = parts[0]
    if not values:
        return None
    if direct_ref not in values:
        raise ReleaseError('远端 tag 缺少直接对象 ref')
    annotated = peeled_ref in values
    return {
        'object_id': values[direct_ref],
        'commit': values.get(peeled_ref, values[direct_ref]),
        'annotated': annotated,
    }


def _remote_tag_state(tag):
    result = run_command(
        [
            'git',
            'ls-remote',
            '--tags',
            'origin',
            'refs/tags/' + tag,
            'refs/tags/' + tag + '^{}',
        ],
        capture=True,
    )
    return _parse_remote_tag_state(result.stdout, tag)


def _release_state(tag):
    result = run_command(
        [
            'gh',
            'release',
            'view',
            tag,
            '-R',
            REPOSITORY,
            '--json',
            (
                'url,isDraft,isImmutable,isPrerelease,tagName,targetCommitish,'
                'name,body,assets'
            ),
        ],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or '').strip()
        if 'release not found' in details.casefold():
            return None
        raise ReleaseError('无法读取 GitHub Release 状态：{}'.format(details or '未知错误'))
    try:
        state = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReleaseError('无法解析 GitHub Release 状态') from error
    if not isinstance(state, dict):
        raise ReleaseError('GitHub Release 状态格式错误')
    return state


def _remote_assets_by_name(release):
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise ReleaseError('GitHub Release assets 格式错误')
    result = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get('name'), str):
            raise ReleaseError('GitHub Release 包含格式错误的 asset')
        name = asset['name']
        if name in result:
            raise ReleaseError('GitHub Release 包含重名 asset：{}'.format(name))
        result[name] = asset
    return result


def _validate_draft_state(release, tag, manifest, allowed_asset_names, final=False):
    if release is None:
        raise ReleaseError('GitHub draft 不存在')
    expected_title = '{} {}'.format(APP_NAME, tag)
    expected_commit = manifest['source']['commit']
    checks = {
        'isDraft': release.get('isDraft') is True,
        'isImmutable': release.get('isImmutable') is False,
        'isPrerelease': release.get('isPrerelease') is False,
        'tagName': release.get('tagName') == tag,
        'targetCommitish': release.get('targetCommitish') in (
            MAIN_BRANCH,
            expected_commit,
        ),
        'name': release.get('name') == expected_title,
        'body prefix': _body_starts_with_notes_prefix(release.get('body'), manifest),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ReleaseError('draft Release 状态不符合预期：{}'.format(', '.join(failed)))
    asset_names = set(_remote_assets_by_name(release))
    allowed = set(allowed_asset_names)
    if not asset_names <= allowed:
        raise ReleaseError(
            'draft 包含未授权资产：{}'.format(', '.join(sorted(asset_names - allowed)))
        )
    if final and asset_names != allowed:
        raise ReleaseError(
            'draft 资产集合不完整：缺少 {}'.format(', '.join(sorted(allowed - asset_names)))
        )


def _check_partial_state(tag, head, resume):
    local = _local_tag_state(tag)
    remote = _remote_tag_state(tag)
    release = _release_state(tag)

    for label, state in (('本地 tag', local), ('远端 tag', remote)):
        if state is None:
            continue
        if not state['annotated']:
            raise ReleaseError('{} {} 不是 annotated tag'.format(label, tag))
        if state['commit'] != head:
            raise ReleaseError('{} {} 指向其他 commit：{}'.format(label, tag, state['commit']))
    if local and remote and local['object_id'] != remote['object_id']:
        raise ReleaseError('本地与远端 tag object 不一致，不能自动恢复')
    if release and not release.get('isDraft'):
        raise ReleaseError('Release {} 已发布：{}'.format(tag, release.get('url', '')))
    if release and release.get('tagName') != tag:
        raise ReleaseError('draft Release 的 tagName 不匹配')
    if release and remote is None:
        raise ReleaseError('draft Release 存在，但远端 tag 不存在')

    partial = local is not None or remote is not None or release is not None
    if resume and not partial:
        raise ReleaseError('--resume 只允许恢复已经存在的 tag 或 draft')
    if partial and not resume:
        raise ReleaseError(
            '检测到同版本的未完成 tag/draft。确认属于当前 HEAD 后使用 --resume；'
            '脚本不会自动删除。'
        )
    return {'local': local, 'remote': remote, 'release': release}


def _asset_paths():
    target = BUILD_TARGETS['onefile']
    return [
        os.path.join(ROOT_DIR, target['artifact']),
        os.path.join(ROOT_DIR, target['checksum']),
        os.path.join(ROOT_DIR, target['manifest']),
    ]


def _snapshot_assets(manifest):
    staging_root = os.path.join(ROOT_DIR, 'dist')
    os.makedirs(staging_root, exist_ok=True)
    snapshot_dir = tempfile.mkdtemp(prefix='.release-snapshot-', dir=staging_root)
    try:
        copied = {}
        for source in _asset_paths():
            destination = os.path.join(snapshot_dir, os.path.basename(source))
            shutil.copy2(source, destination)
            name = os.path.basename(destination)
            if name in copied:
                raise ReleaseError('发布资产文件名冲突：{}'.format(name))
            copied[name] = destination

        target = BUILD_TARGETS['onefile']
        exe_name = manifest['artifact']['name']
        exe_path = copied.get(exe_name)
        if (
            exe_path is None
            or os.path.getsize(exe_path) != manifest['artifact']['size']
            or file_sha256(exe_path) != manifest['artifact']['sha256']
        ):
            raise ReleaseError('发布快照中的 EXE 与 manifest 不一致')

        checksum_name = os.path.basename(target['checksum'])
        expected_checksum = '{}  {}\n'.format(
            manifest['artifact']['sha256'],
            exe_name,
        )
        try:
            with open(copied[checksum_name], encoding='ascii', newline='') as stream:
                snapshot_checksum = stream.read()
        except (KeyError, OSError, UnicodeError) as error:
            raise ReleaseError('无法读取发布快照中的 checksum') from error
        if snapshot_checksum != expected_checksum:
            raise ReleaseError('发布快照中的 checksum 与 manifest 不一致')

        manifest_name = os.path.basename(target['manifest'])
        try:
            with open(copied[manifest_name], encoding='utf-8') as stream:
                snapshot_manifest = json.load(stream)
        except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ReleaseError('无法读取发布快照中的 manifest') from error
        if snapshot_manifest != manifest:
            raise ReleaseError('发布快照中的 manifest 与已验证内容不一致')

        expectations = {}
        for name, destination in copied.items():
            expectations[name] = {
                'name': name,
                'path': destination,
                'size': os.path.getsize(destination),
                'sha256': file_sha256(destination),
            }
        return snapshot_dir, expectations
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise


def _verify_snapshot_assets(expectations):
    for expected in expectations.values():
        path = expected['path']
        if not os.path.isfile(path):
            raise ReleaseError('发布快照丢失：{}'.format(expected['name']))
        if os.path.getsize(path) != expected['size'] or file_sha256(path) != expected['sha256']:
            raise ReleaseError('发布快照在确认后被修改：{}'.format(expected['name']))


def _notes_prefix(manifest):
    artifact = manifest['artifact']
    source = manifest['source']
    return (
        '### 构建与校验\n\n'
        '- Commit：`{commit}`\n'
        '- Windows 单文件：`{name}`（{size} bytes）\n'
        '- SHA-256：`{sha256}`\n'
        '- 构建 manifest 与独立 SHA-256 文件已作为附件上传。\n\n'
        '> 该 EXE 尚未进行 Authenticode 代码签名；请只从本发布页下载并核对哈希。'
    ).format(
        commit=source['commit'],
        name=artifact['name'],
        size=artifact['size'],
        sha256=artifact['sha256'],
    )


def _body_starts_with_notes_prefix(body, manifest):
    if not isinstance(body, str):
        return False
    normalized_body = body.replace('\r\n', '\n').replace('\r', '\n')
    expected = _notes_prefix(manifest)
    return normalized_body == expected or normalized_body.startswith(expected + '\n')


def _create_or_reuse_tag(tag, head, digest, partial_state):
    local = partial_state['local']
    remote = partial_state['remote']
    if local is None:
        if remote is None:
            message = (
                '{} {}\n\nCommit: {}\n{} SHA-256: {}'
            ).format(APP_NAME, tag, head, APP_NAME + '.exe', digest)
            run_command(['git', 'tag', '-a', tag, '-m', message, head])
        else:
            run_command([
                'git',
                'fetch',
                'origin',
                'refs/tags/{0}:refs/tags/{0}'.format(tag),
            ])
        local = _local_tag_state(tag)

    if local is None or not local['annotated'] or local['commit'] != head:
        raise ReleaseError('本地 annotated tag 校验失败')
    tag_message = git_output('tag', '--list', tag, '--format=%(contents)')
    digest_pattern = r'(?m)^{} SHA-256: {}$'.format(
        re.escape(APP_NAME + '.exe'),
        re.escape(digest),
    )
    if not re.search(digest_pattern, tag_message):
        raise ReleaseError('现有 tag 注释未以完整行绑定当前 EXE SHA-256')

    if remote is None:
        run_command(['git', 'push', 'origin', tag])
    remote = _remote_tag_state(tag)
    if (
        remote is None
        or not remote['annotated']
        or remote['commit'] != head
        or remote['object_id'] != local['object_id']
    ):
        raise ReleaseError('远端 annotated tag object 校验失败')
    return local['object_id']


def _create_or_reuse_draft(tag, manifest, notes_text, existing_release, allowed_names):
    if existing_release is not None:
        if notes_text is not None:
            raise ReleaseError('--resume 已有 draft 时不能重新指定 --notes-file')
        _validate_draft_state(existing_release, tag, manifest, allowed_names)
        return existing_release

    prefix = _notes_prefix(manifest)
    command = [
        'gh',
        'release',
        'create',
        tag,
        '-R',
        REPOSITORY,
        '--draft',
        '--verify-tag',
        '--fail-on-no-commits',
        '--target',
        MAIN_BRANCH,
        '--title',
        '{} {}'.format(APP_NAME, tag),
    ]
    if notes_text is not None:
        command.extend(['--notes', prefix + '\n\n' + notes_text])
    else:
        command.extend(['--generate-notes', '--notes', prefix])
    run_command(command)
    release = _release_state(tag)
    _validate_draft_state(release, tag, manifest, allowed_names)
    return release


def _strict_remote_asset(asset, expected):
    if asset.get('size') != expected['size']:
        raise ReleaseError('远端资产 {} 大小冲突，不会覆盖'.format(expected['name']))
    digest = asset.get('digest')
    if not isinstance(digest, str) or not digest:
        return False
    expected_digest = 'sha256:' + expected['sha256'].lower()
    if digest.casefold() != expected_digest.casefold():
        raise ReleaseError('远端资产 {} SHA-256 冲突，不会覆盖'.format(expected['name']))
    return True


def _wait_for_remote_asset(tag, manifest, expectations, name, timeout=30.0):
    deadline = time.monotonic() + timeout
    while True:
        release = _release_state(tag)
        _validate_draft_state(release, tag, manifest, expectations)
        asset = _remote_assets_by_name(release).get(name)
        if asset is not None and _strict_remote_asset(asset, expectations[name]):
            return release
        if time.monotonic() >= deadline:
            raise ReleaseError('远端资产 {} 未提供可核验的 SHA-256 digest'.format(name))
        time.sleep(1.0)


def _upload_and_verify_assets(tag, manifest, expectations):
    allowed_names = set(expectations)
    _verify_snapshot_assets(expectations)
    release = _release_state(tag)
    _validate_draft_state(release, tag, manifest, allowed_names)

    for name in sorted(allowed_names):
        _verify_snapshot_assets(expectations)
        release = _release_state(tag)
        _validate_draft_state(release, tag, manifest, allowed_names)
        existing = _remote_assets_by_name(release).get(name)
        if existing is not None:
            if not _strict_remote_asset(existing, expectations[name]):
                release = _wait_for_remote_asset(tag, manifest, expectations, name)
            continue
        run_command([
            'gh',
            'release',
            'upload',
            tag,
            expectations[name]['path'],
            '-R',
            REPOSITORY,
        ])
        release = _wait_for_remote_asset(tag, manifest, expectations, name)

    release = _release_state(tag)
    _validate_draft_state(release, tag, manifest, allowed_names, final=True)
    for name, expected in expectations.items():
        asset = _remote_assets_by_name(release)[name]
        if not _strict_remote_asset(asset, expected):
            raise ReleaseError('远端资产 {} 缺少 digest'.format(name))
    return release


def _confirm_release(tag, manifest, assume_yes):
    if assume_yes:
        return
    artifact = manifest['artifact']
    print()
    print('即将执行不可逆的远端发布操作：')
    print('- tag：{} -> {}'.format(tag, manifest['source']['commit']))
    print('- EXE：{} bytes'.format(artifact['size']))
    print('- SHA-256：{}'.format(artifact['sha256']))
    print('- 创建/恢复 draft，核验三个资产后发布为 Latest')
    answer = input('请输入版本号 {} 以确认：'.format(tag)).strip()
    if answer != tag:
        raise ReleaseError('确认内容不匹配，已取消')


def release(version, *, resume=False, notes_file=None, assume_yes=False):
    os.chdir(ROOT_DIR)
    _require_gh_baseline()
    state = _require_clean_main(version)
    partial = _check_partial_state(version, state['head'], resume)
    if partial['release'] is not None and notes_file:
        raise ReleaseError('--resume 已有 draft 时不能重新指定 --notes-file')
    notes_text = None
    if notes_file:
        with open(notes_file, encoding='utf-8') as stream:
            notes_text = stream.read().strip()

    if resume:
        manifest = validate_release_artifacts(
            state['version'],
            state['head'],
            require_clean=True,
        )
    else:
        run_command([sys.executable, 'build_onefile.py'])
        manifest = validate_release_artifacts(
            state['version'],
            state['head'],
            require_clean=True,
        )

    _ensure_source_unchanged(state)
    snapshot_dir, expectations = _snapshot_assets(manifest)
    try:
        _confirm_release(version, manifest, assume_yes)
        _ensure_source_unchanged(state)
        # 确认期间远端可能变化；重新读取并要求仍符合新建/恢复模式。
        partial = _check_partial_state(version, state['head'], resume)
        _verify_snapshot_assets(expectations)

        digest = manifest['artifact']['sha256']
        expected_tag_object = _create_or_reuse_tag(
            version,
            state['head'],
            digest,
            partial,
        )
        draft = _create_or_reuse_draft(
            version,
            manifest,
            notes_text,
            partial['release'],
            set(expectations),
        )
        _validate_draft_state(draft, version, manifest, set(expectations))
        _upload_and_verify_assets(version, manifest, expectations)

        # 先完成本地和 tag 检查，再把远端资产校验紧邻 publish，缩小竞态窗口。
        _verify_snapshot_assets(expectations)
        _ensure_source_unchanged(state)
        final_tag = _remote_tag_state(version)
        if (
            final_tag is None
            or not final_tag['annotated']
            or final_tag['commit'] != state['head']
            or final_tag['object_id'] != expected_tag_object
        ):
            raise ReleaseError('发布前远端 annotated tag 状态发生变化')

        final_draft = _release_state(version)
        _validate_draft_state(
            final_draft,
            version,
            manifest,
            set(expectations),
            final=True,
        )
        final_assets = _remote_assets_by_name(final_draft)
        for name, expected in expectations.items():
            if not _strict_remote_asset(final_assets[name], expected):
                raise ReleaseError('发布前远端资产 {} 缺少 digest'.format(name))
        run_command([
            'gh',
            'release',
            'edit',
            version,
            '-R',
            REPOSITORY,
            '--draft=false',
            '--latest',
        ])

        published = _release_state(version)
        if published is None or published.get('isDraft') is not False:
            raise ReleaseError('资产已上传，但未能确认 Release 已发布；请检查远端 draft')
        published_checks = {
            'isPrerelease': published.get('isPrerelease') is False,
            'tagName': published.get('tagName') == version,
            'targetCommitish': published.get('targetCommitish') in (
                MAIN_BRANCH,
                state['head'],
            ),
            'name': published.get('name') == '{} {}'.format(APP_NAME, version),
            'body prefix': _body_starts_with_notes_prefix(published.get('body'), manifest),
        }
        failed_published = [
            name for name, passed in published_checks.items() if not passed
        ]
        if failed_published:
            raise ReleaseError(
                '已发布 Release 状态不符合预期：{}'.format(
                    ', '.join(failed_published)
                )
            )
        published_tag = _remote_tag_state(version)
        if (
            published_tag is None
            or not published_tag['annotated']
            or published_tag['commit'] != state['head']
            or published_tag['object_id'] != expected_tag_object
        ):
            raise ReleaseError('发布后远端 annotated tag object 校验失败')
        published_assets = _remote_assets_by_name(published)
        if set(published_assets) != set(expectations):
            raise ReleaseError('已发布 Release 的资产集合发生变化')
        for name, expected in expectations.items():
            if not _strict_remote_asset(published_assets[name], expected):
                raise ReleaseError('已发布资产 {} 缺少 digest'.format(name))
        print('\n发布成功：{}'.format(published.get('url', '')))
    finally:
        shutil.rmtree(snapshot_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description='安全发布 SeavoExplorer GitHub Release')
    parser.add_argument('version', help='发布版本，例如 v0.6.0；必须与 APP_VERSION 一致')
    parser.add_argument(
        '--resume',
        action='store_true',
        help='只恢复当前 commit 已存在的 tag/draft；默认重新构建',
    )
    parser.add_argument(
        '--notes-file',
        help='UTF-8 自定义发布说明；已有 draft 的 --resume 不允许重新指定',
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='跳过输入版本号确认，仅适合受控自动化环境',
    )
    args = parser.parse_args()

    try:
        version = normalize_version(args.version)
        notes_file = os.path.abspath(args.notes_file) if args.notes_file else None
        if notes_file and not os.path.isfile(notes_file):
            raise ReleaseError('说明文件不存在：{}'.format(notes_file))
        release(
            version,
            resume=args.resume,
            notes_file=notes_file,
            assume_yes=args.yes,
        )
    except (BuildError, ReleaseError, OSError, ValueError, json.JSONDecodeError) as error:
        print('\n发布中止：{}'.format(error), file=sys.stderr)
        print(
            '脚本不会自动删除 tag、draft 或资产。若远端已留下同 commit 的部分状态，'
            '确认本地产物未变后使用 --resume；存在任何冲突时请改用新版本号。',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
