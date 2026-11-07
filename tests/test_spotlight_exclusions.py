#!/usr/bin/env python3
"""Spotlight exclusions are added only when missing, undo removes only Groundwork's, and no real mds is touched."""
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'home/dot_local/bin/executable_groundwork-spotlight'
HOOK = REPO / 'home/run_after_34-spotlight-exclusions.sh.tmpl'

loader = SourceFileLoader('groundwork_spotlight', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
gs = importlib.util.module_from_spec(spec)
loader.exec_module(gs)

# Commands the fake privileged boundary may run. Anything else fails the test.
ALLOWED = ({'/bin/cat'}, {'/bin/cp'}, {'true'})


class PureListTests(unittest.TestCase):
    def test_normalize_matches_the_data_volume_and_trailing_slash(self):
        self.assertEqual(gs.normalize('/System/Volumes/Data/Users/a/code/'), '/Users/a/code')
        self.assertEqual(gs.normalize('/Users/a/code'), '/Users/a/code')
        self.assertEqual(gs.normalize('/'), '/')

    def test_adding_is_idempotent_and_keeps_other_entries(self):
        config = {'Exclusions': ['/Volumes/Backup', '/System/Volumes/Data/Users/a/code/'], 'Other': 1}
        updated, added = gs.with_exclusions(config, ['/Users/a/code', '/Users/a/Library/pnpm'])
        self.assertEqual(added, ['/Users/a/Library/pnpm'])
        self.assertEqual(updated['Exclusions'][:2], config['Exclusions'])
        self.assertEqual(updated['Other'], 1)
        again, added_again = gs.with_exclusions(updated, ['/Users/a/code', '/Users/a/Library/pnpm'])
        self.assertEqual(added_again, [])
        self.assertEqual(again, updated)
        self.assertEqual(config['Exclusions'], ['/Volumes/Backup', '/System/Volumes/Data/Users/a/code/'])

    def test_missing_list_is_created(self):
        updated, added = gs.with_exclusions({}, ['/Users/a/code'])
        self.assertEqual(updated, {'Exclusions': ['/Users/a/code']})
        self.assertEqual(added, ['/Users/a/code'])

    def test_removing_takes_only_the_named_roots(self):
        config = {'Exclusions': ['/Volumes/Backup', '/Users/a/code/', '/Users/a/Library/pnpm']}
        updated, removed = gs.without_exclusions(config, ['/Users/a/code'])
        self.assertEqual(updated['Exclusions'], ['/Volumes/Backup', '/Users/a/Library/pnpm'])
        self.assertEqual(removed, ['/Users/a/code/'])
        self.assertEqual(gs.without_exclusions({}, ['/x']), ({}, []))

    def test_format_round_trips_binary_and_xml(self):
        config = {'Exclusions': ['/a'], 'Version': 4}
        for fmt in (plistlib.FMT_BINARY, plistlib.FMT_XML):
            original = plistlib.dumps(config, fmt=fmt)
            dumped = gs.dump_configuration(config, original)
            self.assertEqual(dumped[:6] == b'bplist', fmt == plistlib.FMT_BINARY)
            self.assertEqual(plistlib.loads(dumped), config)

    def test_malformed_configuration_is_refused(self):
        for data in (b'not a plist', plistlib.dumps(['x']), plistlib.dumps({'Exclusions': 'x'}),
                     plistlib.dumps({'Exclusions': [1]})):
            with self.subTest(data=data[:20]):
                with self.assertRaises(gs.ConfigurationError):
                    gs.load_configuration(data)

    def test_code_dir_comes_from_the_data_section(self):
        text = 'code_dir = "/wrong"\n[data]\n    code_dir = "~/src" # chosen\n[other]\ncode_dir = "/nope"\n'
        self.assertEqual(gs.parse_code_dir(text), '~/src')
        self.assertIsNone(gs.parse_code_dir('[data]\ncode_dir = "a\\"b"\n'))
        self.assertIsNone(gs.parse_code_dir('[data]\nname = "x"\n'))


class Machine:
    """A fake Mac: a temporary volume configuration and a logging sudo."""

    def __init__(self, test, *, cached=True, prepare_status=0):
        self.test = test
        self.cached = cached
        self.prepare_status = prepare_status
        self.calls = []
        self.prepares = 0

    def run(self, command, *, timeout=15, capture=True, text=True):
        self.calls.append(list(command))
        if command[:2] == ['sudo', '-n']:
            if not self.cached:
                return subprocess.CompletedProcess(command, 1, stdout=b'' if not text else '', stderr=b'' if not text else '')
            command = command[2:]
        self.test.assertIn({command[0]}, ALLOWED, command)
        for part in command[1:]:
            if part.startswith('/'):
                self.test.assertTrue(part.startswith(str(self.test.root)), f'escaped the fake root: {command}')
        if command[0] == 'true':
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
        result = subprocess.run(command, capture_output=True, text=text, check=False)
        return result

    def sudo_prepare(self):
        self.prepares += 1
        if self.prepare_status == 0:
            self.cached = True
        return self.prepare_status

    def writes(self):
        return [call for call in self.calls if '/bin/cp' in call]


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        (self.home / 'code').mkdir(parents=True)
        (self.home / 'Library' / 'pnpm').mkdir(parents=True)
        self.plist = self.root / 'Spotlight-V100' / 'VolumeConfiguration.plist'
        self.plist.parent.mkdir()
        self.write_plist({'Exclusions': ['/Volumes/Backup'], 'Version': 4})
        overlay = patch.dict(os.environ, {
            'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.root / 'config'),
            'XDG_STATE_HOME': str(self.root / 'state'),
            'XDG_CACHE_HOME': str(self.root / 'cache'),
            'XDG_DATA_HOME': str(self.root / 'data'),
        })
        overlay.start()
        self.addCleanup(overlay.stop)
        self.code = str(self.home / 'code')
        self.pnpm = str(self.home / 'Library' / 'pnpm')

    def write_plist(self, value):
        self.plist.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))

    def listed(self):
        return plistlib.loads(self.plist.read_bytes()).get('Exclusions', [])

    def invoke(self, machine, *argv, system='Darwin'):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(gs, 'run', machine.run), \
                patch.object(gs, 'sudo_prepare', machine.sudo_prepare), \
                patch.object(gs, 'VOLUME_CONFIGURATION', self.plist), \
                patch.object(gs, 'is_root', return_value=False), \
                patch.object(gs.platform, 'system', return_value=system), \
                patch.object(gs.shutil, 'which', return_value=None), \
                patch.object(gs.sys, 'stdout', out), \
                patch.object(gs.sys, 'stderr', err):
            code = gs.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def state(self):
        return self.root / 'state' / 'groundwork'

    def test_prepare_adds_missing_roots_once_and_keeps_user_entries(self):
        machine = Machine(self)
        code, out, _ = self.invoke(machine, 'prepare')
        self.assertEqual(code, 0)
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.code, self.pnpm])
        self.assertNotIn('/Applications', self.listed())
        self.assertEqual(plistlib.loads(self.plist.read_bytes())['Version'], 4)
        self.assertTrue(self.plist.read_bytes().startswith(b'bplist'))
        self.assertIn('takes effect after the next restart', out)
        backups = list((self.state() / 'spotlight-backups').glob('VolumeConfiguration.*.plist'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(plistlib.loads(backups[0].read_bytes())['Exclusions'], ['/Volumes/Backup'])
        self.assertEqual(oct(backups[0].stat().st_mode & 0o777), '0o600')
        self.assertEqual(list((self.state() / 'spotlight-backups').glob('.staged*')), [])
        self.assertEqual(len(machine.writes()), 1)

        again = Machine(self)
        self.assertEqual(self.invoke(again, 'prepare')[0], 0)
        self.assertEqual(again.writes(), [])
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.code, self.pnpm])

    def test_recorded_roots_need_no_password(self):
        self.assertEqual(self.invoke(Machine(self), 'prepare')[0], 0)
        locked = Machine(self, cached=False)
        self.assertEqual(self.invoke(locked, 'prepare')[0], 0)
        self.assertEqual(locked.prepares, 0)
        self.assertEqual(locked.calls, [['sudo', '-n', 'true']])

    def test_a_removed_entry_is_added_back_when_permission_is_cached(self):
        self.invoke(Machine(self), 'prepare')
        self.write_plist({'Exclusions': ['/Volumes/Backup', self.pnpm]})
        machine = Machine(self)
        self.invoke(machine, 'prepare')
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.pnpm, self.code])

    def test_no_terminal_defers_without_change(self):
        machine = Machine(self, cached=False, prepare_status=10)
        code, out, _ = self.invoke(machine, 'prepare')
        self.assertEqual(code, 0)
        self.assertIn('needs an administrator password', out)
        self.assertEqual(self.listed(), ['/Volumes/Backup'])
        self.assertEqual(machine.writes(), [])
        self.assertFalse((self.state() / gs.RECORD_FILENAME).exists())

    def test_cancelled_prompt_fails_without_change(self):
        machine = Machine(self, cached=False, prepare_status=130)
        self.assertEqual(self.invoke(machine, 'prepare')[0], 130)
        self.assertEqual(self.listed(), ['/Volumes/Backup'])

    def test_unreadable_configuration_warns_and_changes_nothing(self):
        self.plist.write_bytes(b'garbage')
        machine = Machine(self)
        code, _, err = self.invoke(machine, 'prepare')
        self.assertEqual(code, 0)
        self.assertIn('were not checked', err)
        self.assertEqual(machine.writes(), [])
        self.assertEqual(self.plist.read_bytes(), b'garbage')
        self.plist.unlink()
        code, _, err = self.invoke(Machine(self), 'prepare')
        self.assertEqual(code, 0)
        self.assertIn('could not read', err)

    def test_only_existing_folders_are_added(self):
        shutil.rmtree(self.home / 'Library')
        self.invoke(Machine(self), 'prepare')
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.code])

    def test_configured_code_dir_is_used(self):
        (self.home / 'src').mkdir()
        config = self.root / 'config' / 'chezmoi'
        config.mkdir(parents=True)
        (config / 'chezmoi.toml').write_text('[data]\n    code_dir = "~/src"\n', encoding='utf-8')
        self.invoke(Machine(self), 'prepare')
        self.assertEqual(self.listed(), ['/Volumes/Backup', str(self.home / 'src'), self.pnpm])

    def test_undo_preview_mutates_nothing(self):
        self.invoke(Machine(self), 'prepare')
        before = self.plist.read_bytes()
        machine = Machine(self)
        code, out, _ = self.invoke(machine, 'undo')
        self.assertEqual(code, 0)
        self.assertIn(f'remove  {self.code}', out)
        self.assertEqual(machine.calls, [])
        self.assertEqual(self.plist.read_bytes(), before)
        self.assertFalse((self.state() / gs.OPT_OUT_FILENAME).exists())

    def test_undo_removes_only_groundwork_entries_and_sticks(self):
        self.write_plist({'Exclusions': ['/Volumes/Backup', self.pnpm + '/']})
        self.invoke(Machine(self), 'prepare')
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.pnpm + '/', self.code])
        code, out, _ = self.invoke(Machine(self), 'undo', '--yes')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.pnpm + '/'])
        self.assertTrue((self.state() / gs.OPT_OUT_FILENAME).is_file())
        self.assertFalse((self.state() / gs.RECORD_FILENAME).exists())

        later = Machine(self)
        code, out, _ = self.invoke(later, 'prepare')
        self.assertEqual(code, 0)
        self.assertIn('are off', out)
        self.assertEqual(later.calls, [])
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.pnpm + '/'])

        self.assertEqual(self.invoke(Machine(self), 'enable')[0], 0)
        self.assertFalse((self.state() / gs.OPT_OUT_FILENAME).exists())
        self.assertEqual(self.listed(), ['/Volumes/Backup', self.pnpm + '/', self.code])

    def test_status_reports_the_live_list_or_the_record(self):
        self.invoke(Machine(self), 'prepare')
        code, out, _ = self.invoke(Machine(self), 'status')
        self.assertEqual(code, 0)
        self.assertIn('  excluded  /Volumes/Backup\n', out)
        self.assertIn(f'  excluded  {self.code} (added by Groundwork)', out)
        self.assertNotIn('missing', out)
        locked = Machine(self, cached=False)
        code, out, _ = self.invoke(locked, 'status')
        self.assertEqual(code, 0)
        self.assertIn('not read', out)
        self.assertIn(f'  recorded  {self.code}', out)
        self.assertEqual(locked.prepares, 0)
        self.write_plist({})
        code, out, _ = self.invoke(Machine(self), 'status')
        self.assertIn(f'  missing   {self.code}', out)

    def test_status_writes_nothing(self):
        machine = Machine(self)
        before = self.plist.read_bytes()
        self.invoke(machine, 'status')
        self.assertEqual(machine.writes(), [])
        self.assertEqual(self.plist.read_bytes(), before)
        self.assertFalse(self.state().exists())

    def test_hostile_arguments_mutate_nothing(self):
        for argv, expected in ((['--help'], 0), (['bogus'], 64), (['prepare', 'extra'], 64),
                               (['--frobnicate'], 64), (['prepare', '--yes'], 64), (['status', '--yes'], 64)):
            with self.subTest(argv=argv):
                machine = Machine(self)
                code, _, _ = self.invoke(machine, *argv)
                self.assertEqual(code, expected)
                self.assertEqual(machine.calls, [])
                self.assertEqual(machine.prepares, 0)
        self.assertEqual(self.listed(), ['/Volumes/Backup'])
        self.assertFalse(self.state().exists())

    def test_other_platforms_change_nothing(self):
        for action in ('prepare', 'undo', 'enable', 'status'):
            with self.subTest(action=action):
                machine = Machine(self)
                code, _, err = self.invoke(machine, action, system='Linux')
                self.assertEqual(code, 1)
                self.assertIn('only on a Mac', err)
                self.assertEqual(machine.calls, [])
        self.assertEqual(self.listed(), ['/Volumes/Backup'])


class RenderTests(unittest.TestCase):
    def test_hook_runs_prepare_only_on_macos(self):
        chezmoi = shutil.which('chezmoi')
        if chezmoi is None:
            self.fail('chezmoi is required to prove hook rendering')
        hook = HOOK.read_text(encoding='utf-8')
        cases = (
            ({'os': 'darwin', 'arch': 'arm64', 'osRelease': {}}, {'headless': False}, True),
            ({'os': 'darwin', 'arch': 'arm64', 'osRelease': {}}, {'headless': True}, True),
            ({'os': 'linux', 'arch': 'amd64', 'osRelease': {'ID': 'ubuntu'}}, {'headless': True}, False),
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            empty = root / 'empty.toml'
            empty.write_text('', encoding='utf-8')
            env = dict(os.environ, HOME=str(root / 'home'), XDG_CONFIG_HOME=str(root / 'config'),
                       XDG_CACHE_HOME=str(root / 'cache'), XDG_STATE_HOME=str(root / 'state'),
                       XDG_DATA_HOME=str(root / 'data'))
            for system, data, enabled in cases:
                with self.subTest(system=system['os'], data=data):
                    result = subprocess.run(
                        [chezmoi, '--config', str(empty), '--source', str(REPO / 'home'),
                         '--destination', str(root / 'dest'),
                         '--override-data', json.dumps(dict(data, chezmoi=system)), 'execute-template'],
                        input=hook, text=True, capture_output=True, env=env, cwd=REPO, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    script = root / 'hook.sh'
                    script.write_text(result.stdout, encoding='utf-8')
                    syntax = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    self.assertEqual('"$HOME/.local/bin/groundwork-spotlight" prepare' in result.stdout, enabled)


if __name__ == '__main__':
    unittest.main()
