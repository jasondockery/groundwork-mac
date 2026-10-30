#!/usr/bin/env python3
"""git-filter-repo is opt-in, per-user, proven by its help text, and never rewrites history."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = "home/run_after_23-git-filter-repo.sh.tmpl"
TEMPLATE = REPO / "home/.chezmoi.toml.tmpl"
CONFIGURE = REPO / "home/dot_local/bin/executable_groundwork-configure"

# A fake git answers only `git filter-repo -h`, from a state file, and records
# every other invocation. A fake pipx "installs" by writing that state file.
FAKE_GIT = """#!/usr/bin/env bash
echo "git $*" >> "$FAKE_LOG"
if [[ "$1" == "filter-repo" && "$2" == "-h" ]]; then
  [[ -f "$FAKE_STATE" ]] && cat "$FAKE_STATE" && exit 0
  echo "git: 'filter-repo' is not a git command." >&2
  exit 1
fi
exit 0
"""
FAKE_PIPX = """#!/usr/bin/env bash
echo "pipx $*" >> "$FAKE_LOG"
case "$1" in
  list) [[ -f "$FAKE_STATE" ]] && echo "git-filter-repo 2.47.0" ; exit 0 ;;
  install|upgrade) printf '%s\\n' "$FAKE_HELP" > "$FAKE_STATE" ;;
esac
exit 0
"""


class GitFilterRepoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-git-filter-repo-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "empty.toml"
        self.config.write_text("", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # Private PATH: a host pipx or git-filter-repo must never be reached.
        for tool in ("bash", "grep", "cat", "env"):
            found = shutil.which(tool)
            self.assertTrue(found, tool)
            (self.bin / tool).symlink_to(found)
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "log"
        self.state = self.root / "state"

    def render(self, path, **data):
        effective = dict(
            name="CI", email_personal="ci@example.com", email_work="w@example.com",
            code_dir="~/code", reset_existing_configs=False, password_manager="none",
            signingkey="", obsidian_vault_name="", game_dev=False, xcode=False,
            headless=False, terminal_multiplexer="herdr", key_repeat="fast",
            personal_apps=True, work=False,
            chezmoi=dict(os="darwin", arch="arm64", osRelease={"ID": "ubuntu"}),
        )
        effective.update(data)
        result = subprocess.run(
            ["chezmoi", "--config", str(self.config), "--source", str(REPO),
             "--override-data", json.dumps(effective), "execute-template"],
            input=(REPO / path).read_text(encoding="utf-8"),
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def install_fake(self, name, body):
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_script(self, text, with_pipx=True, help_text="usage: git filter-repo --sensitive-data-removal", with_gtimeout=True, brew_dirs=""):
        script = self.root / "run.sh"
        script.write_text(text, encoding="utf-8")
        self.install_fake("git", FAKE_GIT)
        if with_gtimeout:
            self.install_fake("gtimeout", 'echo "gtimeout $*" >> "$FAKE_LOG"\nshift 2\nexec "$@"\n'.join(["#!/usr/bin/env bash\n", ""]))
        if with_pipx:
            self.install_fake("pipx", FAKE_PIPX)
        env = {
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "GROUNDWORK_TEST_BREW_BIN_DIRS": brew_dirs,
            "FAKE_LOG": str(self.log),
            "FAKE_STATE": str(self.state),
            "FAKE_HELP": help_text,
        }
        result = subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True, timeout=15)
        return result

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def assertDisabled(self, text):
        # A shebang and set line keep shellcheck and chezmoi happy; no install code renders.
        self.assertEqual(text.strip().splitlines(), ["#!/usr/bin/env bash", "set -euo pipefail"])
        self.assertNotIn("pipx", text)

    def test_default_run_renders_nothing_and_installs_nothing(self):
        for data in ({}, {"git_filter_repo": False}, {"git_filter_repo": "yes"}):
            with self.subTest(data=data):
                self.assertDisabled(self.render(SCRIPT, **data))
        linux = dict(os="linux", arch="amd64", osRelease={"ID": "ubuntu"})
        self.assertDisabled(self.render(SCRIPT, git_filter_repo=True, chezmoi=linux))
        for brewfile in ("Brewfile.optional.tmpl", "Brewfile.tmpl"):
            text = self.render(f"home/dot_config/homebrew/{brewfile}")
            self.assertNotIn("pipx", text.replace("# pipx", ""))
            self.assertNotIn("git-filter-repo", text.replace("# ", ""))

    def test_opt_in_installs_per_user_with_pipx_and_checks_the_help_text(self):
        text = self.render(SCRIPT, git_filter_repo=True)
        self.assertIn("pipx install git-filter-repo", text)
        for forbidden in ("sudo", "brew install", "--global", "filter-repo --", "filter-branch", "push", "--force"):
            self.assertNotIn(forbidden, text)
        result = self.run_script(text, help_text="usage: git filter-repo --sensitive-data-removal")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls().count("pipx install git-filter-repo"), 1)
        self.assertIn("gtimeout --kill-after=5s 300 pipx install git-filter-repo", self.calls())
        self.assertIn("git filter-repo -h", self.calls())
        self.assertIn("--sensitive-data-removal", self.state.read_text())
        self.assertIn("installed for this user", result.stdout)

    def test_opt_in_is_idempotent_once_the_proof_passes(self):
        text = self.render(SCRIPT, git_filter_repo=True)
        self.run_script(text)
        self.log.unlink()
        result = self.run_script(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("pipx")])

    def test_old_build_without_the_flag_fails_the_proof_without_failing_apply(self):
        text = self.render(SCRIPT, git_filter_repo=True)
        result = self.run_script(text, help_text="usage: git filter-repo (older build)")
        self.assertEqual(result.returncode, 0)
        self.assertIn("does not list --sensitive-data-removal", result.stderr)
        self.assertNotIn("installed for this user", result.stdout)

    def test_missing_pipx_asks_for_a_retry_and_installs_nothing(self):
        text = self.render(SCRIPT, git_filter_repo=True)
        result = self.run_script(text, with_pipx=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("pipx is not installed", result.stderr)
        self.assertFalse(self.state.exists())

    def test_missing_gtimeout_warns_and_calls_no_pipx(self):
        text = self.render(SCRIPT, git_filter_repo=True)
        result = self.run_script(text, with_gtimeout=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GNU timeout is required", result.stderr)
        self.assertFalse([c for c in self.calls() if "pipx" in c])
        self.assertFalse(self.state.exists())

    def test_a_pipx_in_a_brew_dir_is_unreachable_unless_the_override_names_it(self):
        text = self.render(SCRIPT, git_filter_repo=True)
        brew = self.root / "brew-bin"
        brew.mkdir()
        fake = brew / "pipx"
        fake.write_text(FAKE_PIPX, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        # Sealed: the override is empty, so the "brew" pipx never runs.
        result = self.run_script(text, with_pipx=False, brew_dirs="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pipx is not installed", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("pipx")])
        self.assertFalse(self.state.exists())
        # Control: naming that dir makes the same script reach it, so the seal is the override.
        self.log.unlink(missing_ok=True)
        result = self.run_script(text, with_pipx=False, brew_dirs=str(brew))
        self.assertIn("pipx install git-filter-repo", self.calls())
        self.assertTrue(self.state.exists())

    def test_no_history_rewrite_command_is_ever_run(self):
        self.run_script(self.render(SCRIPT, git_filter_repo=True))
        for call in self.calls():
            self.assertTrue(call == "git filter-repo -h" or call.startswith(("pipx", "gtimeout")), call)

    def test_pipx_comes_from_the_optional_brewfile_only_when_opted_in(self):
        on = self.render("home/dot_config/homebrew/Brewfile.optional.tmpl", git_filter_repo=True)
        self.assertIn('brew "pipx"', on)
        self.assertNotIn('brew "git-filter-repo"', on)
        off = self.render("home/dot_config/homebrew/Brewfile.optional.tmpl", git_filter_repo=False)
        self.assertNotIn('brew "pipx"', off)

    def test_bootstrap_never_asks_and_a_stored_bool_is_preserved(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn('promptBoolOnce . "git_filter_repo"', template)
        self.assertIn('kindIs "bool" .git_filter_repo', template)
        self.assertIn("git_filter_repo = {{ $gitFilterRepo }}", template)
        configure = CONFIGURE.read_text(encoding="utf-8")
        self.assertIn("git_filter_repo", configure)
        self.assertIn("pipx uninstall git-filter-repo", configure)


if __name__ == "__main__":
    unittest.main()
