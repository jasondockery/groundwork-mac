#!/usr/bin/env python3
"""Stay awake on power changes only pmset -c sleep, records it once, and restores it when no reason is left."""
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'home/dot_local/bin/executable_groundwork-stay-awake'
HOOK = REPO / 'home/run_after_34-stay-awake-on-power.sh.tmpl'
CONFIGURE = REPO / 'home/dot_local/bin/executable_groundwork-configure'
TEMPLATE = REPO / 'home/.chezmoi.toml.tmpl'
DOCTOR = REPO / 'home/dot_local/bin/executable_groundwork-doctor'
_ORIGINAL_ENV = dict(os.environ)

loader = SourceFileLoader('stay_awake', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
sa = importlib.util.module_from_spec(spec)
loader.exec_module(sa)

SUDO = ['bash', '-c', sa.SUDO_PREPARE_SCRIPT]
ON = {'headless': False, 'stay_awake_on_power': True}
OFF = {'headless': False, 'stay_awake_on_power': False}
BOTH = {'headless': False, 'stay_awake_on_power': True, 'imessage_gateway': True}
GATEWAY_ONLY = {'headless': False, 'stay_awake_on_power': False, 'imessage_gateway': True}


class FakePmset:
    """A Mac's power settings as pmset reports and changes them."""

    def __init__(self, ac=10, battery=5, display=10, sudo_status=0, on_sudo=None, pmset_status=0):
        self.ac = ac
        self.pmset_status = pmset_status
        self.battery = battery
        self.display = display
        self.sudo_status = sudo_status
        self.on_sudo = on_sudo
        self.calls = []

    def custom(self):
        return (
            'Battery Power:\n'
            ' disablesleep         0\n'
            f' displaysleep         {self.display}\n'
            f' sleep                {self.battery}\n'
            'AC Power:\n'
            f' displaysleep         {self.display}\n'
            f' sleep                {self.ac}\n'
        )

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if command == sa.PMSET_READ:
            return subprocess.CompletedProcess(command, 0, stdout=self.custom(), stderr='')
        if command == SUDO:
            if self.on_sudo:
                self.on_sudo()
            return subprocess.CompletedProcess(command, self.sudo_status, stdout='', stderr='')
        if command[:4] == ['sudo', 'pmset', '-c', 'sleep'] and len(command) == 5 and command[4].isdigit():
            if self.pmset_status == 0:
                self.ac = int(command[4])
            return subprocess.CompletedProcess(command, self.pmset_status, stdout='', stderr='')
        raise AssertionError(f'unexpected command {command}')

    def commands(self):
        return [command for command, _kwargs in self.calls]


class StayAwakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        overlay = patch.dict(os.environ, {
            'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / 'config'),
            'XDG_STATE_HOME': str(self.home / 'state'),
            'XDG_CACHE_HOME': str(self.home / 'cache'),
            'XDG_DATA_HOME': str(self.home / 'data'),
        })
        overlay.start()
        self.addCleanup(overlay.stop)

    def record(self):
        return self.home / 'state' / 'groundwork' / sa.STATE_FILENAME

    def legacy(self):
        return self.home / 'state' / 'groundwork' / sa.LEGACY_STATE_FILENAME

    def invoke(self, settings, pmset, action='apply', *, system='Darwin', wsl=False, omarchy=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sa.platform, 'system', return_value=system), \
                patch.object(sa, 'is_wsl', return_value=wsl), \
                patch.object(sa.shutil, 'which', return_value='/usr/bin/omarchy' if omarchy else None), \
                patch.object(sa, 'load_settings', return_value=None if settings is None else dict(settings)), \
                patch.object(sa, 'run', side_effect=pmset), \
                patch.object(sa.sys, 'stdout', stdout), \
                patch.object(sa.sys, 'stderr', stderr):
            code = sa.main([action] if action else [])
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_narrow(self, pmset):
        for command in pmset.commands():
            blob = ' '.join(command)
            for banned in ('disablesleep', 'displaysleep', 'caffeinate', '-a', '-b', 'defaults'):
                self.assertNotIn(banned, command, command)
                self.assertNotIn(banned, blob.split(), command)
            if 'pmset' in command:
                self.assertTrue(command == sa.PMSET_READ or command[:4] == ['sudo', 'pmset', '-c', 'sleep'], command)

    def write_record(self, text, path=None):
        path = path or self.record()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_turning_on_records_the_earlier_value_and_sets_only_ac_sleep(self):
        pmset = FakePmset(ac=10, battery=5, display=10)
        code, out, _err = self.invoke(ON, pmset)
        self.assertEqual(code, 0)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ, SUDO, sa.PMSET_SLEEP_ZERO])
        sudo_kwargs = pmset.calls[1][1]
        self.assertIsNone(sudo_kwargs['timeout'])
        self.assertIs(sudo_kwargs['capture'], False)
        self.assertEqual((pmset.ac, pmset.battery, pmset.display), (0, 5, 10))
        self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')
        self.assertEqual(stat.S_IMODE(self.record().stat().st_mode), 0o600)
        self.assertIn('Recorded the previous AC sleep value 10', out)
        self.assertIn('Stay awake on power', out)
        self.assert_narrow(pmset)

    def test_apply_is_idempotent_on_and_off(self):
        pmset = FakePmset(ac=10)
        self.assertEqual(self.invoke(ON, pmset)[0], 0)
        again = FakePmset(ac=pmset.ac)
        code, out, _err = self.invoke(ON, again)
        self.assertEqual(code, 0)
        self.assertEqual(again.commands(), [sa.PMSET_READ])
        self.assertIn('already 0', out)
        self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')

        restored = FakePmset(ac=0)
        self.assertEqual(self.invoke(OFF, restored)[0], 0)
        self.assertEqual(restored.ac, 10)
        idle = FakePmset(ac=10)
        code, out, _err = self.invoke(OFF, idle)
        self.assertEqual(code, 0)
        self.assertEqual(idle.commands(), [])
        self.assertIn('Nothing was changed.', out)

    def test_turning_off_restores_the_recorded_value_and_removes_the_record(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0, battery=5)
        code, out, _err = self.invoke(OFF, pmset)
        self.assertEqual(code, 0)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ, SUDO, ['sudo', 'pmset', '-c', 'sleep', '10']])
        self.assertEqual((pmset.ac, pmset.battery), (10, 5))
        self.assertFalse(self.record().exists())
        self.assertIn('Restored AC sleep to 10', out)
        self.assert_narrow(pmset)

    def test_both_reasons_on_then_one_off_keeps_sleep_at_zero(self):
        pmset = FakePmset(ac=10)
        self.assertEqual(self.invoke(BOTH, pmset)[0], 0)
        self.assertEqual(pmset.ac, 0)
        for remaining in (GATEWAY_ONLY, ON):
            with self.subTest(remaining=remaining):
                still = FakePmset(ac=0)
                code, out, _err = self.invoke(remaining, still)
                self.assertEqual(code, 0)
                self.assertEqual(still.commands(), [sa.PMSET_READ])
                self.assertEqual(still.ac, 0)
                self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')
                self.assertIn('already 0', out)
        last = FakePmset(ac=0)
        self.assertEqual(self.invoke({'headless': False}, last)[0], 0)
        self.assertEqual(last.ac, 10)
        self.assertFalse(self.record().exists())

    def test_a_value_changed_by_hand_is_kept_when_turning_off(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=15)
        code, out, _err = self.invoke(OFF, pmset)
        self.assertEqual(code, 0)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ])
        self.assertEqual(pmset.ac, 15)
        self.assertFalse(self.record().exists())
        self.assertIn('left as it is', out)

    def test_an_existing_record_is_kept_while_on(self):
        self.write_record('3\n')
        pmset = FakePmset(ac=10)
        self.assertEqual(self.invoke(ON, pmset)[0], 0)
        self.assertEqual(pmset.ac, 0)
        self.assertEqual(self.record().read_text(encoding='utf-8'), '3\n')

    def test_the_gateway_record_from_an_earlier_release_is_adopted(self):
        self.write_record('7\n', self.legacy())
        pmset = FakePmset(ac=0)
        code, out, _err = self.invoke(OFF, pmset)
        self.assertEqual(code, 0)
        self.assertEqual(pmset.ac, 7)
        self.assertFalse(self.legacy().exists())
        self.assertFalse(self.record().exists())
        self.assertIn('Moved the earlier iMessage gateway sleep record', out)

    def test_an_unreadable_gateway_record_blocks_every_change(self):
        self.write_record('nope\n', self.legacy())
        pmset = FakePmset(ac=10)
        code, _out, err = self.invoke(ON, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [])
        self.assertEqual(self.legacy().read_text(encoding='utf-8'), 'nope\n')
        self.assertIn('cannot be restored', err)
        self.assertIn('Check the value, then remove the file or replace it with one integer.', err)

    def test_sudo_defer_and_cancel_change_nothing(self):
        for settings, record in ((ON, None), (OFF, '10\n')):
            for status in (10, 130, 2):
                with self.subTest(settings=settings, status=status):
                    if record:
                        self.write_record(record)
                    elif self.record().exists():
                        self.record().unlink()
                    pmset = FakePmset(ac=0 if record else 10, sudo_status=status)
                    code, out, err = self.invoke(settings, pmset)
                    self.assertEqual(code, 0 if status == 10 else status)
                    self.assertEqual(pmset.commands(), [sa.PMSET_READ, SUDO])
                    self.assertEqual(pmset.ac, 0 if record else 10)
                    if record:
                        self.assertEqual(self.record().read_text(encoding='utf-8'), record)
                    else:
                        self.assertFalse(self.record().exists())
                    if status == 10:
                        self.assertIn('Nothing was changed.', out)
                    if status == 130:
                        self.assertIn('cancelled', err)

    def test_a_record_planted_during_the_password_prompt_is_set_aside(self):
        planted = b'0\n'

        def plant():
            self.record().parent.mkdir(parents=True, exist_ok=True)
            self.record().write_bytes(planted)

        pmset = FakePmset(ac=10, on_sudo=plant)
        code, _out, err = self.invoke(ON, pmset)
        self.assertEqual(code, 1)
        self.assertNotIn(sa.PMSET_SLEEP_ZERO, pmset.commands())
        self.assertFalse(self.record().exists())
        asides = list(self.record().parent.glob(f'.{self.record().name}.aside.*'))
        self.assertEqual([item.read_bytes() for item in asides], [planted])
        self.assertIn('AC sleep was not changed', err)

    def test_a_record_changed_during_the_restore_prompt_blocks_restore(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0, on_sudo=lambda: self.record().write_text('99\n', encoding='utf-8'))
        code, _out, err = self.invoke(OFF, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.ac, 0)
        self.assertEqual(self.record().read_text(encoding='utf-8'), '99\n')
        self.assertIn('changed during the password prompt', err)

    def test_symlink_and_invalid_records_block_changes(self):
        target = self.home / 'keep'
        target.write_text('42\n', encoding='utf-8')
        self.record().parent.mkdir(parents=True)
        self.record().symlink_to(target)
        for settings in (ON, OFF):
            with self.subTest(settings=settings, record='symlink'):
                pmset = FakePmset(ac=10 if settings is ON else 0)
                self.assertEqual(self.invoke(settings, pmset)[0], 1)
                self.assertNotIn(SUDO, pmset.commands())
                self.assertTrue(self.record().is_symlink())
                self.assertEqual(target.read_text(encoding='utf-8'), '42\n')
        self.record().unlink()
        self.write_record('nope\n')
        pmset = FakePmset(ac=0)
        code, _out, err = self.invoke(OFF, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [])
        self.assertIn('cannot be restored', err)

    def test_a_failed_sleep_write_keeps_the_new_record(self):
        pmset = FakePmset(ac=10, pmset_status=1)
        code, _out, err = self.invoke(ON, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ, SUDO, sa.PMSET_SLEEP_ZERO])
        self.assertEqual(pmset.ac, 10)
        self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')
        self.assertIn('AC sleep was not changed', err)
        self.assertIn('value 10 is recorded', err)

    def test_a_failed_restore_keeps_the_record(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0, pmset_status=1)
        code, _out, err = self.invoke(OFF, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ, SUDO, ['sudo', 'pmset', '-c', 'sleep', '10']])
        self.assertEqual(pmset.ac, 0)
        self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')
        self.assertIn('still recorded', err)

    def test_a_stale_gateway_record_is_set_aside_when_the_shared_record_exists(self):
        self.write_record('10\n')
        self.write_record('3\n', self.legacy())
        pmset = FakePmset(ac=0)
        code, out, _err = self.invoke(ON, pmset)
        self.assertEqual(code, 0)
        self.assertFalse(self.legacy().exists() or self.legacy().is_symlink())
        asides = list(self.legacy().parent.glob(f'.{self.legacy().name}.aside.*'))
        self.assertEqual([item.read_text(encoding='utf-8') for item in asides], ['3\n'])
        self.assertIn('Set aside the earlier iMessage gateway sleep record', out)
        restored = FakePmset(ac=0)
        self.assertEqual(self.invoke(OFF, restored)[0], 0)
        self.assertEqual(restored.ac, 10)
        self.assertFalse(self.record().exists())
        idle = FakePmset(ac=10)
        self.assertEqual(self.invoke(OFF, idle)[0], 0)
        self.assertEqual(idle.commands(), [])

    def test_a_mac_switched_to_headless_restores_the_record(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0)
        code, out, _err = self.invoke({'headless': True, 'stay_awake_on_power': True}, pmset)
        self.assertEqual(code, 0)
        self.assertEqual(pmset.ac, 10)
        self.assertFalse(self.record().exists())
        self.assertIn('Restored AC sleep to 10', out)

    def test_an_unreadable_config_changes_nothing(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0)
        code, _out, err = self.invoke(None, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [])
        self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')
        self.assertIn('could not be read', err)
        self.assertNotIn('applies only on a desktop Mac', err)

    def test_undecodable_config_and_records_are_unreadable_not_a_crash(self):
        config = self.home / 'config' / 'chezmoi' / 'chezmoi.toml'
        config.parent.mkdir(parents=True)
        config.write_bytes(b'[data]\nheadless = false\n\xff\xfe\n')
        self.assertIsNone(sa.load_settings())
        self.record().parent.mkdir(parents=True)
        self.record().write_bytes(b'\xff\xfe\n')
        self.assertEqual(sa.read_recorded(self.record()), 'unreadable')
        pmset = FakePmset(ac=0)
        code, _out, err = self.invoke(OFF, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [])
        self.assertEqual(self.record().read_bytes(), b'\xff\xfe\n')
        self.assertIn('Check the value, then remove the file or replace it with one integer.', err)
        on = FakePmset(ac=10)
        code, _out, err = self.invoke(ON, on)
        self.assertEqual(code, 1)
        self.assertNotIn(SUDO, on.commands())
        self.assertIn('Check the value', err)

    def test_status_with_an_unreadable_config_says_unknown(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0)
        code, out, err = self.invoke(None, pmset, 'status')
        self.assertEqual(code, 0)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ])
        self.assertIn('Wanted here: unknown (config unreadable)', out)
        self.assertNotIn('Wanted here: no', out)
        self.assertNotIn('next apply restores', out)
        self.assertIn('could not be read', err)

    def test_an_unreadable_shared_record_keeps_the_gateway_record(self):
        self.write_record('nope\n')
        self.write_record('3\n', self.legacy())
        pmset = FakePmset(ac=0)
        code, _out, err = self.invoke(OFF, pmset)
        self.assertEqual(code, 1)
        self.assertEqual(pmset.commands(), [])
        self.assertEqual(self.legacy().read_text(encoding='utf-8'), '3\n')
        self.assertEqual(list(self.legacy().parent.glob('.*.aside.*')), [])
        self.assertIn('Check the value', err)

    def test_unknown_ac_sleep_changes_nothing(self):
        def unreadable(command, **_kwargs):
            if command == sa.PMSET_READ:
                return subprocess.CompletedProcess(command, 0, stdout='AC Power:\n displaysleep 10\n', stderr='')
            raise AssertionError(f'unexpected command {command}')

        self.assertEqual(self.invoke(ON, unreadable)[0], 1)
        self.assertFalse(self.record().exists())

    def test_headless_and_other_platforms_change_nothing(self):
        pmset = FakePmset()
        code, out, _err = self.invoke({'headless': True, 'stay_awake_on_power': True}, pmset)
        self.assertEqual(code, 0)
        self.assertIn('Nothing was changed.', out)
        cases = (
            (dict(system='Linux', wsl=True), 'WSL has no Mac power settings'),
            (dict(system='Linux', omarchy=True), 'groundwork-omarchy-mac-arm64'),
            (dict(system='Linux'), 'applies only on a desktop Mac'),
        )
        for kwargs, message in cases:
            for action in ('apply', 'status', None):
                with self.subTest(kwargs=kwargs, action=action):
                    code, _out, err = self.invoke(ON, pmset, action, **kwargs)
                    self.assertEqual(code, 1)
                    self.assertIn(message, err)
        self.assertEqual(pmset.commands(), [])

    def test_status_prints_pmset_custom_and_changes_nothing(self):
        self.write_record('10\n')
        pmset = FakePmset(ac=0, battery=5)
        code, out, _err = self.invoke(GATEWAY_ONLY, pmset, 'status')
        self.assertEqual(code, 0)
        self.assertEqual(pmset.commands(), [sa.PMSET_READ])
        self.assertIn('Stay awake on power: off (stay_awake_on_power)', out)
        self.assertIn('iMessage gateway: on (imessage_gateway)', out)
        self.assertIn('Wanted here: yes (iMessage gateway)', out)
        self.assertIn(f'Recorded previous AC sleep: 10 ({self.record()})', out)
        self.assertIn('pmset -g custom:\n  Battery Power:\n', out)
        self.assertIn('   sleep                0\n', out)
        self.assertIn('closed lid still sleeps', out)
        self.assertEqual(self.record().read_text(encoding='utf-8'), '10\n')
        self.assertNotIn('next apply restores', out)
        pending = FakePmset(ac=0)
        code, out, _err = self.invoke(OFF, pending, 'status')
        self.assertEqual(code, 0)
        self.assertIn('The next apply restores AC sleep to 10', out)
        self.record().unlink()
        default = FakePmset(ac=10)
        code, out, _err = self.invoke({'headless': False}, default, None)
        self.assertEqual(code, 0)
        self.assertEqual(default.commands(), [sa.PMSET_READ])
        self.assertIn('Wanted here: no', out)
        self.assertIn('not recorded', out)

    def test_help_and_rejected_arguments_run_nothing(self):
        stdout = io.StringIO()
        with patch.object(sa.sys, 'stdout', stdout), patch.object(sa.sys, 'stderr', io.StringIO()), \
                patch.object(sa, 'run') as run:
            self.assertEqual(sa.main(['--help']), 0)
            self.assertEqual(sa.main(['--bogus']), 64)
            self.assertEqual(sa.main(['apply', 'extra']), 64)
            self.assertEqual(sa.main(['nope']), 64)
        run.assert_not_called()
        self.assertIn('Changes nothing', stdout.getvalue())

    def test_parsers_ignore_decoys_and_non_bools(self):
        self.assertEqual(sa.parse_pmset(FakePmset(ac=10, battery=5).custom()), (10, 5))
        self.assertEqual(sa.parse_pmset('sleep 10\nSleep On Power Button 1\n'), (None, None))
        text = '[other]\nstay_awake_on_power = true\n[data]\nheadless = false\nstay_awake_on_power = true # kept\nimessage_gateway = "yes"\n'
        self.assertEqual(sa.parse_settings(text), {'headless': False, 'stay_awake_on_power': True})

    def test_source_never_names_the_settings_it_must_leave_alone(self):
        self.assertEqual(sa.PMSET_READ, ['pmset', '-g', 'custom'])
        self.assertEqual(sa.PMSET_SLEEP_ZERO, ['sudo', 'pmset', '-c', 'sleep', '0'])
        code = SOURCE.read_text(encoding='utf-8')
        executable = '\n'.join(line for line in code.splitlines() if not line.lstrip().startswith(('#', "'", '"')))
        self.assertNotRegex(executable, r"'(disablesleep|displaysleep)'")
        self.assertNotRegex(code, r"\['sudo', 'pmset', '-[ab]'")
        self.assertNotIn('caffeinate', executable)

    def test_configure_and_template_register_the_setting_without_a_bootstrap_prompt(self):
        text = CONFIGURE.read_text(encoding='utf-8')
        keys = _array(text, 'fields_key')
        kinds = _array(text, 'fields_kind')
        clears = _array(text, 'fields_clear')
        labels = re.findall(r'"([^"]*)"', _line(text, 'fields_label'))
        self.assertEqual(len({len(keys), len(kinds), len(clears), len(labels)}), 1)
        index = keys.index('stay_awake_on_power')
        self.assertEqual((kinds[index], clears[index], labels[index]), ('bool', 'no', 'Stay awake on power'))
        self.assertIn('"stay_awake_on_power") or isinstance(data.get(k), bool):', text)
        template = TEMPLATE.read_text(encoding='utf-8')
        self.assertNotIn('promptBoolOnce . "stay_awake_on_power"', template)
        self.assertIn('stay_awake_on_power = {{ $stayAwakeOnPower }}', template)

    def test_doctor_runs_the_read_only_status(self):
        text = DOCTOR.read_text(encoding='utf-8')
        self.assertIn('"$helper" status', text)
        self.assertNotIn('groundwork-stay-awake" apply', text)
        body = text[text.index('power_section() {'):]
        self.assertIn('    always_on_apps_section\n    power_section\n', text)
        self.assertNotIn('pmset -c', body[:body.index('\n}\n')])


class RenderTests(unittest.TestCase):
    def test_hook_runs_only_for_a_reason_or_a_record_and_config_keeps_the_bool(self):
        chezmoi = shutil.which('chezmoi')
        if chezmoi is None:
            self.fail('chezmoi is required to prove config and hook rendering')
        before = _config_bytes()
        hook = HOOK.read_text(encoding='utf-8')
        darwin = {'os': 'darwin', 'arch': 'arm64', 'osRelease': {}}
        linux = {'os': 'linux', 'arch': 'amd64', 'osRelease': {'ID': 'ubuntu'}}
        cases = (
            ({'headless': False, 'stay_awake_on_power': True, 'chezmoi': darwin}, None, True),
            ({'headless': False, 'imessage_gateway': True, 'chezmoi': darwin}, None, True),
            ({'headless': False, 'stay_awake_on_power': False, 'chezmoi': darwin}, None, False),
            ({'headless': False, 'stay_awake_on_power': 'yes', 'chezmoi': darwin}, None, False),
            ({'headless': False, 'chezmoi': darwin}, None, False),
            ({'headless': False, 'chezmoi': darwin}, 'stay-awake-ac-sleep', True),
            ({'headless': False, 'chezmoi': darwin}, 'imessage-gateway-ac-sleep', True),
            ({'headless': True, 'stay_awake_on_power': True, 'chezmoi': darwin}, None, False),
            ({'headless': True, 'stay_awake_on_power': True, 'chezmoi': darwin}, 'stay-awake-ac-sleep', True),
            ({'headless': False, 'stay_awake_on_power': True, 'chezmoi': linux}, 'stay-awake-ac-sleep', False),
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            records = root / 'state' / 'groundwork'
            records.mkdir(parents=True)
            for data, record, enabled in cases:
                with self.subTest(data=data, record=record):
                    for leftover in records.iterdir():
                        leftover.unlink()
                    if record:
                        (records / record).write_text('10\n', encoding='utf-8')
                    rendered = _execute(chezmoi, root, hook, data)
                    script = root / 'hook.sh'
                    script.write_text(rendered, encoding='utf-8')
                    syntax = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    self.assertEqual('"$HOME/.local/bin/groundwork-stay-awake" apply' in rendered, enabled)
            for extra, expected in (
                ('', 'stay_awake_on_power = false'),
                ('    stay_awake_on_power = true\n', 'stay_awake_on_power = true'),
                ('    stay_awake_on_power = "yes"\n', 'stay_awake_on_power = false'),
            ):
                with self.subTest(extra=extra):
                    self.assertIn(expected, _init(chezmoi, root, _fixture(extra)))
        self.assertEqual(_config_bytes(), before)


def _config_bytes():
    root = _ORIGINAL_ENV.get('XDG_CONFIG_HOME') or str(Path(_ORIGINAL_ENV.get('HOME', '/')) / '.config')
    path = Path(root) / 'chezmoi' / 'chezmoi.toml'
    return path.read_bytes() if path.exists() else None


def _line(text, name):
    match = re.search(rf'^{name}=\((.*)\)\s*$', text, re.M)
    if match is None:
        raise AssertionError(f'missing {name}')
    return match.group(1)


def _array(text, name):
    return _line(text, name).split()


def _fixture(extra=''):
    return f'''sourceDir = "{REPO / "home"}"
[data]
    code_dir = "~/code"
    email_personal = "t@example.com"
    email_work = ""
    game_dev = false
    headless = true
    key_repeat = "standard"
    name = "Test"
    obsidian_vault_name = "v"
    password_manager = "none"
    terminal_multiplexer = "tmux"
    reset_existing_configs = false
    signingkey = ""
    xcode = false
{extra}'''


def _env(root):
    env = os.environ.copy()
    env.update({
        'HOME': str(root / 'home'),
        'XDG_CONFIG_HOME': str(root / 'config'),
        'XDG_CACHE_HOME': str(root / 'cache'),
        'XDG_DATA_HOME': str(root / 'data'),
        'XDG_STATE_HOME': str(root / 'state'),
    })
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    return env


def _execute(chezmoi, root, hook, data):
    empty = root / 'empty.toml'
    empty.write_text('', encoding='utf-8')
    destination = root / 'dest'
    destination.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            chezmoi, '--config', str(empty), '--source', str(REPO / 'home'),
            '--destination', str(destination), '--override-data', json.dumps(data),
            'execute-template',
        ],
        input=hook, text=True, capture_output=True, env=_env(root), cwd=REPO, check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


def _init(chezmoi, root, text):
    incoming = root / 'incoming.toml'
    outgoing = root / 'outgoing.toml'
    incoming.write_text(text, encoding='utf-8')
    cache = root / 'chezmoi-cache'
    cache.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            chezmoi, '--config', str(incoming), '--source', str(REPO / 'home'),
            '--persistent-state', str(root / 'state.boltdb'), '--cache', str(cache),
            'init', '--config-path', str(outgoing),
        ],
        text=True, capture_output=True, env=_env(root), cwd=REPO, stdin=subprocess.DEVNULL, check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return outgoing.read_text(encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
