#!/usr/bin/env python3
"""Opt-in Apple Silicon Ollama stays off, installs no weights, and stays off other machines."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIGURE = REPO / "home/dot_local/bin/executable_groundwork-configure"
TEMPLATE = REPO / "home/.chezmoi.toml.tmpl"


class LocalInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-local-inference-")
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
        result = subprocess.run(
            command,
            input=(REPO / path).read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_default_apple_silicon_keeps_the_menu_bar_app_and_skips_the_formula(self):
        brewfile = self.render("home/dot_config/homebrew/Brewfile.tmpl")
        optional = self.render("home/dot_config/homebrew/Brewfile.optional.tmpl")
        self.assertIn('cask "ollama-app"', brewfile)
        self.assertNotIn('brew "ollama"', brewfile)
        self.assertNotIn('brew "ollama"', optional)
        self.assertNotIn("ollama pull", brewfile + optional)

    def test_opt_in_installs_the_formula_only_on_apple_silicon(self):
        cases = (
            ("darwin", "arm64", False, True, False),
            ("darwin", "arm64", True, True, False),
            ("darwin", "amd64", False, False, True),
            ("linux", "arm64", False, False, False),
            ("linux", "amd64", True, False, False),
        )
        for os_name, arch, headless, formula, menu_app in cases:
            with self.subTest(os=os_name, arch=arch, headless=headless):
                data = dict(
                    local_inference=True,
                    headless=headless,
                    chezmoi=dict(os=os_name, arch=arch, osRelease={"ID": "ubuntu"}),
                )
                brewfile = self.render("home/dot_config/homebrew/Brewfile.tmpl", **data)
                optional = self.render("home/dot_config/homebrew/Brewfile.optional.tmpl", **data)
                if formula:
                    self.assertIn('brew "ollama"\n', optional)
                else:
                    self.assertNotIn('brew "ollama"', optional)
                self.assertNotIn('brew "ollama"', brewfile)
                if menu_app:
                    self.assertIn('cask "ollama-app"', brewfile)
                else:
                    self.assertNotIn('cask "ollama-app"', brewfile)
                self.assertNotIn("ollama pull", optional)
                self.assertNotIn("ollama run", optional)

    def test_opt_in_does_not_require_personal_apps_or_a_desktop(self):
        optional = self.render(
            "home/dot_config/homebrew/Brewfile.optional.tmpl",
            local_inference=True,
            personal_apps=False,
            work=True,
            headless=True,
        )
        self.assertIn('brew "ollama"\n', optional)
        self.assertNotIn("cliamp", optional)
        self.assertNotIn('cask "', optional)

    def test_a_non_bool_does_not_enable_install(self):
        optional = self.render(
            "home/dot_config/homebrew/Brewfile.optional.tmpl",
            local_inference="yes",
        )
        self.assertNotIn('brew "ollama"', optional)

    def test_installer_warns_about_the_menu_bar_conflict_and_never_pulls(self):
        script = self.render("home/run_onchange_after_10-brew-bundle.sh.tmpl", local_inference=True)
        self.assertIn('brew "ollama"', script)
        self.assertIn("brew uninstall --cask ollama-app", script)
        self.assertIn("leaves models in ~/.ollama", script)
        self.assertNotIn("ollama pull", script)
        self.assertNotIn("ollama run", script)
        self.assertNotIn("ollama serve", script)
        syntax = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_home_sources_do_not_name_a_model_download(self):
        banned = ("ollama pull", "ollama run", "ollama serve", "mlx_lm", "lm-studio")
        for path in (REPO / "home").rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {"", ".tmpl", ".sh"} and "executable_" not in path.name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for phrase in banned:
                self.assertNotIn(phrase, text, f"{path} contains {phrase}")

    def test_configure_registers_the_flag_without_a_bootstrap_prompt(self):
        text = CONFIGURE.read_text(encoding="utf-8")
        keys = _array(text, "fields_key")
        kinds = _array(text, "fields_kind")
        clears = _array(text, "fields_clear")
        labels = _quoted(text, "fields_label")
        self.assertEqual(len(keys), len(kinds))
        self.assertEqual(len(keys), len(clears))
        self.assertEqual(len(keys), len(labels))
        index = keys.index("local_inference")
        self.assertEqual(keys[index - 1], "xcode")
        self.assertEqual(kinds[index], "bool")
        self.assertEqual(clears[index], "no")
        self.assertEqual(labels[index], "Local inference")
        self.assertIn("does not download model weights", text)
        self.assertIn("or change Claude, Codex, ChatGPT", text)
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn('promptBoolOnce . "local_inference"', template)
        self.assertIn('kindIs "bool" .local_inference', template)
        self.assertIn("local_inference = {{ $localInference }}", template)

    def test_stored_bool_survives_init_and_a_missing_key_stays_off(self):
        chezmoi = __import__("shutil").which("chezmoi")
        if chezmoi is None:
            self.fail("chezmoi is required to prove config rendering")
        absent = _init(chezmoi, self.root, _fixture())
        self.assertIn("local_inference = false", absent)
        kept = _init(chezmoi, self.root, _fixture("    local_inference = true\n"))
        self.assertIn("local_inference = true", kept)
        coerced = _init(chezmoi, self.root, _fixture('    local_inference = "yes"\n'))
        self.assertIn("local_inference = false", coerced)
        self.assertNotIn('local_inference = "yes"', coerced)

    def test_profile_reports_when_a_stored_flag_cannot_apply(self):
        apple = self.render("home/dot_local/bin/executable_groundwork-profile.tmpl", local_inference=True)
        intel = self.render(
            "home/dot_local/bin/executable_groundwork-profile.tmpl",
            local_inference=True,
            chezmoi=dict(os="darwin", arch="amd64", osRelease={}),
        )
        self.assertIn('local_inference=true', apple)
        self.assertIn('local_inference_applies=true', apple)
        self.assertIn("inactive (stored enabled; Apple Silicon only)", intel)
        self.assertIn('local_inference_applies=false', intel)


def _array(text, name):
    import re

    match = re.search(rf"^{name}=\((.*)\)\s*$", text, re.M)
    if match is None:
        raise AssertionError(f"missing {name}")
    return match.group(1).split()


def _quoted(text, name):
    import re

    match = re.search(rf"^{name}=\((.*)\)\s*$", text, re.M)
    if match is None:
        raise AssertionError(f"missing {name}")
    return re.findall(r'"([^"]*)"', match.group(1))


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


def _init(chezmoi, root, text):
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
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return outgoing.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
