#!/usr/bin/env python3
"""update-all's automatic Claude Code handover and the doctor's T3 Code check.

Every test runs in a private HOME with fake native and Homebrew layouts, a fake
pgrep reading a fake process table, and a login-shell stub. No real claude,
process, Homebrew, or T3 Code file is read or changed.
"""
import contextlib
import io
import json
import os
import pty
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "home/dot_local/bin/executable_groundwork-claude-owner"
LIB = REPO / "home/dot_local/share/groundwork/lib/coding-cli-ownership.sh"
DOCTOR = REPO / "home/dot_local/bin/executable_groundwork-doctor"
UPDATE_RUN = REPO / "home/dot_local/bin/executable_groundwork-update-run.tmpl"

# Emulates `zsh -lic CMD` and `$SHELL -ilc CMD`: read the login profile, run CMD.
LOGIN_SHELL = """#!/bin/bash
[[ "$1" == -lic || "$1" == -ilc ]] || exit 9
[[ -z "${LOGIN_SHELL_FAIL:-}" ]] || exit 1
. "$ZDOTDIR/.zprofile"
eval "$2"
"""

# A pgrep over FAKE_PROCS lines of "pid<TAB>process name<TAB>command line".
# -x compares the process name exactly; -f runs the real `grep -E` on the
# command line, so the helper's pattern is proven with a real ERE engine.
FAKE_PGREP = r"""#!/bin/bash
printf '%s\n' "$*" >>"$PGREP_LOG"
if [[ -n "${FAKE_PGREP_STATUS:-}" ]]; then
  printf '%b' "${FAKE_PGREP_OUTPUT:-}"
  exit "$FAKE_PGREP_STATUS"
fi
mode='' pattern=''
while (($#)); do
  case "$1" in
    -a) ;;
    -x | -f) mode="$1"; pattern="$2"; shift ;;
    *) exit 2 ;;
  esac
  shift
done
found=1
while IFS=$'\t' read -r pid name args; do
  [[ -n "$pid" ]] || continue
  if [[ "$mode" == -x && "$name" == "$pattern" ]] \
    || { [[ "$mode" == -f ]] && printf '%s\n' "$args" | grep -Eq -- "$pattern"; }; then
    echo "$pid"
    found=0
  fi
done <"${FAKE_PROCS:-/dev/null}"
exit "$found"
"""

# Real Claude Code processes: each one alone must block the handover.
CLAUDE_PROCESSES = [
    ("claude", "claude"),
    ("claude", "claude --resume"),
    ("claude", "/opt/homebrew/bin/claude -p hello"),
    ("2.1.314", "/Users/someone/.local/share/claude/versions/2.1.314 --print"),
    ("node", "/Users/someone/.local/bin/claude"),
    ("node", "node /usr/local/bin/claude"),
    ("node", "/usr/bin/node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"),
    ("bun", "bun /opt/tools/claude --continue"),
    ("claude", "unreadable arguments"),
]
# Unrelated processes whose names or arguments contain "claude".
UNRELATED_PROCESSES = [
    ("Claude", "/Applications/Claude.app/Contents/MacOS/Claude"),
    ("Claude Helper", "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper"),
    ("claude-squad", "claude-squad"),
    ("claude_monitor", "/usr/local/bin/claude_monitor"),
    ("nvim", "nvim CLAUDE.md"),
    ("vim", "vim /home/someone/bin/claude"),
    ("grep", "grep -r claude ."),
    ("tail", "tail -f /home/someone/.claude/debug.log"),
    ("python3", "python3 /opt/tools/claude.py"),
    ("node", "node /opt/tools/claude-proxy.js"),
    ("bash", "bash -c claude --version"),
]


class Sandbox(unittest.TestCase):
    def setUp(self):
        # The handover rejects world-writable ancestors such as /tmp.
        self.temp = tempfile.TemporaryDirectory(prefix=".groundwork-auto-handover-", dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.prefix = self.root / "brew"
        (self.prefix / "bin").mkdir(parents=True)
        for name in ("dirname", "basename", "readlink", "sed", "cat", "grep", "tail", "uname", "ps"):
            found = shutil.which(name)
            self.assertIsNotNone(found, name)
            (self.tools / name).symlink_to(found)
        supervisor = shutil.which("timeout") or shutil.which("gtimeout")
        self.assertIsNotNone(supervisor, "coreutils timeout is a declared prerequisite")
        (self.tools / "timeout").symlink_to(supervisor)
        jq = shutil.which("jq")
        self.assertIsNotNone(jq, "jq is a declared prerequisite")
        (self.tools / "jq").symlink_to(jq)
        self.script(self.tools / "brew", 'printf "%s\\n" "$FAKE_BREW_PREFIX"')
        self.script(self.tools / "zsh", LOGIN_SHELL.removeprefix("#!/bin/bash\n"))
        self.script(self.tools / "pgrep", FAKE_PGREP.removeprefix("#!/bin/bash\n"))
        self.procs = self.root / "procs.tsv"
        self.procs.write_text("")
        self.pgrep_log = self.root / "pgrep.log"
        path = f"{self.bin}:{self.prefix / 'bin'}:{self.tools}"
        zdot = self.root / "login"
        zdot.mkdir()
        (zdot / ".zprofile").write_text(f"export PATH='{path}'\n")
        self.env = {
            "HOME": str(self.home),
            "PATH": path,
            "ZDOTDIR": str(zdot),
            "SHELL": str(self.tools / "zsh"),
            "FAKE_BREW_PREFIX": str(self.prefix),
            "FAKE_PROCS": str(self.procs),
            "PGREP_LOG": str(self.pgrep_log),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "GNUPGHOME": str(self.root / "gnupg"),
            "LANG": "C.UTF-8",
        }
        self.marker = self.root / "state/groundwork/claude-handover-declined"
        self.backups = self.home / ".local/state/groundwork/claude-handover"

    def script(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)

    def install(self, version, native=False):
        if native:
            target = self.home / ".local/share/claude/versions" / version
            link = self.bin / "claude"
        else:
            target = self.prefix / "Caskroom/claude-code@latest" / version / "claude"
            link = self.prefix / "bin/claude"
        self.script(target, f'printf "%s (Claude Code)\\n" {version}')
        link.symlink_to(target)
        return link


class AutoHandoverTests(Sandbox):
    def run_helper(self, *args, interactive=True, extra=None):
        env = dict(self.env, **(extra or {}))
        if not interactive:
            return subprocess.run([sys.executable, "-B", str(HELPER), *args], env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=60)
        leader, follower = pty.openpty()
        try:
            return subprocess.run([sys.executable, "-B", str(HELPER), *args], env=env,
                                  stdin=follower, capture_output=True, text=True, timeout=60)
        finally:
            os.close(leader)
            os.close(follower)

    def state(self):
        """Every file under HOME except the handover's own backup directory."""
        return sorted((str(p.relative_to(self.home)),
                       os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                      for p in self.home.rglob("*") if self.backups not in (p, *p.parents))

    def assert_skipped(self, result, before, reason):
        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        self.assertIn("automatic handover to Homebrew skipped", result.stdout)
        self.assertRegex(result.stdout, reason)
        self.assertIn("Nothing was changed", result.stdout)
        self.assertEqual(before, self.state())
        self.assertFalse(self.backups.exists())

    def test_hands_over_when_every_condition_holds(self):
        native = self.install("2.4.1", native=True)
        target = native.resolve()
        managed = self.install("2.4.2")
        # Settings, credentials and native version files are never touched.
        (self.home / ".claude").mkdir()
        (self.home / ".claude/settings.json").write_text('{"model": "x"}')
        (self.home / ".claude.json").write_text('{"oauthAccount": {}}')
        kept = {p: p.read_bytes() for p in (self.home / ".claude/settings.json",
                                            self.home / ".claude.json", target)}
        result = self.run_helper("auto", "homebrew")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("handing", result.stdout)
        self.assertIn("Backup directory:", result.stdout)
        self.assertRegex(result.stdout, r"Rollback: groundwork-claude-owner rollback \S+ --yes")
        self.assertIn(f"Fresh login shell verified: {managed}", result.stdout)
        self.assertFalse(os.path.lexists(native))
        backup = next(self.backups.iterdir())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual(os.readlink(backup / "claude"), str(target))
        self.assertEqual(kept, {p: p.read_bytes() for p in kept})
        calls = self.pgrep_log.read_text().splitlines()
        self.assertIn("-x claude", calls)
        self.assertTrue(any(call.startswith("-f ^") for call in calls), calls)
        # The second run finds Homebrew already effective and stays quiet.
        again = self.run_helper("auto", "homebrew")
        self.assertEqual((again.returncode, again.stdout), (0, ""), again.stderr)

    def test_equal_versions_hand_over_and_older_homebrew_skips(self):
        self.install("2.4.2", native=True)
        self.install("2.4.2")
        self.assertEqual(self.run_helper("auto", "homebrew").returncode, 0)
        self.assertFalse(os.path.lexists(self.bin / "claude"))
        shutil.rmtree(self.backups)
        (self.prefix / "bin/claude").unlink()
        self.install("2.10.0", native=True)
        self.install("2.9.9")
        before = self.state()
        self.assert_skipped(self.run_helper("auto", "homebrew"), before,
                            r"Homebrew 2\.9\.9 is older than native 2\.10\.0")

    def test_native_owner_and_missing_copies_are_quiet(self):
        self.install("2.4.1", native=True)
        before = self.state()
        result = self.run_helper("auto", "homebrew")  # no Homebrew copy yet
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.install("2.4.2")
        result = self.run_helper("auto", "native")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertEqual(before, self.state())
        self.assertFalse(self.pgrep_log.exists())

    def test_non_interactive_run_skips(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        before = self.state()
        self.assert_skipped(self.run_helper("auto", "homebrew", interactive=False), before,
                            "no interactive terminal")
        self.assertFalse(self.pgrep_log.exists())

    def test_running_claude_process_skips(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        self.procs.write_text("100\tzsh\t-zsh\n4242\tclaude\tclaude --resume\n")
        before = self.state()
        self.assert_skipped(self.run_helper("auto", "homebrew"), before,
                            r"Claude Code is running \(PID 4242\)")

    def test_an_uncertain_process_check_skips(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        before = self.state()
        cases = {
            "pgrep error": {"FAKE_PGREP_STATUS": "2"},
            "pgrep fatal": {"FAKE_PGREP_STATUS": "3"},
            "match without PIDs": {"FAKE_PGREP_STATUS": "0"},
            "non-PID output": {"FAKE_PGREP_STATUS": "0", "FAKE_PGREP_OUTPUT": "4242 claude\\n"},
            "no-match status with output": {"FAKE_PGREP_STATUS": "1", "FAKE_PGREP_OUTPUT": "4242\\n"},
        }
        for name, extra in cases.items():
            with self.subTest(name):
                self.assert_skipped(self.run_helper("auto", "homebrew", extra=extra), before,
                                    r"process check was ambiguous")
        (self.tools / "pgrep").unlink()
        self.assert_skipped(self.run_helper("auto", "homebrew"), before, "pgrep is unavailable")

    def test_decline_marker_from_native_or_rollback_keeps_handover_off(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        kept = self.run_helper("native")
        self.assertEqual(kept.returncode, 0, kept.stderr)
        self.assertTrue(self.marker.is_file())
        before = self.state()
        result = self.run_helper("auto", "homebrew")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("automatic handover is off", result.stdout)
        self.assertEqual(before, self.state())
        # An explicit Homebrew selection clears the decline.
        chosen = self.run_helper("homebrew", "--yes")
        self.assertEqual(chosen.returncode, 0, chosen.stderr)
        self.assertFalse(os.path.lexists(self.marker))
        # Rolling back records it again, and the next update-all leaves native alone.
        backup = next(self.backups.iterdir())
        restored = self.run_helper("rollback", str(backup), "--yes")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertTrue(self.marker.is_file())
        self.assertTrue((self.bin / "claude").is_symlink())
        result = self.run_helper("auto", "homebrew")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("automatic handover is off", result.stdout)
        self.assertTrue((self.bin / "claude").is_symlink())
        self.assertIn("Automatic handover: off", self.run_helper("status").stdout)

    def test_unverified_native_command_skips(self):
        self.install("2.4.2")
        other = self.home / "tools/claude"
        self.script(other, 'echo "2.4.1 (Claude Code)"')
        (self.bin / "claude").symlink_to(other)
        before = self.state()
        self.assert_skipped(self.run_helper("auto", "homebrew"), before, "not a verified native symlink")

    def test_failed_login_verification_reports_the_rollback(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        result = self.run_helper("auto", "homebrew", extra={"LOGIN_SHELL_FAIL": "1"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Rollback:", result.stdout)
        self.assertNotIn("ownership verified", result.stdout)
        self.assertTrue((next(self.backups.iterdir()) / "claude").is_symlink())

    def test_deadline_without_room_to_verify_skips(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        before = self.state()
        main = runpy.run_path(str(HELPER))["main"]
        output = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.dict(main.__globals__, DEADLINE=time.monotonic() + 15), \
                mock.patch("os.isatty", return_value=True), contextlib.redirect_stdout(output):
            status = main(["auto", "homebrew"])
        self.assertEqual(status, 75, output.getvalue())
        self.assertIn("deadline does not leave time", output.getvalue())
        self.assertEqual(before, self.state())

    def test_invalid_auto_arguments_do_nothing(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        before = self.state()
        for args in (["auto"], ["auto", "bogus"], ["auto", "homebrew", "--yes"]):
            with self.subTest(args=args):
                self.assertEqual(self.run_helper(*args).returncode, 64)
        self.assertEqual(before, self.state())
        self.assertFalse(self.pgrep_log.exists())


class ProcessMatchingTests(Sandbox):
    def processes(self, rows, platform="linux"):
        self.procs.write_text("".join(f"{100 + i}\t{name}\t{args}\n" for i, (name, args) in enumerate(rows)))
        module = runpy.run_path(str(HELPER))
        with mock.patch.dict(os.environ, self.env, clear=True):
            return module["claude_processes"](platform)

    def test_each_claude_code_process_matches(self):
        for row in CLAUDE_PROCESSES:
            with self.subTest(row=row):
                self.assertEqual(self.processes([row]), ["100"])

    def test_unrelated_names_containing_claude_do_not_match(self):
        self.assertEqual(self.processes(UNRELATED_PROCESSES), [])
        for row in UNRELATED_PROCESSES:
            with self.subTest(row=row):
                self.assertEqual(self.processes([row]), [])

    def test_macos_includes_ancestors_and_linux_does_not_pass_a(self):
        module = runpy.run_path(str(HELPER))
        darwin = module["pgrep_arguments"]("darwin", "pgrep")
        linux = module["pgrep_arguments"]("linux", "pgrep")
        self.assertEqual([args[:3] for args in darwin], [["pgrep", "-a", "-x"], ["pgrep", "-a", "-f"]])
        self.assertEqual([args[:2] for args in linux], [["pgrep", "-x"], ["pgrep", "-f"]])
        self.assertNotIn("-a", linux[0] + linux[1])
        self.assertEqual(self.processes([CLAUDE_PROCESSES[1]], platform="darwin"), ["100"])
        self.assertIn("-a -x claude", self.pgrep_log.read_text())


class UpdateRunSectionTests(Sandbox):
    """Render the update-run Claude handover block and run it with a stub helper."""

    def render_block(self, owner):
        chezmoi = shutil.which("chezmoi")
        self.assertIsNotNone(chezmoi, "chezmoi is required to render the update runner")
        config = self.root / "empty.toml"
        config.write_text("")
        source = UPDATE_RUN.read_text(encoding="utf-8")
        start = source.index("claude_handover_unfinished=0\n")
        end = source.index("# Installation success alone cannot prove")
        data = {"claude_code_owner": owner} if owner else {}
        rendered = subprocess.run(
            [chezmoi, "--config", str(config), "--source", str(REPO),
             "--override-data", json.dumps(data), "execute-template"],
            input=source[start:end], text=True, capture_output=True, timeout=30,
            env=dict(self.env, PATH=os.environ["PATH"]))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        return rendered.stdout

    def run_block(self, owner, status, interactive):
        log = self.root / "helper.log"
        self.script(self.bin / "groundwork-claude-owner",
                    f'printf "%s stdin-tty=%s\\n" "$*" "$([[ -t 0 ]] && echo 1 || echo 0)" >>{log}\n'
                    f'exit {status}')
        if not (self.bin / "claude").exists():
            self.install("2.4.1", native=True)
        block = self.render_block(owner)
        script = ("set -euo pipefail\n"
                  f"groundwork_interactive_tty_available={1 if interactive else 0}\n"
                  + ("exec 7<&0\n" if interactive else "")
                  + block + 'echo "unfinished=$claude_handover_unfinished"\n')
        leader, follower = pty.openpty()
        try:
            result = subprocess.run(["/bin/bash", "-c", script], env=self.env, stdin=follower,
                                    capture_output=True, text=True, timeout=30)
        finally:
            os.close(leader)
            os.close(follower)
        calls = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return result, calls

    def test_owner_and_terminal_reach_the_helper(self):
        result, calls = self.run_block(None, 0, interactive=True)
        self.assertEqual(calls, ["auto homebrew stdin-tty=1"])
        self.assertIn("unfinished=0", result.stdout)
        result, calls = self.run_block("native", 0, interactive=False)
        self.assertEqual(calls, ["auto native stdin-tty=0"])

    def test_skip_is_quiet_and_failure_or_interrupt_is_surfaced(self):
        result, _ = self.run_block("homebrew", 75, interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unfinished=0", result.stdout)
        result, _ = self.run_block("homebrew", 1, interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unfinished=1", result.stdout)
        self.assertIn("automatic handover did not finish (exit 1)", result.stderr)
        for status in (129, 130, 143):
            result, _ = self.run_block("homebrew", status, interactive=False)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertNotIn("unfinished=", result.stdout)

    def test_no_native_link_never_calls_the_helper(self):
        self.install("2.4.2")
        self.script(self.bin / "claude", 'echo "2.4.1 (Claude Code)"')  # not a symlink
        result, calls = self.run_block("homebrew", 0, interactive=False)
        self.assertEqual(calls, [])
        self.assertIn("unfinished=0", result.stdout)


class T3ResolutionTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.t3 = self.home / ".t3"
        self.settings = self.t3 / "userdata/settings.json"

    def write_settings(self, value):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        text = value if isinstance(value, str) else json.dumps(value)
        self.settings.write_text(text)
        return self.settings.stat().st_mtime_ns, text

    def claude_instance(self, binary_path=None, **extra):
        config = {} if binary_path is None else {"binaryPath": binary_path}
        return {"driver": "claudeAgent", "enabled": True, "config": config, **extra}

    def report(self, owner="homebrew", extra=None):
        command = ["/bin/bash", "-c", 'set -euo pipefail; . "$1"; gw_t3_claude_report "$2"',
                   "test", str(LIB), owner]
        result = subprocess.run(command, env=dict(self.env, **(extra or {})),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_without_t3_nothing_is_checked(self):
        self.assertIn("not found; Claude resolution not checked", self.report())

    def test_default_instance_resolves_on_the_login_shell_path(self):
        managed = self.install("2.4.2")
        self.t3.mkdir()
        output = self.report()
        self.assertIn(f"Claude instance claudeAgent would run {managed} (resolves to "
                      f"{managed.resolve()})", output)
        self.assertNotIn("warning", output)

    def test_nothing_resolvable_is_flagged(self):
        self.write_settings({"providerInstances": {"grok": {"driver": "grok"}}})
        output = self.report()
        self.assertIn("Claude instance claudeAgent cannot resolve claude on the login-shell PATH", output)
        self.assertIn(f"{self.prefix}/bin/claude", output)

    def test_missing_binary_path_names_the_exact_setting(self):
        self.install("2.4.2")
        missing = f"{self.home}/.local/bin/claude"
        mtime, text = self.write_settings({"providerInstances": {
            "claude_work": self.claude_instance(missing, environment=[
                {"name": "ANTHROPIC_API_KEY", "value": "sk-never-print-this", "sensitive": True}]),
        }})
        output = self.report()
        self.assertIn(f"Claude instance claude_work has Binary path {missing}, which no longer exists", output)
        self.assertIn("open Settings > Providers > claude_work and clear Binary path, or set it to "
                      f"{self.prefix}/bin/claude", output)
        self.assertIn(f"providerInstances.claude_work.config.binaryPath in {self.settings}", output)
        self.assertNotIn("sk-never-print-this", output)
        # Report only: T3's settings are never written.
        self.assertEqual((self.settings.stat().st_mtime_ns, self.settings.read_text()), (mtime, text))

    def test_native_after_handover_is_flagged(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        native.unlink()  # handed over: the native version file remains
        self.write_settings({"providerInstances": {
            "claudeAgent": self.claude_instance("~/.local/share/claude/versions/2.4.1")}})
        output = self.report()
        self.assertIn("would run " + str(self.home / ".local/share/claude/versions/2.4.1"), output)
        self.assertIn("that is the native copy, after the handover to Homebrew", output)
        self.assertNotIn("native copy", self.report(owner="native"))

    def test_native_owner_resolving_native_is_not_flagged(self):
        native = self.install("2.4.1", native=True)
        self.t3.mkdir()
        output = self.report(owner="native")
        self.assertIn(f"would run {native}", output)
        self.assertNotIn("warning", output)

    def test_unrecognized_settings_are_reported_not_guessed(self):
        for text in ("{not json", json.dumps({"providerInstances": []}),
                     json.dumps({"providerInstances": {"c": self.claude_instance(7)}}), "[]"):
            with self.subTest(text=text):
                self.write_settings(text)
                output = self.report()
                self.assertIn("not in a format Groundwork recognizes", output)
                self.assertIn("Settings > Providers > Claude > Binary path", output)

    def test_unobservable_login_shell_is_reported(self):
        self.install("2.4.2")
        self.t3.mkdir()
        output = self.report(extra={"LOGIN_SHELL_FAIL": "1"})
        self.assertIn("login-shell PATH T3 Code reads could not be observed", output)

    def test_doctor_ai_tools_includes_the_t3_check(self):
        managed = self.install("2.4.2")
        self.t3.mkdir()
        share = self.home / ".local/share/groundwork/lib"
        share.mkdir(parents=True)
        shutil.copy(LIB, share / LIB.name)
        result = subprocess.run(["/bin/bash", str(DOCTOR), "--ai-tools"], env=self.env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"T3 Code: Claude instance claudeAgent would run {managed}", result.stdout)
        self.assertRegex(DOCTOR.read_text(), re.compile(r"T3 Code's settings are read, never changed"))


if __name__ == "__main__":
    unittest.main()
