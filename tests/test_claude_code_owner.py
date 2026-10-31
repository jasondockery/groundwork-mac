#!/usr/bin/env python3
"""claude_code_owner names one Claude Code owner; two copies warn without failing."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "home/dot_local/share/groundwork/lib/coding-cli-ownership.sh"
DOCTOR = REPO / "home/dot_local/bin/executable_groundwork-doctor"
CONFIGURE = REPO / "home/dot_local/bin/executable_groundwork-configure"
UPDATE_RUN = REPO / "home/dot_local/bin/executable_groundwork-update-run.tmpl"
TEMPLATE = REPO / "home/.chezmoi.toml.tmpl"
BREWFILE = "home/dot_config/homebrew/Brewfile.tmpl"
VERSION = "2.1.314"


class DualInstallTests(unittest.TestCase):
    """Temp HOME, a fake Homebrew prefix, and fake claude binaries only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-claude-owner-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.prefix = self.root / "brew"
        (self.prefix / "bin").mkdir(parents=True)
        for name in ("dirname", "basename", "readlink", "cat", "sed", "uname", "ps"):
            found = shutil.which(name)
            self.assertIsNotNone(found, name)
            (self.tools / name).symlink_to(found)
        supervisor = shutil.which("timeout") or shutil.which("gtimeout")
        self.assertIsNotNone(supervisor, "coreutils timeout is a declared prerequisite")
        (self.tools / "timeout").symlink_to(supervisor)
        self.script(self.tools / "brew", 'printf "%s\\n" "$FAKE_BREW_PREFIX"')
        share = self.home / ".local/share/groundwork/lib"
        share.mkdir(parents=True)
        shutil.copy(LIB, share / LIB.name)
        # The private PATH puts the native copy first, as the native installer does.
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{self.tools}",
            "FAKE_BREW_PREFIX": str(self.prefix),
            "XDG_CONFIG_HOME": str(self.root / "xdg"),
        }

    def script(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)

    def fake_claude(self, target):
        self.script(target, f'printf "%s (Claude Code)\\n" {VERSION}')

    def install_native(self):
        target = self.home / ".local/share/claude/versions" / VERSION
        self.fake_claude(target)
        (self.bin / "claude").symlink_to(target)
        return self.bin / "claude"

    def install_cask(self, cask="claude-code@latest"):
        target = self.prefix / "Caskroom" / cask / VERSION / "claude"
        self.fake_claude(target)
        (self.prefix / "bin/claude").symlink_to(target)
        return self.prefix / "bin/claude"

    def report(self, owner):
        command = ["/bin/bash", "-c", '. "$1"; gw_claude_dual_install_report "$2"', "test", str(LIB), owner]
        return subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=15)

    def test_both_copies_with_homebrew_owner_name_the_native_removal(self):
        native = self.install_native()
        managed = self.install_cask()
        result = self.report("homebrew")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"two copies are installed: native {native} (version {VERSION})", result.stdout)
        self.assertIn(f"Homebrew claude-code@latest {managed} (version {VERSION})", result.stdout)
        self.assertIn("Claude Code chosen owner: homebrew", result.stdout)
        self.assertIn("groundwork-claude-owner homebrew --yes", result.stdout)
        self.assertNotIn("brew uninstall", result.stdout)
        self.assertIn(f"Binary path at the chosen owner: {managed}\n", result.stdout)
        # Reporting never changes either installation.
        self.assertTrue(native.is_symlink())
        self.assertTrue(managed.is_symlink())

    def test_both_copies_with_native_owner_name_the_cask_removal(self):
        native = self.install_native()
        self.install_cask()
        result = self.report("native")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Claude Code chosen owner: native", result.stdout)
        self.assertIn("brew uninstall --cask claude-code@latest", result.stdout)
        self.assertNotIn("groundwork-claude-owner homebrew --yes", result.stdout)
        self.assertIn(f"Binary path at the chosen owner: {native}\n", result.stdout)

    def test_unknown_or_missing_owner_falls_back_to_homebrew(self):
        self.install_native()
        self.install_cask()
        for owner in ("", "bogus"):
            with self.subTest(owner=owner):
                result = self.report(owner)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Claude Code chosen owner: homebrew", result.stdout)

    def test_one_copy_or_an_unrecognized_brew_command_is_quiet(self):
        self.install_native()
        self.assertEqual(self.report("homebrew").stdout, "")
        self.install_cask(cask="claude-code")
        self.assertEqual(self.report("homebrew").stdout, "", "only the claude-code@latest cask counts")
        (self.bin / "claude").unlink()
        (self.prefix / "bin/claude").unlink()
        self.install_cask()
        result = self.report("native")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_doctor_warns_without_failing_and_reads_the_profile_owner(self):
        self.install_native()
        self.install_cask()
        command = ["/bin/bash", str(DOCTOR), "--ai-tools"]
        # No chezmoi on the private PATH: the profile cannot be read, so homebrew.
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("== AI tools ==", result.stdout)
        self.assertIn("Claude Code warning: two copies are installed", result.stdout)
        self.assertIn("Claude Code chosen owner: homebrew", result.stdout)
        jq = shutil.which("jq")
        self.assertIsNotNone(jq, "jq is a declared prerequisite")
        (self.tools / "jq").symlink_to(jq)
        self.script(self.tools / "chezmoi", 'printf \'%s\\n\' \'{"claude_code_owner":"native"}\'')
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Claude Code chosen owner: native", result.stdout)
        self.assertIn("brew uninstall --cask claude-code@latest", result.stdout)


class SettingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-claude-owner-setting-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "empty.toml"
        self.config.write_text("", encoding="utf-8")
        self.chezmoi = shutil.which("chezmoi")
        self.assertIsNotNone(self.chezmoi, "chezmoi is required to prove config rendering")

    def env(self):
        env = os.environ.copy()
        for name, sub in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                          ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            env[name] = str(self.root / sub)
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        return env

    def render(self, text, **data):
        effective = dict(
            name="CI", email_personal="ci@example.com", email_work="", code_dir="~/code",
            reset_existing_configs=False, password_manager="none", signingkey="",
            obsidian_vault_name="", game_dev=False, xcode=False, headless=True,
            terminal_multiplexer="tmux", key_repeat="fast", personal_apps=True, work=False,
            chezmoi=dict(os="darwin", arch="arm64", osRelease={"ID": "ubuntu"}),
        )
        effective.update(data)
        result = subprocess.run(
            [self.chezmoi, "--config", str(self.config), "--source", str(REPO),
             "--override-data", json.dumps(effective), "execute-template"],
            input=text, text=True, capture_output=True, env=self.env(), timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def init(self, extra):
        incoming = self.root / "incoming.toml"
        outgoing = self.root / "outgoing.toml"
        incoming.write_text(f'''sourceDir = "{REPO / "home"}"
[data]
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
    profile_preset = "personal-current"
    terminal_multiplexer = "tmux"
    reset_existing_configs = false
    signingkey = ""
    work = false
    xcode = false
{extra}''', encoding="utf-8")
        (self.root / "chezmoi-cache").mkdir(exist_ok=True)
        result = subprocess.run(
            [self.chezmoi, "--config", str(incoming), "--source", str(REPO / "home"),
             "--persistent-state", str(self.root / "state.boltdb"),
             "--cache", str(self.root / "chezmoi-cache"), "init", "--config-path", str(outgoing)],
            text=True, capture_output=True, env=self.env(), cwd=REPO,
            stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return outgoing.read_text(encoding="utf-8")

    def test_default_is_homebrew_and_a_stored_native_survives_init(self):
        self.assertIn('claude_code_owner = "homebrew"', self.init(""))
        self.assertIn('claude_code_owner = "native"', self.init('    claude_code_owner = "native"\n'))
        coerced = self.init('    claude_code_owner = "mise"\n')
        self.assertIn('claude_code_owner = "homebrew"', coerced)
        template = TEMPLATE.read_text(encoding="utf-8")
        # groundwork-configure owns the change; bootstrap never asks.
        self.assertNotRegex(template, r'prompt\w*Once \. "claude_code_owner"')

    def test_native_owner_leaves_the_cask_out_of_the_brewfile(self):
        brewfile = (REPO / BREWFILE).read_text(encoding="utf-8")
        cask = re.compile(r'^cask "claude-code@latest"$', re.M)
        self.assertRegex(self.render(brewfile), cask)
        self.assertRegex(self.render(brewfile, claude_code_owner="homebrew"), cask)
        native = self.render(brewfile, claude_code_owner="native")
        self.assertNotRegex(native, cask)
        self.assertRegex(native, re.compile(r'^cask "codex"$', re.M))

    def test_update_all_reports_two_copies_with_the_rendered_owner(self):
        source = UPDATE_RUN.read_text(encoding="utf-8")
        line = next(item for item in source.splitlines() if "gw_claude_dual_install_report" in item)
        self.assertEqual(self.render(line).strip(), 'gw_claude_dual_install_report "homebrew"')
        self.assertEqual(self.render(line, claude_code_owner="native").strip(),
                         'gw_claude_dual_install_report "native"')
        report = source.index("  gw_claude_ownership_report\n  gw_claude_dual_install_report")
        self.assertGreater(report, 0)

    def test_configure_offers_homebrew_and_native(self):
        text = CONFIGURE.read_text(encoding="utf-8")
        arrays = {name: re.search(rf"^{name}=\((.*)\)\s*$", text, re.M).group(1)
                  for name in ("fields_key", "fields_label", "fields_kind", "fields_clear")}
        keys = arrays["fields_key"].split()
        labels = re.findall(r'"([^"]*)"', arrays["fields_label"])
        kinds = arrays["fields_kind"].split()
        clears = arrays["fields_clear"].split()
        self.assertEqual({len(keys), len(labels), len(kinds), len(clears)}, {len(keys)})
        index = keys.index("claude_code_owner")
        self.assertEqual((labels[index], kinds[index], clears[index]),
                         ("Claude Code owner", "claudeowner", "no"))
        self.assertIn("choice_values=(homebrew native)", text)
        self.assertIn('data.setdefault("claude_code_owner", "homebrew")', text)


if __name__ == "__main__":
    unittest.main()
