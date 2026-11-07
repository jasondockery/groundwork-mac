#!/usr/bin/env python3
"""The iMessage gateway role is off until asked, and then touches only Remote Login; groundwork-stay-awake owns its AC sleep."""
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'home/dot_local/bin/executable_groundwork-imessage-gateway'
HOOK = REPO / 'home/run_after_33-imessage-gateway.sh.tmpl'
CONFIGURE = REPO / 'home/dot_local/bin/executable_groundwork-configure'
TEMPLATE = REPO / 'home/.chezmoi.toml.tmpl'
_ORIGINAL_ENV = dict(os.environ)

loader = SourceFileLoader('imessage_gateway', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
gw = importlib.util.module_from_spec(spec)
loader.exec_module(gw)

BANNED = (
    'authorized_keys',
    'TCC.db',
    'tccutil',
    'defaults',
    '--markread',
    'disablesleep',
    'idleTime',
)


def real_chezmoi_config():
    root = _ORIGINAL_ENV.get('XDG_CONFIG_HOME') or str(Path(_ORIGINAL_ENV.get('HOME', '/')) / '.config')
    return Path(root) / 'chezmoi' / 'chezmoi.toml'


class GatewayTests(unittest.TestCase):
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

    def completed(self, status=0, stdout='', stderr=''):
        return subprocess.CompletedProcess([], status, stdout=stdout, stderr=stderr)

    def desktop(self, settings, *, system='Darwin', wsl=False, omarchy=False):
        which = '/usr/bin/omarchy' if omarchy else None
        return _Desktop(
            patch.object(gw.platform, 'system', return_value=system),
            patch.object(gw, 'is_wsl', return_value=wsl),
            patch.object(gw.shutil, 'which', return_value=which),
            patch.object(gw, 'load_settings', return_value=dict(settings)),
            patch.object(gw.sys, 'stdout', io.StringIO()),
            patch.object(gw.sys, 'stderr', io.StringIO()),
        )

    def assert_narrow(self, run):
        for call in run.call_args_list:
            command = call.args[0]
            self.assertIsInstance(command, list)
            blob = ' '.join(command)
            for banned in BANNED:
                self.assertNotIn(banned, blob, command)
            self.assertNotIn('pmset', command)
            self.assertNotIn('-a', command)
            self.assertNotIn('-b', command)

    def test_parsers_ignore_decoys_and_non_bools(self):
        text = """\
imessage_gateway = true
[other]
headless = false
imessage_gateway = true
[data]
headless = false
imessage_gateway = true # kept
note = "yes"
imessage_gateway = "yes"
"""
        self.assertEqual(gw.parse_settings(text), {'headless': False, 'imessage_gateway': True})
        self.assertEqual(
            gw.parse_settings('[data]\nimessage_gateway = "yes"\nheadless = false\n'),
            {'headless': False},
        )

    def test_constants_are_the_narrow_contract(self):
        self.assertEqual(gw.SYSTEMSETUP, ['sudo', '/usr/sbin/systemsetup', '-setremotelogin', 'on'])
        self.assertEqual(gw.SSH_SERVICE, ['launchctl', 'print', 'system/com.openssh.sshd'])
        self.assertEqual(gw.TAILSCALE_PROCESS, ['pgrep', '-x', 'Tailscale'])
        text = SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('TCC.db', text)
        self.assertNotIn('disablesleep', text)
        self.assertNotIn('idleTime', text)
        self.assertNotRegex(text, r'\bdefaults write\b')
        self.assertNotRegex(text, r"\['defaults'")
        self.assertNotRegex(text, r"\['sudo', 'pmset'")

    def test_role_off_prepare_changes_nothing(self):
        for settings in ({'headless': False, 'imessage_gateway': False}, {'headless': False}):
            with self.subTest(settings=settings):
                with self.desktop(settings) as (stdout, _stderr):
                    with patch.object(gw, 'run') as run:
                        self.assertEqual(gw.main(['prepare']), 0)
                run.assert_not_called()
                self.assertIn('Nothing was changed.', stdout.getvalue())

    def test_headless_prepare_changes_nothing(self):
        with self.desktop({'headless': True, 'imessage_gateway': True}) as (_stdout, stderr):
            with patch.object(gw, 'run') as run:
                self.assertEqual(gw.main(['prepare']), 1)
        run.assert_not_called()
        self.assertIn('Nothing was changed.', stderr.getvalue())

    def test_prepare_enables_remote_login_and_leaves_sleep_to_stay_awake(self):
        effects = [
            self.completed(1),
            self.completed(0),
            self.completed(1, stderr='Operation not permitted'),
            self.completed(0),
        ]
        with self.desktop({'headless': False, 'imessage_gateway': True}) as (stdout, _stderr):
            with patch.object(gw, 'run', side_effect=effects) as run:
                self.assertEqual(gw.main(['prepare']), 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [
            gw.SSH_SERVICE,
            ['bash', '-c', gw.SUDO_PREPARE_SCRIPT],
            gw.SYSTEMSETUP,
            ['open', gw.SHARING_URL],
        ])
        self.assertNotIn(gw.PRIVACY_URL, str(commands))
        sudo = run.call_args_list[1]
        self.assertIsNone(sudo.kwargs['timeout'])
        self.assertIs(sudo.kwargs['capture'], False)
        self.assert_narrow(run)
        self.assertIn('Sharing settings is open.', stdout.getvalue())
        self.assertFalse((self.home / 'state').exists())

    def test_prepare_is_idle_when_remote_login_is_on(self):
        with self.desktop({'headless': False, 'imessage_gateway': True}) as (stdout, _stderr):
            with patch.object(gw, 'run', side_effect=[self.completed(0)]) as run:
                self.assertEqual(gw.main(['prepare']), 0)
        self.assertEqual([call.args[0] for call in run.call_args_list], [gw.SSH_SERVICE])
        self.assertIn('Remote Login is on.', stdout.getvalue())

    def test_sudo_defer_and_cancel_do_not_write(self):
        for status in (10, 130, 2):
            with self.subTest(status=status):
                effects = [self.completed(1), self.completed(status)]
                with self.desktop({'headless': False, 'imessage_gateway': True}) as (stdout, stderr):
                    with patch.object(gw, 'run', side_effect=effects) as run:
                        self.assertEqual(gw.main(['prepare']), 0 if status == 10 else status)
                self.assertEqual(len(run.call_args_list), 2)
                self.assert_narrow(run)
                if status == 10:
                    self.assertIn('Nothing was changed.', stdout.getvalue())
                if status == 130:
                    self.assertIn('cancelled', stderr.getvalue())

    def test_status_is_read_only(self):
        effects = [
            self.completed(0),
            self.completed(1, stderr='eDSRecordNotFound'),
            self.completed(0),
            self.completed(0, 'Wanted here: no\npmset -g custom:\n  AC Power:\n'),
        ]
        with self.desktop({'headless': False, 'imessage_gateway': False}) as (stdout, _stderr):
            with patch.object(gw, 'run', side_effect=effects) as run:
                self.assertEqual(gw.main(['status']), 0)
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [gw.SSH_SERVICE, gw.ACCESS_GROUP, gw.TAILSCALE_PROCESS, [gw.stay_awake_command(), 'status']],
        )
        text = stdout.getvalue()
        self.assertIn('Role stored: off', text)
        self.assertIn('Role applied here: no', text)
        self.assertIn('Remote Login: on', text)
        self.assertIn('not limited to a selected list', text)
        self.assertIn('gateway account alone', text)
        self.assertIn('Tailscale: running', text)
        self.assertIn('Power (groundwork-stay-awake status):\n  Wanted here: no\n  pmset -g custom:\n', text)
        self.assertIn('Blip check: not installed', text)
        self.assertNotIn('python3', text)
        self.assert_narrow(run)
        self.assertFalse((self.home / 'state').exists())

    def test_status_reports_installed_blip_check_without_running_it(self):
        blip = self.home / '.blip' / 'bin' / 'blip-check'
        blip.parent.mkdir(parents=True)
        blip.write_text('print("ok")\n', encoding='utf-8')
        effects = [
            self.completed(0),
            self.completed(0, 'GroupMembership: gateway\n'),
            self.completed(1),
            self.completed(0, 'Wanted here: no\npmset -g custom:\n  AC Power:\n'),
        ]
        with self.desktop({'headless': False, 'imessage_gateway': True}) as (stdout, _stderr):
            with patch.object(gw, 'run', side_effect=effects) as run:
                self.assertEqual(gw.main(['status']), 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands,
            [gw.SSH_SERVICE, gw.ACCESS_GROUP, gw.TAILSCALE_PROCESS, [gw.stay_awake_command(), 'status']],
        )
        for command in commands:
            blob = ' '.join(command)
            self.assertNotIn('python3', blob)
            self.assertNotIn('blip-check', blob)
        text = stdout.getvalue()
        self.assertIn('Blip check: installed', text)
        self.assertIn('ssh <host> \'python3 "$HOME/.blip/bin/blip-check"\'', text)
        self.assertIn('one-time Allow prompt', text)
        self.assertIn('status does not run it', text)
        self.assertIn('gateway', text)
        self.assertIn('Tailscale: not running', text)
        self.assertEqual(blip.read_text(encoding='utf-8'), 'print("ok")\n')
        self.assert_narrow(run)

    def test_setup_opens_both_panes_without_pmset(self):
        with self.desktop({'headless': False, 'imessage_gateway': False}) as (stdout, _stderr):
            with patch.object(gw, 'run', side_effect=[self.completed(0), self.completed(0)]) as run:
                self.assertEqual(gw.main(['setup']), 0)
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [['open', gw.SHARING_URL], ['open', gw.PRIVACY_URL]],
        )
        self.assertIn('Manual steps', stdout.getvalue())
        self.assert_narrow(run)

    def test_headless_setup_prints_steps_without_opening_panes(self):
        with self.desktop({'headless': True, 'imessage_gateway': True}) as (stdout, stderr):
            with patch.object(gw, 'run') as run:
                self.assertEqual(gw.main(['setup']), 1)
        run.assert_not_called()
        self.assertIn('Nothing was opened.', stderr.getvalue())
        self.assertIn('Manual steps', stdout.getvalue())

    def test_markread_uses_the_client_command(self):
        command = 'ssh <host> \'python3 "$HOME/.blip/bin/blip-check" --markread\''
        local = 'python3 ~/.blip/bin/blip-check --markread'
        doc = (REPO / 'docs/imessage-gateway.md').read_text(encoding='utf-8')
        steps = '\n'.join(gw.MANUAL_STEPS)
        for text in (steps, doc):
            self.assertIn(command, text)
            self.assertIn('This Mac is only where the Allow prompt is clicked.', text)
            self.assertNotIn(local, text)

    def test_help_and_rejected_arguments_do_not_run_commands(self):
        stdout = io.StringIO()
        with patch.object(gw.sys, 'stdout', stdout), patch.object(gw.sys, 'stderr', io.StringIO()):
            with patch.object(gw, 'run') as run:
                self.assertEqual(gw.main(['--help']), 0)
                self.assertEqual(gw.main(['--bogus']), 64)
                self.assertEqual(gw.main(['status', 'extra']), 64)
                self.assertEqual(gw.main(['nope']), 64)
        run.assert_not_called()
        help_text = stdout.getvalue()
        self.assertIn('Changes nothing', help_text)
        self.assertIn('does not run blip-check', help_text)
        self.assertNotIn('--markread', help_text)

    def test_other_platforms_do_not_run_commands(self):
        cases = (
            (True, False, 'Linux', 'WSL does not configure a Mac iMessage gateway'),
            (False, True, 'Linux', 'groundwork-omarchy-mac-arm64'),
            (False, False, 'Linux', 'applies only on a desktop Mac'),
        )
        for wsl, omarchy, system, message in cases:
            for action in (['status'], ['prepare'], ['setup'], []):
                with self.subTest(message=message, action=action):
                    with self.desktop({}, system=system, wsl=wsl, omarchy=omarchy) as (stdout, stderr):
                        with patch.object(gw, 'run') as run:
                            self.assertEqual(gw.main(action), 1)
                    run.assert_not_called()
                    self.assertIn(message, stderr.getvalue())
                    if action in ([], ['setup']):
                        self.assertIn('Manual steps', stdout.getvalue())

    def test_configure_registers_the_role_without_a_bootstrap_prompt(self):
        text = CONFIGURE.read_text(encoding='utf-8')
        keys = _array(text, 'fields_key')
        kinds = _array(text, 'fields_kind')
        clears = _array(text, 'fields_clear')
        labels = _quoted(text, 'fields_label')
        self.assertEqual(len(keys), len(kinds))
        self.assertEqual(len(keys), len(clears))
        self.assertEqual(len(keys), len(labels))
        index = keys.index('imessage_gateway')
        self.assertEqual(kinds[index], 'bool')
        self.assertEqual(clears[index], 'no')
        self.assertEqual(labels[index], 'iMessage gateway')
        self.assertIn(
            'This applies only on a desktop Mac. Linux, WSL, a headless Mac, and Omarchy keep the saved answer and do not change Remote Login or sleep.',
            text,
        )
        self.assertIn(
            'if k in ("personal_apps", "work_extensions", "imessage_gateway", "stay_awake_on_power") or isinstance(data.get(k), bool):',
            text,
        )
        template = TEMPLATE.read_text(encoding='utf-8')
        self.assertNotIn('promptBoolOnce . "imessage_gateway"', template)
        self.assertIn('kindIs "bool" .imessage_gateway', template)
        self.assertLess(
            template.index('hasKey . "imessage_gateway"'),
            template.index('kindIs "bool" .imessage_gateway'),
        )


class _Desktop:
    def __init__(self, *patches):
        self.patches = patches
        self.entered = []

    def __enter__(self):
        for item in self.patches:
            self.entered.append(item.__enter__())
        return self.entered[-2], self.entered[-1]

    def __exit__(self, exc_type, exc, tb):
        result = False
        for item in reversed(self.patches):
            result = item.__exit__(exc_type, exc, tb) or result
        return result


class RenderTests(unittest.TestCase):
    def test_hook_and_config_follow_the_stored_bool(self):
        before = _config_bytes()
        chezmoi = __import__('shutil').which('chezmoi')
        if chezmoi is None:
            self.fail('chezmoi is required to prove config and hook rendering')
        hook = HOOK.read_text(encoding='utf-8')
        cases = (
            ({'headless': False, 'imessage_gateway': True, 'chezmoi': _darwin()}, True),
            ({'headless': False, 'imessage_gateway': False, 'chezmoi': _darwin()}, False),
            ({'headless': False, 'chezmoi': _darwin()}, False),
            ({'headless': True, 'imessage_gateway': True, 'chezmoi': _darwin()}, False),
            ({'headless': False, 'imessage_gateway': True, 'chezmoi': _linux()}, False),
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for data, enabled in cases:
                with self.subTest(data=data):
                    rendered = _execute(chezmoi, root, hook, data)
                    script = root / 'hook.sh'
                    script.write_text(rendered, encoding='utf-8')
                    syntax = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    if enabled:
                        self.assertIn('"$HOME/.local/bin/groundwork-imessage-gateway" prepare', rendered)
                    else:
                        self.assertNotIn('groundwork-imessage-gateway', rendered)
            absent = _init(chezmoi, root, _fixture())
            self.assertIn('imessage_gateway = false', absent)
            kept = _init(chezmoi, root, _fixture('    imessage_gateway = true\n'))
            self.assertIn('imessage_gateway = true', kept)
            coerced = _init(chezmoi, root, _fixture('    imessage_gateway = "yes"\n'))
            self.assertIn('imessage_gateway = false', coerced)
            self.assertNotIn('imessage_gateway = "yes"', coerced)
        self.assertEqual(_config_bytes(), before)


def _darwin():
    return {'os': 'darwin', 'arch': 'arm64', 'osRelease': {}}


def _linux():
    return {'os': 'linux', 'arch': 'amd64', 'osRelease': {'ID': 'ubuntu'}}


def _config_bytes():
    path = real_chezmoi_config()
    if not path.exists():
        return None
    return path.read_bytes()


def _array(text, name):
    import re
    match = re.search(rf'^{name}=\((.*)\)\s*$', text, re.M)
    if match is None:
        raise AssertionError(f'missing {name}')
    return match.group(1).split()


def _quoted(text, name):
    import re
    match = re.search(rf'^{name}=\((.*)\)\s*$', text, re.M)
    if match is None:
        raise AssertionError(f'missing {name}')
    return re.findall(r'"([^"]*)"', match.group(1))


def _fixture(extra=''):
    return f'''sourceDir = "{REPO / "home"}"
[data]
    beta = true
    code_dir = "~/code"
    email_personal = "t@example.com"
    email_work = ""
    game_dev = false
    headless = true
    install_chrome = false
    key_repeat = "standard"
    name = "Test"
    obsidian_vault_name = "v"
    password_manager = "none"
    profile_preset = "personal-preview"
    terminal_multiplexer = "tmux"
    reset_existing_configs = false
    signingkey = ""
    work = false
    xcode = true
{extra}'''


def _env(root):
    env = os.environ.copy()
    env['HOME'] = str(root / 'home')
    env['XDG_CONFIG_HOME'] = str(root / 'config')
    env['XDG_CACHE_HOME'] = str(root / 'cache')
    env['XDG_DATA_HOME'] = str(root / 'data')
    env['XDG_STATE_HOME'] = str(root / 'state')
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
        input=hook,
        text=True,
        capture_output=True,
        env=_env(root),
        cwd=REPO,
        check=False,
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
        text=True,
        capture_output=True,
        env=_env(root),
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return outgoing.read_text(encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
