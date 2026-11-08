#!/usr/bin/env python3
"""Report-only PATH shadow check for Groundwork-managed CLIs.

A binary earlier on PATH than the managed copy must show up in groundwork-doctor
and in the update-all summary. The check never deletes the other copy.
"""

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "home/dot_local/bin/executable_groundwork-path-shadow"
DOCTOR = REPO / "home/dot_local/bin/executable_groundwork-doctor"
RUNNER = REPO / "home/dot_local/bin/executable_groundwork-update-run.tmpl"
LIB = REPO / "home/dot_local/share/groundwork/lib/coding-cli-ownership.sh"
LOCK = REPO / "home/dot_local/lib/groundwork/update-lock.sh"
MAINTENANCE = REPO / "home/dot_local/share/groundwork/lib/maintenance-runner.sh"


def _script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + textwrap.dedent(body).lstrip("\n") + "\n", encoding="utf-8")
    path.chmod(0o755)


class PathShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gw-path-shadow-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.local_bin = self.home / ".local/bin"
        self.brew = self.root / "brew/bin"
        self.grok_real = self.home / ".grok/bin"
        self.mise_bin = self.root / "mise/bin"
        self.t3_bin = self.root / "t3/bin"
        for path in (self.local_bin, self.brew, self.grok_real, self.mise_bin, self.t3_bin):
            path.mkdir(parents=True)
        lib_dir = self.home / ".local/share/groundwork/lib"
        lib_dir.mkdir(parents=True)
        shutil.copy(LIB, lib_dir / "coding-cli-ownership.sh")
        timeout = shutil.which("timeout") or shutil.which("gtimeout")
        self.assertIsNotNone(timeout, "a bounded timeout command is required")
        self.tools = self.root / "tools"
        self.tools.mkdir()
        (self.tools / "timeout").symlink_to(timeout)
        if shutil.which("gtimeout"):
            (self.tools / "gtimeout").symlink_to(timeout)
        self.mise_cmd = self.root / "mise-cmd"
        self.mise_cmd.mkdir()
        _script(self.mise_cmd / "mise", '''
            if [[ "${1:-}" == which && "${2:-}" == node ]]; then
              printf '%s\n' "$MISE_NODE"
              exit 0
            fi
            exit 1
        ''')
        (self.home / ".zshrc").write_text(
            'export PATH="$HOME/.local/bin:$PATH"\n', encoding="utf-8")
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "PATH": f"{self.local_bin}:{self.mise_cmd}:{self.tools}:/usr/bin:/bin",
            "GROUNDWORK_BREW_PREFIX": str(self.root / "brew"),
            "T3CODE_INSTALL_BIN_DIR": str(self.t3_bin),
            "MISE_NODE": str(self.mise_bin / "node"),
            "TZ": "UTC",
        })
        for key in list(self.env):
            if key.startswith("XDG_"):
                self.env.pop(key)
        self._install_helper()

    def _install_helper(self):
        self.assertTrue(HELPER.is_file(), "path-shadow command is missing")
        shutil.copy(HELPER, self.local_bin / "groundwork-path-shadow")
        (self.local_bin / "groundwork-path-shadow").chmod(0o755)

    def _version(self, path, version):
        _script(path, f'printf "%s\\n" "{version}"')

    def _run(self, *args, env=None):
        return subprocess.run(
            ["bash", str(self.local_bin / "groundwork-path-shadow"), *args],
            env=env or self.env, text=True, capture_output=True, check=False,
        )

    def test_help_and_unknown_flag_change_nothing(self):
        before = sorted(p.relative_to(self.home) for p in self.home.rglob("*"))
        help_result = self._run("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("never deletes", help_result.stdout)
        unknown = self._run("--delete")
        self.assertEqual(unknown.returncode, 64, unknown.stdout)
        self.assertEqual(before, sorted(p.relative_to(self.home) for p in self.home.rglob("*")))

    def test_grok_shadow_names_paths_versions_shell_file_and_fix(self):
        self._version(self.grok_real / "grok", "1.0.62")
        (self.local_bin / "grok").symlink_to(self.grok_real / "grok")
        self._version(self.brew / "grok", "1.0.77")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout
        self.assertIn("grok", text)
        self.assertIn(str(self.local_bin / "grok"), text)
        self.assertIn(str(self.grok_real / "grok"), text)
        self.assertIn("1.0.62", text)
        self.assertIn(str(self.brew / "grok"), text)
        self.assertIn("1.0.77", text)
        self.assertIn(str(self.home / ".zshrc"), text)
        self.assertIn(f"export PATH='{self.root / 'brew' / 'bin'}':\"$PATH\"", text)
        self.assertIn("did not remove", text)
        self.assertFalse(any(self.home.rglob("*.deleted")))

    def test_managed_grok_wins_with_no_warning(self):
        self._version(self.brew / "grok", "1.0.77")
        env = self.env.copy()
        env["PATH"] = f"{self.brew}:{self.tools}:/usr/bin:/bin"
        result = self._run(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("grok is shadowed", result.stdout)
        self.assertNotIn("Warning:", result.stdout)
        self.assertIn("no PATH shadow", result.stdout)

    def test_managed_copy_missing_is_reported(self):
        self._version(self.local_bin / "grok", "1.0.62")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("missing", result.stdout)
        self.assertIn(str(self.brew / "grok"), result.stdout)
        self.assertIn("1.0.62", result.stdout)
        self.assertTrue((self.local_bin / "grok").exists())

    def test_managed_copy_not_on_path_is_reported(self):
        self._version(self.brew / "codex", "1.2.3")
        env = self.env.copy()
        env["PATH"] = f"{self.tools}:/usr/bin:/bin"
        result = self._run(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("codex", result.stdout)
        self.assertIn("not on PATH", result.stdout)
        self.assertIn(str(self.brew / "codex"), result.stdout)
        self.assertIn("1.2.3", result.stdout)

    def test_each_managed_cli_can_be_shadowed(self):
        self._version(self.mise_bin / "node", "25.1.0")
        self._version(self.mise_bin / "pnpm", "10.1.0")
        cases = {
            "codex": self.brew / "codex",
            "claude": self.brew / "claude",
            "opencode": self.brew / "opencode",
            "t3": self.t3_bin / "t3",
            "node": self.mise_bin / "node",
            "pnpm": self.mise_bin / "pnpm",
        }
        for name, managed in cases.items():
            self._version(managed, "9.9.9")
            self._version(self.local_bin / name, "1.0.0")
        (self.home / ".opencode.json").write_text("{}\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, managed in cases.items():
            self.assertIn(name, result.stdout, result.stdout)
            self.assertIn(str(managed), result.stdout, name)
        self.assertIn("~/.opencode.json", result.stdout)
        self.assertIn("~/.config/opencode/", result.stdout)

    def test_apostrophe_in_the_managed_directory_is_a_shell_command(self):
        brew = self.root / "O'Brien" / "brew" / "bin"
        brew.mkdir(parents=True)
        self._version(brew / "grok", "1.0.77")
        self._version(self.local_bin / "grok", "1.0.62")
        env = self.env.copy()
        env["GROUNDWORK_BREW_PREFIX"] = str(brew.parent)
        result = self._run(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        command = result.stdout.rsplit("To prefer the managed copy in this shell: ", 1)[-1].strip()
        quoted = "'" + str(brew).replace("'", "'\\''") + "'"
        self.assertEqual(command, f'export PATH={quoted}:"$PATH"')
        probe = self.root / "probe.sh"
        probe.write_text(command + "\n", encoding="utf-8")
        syntax = subprocess.run(["bash", "-n", str(probe)], text=True, capture_output=True, check=False)
        self.assertEqual(syntax.returncode, 0, syntax.stderr + command)

    def test_native_claude_owner_is_the_local_copy(self):
        self._version(self.local_bin / "claude", "2.0.0")
        self._version(self.brew / "claude", "1.0.0")
        env = self.env.copy()
        env["PATH"] = f"{self.brew}:{self.tools}:/usr/bin:/bin"
        env["GROUNDWORK_CLAUDE_CODE_OWNER"] = "native"
        result = self._run(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.local_bin / "claude"), result.stdout)
        self.assertIn("2.0.0", result.stdout)
        self.assertIn("is shadowed", result.stdout)

    def test_summary_is_quiet_when_the_managed_copy_wins(self):
        self._version(self.brew / "grok", "1.0.77")
        env = self.env.copy()
        env["PATH"] = f"{self.brew}:{self.tools}:/usr/bin:/bin"
        result = self._run("--summary", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_doctor_section_reports_the_shadow(self):
        self._version(self.local_bin / "grok", "1.0.62")
        self._version(self.brew / "grok", "1.0.77")
        result = subprocess.run(
            ["bash", str(DOCTOR), "--path-shadow"],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PATH shadows", result.stdout)
        self.assertIn("1.0.62", result.stdout)
        self.assertIn("1.0.77", result.stdout)
        help_result = subprocess.run(
            ["bash", str(DOCTOR), "--help"],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--path-shadow", help_result.stdout)

    def test_rendered_runner_puts_the_shadow_in_the_final_summary(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            text.count('"$HOME/.local/bin/groundwork-path-shadow" --summary'), 2)
        self._version(self.grok_real / "grok", "1.0.62")
        (self.local_bin / "grok").symlink_to(self.grok_real / "grok")
        self._version(self.brew / "grok", "1.0.77")
        chezmoi = shutil.which("chezmoi")
        self.assertIsNotNone(chezmoi)
        destination = self.root / "dest"
        destination.mkdir()
        empty = self.root / "empty.toml"
        empty.write_text("", encoding="utf-8")
        data = {
            "name": "CI User", "email_personal": "ci@example.com", "email_work": "",
            "code_dir": "~/code", "reset_existing_configs": False,
            "password_manager": "bitwarden", "signingkey": "",
            "obsidian_vault_name": "ci", "game_dev": False,
            "release_posture": "current", "docker_backend": "docker-desktop",
            "headless": True, "xcode": False, "beta": False,
            "chezmoi": {"os": "linux", "arch": "amd64",
                        "osRelease": {"ID": "ubuntu"}, "workingTree": str(self.root / "tree")},
        }
        (self.root / "tree/home/dot_local/share/groundwork/lib").mkdir(parents=True)
        rendered = subprocess.run(
            [chezmoi, "--config", str(empty), "--source", str(REPO),
             "--destination", str(destination), "--override-data", json.dumps(data),
             "execute-template"],
            input=RUNNER.read_text(encoding="utf-8"),
            text=True, capture_output=True, check=False, env=self.env, cwd=REPO,
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        lines = []
        for line in rendered.stdout.splitlines():
            if "checkout-core.sh" in line:
                lines.append(":")
            elif line.startswith("export PATH=") and "homebrew" in line:
                lines.append('export PATH="$HOME/.local/bin:$GROUNDWORK_TEST_PATH"')
            else:
                lines.append(line)
        script = self.root / "runner"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)
        _script(self.local_bin / "chezmoi", '''
            case "${1:-}" in
              source-path) printf '%s\n' "$CHEZMOI_SOURCE" ;;
              *) printf 'CHEZMOI %s\n' "$1" ;;
            esac
            exit 0
        ''')
        _script(self.local_bin / "groundwork-platform", 'printf "linux\\n"')
        repo = self.root / "clone"
        _script(self.tools / "git", 'exec /usr/bin/git "$@"')
        subprocess.run(
            ["/usr/bin/git", "init", "-q", "-b", "main", str(repo)],
            check=True, env={**self.env, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
                             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"},
        )
        subprocess.run(
            ["/usr/bin/git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
            check=True, env={**self.env, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
                             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"},
        )
        lib = self.home / ".local/lib/groundwork"
        lib.mkdir(parents=True)
        shutil.copy(LOCK, lib / "update-lock.sh")
        shutil.copy(MAINTENANCE, self.home / ".local/share/groundwork/lib/maintenance-runner.sh")
        env = self.env.copy()
        env.update({
            "PATH": f"{self.local_bin}:{self.tools}:/usr/bin:/bin",
            "GROUNDWORK_TEST_PATH": f"{self.tools}:/usr/bin:/bin",
            "CHEZMOI_SOURCE": str(repo),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        })
        result = subprocess.run(
            ["bash", str(script), "--skip-maintenance"],
            env=env, text=True, capture_output=True, check=False,
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        summary = result.stdout.index("PATH shadows")
        finished = result.stdout.index("\nResult\n")
        self.assertLess(summary, finished)
        self.assertIn("1.0.62", result.stdout)
        self.assertIn("1.0.77", result.stdout)
        self.assertIn("did not remove", result.stdout)
        self.assertTrue((self.local_bin / "grok").is_symlink())


if __name__ == "__main__":
    unittest.main()
