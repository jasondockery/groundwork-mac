#!/usr/bin/env python3
"""update-all warns when the chezmoi source checkout is not main, is behind, or is dirty.

The check is report-only. These tests run it against fixture repositories and
stubbed update-all entry points. They do not fetch GitHub or apply chezmoi.
"""

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "home/dot_local/bin/executable_groundwork-apply-source-warning"
LAUNCHER = REPO / "home/dot_local/bin/executable_update-all"
RUNNER = REPO / "home/dot_local/bin/executable_groundwork-update-run.tmpl"
PREFLIGHT = REPO / "home/dot_local/bin/executable_groundwork-source-preflight"
LOCK = REPO / "home/dot_local/lib/groundwork/update-lock.sh"
MAINTENANCE_RUNNER = REPO / "home/dot_local/share/groundwork/lib/maintenance-runner.sh"

GIT_WRAPPER = """#!/bin/bash
set -eu
printf '%s\\n' "$*" >>"$GIT_GUARD_LOG"
for arg in "$@"; do
  case "$arg" in
    checkout|switch|stash|reset|clean|commit|merge|rebase|pull|push|restore)
      echo "forbidden git $arg" >>"$GIT_GUARD_LOG"
      exit 97
      ;;
  esac
done
if [[ "${GIT_FETCH_FAIL:-0}" == 1 ]]; then
  for arg in "$@"; do
    if [[ "$arg" == fetch ]]; then
      echo "fetch-failed" >>"$GIT_GUARD_LOG"
      exit 1
    fi
  done
fi
exec /usr/bin/git "$@"
"""

CHEZMOI_STUB = """#!/bin/bash
printf '%s\\n' "$*" >>"$CHEZMOI_LOG"
case "${1:-}" in
  source-path) printf '%s\\n' "$CHEZMOI_SOURCE" ;;
  apply)
    printf 'CHEZMOI %s\\n' "$1"
    if [[ -n "${STUB_RUNNER:-}" ]]; then
      cp "$STUB_RUNNER" "$HOME/.local/bin/groundwork-update-run"
      chmod +x "$HOME/.local/bin/groundwork-update-run"
    fi
    ;;
  *) printf 'CHEZMOI %s\\n' "$1" ;;
esac
exit 0
"""

PLATFORM_STUB = """#!/bin/bash
printf 'linux\\n'
"""

STUB_RUNNER = """#!/bin/bash
printf 'RUNNER\\n'
exec "$HOME/.local/bin/groundwork-apply-source-warning" --summary
"""


def _run(cmd, env, cwd=None):
    result = subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )
    return result


def _git(repo, env, *args):
    result = _run(["/usr/bin/git", "-C", str(repo), *args], env)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gw-apply-source-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self._install(self.tools / "git", GIT_WRAPPER)
        timeout = shutil.which("gtimeout") or shutil.which("timeout")
        self.assertIsNotNone(timeout, "a bounded timeout command is required")
        (self.tools / "timeout").symlink_to(timeout)
        if shutil.which("gtimeout"):
            (self.tools / "gtimeout").symlink_to(timeout)
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_GUARD_LOG": str(self.root / "git-guard.log"),
            "PATH": f"{self.tools}:{self.bin}:/usr/bin:/bin",
            "GROUNDWORK_QUIET_APPLY_SOURCE": "",
        })
        self.env.pop("GROUNDWORK_QUIET_APPLY_SOURCE", None)
        for key in list(self.env):
            if key.startswith("XDG_"):
                self.env.pop(key)

    def _install(self, path, text):
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
        path.chmod(0o755)

    def _git_env(self):
        env = self.env.copy()
        env["PATH"] = "/usr/bin:/bin"
        return env

    def _commit(self, repo, message, *, days_old=0):
        env = self._git_env()
        if days_old:
            stamp = str(int(time.time()) - (days_old * 86400 + 7200))
            env["GIT_AUTHOR_DATE"] = stamp
            env["GIT_COMMITTER_DATE"] = stamp
        _git(repo, env, "commit", "-q", "--allow-empty", "-m", message)

    def _repo(self, *, branch="main", days_old=0, extra_on_origin=0, dirty=0, tracked_feature=False):
        env = self._git_env()
        seed = self.root / "seed"
        clone = self.root / "clone"
        _run(["/usr/bin/git", "init", "-q", "-b", "main", str(seed)], env)
        self._commit(seed, "init", days_old=days_old)
        _run(["/usr/bin/git", "clone", "-q", str(seed), str(clone)], env)
        if branch != "main":
            _git(clone, env, "checkout", "-q", "-b", branch)
            if tracked_feature:
                _git(clone, env, "branch", "--set-upstream-to=origin/main", branch)
        for index in range(extra_on_origin):
            self._commit(seed, f"later {index}")
        for index in range(dirty):
            (clone / f"uncommitted-{index}.txt").write_text("local\n", encoding="utf-8")
        return clone

    def _helper(self, repo, *args, fetch_fail=False):
        self.assertTrue(HELPER.is_file(), "apply-source warning command is missing")
        self._install(self.bin / "chezmoi", CHEZMOI_STUB)
        env = self.env.copy()
        env["CHEZMOI_SOURCE"] = str(repo)
        env["CHEZMOI_LOG"] = str(self.root / "chezmoi.log")
        if fetch_fail:
            env["GIT_FETCH_FAIL"] = "1"
        before = _git(repo, self._git_env(), "status", "--porcelain")
        head = _git(repo, self._git_env(), "rev-parse", "HEAD").stdout.strip()
        branch = _git(repo, self._git_env(), "branch", "--show-current").stdout.strip()
        stash = _git(repo, self._git_env(), "stash", "list").stdout
        result = _run(["bash", str(HELPER), *args], env)
        self.assertEqual(before.stdout, _git(repo, self._git_env(), "status", "--porcelain").stdout)
        self.assertEqual(head, _git(repo, self._git_env(), "rev-parse", "HEAD").stdout.strip())
        self.assertEqual(branch, _git(repo, self._git_env(), "branch", "--show-current").stdout.strip())
        self.assertEqual(stash, _git(repo, self._git_env(), "stash", "list").stdout)
        guard = Path(env["GIT_GUARD_LOG"]).read_text(encoding="utf-8") if Path(env["GIT_GUARD_LOG"]).exists() else ""
        self.assertNotIn("forbidden git", guard)
        result.guard = guard
        return result

    def test_main_and_current_is_silent(self):
        repo = self._repo()
        result = self._helper(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self._helper(repo, "--summary").stdout, "")

    def test_feature_branch_warns_and_stays_there(self):
        repo = self._repo(branch="fix/spotlight-fixture-firmlink", days_old=12)
        result = self._helper(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("from branch fix/spotlight-fixture-firmlink", result.stdout)
        self.assertIn("12 days old", result.stdout)
        self.assertIn("0 commits behind origin/main", result.stdout)
        self.assertIn("0 uncommitted files", result.stdout)
        quoted = "'" + os.path.realpath(repo).replace("'", "'\\''") + "'"
        self.assertIn(
            f"git -C {quoted} switch main && git -C {quoted} pull",
            result.stdout,
        )
        self.assertNotIn(f"git -C {quoted} switch main && git pull", result.stdout)
        self.assertIn("did not switch, stash, or reset", result.stdout)

    def test_behind_origin_main_names_the_count(self):
        repo = self._repo(extra_on_origin=40)
        result = self._helper(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("from branch main", result.stdout)
        self.assertIn("40 commits behind origin/main", result.stdout)

    def test_dirty_tree_names_the_file_count(self):
        repo = self._repo(dirty=2)
        result = self._helper(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 uncommitted files", result.stdout)

    def test_offline_fetch_says_it_could_not_check_and_exits_zero(self):
        repo = self._repo()
        result = self._helper(repo, fetch_fail=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not check", result.stdout)
        self.assertIn("fetch-failed", result.guard)

    def test_summary_repeats_the_warning(self):
        repo = self._repo(branch="fix/spotlight-fixture-firmlink", days_old=12, dirty=2)
        result = self._helper(repo, "--summary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\nApply source\n", result.stdout)
        self.assertIn("from branch fix/spotlight-fixture-firmlink", result.stdout)
        self.assertIn("2 uncommitted files", result.stdout)

    def test_quiet_environment_skips_the_fetch(self):
        repo = self._repo(branch="fix/spotlight-fixture-firmlink")
        self.env["GROUNDWORK_QUIET_APPLY_SOURCE"] = "1"
        result = self._helper(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("fetch", result.guard)

    def test_help_and_unknown_arguments_do_not_fetch(self):
        repo = self._repo()
        help_result = self._helper(repo, "--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("GROUNDWORK_QUIET_APPLY_SOURCE=1", help_result.stdout)
        self.assertNotIn("fetch", help_result.guard)
        unknown = self._helper(repo, "--switch-main")
        self.assertEqual(unknown.returncode, 64, unknown.stderr)
        self.assertNotIn("fetch", unknown.guard)

    def _launcher_env(self, repo):
        self._install(self.bin / "chezmoi", CHEZMOI_STUB)
        self._install(self.bin / "groundwork-platform", PLATFORM_STUB)
        self._install(self.bin / "groundwork-update-run", STUB_RUNNER)
        self._install(self.root / "stub-runner", STUB_RUNNER)
        shutil.copy(HELPER, self.bin / "groundwork-apply-source-warning")
        (self.bin / "groundwork-apply-source-warning").chmod(0o755)
        shutil.copy(PREFLIGHT, self.bin / "groundwork-source-preflight")
        (self.bin / "groundwork-source-preflight").chmod(0o755)
        lock_dir = self.home / ".local/lib/groundwork"
        lock_dir.mkdir(parents=True)
        shutil.copy(LOCK, lock_dir / "update-lock.sh")
        env = self.env.copy()
        env["PATH"] = f"{self.tools}:{self.bin}:/usr/bin:/bin"
        env["CHEZMOI_SOURCE"] = str(repo)
        env["CHEZMOI_LOG"] = str(self.root / "chezmoi.log")
        env["STUB_RUNNER"] = str(self.root / "stub-runner")
        return env

    def test_launcher_warns_at_the_start_and_in_the_final_summary(self):
        repo = self._repo(branch="fix/spotlight-fixture-firmlink", days_old=12, tracked_feature=True)
        env = self._launcher_env(repo)
        result = _run(["bash", str(LAUNCHER)], env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        warning = result.stdout.index("from branch fix/spotlight-fixture-firmlink")
        update = result.stdout.index("CHEZMOI update")
        summary = result.stdout.index("Apply source")
        self.assertLess(warning, update)
        self.assertLess(update, summary)
        self.assertIn("12 days old", result.stdout)
        self.assertEqual(
            _git(repo, self._git_env(), "branch", "--show-current").stdout.strip(),
            "fix/spotlight-fixture-firmlink",
        )

    def test_quiet_flag_silences_one_launcher_run(self):
        repo = self._repo(branch="fix/spotlight-fixture-firmlink", tracked_feature=True)
        env = self._launcher_env(repo)
        result = _run(["bash", str(LAUNCHER), "--quiet-apply-source"], env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("CHEZMOI update", result.stdout)
        self.assertNotIn("Apply source", result.stdout)
        self.assertNotIn("applying this machine", result.stdout)
        help_result = _run(["bash", str(LAUNCHER), "--help"], env)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("CHEZMOI", help_result.stdout)
        self.assertIn("--quiet-apply-source", help_result.stdout)
        unknown = _run(["bash", str(LAUNCHER), "--stash"], env)
        self.assertEqual(unknown.returncode, 64)
        self.assertNotIn("CHEZMOI", unknown.stdout)

    def test_rendered_runner_puts_the_warning_in_its_final_summary(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            text.count('"$HOME/.local/bin/groundwork-apply-source-warning" --summary'), 3)
        chezmoi = shutil.which("chezmoi")
        self.assertIsNotNone(chezmoi)
        repo = self._repo(branch="fix/spotlight-fixture-firmlink", days_old=12, extra_on_origin=3)
        destination = self.root / "dest"
        destination.mkdir()
        empty = self.root / "empty.toml"
        empty.write_text("", encoding="utf-8")
        data = {
            "name": "CI User",
            "email_personal": "ci@example.com",
            "email_work": "",
            "code_dir": "~/code",
            "reset_existing_configs": False,
            "password_manager": "bitwarden",
            "signingkey": "",
            "obsidian_vault_name": "ci",
            "game_dev": False,
            "release_posture": "current",
            "docker_backend": "docker-desktop",
            "headless": True,
            "xcode": False,
            "beta": False,
            "chezmoi": {
                "os": "linux",
                "arch": "amd64",
                "osRelease": {"ID": "ubuntu"},
                "workingTree": str(REPO),
            },
        }
        rendered_result = subprocess.run(
            [
                chezmoi, "--config", str(empty), "--source", str(REPO),
                "--destination", str(destination), "--override-data", json.dumps(data),
                "execute-template",
            ],
            input=RUNNER.read_text(encoding="utf-8"),
            text=True, capture_output=True, check=False, env=self._git_env(), cwd=REPO,
        )
        self.assertEqual(rendered_result.returncode, 0, rendered_result.stderr)
        rendered_lines = []
        for line in rendered_result.stdout.splitlines():
            if "checkout-core.sh" in line:
                rendered_lines.append(":")
            elif line.startswith("export PATH=") and "homebrew" in line:
                rendered_lines.append('export PATH="$HOME/.local/bin:$GROUNDWORK_TEST_PATH"')
            else:
                rendered_lines.append(line)
        rendered = "\n".join(rendered_lines) + "\n"
        self.assertNotIn("/opt/homebrew/bin", rendered)
        self.assertNotIn("checkout-core.sh", rendered)
        script = self.root / "runner"
        script.write_text(rendered, encoding="utf-8")
        script.chmod(0o755)
        self._install(self.bin / "chezmoi", CHEZMOI_STUB)
        self._install(self.bin / "groundwork-platform", PLATFORM_STUB)
        shutil.copy(HELPER, self.bin / "groundwork-apply-source-warning")
        (self.bin / "groundwork-apply-source-warning").chmod(0o755)
        lib = self.home / ".local/lib/groundwork"
        share = self.home / ".local/share/groundwork/lib"
        lib.mkdir(parents=True)
        share.mkdir(parents=True)
        shutil.copy(LOCK, lib / "update-lock.sh")
        shutil.copy(MAINTENANCE_RUNNER, share / "maintenance-runner.sh")
        env = self.env.copy()
        env["CHEZMOI_SOURCE"] = str(repo)
        env["CHEZMOI_LOG"] = str(self.root / "chezmoi.log")
        env["GROUNDWORK_TEST_PATH"] = f"{self.tools}:/usr/bin:/bin"
        env["PATH"] = f"{self.bin}:{self.tools}:/usr/bin:/bin"
        result = _run(["bash", str(script), "--skip-maintenance"], env)
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        summary = result.stdout.index("Apply source")
        complete = result.stdout.index("Groundwork update complete")
        finished = result.stdout.index("\nResult\n")
        self.assertLess(complete, summary)
        self.assertLess(summary, finished)
        self.assertIn("from branch fix/spotlight-fixture-firmlink", result.stdout)
        self.assertIn("3 commits behind origin/main", result.stdout)
        quoted = "'" + os.path.realpath(repo).replace("'", "'\\''") + "'"
        self.assertIn(f"git -C {quoted} switch main && git -C {quoted} pull", result.stdout)
        self.assertEqual(
            _git(repo, self._git_env(), "branch", "--show-current").stdout.strip(),
            "fix/spotlight-fixture-firmlink",
        )


if __name__ == "__main__":
    unittest.main()
