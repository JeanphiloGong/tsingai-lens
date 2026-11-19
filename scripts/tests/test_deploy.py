"""Operator sequencing tests; Docker is recorded while real file backups run."""
from pathlib import Path
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ['postgres', 'frontend', 'backend', 'user-service',
            'document-preparation-worker', 'objective-discovery-worker', 'objective-analysis-worker',
            'feedback-analysis-worker', 'correction-signal-analysis-worker',
            'tool-failure-analysis-worker', 'dataset-sample-worker']
DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['DOCKER_LOG'], 'a') as log:
    log.write(json.dumps({'args': args, 'version': os.getenv('LENS_VERSION')}) + '\n')
failure = os.getenv('FAIL_AT', '')
if failure and ((failure == 'goose' and 'goose' in args) or (failure == 'pull' and 'pull' in args) or (failure == 'dump' and 'pg_dump' in args)):
    sys.exit(7)
if '--services' in args:
    print(os.environ['FAKE_SERVICES'])
elif 'to_regclass' in ' '.join(args):
    print(os.getenv('LEGACY_PRESENT', 'f'))
elif 'pg_dump' in args:
    print('test-archive')
elif 'pg_restore' in args:
    assert sys.stdin.read().strip() == 'test-archive'
elif 'psql' in args or ('python' in args and '-' in args):
    sys.stdin.read()
'''


class DeployScripts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lens-deploy-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.runtime = self.base / 'runtime'
        self.bundle = self.base / 'candidate'
        shutil.copytree(ROOT / 'deploy', self.runtime,
                        ignore=shutil.ignore_patterns('.env', 'backend.env', 'user-service.env', 'data', 'backups', 'identity-certs', 'public-tls'))
        shutil.copytree(self.runtime, self.bundle)
        self.password = secrets.token_hex(32)
        (self.runtime / '.env').write_text(
            'COMPOSE_PROJECT_NAME=lens-test\nLENS_VERSION=v1.0.0\n'
            'LENS_PUBLIC_URL=https://lens.example.test\n'
            'POSTGRES_PASSWORD=' + secrets.token_hex(32) + '\nLENS_USERS_PASSWORD=' + self.password + '\n'
        )
        (self.runtime / 'backend.env').write_text('LLM_API_KEY=\n')
        shutil.copy(self.runtime / 'user-service.env.example', self.runtime / 'user-service.env')
        for name in ['public-tls/tls.crt', 'public-tls/tls.key', 'identity-certs/ca.crt',
                     'identity-certs/server.crt', 'identity-certs/server.key',
                     'identity-certs/client.crt', 'identity-certs/client.key', 'data/backend/source.pdf']:
            path = self.runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        model_key = self.runtime / 'model-secrets' / 'model-key'
        model_key.parent.mkdir()
        model_key.write_bytes(secrets.token_bytes(32))
        tools = self.base / 'bin'
        tools.mkdir()
        (tools / 'docker').write_text(DOCKER)
        (tools / 'curl').write_text('#!/bin/sh\nexit "${FAIL_PROBE:-0}"\n')
        for path in tools.iterdir():
            path.chmod(0o755)
        self.log = self.base / 'docker.jsonl'
        self.environment = os.environ | {
            'PATH': str(tools) + os.pathsep + os.environ['PATH'],
            'LENS_DEPLOY_DIR': str(self.runtime), 'DOCKER_LOG': str(self.log),
            'FAKE_SERVICES': '\n'.join(SERVICES),
        }

    def upgrade(self, version='v1.1.0', **environment):
        return subprocess.run(['sh', str(self.bundle / 'scripts/upgrade.sh'), version],
                              env=self.environment | environment, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line)['args'] for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_rejects_shell_input_before_docker_or_version_changes(self):
        result = self.upgrade('v1.1.0;touch-owned')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertIn('LENS_VERSION=v1.0.0', (self.runtime / '.env').read_text())

    def test_legacy_identity_requires_explicit_cutover(self):
        result = self.upgrade(LEGACY_PRESENT='t')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('account import', result.stderr)
        self.assertFalse(any('stop' in call or 'pull' in call for call in self.calls()))

    def test_pull_failure_leaves_existing_services_running(self):
        result = self.upgrade(FAIL_AT='pull')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('stop' in call for call in self.calls()))
        self.assertFalse((self.runtime / 'backups').exists())

    def test_success_backs_up_all_writes_before_migration_and_persists_version(self):
        result = self.upgrade()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        first_dump = next(i for i, call in enumerate(calls) if 'pg_dump' in call)
        first_migration = next(i for i, call in enumerate(calls) if 'goose' in call)
        stopped = {call[-1] for call in calls[:first_dump] if 'stop' in call}
        self.assertEqual(stopped, set(SERVICES) - {'postgres'})
        self.assertEqual(sum('pg_dump' in call for call in calls[:first_migration]), 2)
        self.assertEqual(sum('pg_restore' in call for call in calls[:first_migration]), 2)
        self.assertIn('LENS_VERSION=v1.1.0', (self.runtime / '.env').read_text())
        self.assertNotIn(self.password, self.log.read_text())
        backup = next((self.runtime / 'backups').iterdir())
        for name in ['lens.dump', 'lens_users.dump', 'runtime.tgz', 'resources.tgz']:
            self.assertTrue((backup / name).is_file(), name)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)

    def test_failed_migration_keeps_maintenance_and_original_version(self):
        result = self.upgrade(FAIL_AT='goose')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('maintenance', result.stderr)
        self.assertIn('LENS_VERSION=v1.0.0', (self.runtime / '.env').read_text())
        calls = self.calls()
        self.assertFalse(any('up' in call and '--wait' in call for call in calls))
        failure = next(i for i, call in enumerate(calls) if 'goose' in call)
        self.assertEqual({call[-1] for call in calls[failure:] if 'stop' in call}, set(SERVICES) - {'postgres'})

    def test_failed_backup_prevents_every_migration(self):
        result = self.upgrade(FAIL_AT='dump')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backup is incomplete', result.stderr)
        self.assertFalse(any('goose' in call or 'alembic' in call for call in self.calls()))

    def test_failed_public_probe_stops_candidate_and_does_not_persist_version(self):
        result = self.upgrade(FAIL_PROBE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('LENS_VERSION=v1.0.0', (self.runtime / '.env').read_text())
        self.assertTrue(any('up' in call and '--wait' in call for call in self.calls()))
        self.assertEqual(self.calls()[-1][-2:], ['stop', SERVICES[-1]])


class ComposeContract(unittest.TestCase):
    def test_three_images_share_tag_and_identity_uses_the_private_proxy(self):
        if not shutil.which('docker'):
            self.skipTest('Docker Compose CLI is not available')
        with tempfile.TemporaryDirectory(prefix='lens-compose-test-') as directory:
            bundle = Path(directory)
            shutil.copy(ROOT / 'deploy/compose.yml', bundle / 'compose.yml')
            shutil.copy(ROOT / 'deploy/backend.env.example', bundle / 'backend.env')
            shutil.copy(ROOT / 'deploy/user-service.env.example', bundle / 'user-service.env')
            (bundle / '.env').write_text('LENS_VERSION=v9.9.9\nLENS_PUBLIC_URL=https://lens.example.test\nPOSTGRES_PASSWORD='+secrets.token_hex(32)+'\nLENS_USERS_PASSWORD='+secrets.token_hex(32)+'\n')
            result = subprocess.run(['docker', 'compose', '--env-file', str(bundle / '.env'), '-f', str(bundle / 'compose.yml'), 'config', '--format', 'json'], capture_output=True, text=True, check=True)
            config = json.loads(result.stdout)
            services = config['services']
            for name in ['frontend', 'backend', 'user-service']:
                self.assertTrue(services[name]['image'].endswith(':v9.9.9'))
            # The API and every worker must keep simultaneous SELinux access.
            for service in services.values():
                for volume in service.get('volumes', []):
                    if volume.get('target') == '/app/data':
                        self.assertEqual(volume['bind']['selinux'], 'z')
            self.assertNotIn('ports', services['user-service'])
            proxy = services['frontend']['networks']['default']['ipv4_address']
            self.assertEqual(services['user-service']['environment']['TRUSTED_PROXY_IP'], proxy)
            self.assertEqual(services['backend']['environment']['USER_RPC_TARGET'], 'user-service:50057')
            key_path = '/run/lens-secrets/model-key'
            for name in ('backend', 'document-preparation-worker', 'objective-discovery-worker',
                         'objective-analysis-worker', 'correction-signal-analysis-worker',
                         'dataset-sample-worker'):
                service = services[name]
                self.assertEqual(service['environment']['LENS_MODEL_KEY_FILE'], key_path)
                mount = next(volume for volume in service['volumes'] if volume['target'] == key_path)
                self.assertTrue(mount['read_only'])
                self.assertEqual(mount['bind']['selinux'], 'z')
            self.assertEqual(services['user-service']['environment']['BROWSER_ORIGIN'], 'https://lens.example.test')
            self.assertTrue(services['user-service']['healthcheck']['test'])


class BundleInstall(unittest.TestCase):
    def test_install_uses_selected_tag_and_preserves_private_configuration(self):
        with tempfile.TemporaryDirectory(prefix='lens-install-test-') as directory:
            base = Path(directory)
            tools = base / 'bin'
            tools.mkdir()
            curl = tools / 'curl'
            curl.write_text('''#!/usr/bin/env python3
import os, pathlib, shutil, sys
url = sys.argv[2]
ref, name = url.split('/deploy/', 1)
assert ref.endswith('/v1.2.3'), url
shutil.copyfile(pathlib.Path(os.environ['BUNDLE_SOURCE']) / name, sys.argv[4])
''')
            curl.chmod(0o755)
            target = base / 'runtime'
            environment = os.environ | {
                'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                'BUNDLE_SOURCE': str(ROOT / 'deploy'),
            }
            command = ['sh', str(ROOT / 'deploy/install.sh'), '--version', 'v1.2.3', '--dir', str(target)]
            subprocess.run(command, env=environment, capture_output=True, check=True)
            self.assertIn('LENS_VERSION=v1.2.3', (target / '.env').read_text())
            for name in ['.env', 'backend.env', 'user-service.env']:
                self.assertEqual((target / name).stat().st_mode & 0o777, 0o600)
                (target / name).write_text('private existing configuration\n')
            subprocess.run(command, env=environment, capture_output=True, check=True)
            for name in ['.env', 'backend.env', 'user-service.env']:
                self.assertEqual((target / name).read_text(), 'private existing configuration\n')


if __name__ == '__main__':
    unittest.main()
