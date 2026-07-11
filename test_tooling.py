"""构建与发布辅助链路的无网络、无打包单元测试。"""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest import mock

import build_support
import make_ico
import release


TEST_TMP_ROOT = r'D:\tmp' if os.path.isdir(r'D:\tmp') else None


@contextmanager
def release_manifest_fixture():
    with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
        dist = os.path.join(root, 'dist')
        os.makedirs(dist)
        artifact = os.path.join(dist, 'SeavoExplorer.exe')
        checksum = os.path.join(dist, 'SeavoExplorer.exe.sha256')
        manifest_path = os.path.join(dist, 'SeavoExplorer.build.json')
        with open(artifact, 'wb') as stream:
            stream.write(b'fixture-exe')
        digest = build_support.file_sha256(artifact)
        with open(checksum, 'w', encoding='ascii', newline='\n') as stream:
            stream.write('{}  SeavoExplorer.exe\n'.format(digest))

        checks = {name: True for name in build_support.RELEASE_REQUIRED_CHECKS}
        manifest = {
            'schema_version': 1,
            'application': {'name': 'SeavoExplorer', 'version': '0.5.0'},
            'build': {'type': 'onefile', 'spec': 'main.spec'},
            'source': {
                'commit': 'a' * 40,
                'branch': 'main',
                'dirty': False,
                'origin': 'https://github.com/fengbujue0104/seavoexplorer',
            },
            'environment': {
                'python': build_support.VERIFIED_PYTHON,
                'architecture': build_support.VERIFIED_ARCHITECTURE,
                'path_sanitized': True,
                'strict_environment': True,
                'distributions': {'Pinned': '1.0'},
            },
            'inputs_sha256': {'input.txt': 'B' * 64},
            'checks': checks,
            'binary_source_audit': {'external_binary_count': 0},
            'artifact': {
                'kind': 'file',
                'path': 'dist/SeavoExplorer.exe',
                'name': 'SeavoExplorer.exe',
                'size': os.path.getsize(artifact),
                'sha256': digest,
                'checksum_file': 'dist/SeavoExplorer.exe.sha256',
            },
        }
        with open(manifest_path, 'w', encoding='utf-8') as stream:
            json.dump(manifest, stream)

        targets = {
            'onefile': {
                'kind': 'file',
                'artifact': os.path.join('dist', 'SeavoExplorer.exe'),
                'entrypoint': os.path.join('dist', 'SeavoExplorer.exe'),
                'checksum': os.path.join('dist', 'SeavoExplorer.exe.sha256'),
                'manifest': os.path.join('dist', 'SeavoExplorer.build.json'),
            }
        }
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(build_support, 'ROOT_DIR', root))
            stack.enter_context(mock.patch.object(build_support, 'BUILD_TARGETS', targets))
            stack.enter_context(mock.patch.object(
                build_support,
                '_exact_build_requirements',
                return_value={'Pinned': '1.0'},
            ))
            stack.enter_context(mock.patch.object(
                build_support,
                '_input_hashes',
                return_value={'input.txt': 'B' * 64},
            ))
            yield {
                'root': root,
                'artifact': artifact,
                'checksum': checksum,
                'manifest_path': manifest_path,
                'manifest': manifest,
                'targets': targets,
            }


class VersionParsingTests(unittest.TestCase):
    def test_current_versions_are_consistent(self):
        version = build_support.validate_version_consistency()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')

    def test_app_version_requires_one_literal_assignment(self):
        self.assertEqual(
            build_support._app_version_from_source("APP_VERSION = '1.2.3'"),
            '1.2.3',
        )
        invalid_sources = (
            '',
            "APP_VERSION = '1.2.3'\nAPP_VERSION = '1.2.4'",
            "APP_VERSION = '.'.join(('1', '2', '3'))",
            "APP_VERSION = '1.2'",
        )
        for source in invalid_sources:
            with self.subTest(source=source), self.assertRaises(build_support.BuildError):
                build_support._app_version_from_source(source)

    def test_project_version_parser_stays_inside_project_section(self):
        text = '[project]\nname = "x"\n[tool.demo]\nversion = "9.9.9"\n'
        with self.assertRaises(build_support.BuildError):
            build_support._project_version_from_toml(text)
        self.assertEqual(
            build_support._project_version_from_toml(
                '[project]\nversion = "1.2.3"\n[tool.demo]\nversion = "9.9.9"\n'
            ),
            '1.2.3',
        )

    def test_pe_version_components_are_bounded(self):
        self.assertEqual(build_support._four_part_version('65535.0.1'), (65535, 0, 1, 0))
        with self.assertRaises(build_support.BuildError):
            build_support._four_part_version('65536.0.0')

    def test_release_version_normalization(self):
        self.assertEqual(release.normalize_version(' 0.6.0 '), 'v0.6.0')
        self.assertEqual(release.normalize_version('v0.6.0'), 'v0.6.0')
        for value in ('', '0.6', '0.6.0.1', 'v0.6.0-rc1', 'v$(calc)'):
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                release.normalize_version(value)


class PathAndHashTests(unittest.TestCase):
    def test_file_sha256_known_vectors(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'data.bin')
            with open(path, 'wb') as stream:
                stream.write(b'')
            self.assertEqual(
                build_support.file_sha256(path),
                'E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855',
            )
            with open(path, 'wb') as stream:
                stream.write(b'abc')
            self.assertEqual(
                build_support.file_sha256(path),
                'BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD',
            )

    def test_binary_audit_rejects_relative_external_and_malformed_sources(self):
        allowed = os.path.join(build_support.ROOT_DIR, 'inside.dll')
        self.assertEqual(
            build_support.audit_binary_entries([('inside.dll', allowed, 'BINARY')]),
            1,
        )
        invalid_entries = (
            [('evil.dll', '..\\outside\\evil.dll', 'BINARY')],
            [('evil.dll', os.path.abspath(r'D:\outside\evil.dll'), 'BINARY')],
            [('evil.dll', allowed, 'DATA')],
            [('broken', allowed)],
        )
        for entries in invalid_entries:
            with self.subTest(entries=entries), self.assertRaises(build_support.BuildError):
                build_support.audit_binary_entries(entries)

    def test_manifest_remote_sanitizer_never_keeps_credentials_or_local_paths(self):
        self.assertEqual(
            build_support._sanitize_remote_for_manifest(
                'https://token@example.com/Owner/Repo.git'
            ),
            'https://example.com/Owner/Repo',
        )
        self.assertEqual(
            build_support._sanitize_remote_for_manifest('git@github.com:Owner/Repo.git'),
            'ssh://github.com/Owner/Repo',
        )
        self.assertIsNone(build_support._sanitize_remote_for_manifest(r'D:\private\repo'))

    def test_onedir_checksum_covers_every_payload_file(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            dist = os.path.join(root, 'dist', 'SeavoExplorer')
            internal = os.path.join(dist, '_internal')
            os.makedirs(internal)
            with open(os.path.join(dist, 'SeavoExplorer.exe'), 'wb') as stream:
                stream.write(b'exe')
            with open(os.path.join(internal, 'library.dll'), 'wb') as stream:
                stream.write(b'dll')
            target = {
                'kind': 'directory',
                'artifact': os.path.join('dist', 'SeavoExplorer'),
                'entrypoint': os.path.join('dist', 'SeavoExplorer', 'SeavoExplorer.exe'),
                'checksum': os.path.join(
                    'dist', 'SeavoExplorer', 'SeavoExplorer.directory.sha256'
                ),
                'manifest': os.path.join(
                    'dist', 'SeavoExplorer', 'SeavoExplorer.build.json'
                ),
            }
            with mock.patch.object(build_support, 'ROOT_DIR', root):
                artifact = build_support._write_checksum_and_describe_artifact(target)
            self.assertEqual(artifact['kind'], 'directory')
            self.assertEqual(artifact['file_count'], 2)
            self.assertEqual(artifact['size'], 6)
            with open(os.path.join(root, target['checksum']), encoding='utf-8') as stream:
                checksum_text = stream.read()
            self.assertIn('SeavoExplorer.exe', checksum_text)
            self.assertIn('_internal/library.dll', checksum_text)

    def test_make_ico_fallback_does_not_require_png(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(make_ico, 'SRC_PNG', 'missing-source.png'))
            stack.enter_context(mock.patch.object(
                make_ico,
                'ICO_PATH',
                os.path.join(build_support.ROOT_DIR, 'favicon.ico'),
            ))
            image, source, size = make_ico.load_source()
        try:
            self.assertTrue(source.endswith('favicon.ico'))
            self.assertEqual(size, (256, 256))
            self.assertEqual(image.mode, 'RGBA')
        finally:
            image.close()

    def test_strict_environment_rejects_extra_distributions(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                build_support,
                '_isolated_venv_status',
                return_value=(True, ''),
            ))
            stack.enter_context(mock.patch.object(
                build_support,
                '_exact_build_requirements',
                return_value={'Pinned': '1.0'},
            ))
            stack.enter_context(mock.patch.object(
                build_support,
                'installed_distribution_versions',
                return_value={'Pinned': '1.0', 'Unexpected': '2.0', 'pip': '24.3.1'},
            ))
            stack.enter_context(mock.patch.object(
                build_support.platform,
                'python_version',
                return_value=build_support.VERIFIED_PYTHON,
            ))
            stack.enter_context(mock.patch.object(
                build_support.platform,
                'architecture',
                return_value=(build_support.VERIFIED_ARCHITECTURE, ''),
            ))
            with self.assertRaises(build_support.BuildError):
                build_support.verify_build_environment(strict=True)

    def test_subprocess_environment_scrubs_python_and_qt_injection(self):
        injected = {
            'PATH': r'D:\untrusted',
            'PYTHONPATH': r'D:\untrusted\python',
            'PYTHONHOME': r'D:\untrusted\home',
            'QT_PLUGIN_PATH': r'D:\untrusted\qt',
            'QML2_IMPORT_PATH': r'D:\untrusted\qml',
        }
        with mock.patch.dict(os.environ, injected, clear=False):
            with mock.patch.object(build_support.sys, 'platform', 'win32'):
                with mock.patch.object(
                    build_support,
                    'sanitized_windows_path',
                    return_value=r'C:\python-safe',
                ):
                    with mock.patch.object(
                        build_support,
                        'sanitized_windows_runtime_path',
                        return_value=r'C:\windows-safe',
                    ):
                        environment = build_support.build_subprocess_environment('onedir')
                        runtime_environment = build_support.runtime_subprocess_environment()
        self.assertEqual(environment['PATH'], r'C:\python-safe')
        self.assertEqual(runtime_environment['PATH'], r'C:\windows-safe')
        self.assertEqual(environment['SEAVO_BUILD_MODE'], 'onedir')
        self.assertEqual(environment['PYTHONNOUSERSITE'], '1')
        self.assertEqual(environment['PYTHONUTF8'], '1')
        for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
            self.assertNotIn(name, environment)

        smoke_process = mock.Mock()
        smoke_process.pid = 1234
        smoke_process.poll.return_value = None
        cleanup_result = SimpleNamespace(returncode=0)
        smoke_root = os.path.join(build_support.ROOT_DIR, 'build')
        smoke_directory = os.path.join(smoke_root, 'seavo-build-smoke-test')
        with mock.patch.object(build_support.sys, 'platform', 'win32'):
            with mock.patch.object(build_support.os.path, 'isfile', return_value=True):
                with mock.patch.object(build_support, '_is_smoke_directory', return_value=True):
                    with mock.patch.object(
                        build_support.subprocess,
                        'run',
                        return_value=cleanup_result,
                    ) as run_cleanup:
                        build_support._stop_smoke_process(
                            smoke_process,
                            smoke_directory,
                            smoke_root,
                        )
        cleanup_command = run_cleanup.call_args.args[0]
        self.assertTrue(cleanup_command[0].casefold().endswith('powershell.exe'))
        self.assertIn('Get-SmokeProcesses', cleanup_command[-1])
        self.assertEqual(
            run_cleanup.call_args.kwargs['env']['SEAVO_SMOKE_ROOT'],
            smoke_directory,
        )
        smoke_process.wait.assert_called_once_with(timeout=10)

    def test_onedir_checksum_rejects_directory_links_and_walk_errors(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            linked_directory = os.path.join(root, 'linked')
            os.makedirs(linked_directory)
            original_islink = os.path.islink

            def simulated_islink(path):
                return path == linked_directory or original_islink(path)

            with mock.patch.object(os.path, 'islink', side_effect=simulated_islink):
                with self.assertRaises(build_support.BuildError):
                    build_support._directory_payload_records(root, ())

            excluded_link = os.path.join(root, 'excluded-link')
            with open(excluded_link, 'wb') as stream:
                stream.write(b'link target')
            with mock.patch.object(
                os.path,
                'islink',
                side_effect=lambda path: path == excluded_link,
            ):
                with self.assertRaises(build_support.BuildError):
                    build_support._directory_payload_records(root, (excluded_link,))

        walk_error = OSError('access denied')

        def failing_walk(_directory, onerror=None, followlinks=False):
            self.assertFalse(followlinks)
            onerror(walk_error)
            return iter(())

        with mock.patch.object(build_support.os, 'walk', side_effect=failing_walk):
            with self.assertRaises(build_support.BuildError):
                build_support._directory_payload_records('missing', ())


class ManifestValidationTests(unittest.TestCase):
    def test_valid_manifest_is_accepted(self):
        with release_manifest_fixture() as fixture:
            manifest = build_support.validate_release_artifacts(
                '0.5.0', 'a' * 40, require_clean=True
            )
            self.assertEqual(manifest['artifact']['sha256'], fixture['manifest']['artifact']['sha256'])

    def test_diagnostic_or_tampered_manifest_is_rejected(self):
        mutations = (
            lambda manifest: manifest['checks'].__setitem__('isolated_exe_smoke', None),
            lambda manifest: manifest['environment'].__setitem__('strict_environment', False),
            lambda manifest: manifest['inputs_sha256'].__setitem__('input.txt', '0' * 64),
            lambda manifest: manifest['artifact'].__setitem__('path', 'other.exe'),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), release_manifest_fixture() as fixture:
                mutate(fixture['manifest'])
                with open(fixture['manifest_path'], 'w', encoding='utf-8') as stream:
                    json.dump(fixture['manifest'], stream)
                with self.assertRaises(build_support.BuildError):
                    build_support.validate_release_artifacts('0.5.0', 'a' * 40)

    def test_invalid_json_shapes_and_checksum_fail_closed(self):
        with release_manifest_fixture() as fixture:
            with open(fixture['manifest_path'], 'w', encoding='utf-8') as stream:
                json.dump([], stream)
            with self.assertRaises(build_support.BuildError):
                build_support.validate_release_artifacts('0.5.0', 'a' * 40)
        with release_manifest_fixture() as fixture:
            with open(fixture['checksum'], 'w', encoding='ascii') as stream:
                stream.write('')
            with self.assertRaises(build_support.BuildError):
                build_support.validate_release_artifacts('0.5.0', 'a' * 40)
        with release_manifest_fixture() as fixture:
            digest = fixture['manifest']['artifact']['sha256']
            with open(fixture['checksum'], 'w', encoding='ascii') as stream:
                stream.write('{}  wrong.exe\n'.format(digest))
            with self.assertRaises(build_support.BuildError):
                build_support.validate_release_artifacts('0.5.0', 'a' * 40)


class ReleaseStateTests(unittest.TestCase):
    def test_origin_allowlist_rejects_http_credentials_and_lookalikes(self):
        valid = (
            'https://github.com/FengBujue0104/SeavoExplorer.git',
            'git@github.com:FengBujue0104/SeavoExplorer.git',
            'ssh://git@github.com/FengBujue0104/SeavoExplorer.git',
        )
        invalid = (
            'http://github.com/FengBujue0104/SeavoExplorer.git',
            'https://token@github.com/FengBujue0104/SeavoExplorer.git',
            'https://github.com.evil/FengBujue0104/SeavoExplorer.git',
            'https://github.com/other/SeavoExplorer.git',
            'ssh://root@github.com/FengBujue0104/SeavoExplorer.git',
            '',
        )
        for value in valid:
            with self.subTest(value=value):
                self.assertTrue(release._origin_matches_repository(value))
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(release._origin_matches_repository(value))

    def test_remote_tag_parser_distinguishes_annotated_and_lightweight(self):
        tag = 'v1.2.3'
        direct = '1' * 40
        commit = '2' * 40
        lightweight = release._parse_remote_tag_state(
            '{}\trefs/tags/{}\n'.format(direct, tag), tag
        )
        self.assertFalse(lightweight['annotated'])
        annotated = release._parse_remote_tag_state(
            '{}\trefs/tags/{}^{{}}\n{}\trefs/tags/{}\n'.format(
                commit, tag, direct, tag
            ),
            tag,
        )
        self.assertTrue(annotated['annotated'])
        self.assertEqual(annotated['object_id'], direct)
        self.assertEqual(annotated['commit'], commit)
        self.assertIsNone(release._parse_remote_tag_state('', tag))

        partial = {'local': annotated, 'remote': annotated, 'release': None}
        tag_message = 'SeavoExplorer.exe SHA-256: {}'.format('A' * 64)
        with mock.patch.object(release, 'git_output', return_value=tag_message):
            with mock.patch.object(release, '_remote_tag_state', return_value=annotated):
                object_id = release._create_or_reuse_tag(
                    tag,
                    commit,
                    'A' * 64,
                    partial,
                )
        self.assertEqual(object_id, direct)

    def test_resume_requires_existing_partial_state(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(release, '_local_tag_state', return_value=None))
            stack.enter_context(mock.patch.object(release, '_remote_tag_state', return_value=None))
            stack.enter_context(mock.patch.object(release, '_release_state', return_value=None))
            with self.assertRaises(release.ReleaseError):
                release._check_partial_state('v1.2.3', 'a' * 40, resume=True)

    def test_remote_asset_requires_digest_and_rejects_mismatch(self):
        expected = {'name': 'x.bin', 'size': 3, 'sha256': build_support.file_sha256(__file__)}
        # Use a stable synthetic expectation for the pure comparison.
        expected['sha256'] = 'A' * 64
        self.assertFalse(release._strict_remote_asset({'name': 'x.bin', 'size': 3}, expected))
        with self.assertRaises(release.ReleaseError):
            release._strict_remote_asset(
                {'name': 'x.bin', 'size': 3, 'digest': 'sha256:' + 'b' * 64},
                expected,
            )

    def test_snapshot_verification_detects_local_and_source_replacement(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as root:
            path = os.path.join(root, 'asset.bin')
            with open(path, 'wb') as stream:
                stream.write(b'first')
            expected = {
                'asset.bin': {
                    'name': 'asset.bin',
                    'path': path,
                    'size': os.path.getsize(path),
                    'sha256': build_support.file_sha256(path),
                }
            }
            release._verify_snapshot_assets(expected)
            with open(path, 'wb') as stream:
                stream.write(b'other')
            with self.assertRaises(release.ReleaseError):
                release._verify_snapshot_assets(expected)

        with release_manifest_fixture() as fixture:
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(release, 'ROOT_DIR', fixture['root']))
                stack.enter_context(
                    mock.patch.object(release, 'BUILD_TARGETS', fixture['targets'])
                )
                snapshot_dir, expectations = release._snapshot_assets(fixture['manifest'])
                try:
                    release._verify_snapshot_assets(expectations)
                finally:
                    release.shutil.rmtree(snapshot_dir, ignore_errors=True)

                with open(fixture['checksum'], 'w', encoding='ascii') as stream:
                    stream.write('{}  wrong.exe\n'.format(
                        fixture['manifest']['artifact']['sha256']
                    ))
                with self.assertRaises(release.ReleaseError):
                    release._snapshot_assets(fixture['manifest'])

                with open(fixture['checksum'], 'w', encoding='ascii', newline='\n') as stream:
                    stream.write('{}  SeavoExplorer.exe\n'.format(
                        fixture['manifest']['artifact']['sha256']
                    ))
                replaced_manifest = json.loads(json.dumps(fixture['manifest']))
                replaced_manifest['source']['commit'] = 'c' * 40
                with open(fixture['manifest_path'], 'w', encoding='utf-8') as stream:
                    json.dump(replaced_manifest, stream)
                with self.assertRaises(release.ReleaseError):
                    release._snapshot_assets(fixture['manifest'])

    def test_release_state_only_treats_explicit_not_found_as_absent(self):
        not_found = SimpleNamespace(
            returncode=1,
            stdout='',
            stderr='release not found',
        )
        auth_error = SimpleNamespace(
            returncode=1,
            stdout='',
            stderr='authentication failed',
        )
        with mock.patch.object(release, 'run_command', return_value=not_found):
            self.assertIsNone(release._release_state('v1.2.3'))
        with mock.patch.object(release, 'run_command', return_value=auth_error):
            with self.assertRaises(release.ReleaseError):
                release._release_state('v1.2.3')

    def test_draft_rejects_extra_assets_and_non_draft_state(self):
        manifest = {
            'source': {'commit': 'a' * 40},
            'artifact': {
                'name': 'SeavoExplorer.exe',
                'size': 3,
                'sha256': 'B' * 64,
            },
        }
        base = {
            'isDraft': True,
            'isImmutable': False,
            'isPrerelease': False,
            'tagName': 'v1.2.3',
            'targetCommitish': 'main',
            'name': 'SeavoExplorer v1.2.3',
            'body': release._notes_prefix(manifest),
            'assets': [],
        }
        release._validate_draft_state(base, 'v1.2.3', manifest, {'allowed.exe'})
        with self.assertRaises(release.ReleaseError):
            release._validate_draft_state(
                dict(base, body='{} {}'.format('a' * 40, 'B' * 64)),
                'v1.2.3',
                manifest,
                {'allowed.exe'},
            )
        with self.assertRaises(release.ReleaseError):
            release._validate_draft_state(
                dict(base, assets=[{'name': 'unexpected.bin'}]),
                'v1.2.3',
                manifest,
                {'allowed.exe'},
            )
        with self.assertRaises(release.ReleaseError):
            release._validate_draft_state(
                dict(base, isDraft=False),
                'v1.2.3',
                manifest,
                {'allowed.exe'},
            )


if __name__ == '__main__':
    unittest.main()
