#!/usr/bin/env python3
"""Antigravity casks, the bool opt-out, and the T3 provider merge."""
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIGURE = REPO / "home/dot_local/bin/executable_groundwork-configure"
TEMPLATE = REPO / "home/.chezmoi.toml.tmpl"
SCRIPT = "home/run_after_22-antigravity-settings.sh.tmpl"
BUNDLE = "home/run_onchange_after_10-brew-bundle.sh.tmpl"
BREWFILE = "home/dot_config/homebrew/Brewfile.tmpl"
SECRET = "groundwork-test-secret-value"
SETTINGS_LIB = REPO / "home/dot_local/share/groundwork/lib/antigravity-t3-settings.sh"
# Chezmoi script order is the target name after stripping run_, then once_ or
# onchange_, then before_ or after_, then the .tmpl suffix. These four stay
# in the after phase, so that order is the apply order.
HOOK_ORDER = (
    "home/run_onchange_after_10-brew-bundle.sh.tmpl",
    "home/run_after_12-sudo-deferred-casks.sh",
    "home/run_after_21-t3-code.sh.tmpl",
    "home/run_after_22-antigravity-settings.sh.tmpl",
)


class AntigravityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-antigravity-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "empty.toml"
        self.config.write_text("", encoding="utf-8")
        self.base = dict(
            name="CI",
            email_personal="ci@example.com",
            email_work="work@example.com",
            code_dir="~/code",
            reset_existing_configs=False,
            password_manager="none",
            signingkey="",
            obsidian_vault_name="",
            game_dev=False,
            xcode=False,
            headless=False,
            terminal_multiplexer="herdr",
            key_repeat="fast",
            personal_apps=True,
            work=False,
            chezmoi=dict(os="darwin", arch="arm64", osRelease={"ID": "ubuntu"}),
        )

    def render(self, path, **data):
        effective = dict(self.base, **data)
        command = [
            "chezmoi",
            "--config",
            str(self.config),
            "--source",
            str(REPO),
            "--override-data",
            json.dumps(effective),
            "execute-template",
        ]
        return subprocess.run(
            command,
            input=(REPO / path).read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def render_ok(self, path, **data):
        result = self.render(path, **data)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_brewfile_installs_the_cli_everywhere_and_the_app_on_desktop_macs(self):
        cases = (
            ("darwin", "arm64", False, True),
            ("darwin", "amd64", False, True),
            ("darwin", "arm64", True, False),
            ("linux", "arm64", False, False),
            ("linux", "amd64", True, False),
        )
        desktop = re.compile(r'(?m)^cask "antigravity"([ \t]+#.*)?$')
        cli = re.compile(r'(?m)^cask "antigravity-cli"([ \t]+#.*)?$')
        for os_name, arch, headless, app in cases:
            with self.subTest(os=os_name, arch=arch, headless=headless):
                brewfile = self.render_ok(
                    BREWFILE,
                    headless=headless,
                    chezmoi=dict(os=os_name, arch=arch, osRelease={"ID": "ubuntu"}),
                )
                self.assertRegex(brewfile, cli)
                if app:
                    self.assertRegex(brewfile, desktop)
                else:
                    self.assertNotRegex(brewfile, desktop)

    def test_opt_out_omits_both_casks_and_does_not_touch_settings(self):
        brewfile = self.render_ok(BREWFILE, antigravity=False)
        self.assertNotIn('cask "antigravity"', brewfile)
        script = self.render_ok(SCRIPT, antigravity=False)
        self.assertTrue(script.startswith("#!/usr/bin/env bash\n"), script[:80])
        self.assertNotIn("--help", script)
        self.assertNotIn("--version", script)
        settings = self.root / "settings.json"
        original = b'{ "apiKey": "%s", "keep": true }\n' % SECRET.encode()
        settings.write_bytes(original)
        result = self.run_script(script, settings, brew=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(settings.read_bytes(), original)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertIn("antigravity = false", result.stdout)
        self.assertIn("does not uninstall", result.stdout)
        self.assertIn("brew uninstall --cask antigravity antigravity-cli", result.stdout)

    def test_a_non_bool_fails_closed(self):
        for value in ("yes", 1, "true"):
            with self.subTest(value=value):
                result = self.render(BREWFILE, antigravity=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("antigravity must be true or false", result.stderr)
                self.assertNotIn('cask "antigravity"', result.stdout)

    def test_init_defaults_true_keeps_false_and_rejects_a_non_bool(self):
        chezmoi = __import__("shutil").which("chezmoi")
        if chezmoi is None:
            self.fail("chezmoi is required to prove config rendering")
        absent = _init(chezmoi, self.root / "absent", _fixture())
        self.assertIn("antigravity = true", absent)
        kept = _init(chezmoi, self.root / "kept", _fixture("    antigravity = false\n"))
        self.assertIn("antigravity = false", kept)
        self.assertNotIn("antigravity = true", kept)
        rejected = _init(
            chezmoi,
            self.root / "rejected",
            _fixture('    antigravity = "yes"\n'),
            expect_ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("antigravity must be true or false", rejected.stderr)

    def test_configure_registers_the_bool_without_a_bootstrap_prompt(self):
        text = CONFIGURE.read_text(encoding="utf-8")
        keys = _words(text, "fields_key")
        kinds = _words(text, "fields_kind")
        clears = _words(text, "fields_clear")
        labels = re.findall(r'"([^"]*)"', _words(text, "fields_label", raw=True))
        self.assertEqual(len({len(keys), len(kinds), len(clears), len(labels)}), 1)
        index = keys.index("antigravity")
        self.assertEqual((kinds[index], clears[index], labels[index]), ("bool", "no", "Antigravity"))
        self.assertIn(
            '"stay_awake_on_power", "antigravity") or isinstance(data.get(k), bool):',
            text,
        )
        self.assertIn("brew uninstall --cask antigravity antigravity-cli", text)
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn('promptBoolOnce . "antigravity"', template)
        self.assertIn('antigravity = {{ get $developer "antigravity" }}', template)

    def test_merge_adds_the_provider_when_absent_and_hides_secrets(self):
        agy = self.install_agy()
        settings = self.root / "home" / ".t3" / "userdata" / "settings.json"
        settings.parent.mkdir(parents=True)
        original = {
            "apiKey": SECRET,
            "theme": "dark",
            "providerInstances": {
                "codex": {"enabled": True, "config": {"apiKey": SECRET}},
            },
        }
        settings.write_text(json.dumps(original) + "\n", encoding="utf-8")
        os.chmod(settings, 0o640)
        script = self.render_ok(SCRIPT)
        result = self.run_script(script, settings, agy=agy, home=self.root / "home")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn("--help", result.stdout + result.stderr)
        self.assertFalse((self.root / "agy-executed").exists())
        self.assertIn("Added the Antigravity provider", result.stdout)
        merged = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(merged["apiKey"], SECRET)
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["providerInstances"]["codex"]["config"]["apiKey"], SECRET)
        self.assertEqual(
            merged["providerInstances"]["antigravity"],
            {
                "driver": "antigravity",
                "enabled": True,
                "config": {"binaryPath": str(agy)},
            },
        )
        self.assertNotIn("authMethod", json.dumps(merged["providerInstances"]["antigravity"]))
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o640)
        self.assertFalse(list(settings.parent.glob(".settings.json.*")))

    def test_missing_provider_object_is_added_without_dropping_siblings(self):
        agy = self.install_agy()
        t3, settings = self.t3_settings("empty-object")
        settings.write_text('{"theme":"dark"}\n', encoding="utf-8")
        script = self.render_ok(SCRIPT)
        result = self.run_script(script, settings, agy=agy, t3_home=t3)
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(
            merged["providerInstances"]["antigravity"],
            {
                "driver": "antigravity",
                "enabled": True,
                "config": {"binaryPath": str(agy)},
            },
        )
        self.assertFalse((self.root / "agy-executed").exists())

    def test_existing_instance_is_byte_for_byte_unchanged(self):
        agy = self.install_agy()
        cases = {
            "disabled": {
                "providerInstances": {
                    "antigravity": {
                        "driver": "antigravity",
                        "enabled": False,
                        "config": {"binaryPath": "/custom/agy"},
                    }
                }
            },
            "custom-path": {
                "apiKey": SECRET,
                "providerInstances": {
                    "antigravity": {
                        "driver": "antigravity",
                        "enabled": True,
                        "config": {"binaryPath": "/elsewhere/agy", "apiKey": SECRET},
                    }
                },
            },
            "null-value": {"providerInstances": {"antigravity": None}},
            "false-value": {"providerInstances": {"antigravity": False}},
        }
        script = self.render_ok(SCRIPT)
        for name, payload in cases.items():
            with self.subTest(name=name):
                t3, settings = self.t3_settings(name)
                raw = json.dumps(payload, indent=2).encode() + b"\n"
                settings.write_bytes(raw)
                result = self.run_script(script, settings, agy=agy, t3_home=t3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(settings.read_bytes(), raw)
                self.assertIn("unchanged", result.stdout)
                self.assertNotIn(SECRET, result.stdout + result.stderr)
                self.assertFalse((self.root / "agy-executed").exists())

    def test_missing_file_is_created_under_t3code_home_with_mode_0600(self):
        agy = self.install_agy()
        home = self.root / "home"
        t3 = self.root / "custom-t3"
        home.mkdir()
        script = self.render_ok(SCRIPT)
        result = self.run_script(script, t3 / "userdata" / "settings.json", agy=agy, home=home, t3_home=t3)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = t3 / "userdata" / "settings.json"
        self.assertTrue(settings.is_file())
        self.assertFalse((home / ".t3").exists())
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(settings.read_text(encoding="utf-8")),
            {
                "providerInstances": {
                    "antigravity": {
                        "driver": "antigravity",
                        "enabled": True,
                        "config": {"binaryPath": str(agy)},
                    }
                }
            },
        )
        self.assertIn(str(settings), result.stdout)

    def test_invalid_json_is_left_untouched_and_secrets_are_not_printed(self):
        agy = self.install_agy()
        t3, settings = self.t3_settings("broken")
        original = ('{ "apiKey": "%s"\n' % SECRET).encode()
        settings.write_bytes(original)
        script = self.render_ok(SCRIPT)
        result = self.run_script(script, settings, agy=agy, t3_home=t3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(settings.read_bytes(), original)
        self.assertIn("not valid JSON", result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertFalse(list(settings.parent.glob(".settings.json.*")))

    def test_unsafe_shapes_and_a_symlink_are_left_untouched(self):
        agy = self.install_agy()
        script = self.render_ok(SCRIPT)
        for name, payload in (("array", b"[]\n"), ("providers", b'{"providerInstances":[]}\n')):
            with self.subTest(name=name):
                t3, settings = self.t3_settings(name)
                settings.write_bytes(payload)
                result = self.run_script(script, settings, agy=agy, t3_home=t3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(settings.read_bytes(), payload)
                self.assertIn("unchanged", result.stderr)
        link_target = self.root / "real.json"
        link_target.write_text("{}\n", encoding="utf-8")
        t3, link = self.t3_settings("link")
        link.symlink_to(link_target)
        before = link_target.read_bytes()
        result = self.run_script(script, link, agy=agy, t3_home=t3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(link_target.read_bytes(), before)
        self.assertIn("symbolic link", result.stderr)

    def test_missing_agy_skips_without_writing_or_executing(self):
        t3, settings = self.t3_settings("no-agy")
        settings.write_text("{}\n", encoding="utf-8")
        before = settings.read_bytes()
        script = self.render_ok(SCRIPT)
        prefix = self.root / "empty-prefix"
        brew = self.write_brew(prefix)
        result = self.run_script(script, settings, brew=brew, t3_home=t3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(settings.read_bytes(), before)
        self.assertIn("agy is not installed at", result.stdout)
        self.assertIn(str(prefix / "bin" / "agy"), result.stdout)
        self.assertFalse((self.root / "agy-executed").exists())

    def test_second_run_is_a_noop(self):
        agy = self.install_agy()
        home = self.root / "home"
        home.mkdir()
        script = self.render_ok(SCRIPT)
        settings = home / ".t3" / "userdata" / "settings.json"
        first = self.run_script(script, settings, agy=agy, home=home)
        self.assertEqual(first.returncode, 0, first.stderr)
        raw = settings.read_bytes()
        second = self.run_script(script, settings, agy=agy, home=home)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(settings.read_bytes(), raw)
        self.assertIn("already exist", second.stdout)
        self.assertIn("unchanged", second.stdout)

    def test_rendered_scripts_pass_bash_n_and_do_not_probe_agy(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                script = self.render_ok(SCRIPT, antigravity=enabled)
                self.assertTrue(script.startswith("#!/usr/bin/env bash\n"))
                self.assertNotIn("--help", script)
                self.assertNotIn("--version", script)
                syntax = subprocess.run(
                    ["bash", "-n"],
                    input=script,
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(syntax.returncode, 0, syntax.stderr)
                if enabled:
                    self.assertIn("antigravity-t3-settings.sh", script)
                else:
                    self.assertNotIn("antigravity-t3-settings.sh", script)
        lib = SETTINGS_LIB.read_text(encoding="utf-8")
        self.assertNotIn("--help", lib)
        self.assertNotIn("--version", lib)
        self.assertNotIn("agy --", lib)
        syntax = subprocess.run(
            ["bash", "-n", str(SETTINGS_LIB)],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_stripped_hook_names_keep_the_bundle_before_the_settings_retry(self):
        stripped = [_stripped_script_target(name) for name in HOOK_ORDER]
        self.assertEqual(
            stripped,
            [
                "10-brew-bundle.sh",
                "12-sudo-deferred-casks.sh",
                "21-t3-code.sh",
                "22-antigravity-settings.sh",
            ],
        )
        self.assertEqual(stripped, sorted(stripped))
        for name in HOOK_ORDER:
            path = REPO / name
            self.assertTrue(path.is_file(), name)
            self.assertIn("_after_", path.name)

    def test_bundle_runs_the_shared_merge_after_the_required_bundle_succeeds(self):
        enabled = self.render_ok(BUNDLE, antigravity=True)
        disabled = self.render_ok(BUNDLE, antigravity=False)
        settings = self.render_ok(SCRIPT, antigravity=True)
        marker = "antigravity-t3-settings.sh"
        self.assertIn(marker, enabled)
        self.assertNotIn(marker, disabled)
        self.assertGreater(enabled.index(marker), enabled.index('exit "$bundle_status"'))
        self.assertGreater(enabled.index(marker), enabled.index("Brewfile.optional"))
        self.assertIn('[[ -n "$agy_bin" && -f "$agy_bin" && -x "$agy_bin" ]]', enabled)
        enabled_call = re.search(r'bash ("[^"]*antigravity-t3-settings\.sh") </dev/null', enabled)
        settings_call = re.search(r'bash ("[^"]*antigravity-t3-settings\.sh") </dev/null', settings)
        self.assertIsNotNone(enabled_call)
        self.assertIsNotNone(settings_call)
        self.assertEqual(enabled_call.group(1), settings_call.group(1))
        lib = Path(enabled_call.group(1)[1:-1])
        self.assertEqual(lib, SETTINGS_LIB)
        header = (REPO / SCRIPT).read_text(encoding="utf-8")
        docs = (REPO / "docs/agents.html").read_text(encoding="utf-8")
        for text in (header, docs):
            self.assertNotIn("later hook", text)
            self.assertNotIn("first apply can skip", text)
            self.assertIn("before it returns", text)
        self.assertIn("leaves the settings file untouched", docs)
        syntax = subprocess.run(
            ["bash", "-n"],
            input=enabled,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        syntax = subprocess.run(
            ["bash", "-n"],
            input=disabled,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def install_agy(self):
        prefix = self.root / "homebrew"
        agy = prefix / "bin" / "agy"
        agy.parent.mkdir(parents=True)
        real = self.root / "lib" / "not-the-agy-name"
        real.parent.mkdir()
        marker = self.root / "agy-executed"
        real.write_text("#!/bin/sh\ntouch '%s'\nexit 99\n" % marker, encoding="utf-8")
        real.chmod(0o755)
        agy.symlink_to(real)
        self.write_brew(prefix)
        return agy

    def t3_settings(self, name):
        t3 = self.root / "t3" / name
        settings = t3 / "userdata" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        return t3, settings

    def write_brew(self, prefix):
        brew = self.root / ("brew-" + prefix.name)
        brew.write_text(
            """#!/bin/sh
if [ "$1" = "--prefix" ]; then
  printf '%s\\n' '{prefix}'
  exit 0
fi
exit 1
""".format(prefix=prefix),
            encoding="utf-8",
        )
        brew.chmod(0o755)
        return brew

    def run_script(self, script, settings, agy=None, brew=None, home=None, t3_home=None):
        if brew is None and agy is not None:
            brew = self.root / ("brew-" + agy.parents[1].name)
        env = os.environ.copy()
        env["HOME"] = str(home or self.root / "unused-home")
        env["PATH"] = "/usr/bin:/bin"
        if t3_home is None:
            env.pop("T3CODE_HOME", None)
        else:
            env["T3CODE_HOME"] = str(t3_home)
        if brew:
            env["GROUNDWORK_TEST_BREW_BIN"] = str(brew)
        else:
            env["GROUNDWORK_TEST_BREW_BIN"] = str(self.root / "missing-brew")
        return subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            timeout=15,
            env=env,
            check=False,
        )


def _stripped_script_target(source_name):
    """Target name chezmoi sorts: drop run_, once_/onchange_, before_/after_, and .tmpl."""
    name = source_name.rsplit("/", 1)[-1]
    if name.endswith(".tmpl"):
        name = name[: -len(".tmpl")]
    if not name.startswith("run_"):
        raise AssertionError(name)
    name = name[len("run_") :]
    for prefix in ("once_", "onchange_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    for prefix in ("before_", "after_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    return name


def _words(text, name, raw=False):
    match = re.search(rf"^{name}=\((.*)\)\s*$", text, re.M)
    if match is None:
        raise AssertionError(f"missing {name}")
    if raw:
        return match.group(1)
    return match.group(1).split()


def _fixture(extra=""):
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
    env["HOME"] = str(root / "home")
    env["XDG_CONFIG_HOME"] = str(root / "config")
    env["XDG_CACHE_HOME"] = str(root / "cache")
    env["XDG_DATA_HOME"] = str(root / "data")
    env["XDG_STATE_HOME"] = str(root / "state")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    return env


def _init(chezmoi, root, text, expect_ok=True):
    root.mkdir(parents=True, exist_ok=True)
    incoming = root / "incoming.toml"
    outgoing = root / "outgoing.toml"
    incoming.write_text(text, encoding="utf-8")
    cache = root / "chezmoi-cache"
    cache.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            chezmoi,
            "--config",
            str(incoming),
            "--source",
            str(REPO / "home"),
            "--persistent-state",
            str(root / "state.boltdb"),
            "--cache",
            str(cache),
            "init",
            "--config-path",
            str(outgoing),
        ],
        text=True,
        capture_output=True,
        env=_env(root),
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if expect_ok and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    if expect_ok:
        return outgoing.read_text(encoding="utf-8")
    return result


if __name__ == "__main__":
    unittest.main()
