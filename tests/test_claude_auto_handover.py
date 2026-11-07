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
calls=$(wc -l <"$PGREP_LOG")
if [[ -n "${FAKE_PGREP_SWITCH_AT:-}" && "$calls" -ge "$FAKE_PGREP_SWITCH_AT" ]]; then
  FAKE_PROCS="$FAKE_PROCS_LATE"
fi
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
    ("node", "node /app/node_modules/@anthropic-ai/claude-agent-sdk/cli.js --output-format stream-json"),
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
        for name in ("dirname", "basename", "readlink", "sed", "cat", "grep", "tail", "uname", "ps", "wc"):
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

    def test_failed_login_verification_is_undone_once_per_version_pair(self):
        native = self.install("2.4.1", native=True)
        link = os.readlink(native)
        self.install("2.4.2")
        failed = self.root / "state/groundwork/claude-handover-failed"
        result = self.run_helper("auto", "homebrew", extra={"LOGIN_SHELL_FAIL": "1"})
        self.assertEqual(result.returncode, 76, result.stdout + result.stderr)
        self.assertIn("the handover was undone", result.stdout)
        self.assertIn("Check shell overrides", result.stdout)
        self.assertIn("is no longer needed and was removed", result.stdout)
        self.assertNotIn("ownership verified", result.stdout)
        self.assertEqual(os.readlink(native), link)
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertEqual(failed.read_text(), "native 2.4.1 homebrew 2.4.2\n")
        # The same versions pause with one line instead of repeating the attempt.
        before = self.state()
        checks = self.pgrep_log.read_text()
        again = self.run_helper("auto", "homebrew", extra={"LOGIN_SHELL_FAIL": "1"})
        self.assertEqual(again.returncode, 75, again.stdout + again.stderr)
        self.assertEqual(len(again.stdout.splitlines()), 1, again.stdout)
        self.assertIn("automatic handover paused", again.stdout)
        self.assertEqual(before, self.state())
        self.assertEqual(checks, self.pgrep_log.read_text())
        # A new Homebrew version tries again; success clears the record.
        (self.prefix / "bin/claude").unlink()
        self.install("2.4.3")
        result = self.run_helper("auto", "homebrew")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.lexists(native))
        self.assertFalse(failed.exists())

    def record_failed(self, content):
        failed = self.root / "state/groundwork/claude-handover-failed"
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_bytes(content)
        return failed

    def test_unreadable_or_odd_pause_records_retry_with_every_guard(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        for name, content, mode in (("invalid UTF-8", b"\xff\xfe native 2.4.1\n", 0o600),
                                    ("odd content", b"native 2.4.1 homebrew\n", 0o600),
                                    ("unreadable", b"native 2.4.1 homebrew 2.4.2\n", 0o000)):
            with self.subTest(name):
                failed = self.record_failed(content)
                failed.chmod(mode)
                self.pgrep_log.unlink(missing_ok=True)
                result = self.run_helper("auto", "homebrew", extra={"LOGIN_SHELL_FAIL": "1"})
                self.assertEqual(result.returncode, 76, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("paused", result.stdout)
                self.assertIn("-x claude", self.pgrep_log.read_text())
                self.assertTrue(native.is_symlink())
                self.assertEqual(failed.read_text(), "native 2.4.1 homebrew 2.4.2\n")
                failed.unlink()

    def test_native_version_change_lifts_the_pause(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        failed = self.record_failed(b"native 2.4.1 homebrew 2.4.2\n")
        paused = self.run_helper("auto", "homebrew")
        self.assertEqual(paused.returncode, 75)
        self.assertIn("groundwork-claude-owner homebrew --yes clears the pause", paused.stdout)
        native.unlink()
        self.install("2.4.0", native=True)
        result = self.run_helper("auto", "homebrew")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(os.path.lexists(native))
        self.assertFalse(failed.exists())

    def test_manual_handover_clears_the_pause(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        failed = self.record_failed(b"native 2.4.1 homebrew 2.4.2\n")
        result = self.run_helper("homebrew", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(failed.exists())

    def test_manual_handover_puts_the_link_back_when_a_session_starts_mid_move(self):
        native = self.install("2.4.1", native=True)
        link = os.readlink(native)
        self.install("2.4.2")
        late = self.root / "late.tsv"
        late.write_text("4242\tclaude\tclaude\n")
        # The manual path checks once before the move (two pgrep calls), then after it.
        result = self.run_helper("homebrew", "--yes",
                                 extra={"FAKE_PGREP_SWITCH_AT": "3", "FAKE_PROCS_LATE": str(late)})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Claude Code is running (PID 4242)", result.stderr)
        self.assertIn("Native link put back", result.stdout)
        self.assertEqual(os.readlink(native), link)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_failed_cleanup_does_not_hide_the_original_error(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        with mock.patch("os.rename", side_effect=OSError("rename refused")), \
                mock.patch("pathlib.Path.rmdir", side_effect=OSError("rmdir refused")):
            _, status, stdout, _ = self.run_main(["auto", "homebrew"])
        self.assertEqual(status, 75, stdout)
        self.assertIn("rename refused", stdout)
        self.assertNotIn("rmdir refused", stdout)

    def test_failed_login_with_an_occupied_native_path_keeps_the_backup(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        main = runpy.run_path(str(HELPER))["main"]
        original = main.__globals__["fresh_command"]

        def occupy_then_verify(expected):
            self.script(native, "echo someone-else")
            return original(expected)
        output = io.StringIO()
        with mock.patch.dict(os.environ, dict(self.env, LOGIN_SHELL_FAIL="1"), clear=True), \
                mock.patch.dict(main.__globals__, fresh_command=occupy_then_verify), \
                mock.patch("os.isatty", return_value=True), contextlib.redirect_stdout(output):
            with self.assertRaises(RuntimeError) as raised:
                main(["auto", "homebrew"])
        self.assertNotIn("put back", str(raised.exception))
        self.assertEqual(native.read_text(), "#!/bin/bash\necho someone-else\n")
        self.assertTrue((next(self.backups.iterdir()) / "claude").is_symlink())

    def test_session_started_during_the_move_restores_the_link(self):
        native = self.install("2.4.1", native=True)
        link = os.readlink(native)
        self.install("2.4.2")
        late = self.root / "late.tsv"
        late.write_text("4242\tclaude\tclaude\n")
        # Two pgrep calls per check: auto's check, hand_over's check, then the
        # check right after the rename, which is the first to see the session.
        result = self.run_helper("auto", "homebrew",
                                 extra={"FAKE_PGREP_SWITCH_AT": "5", "FAKE_PROCS_LATE": str(late)})
        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        self.assertIn("Claude Code is running (PID 4242)", result.stdout)
        self.assertIn("Native link put back", result.stdout)
        self.assertEqual(os.readlink(native), link)
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertFalse((self.root / "state/groundwork/claude-handover-failed").exists())

    def run_main(self, args, **patches):
        main = runpy.run_path(str(HELPER))["main"]
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.dict(main.__globals__, **patches), \
                mock.patch("os.isatty", return_value=True), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                status = main(args)
            except (OSError, RuntimeError) as error:
                status = error
        return main, status, stdout.getvalue(), stderr.getvalue()

    def test_entry_replaced_during_the_move_is_kept_and_never_relinked(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        original = os.rename

        def replacing_rename(source, destination):
            native.unlink()
            self.script(native, "echo replacement-command")
            original(source, destination)
        with mock.patch("os.rename", side_effect=replacing_rename):
            _, status, stdout, _ = self.run_main(["auto", "homebrew"])
        self.assertIsInstance(status, RuntimeError)
        self.assertIn("changed during preview", str(status))
        self.assertFalse(os.path.lexists(native))
        backup = next(self.backups.iterdir())
        self.assertEqual((backup / "claude").read_text(), "#!/bin/bash\necho replacement-command\n")
        self.assertIn("Rollback:", stdout)

    def test_failure_before_the_move_leaves_no_backup_directory(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        with mock.patch("os.rename", side_effect=OSError("rename refused")):
            _, status, stdout, _ = self.run_main(["auto", "homebrew"])
        self.assertEqual(status, 75, stdout)
        self.assertIn("rename refused", stdout)
        self.assertTrue(native.is_symlink())
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_failed_marker_write_leaves_no_temporary_file(self):
        self.install("2.4.1", native=True)
        with mock.patch("os.replace", side_effect=OSError("replace refused")):
            _, status, _, _ = self.run_main(["native"])
        self.assertIsInstance(status, OSError)
        self.assertEqual(list((self.root / "state/groundwork").iterdir()), [])

    def test_interrupted_login_check_exits_130_without_a_traceback(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")

        def interrupted(expected):
            raise KeyboardInterrupt
        _, status, stdout, stderr = self.run_main(["auto", "homebrew"], fresh_command=interrupted)
        self.assertEqual(status, 130)
        self.assertEqual(stderr.count("\n"), 1, stderr)
        self.assertIn("handover interrupted", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertIn("Rollback:", stdout)

    def test_manual_handover_refuses_while_claude_runs(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        self.procs.write_text("4242\tclaude\tclaude --resume\n5151\t2.4.1\t"
                              f"{self.home}/.local/share/claude/versions/2.4.1\n")
        before = self.state()
        result = self.run_helper("homebrew", "--yes")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Claude Code is running (PID 4242, 5151); quit every session, then repeat this command",
                      result.stderr)
        self.assertTrue(native.is_symlink())
        self.assertEqual(before, self.state())
        self.assertFalse(self.backups.exists())
        # Preview stays available, and an uncertain check also refuses.
        self.assertEqual(self.run_helper("homebrew").returncode, 0)
        self.procs.write_text("")
        result = self.run_helper("homebrew", "--yes", extra={"FAKE_PGREP_STATUS": "2"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("ambiguous", result.stderr)
        self.assertTrue(native.is_symlink())

    def test_session_seen_by_the_last_check_before_the_move_creates_no_backup(self):
        self.install("2.4.1", native=True)
        self.install("2.4.2")
        late = self.root / "late.tsv"
        late.write_text("4242\tclaude\tclaude\n")
        before = self.state()
        self.assert_skipped(self.run_helper("auto", "homebrew", extra={
            "FAKE_PGREP_SWITCH_AT": "3", "FAKE_PROCS_LATE": str(late)}), before,
            r"Claude Code is running \(PID 4242\)")

    def test_decline_is_recorded_before_anything_else_or_the_command_fails(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        # A failing version probe still leaves the decline in place.
        target = native.resolve()
        self.script(target, "exit 7")
        result = self.run_helper("native")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.marker.is_file())
        shutil.rmtree(self.root / "state")
        self.script(target, 'printf "2.4.1 (Claude Code)\\n"')
        # A marker that cannot be written fails the command with nothing changed.
        (self.root / "state").mkdir()
        (self.root / "state/groundwork").write_text("not a directory")
        before = self.state()
        result = self.run_helper("native")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Native ownership preserved", result.stdout)
        self.assertEqual(before, self.state())

    def test_rollback_records_the_decline_before_restoring(self):
        native = self.install("2.4.1", native=True)
        self.install("2.4.2")
        self.assertEqual(self.run_helper("homebrew", "--yes").returncode, 0)
        backup = next(self.backups.iterdir())
        # The marker cannot be written: rollback fails and native stays absent.
        (self.root / "state").mkdir(exist_ok=True)
        (self.root / "state/groundwork").write_text("not a directory")
        result = self.run_helper("rollback", str(backup), "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.lexists(native))
        self.assertTrue((backup / "claude").is_symlink())
        (self.root / "state/groundwork").unlink()
        # A failed verification after the restore still leaves the decline.
        result = self.run_helper("rollback", str(backup), "--yes", extra={"LOGIN_SHELL_FAIL": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(native.is_symlink())
        self.assertTrue(self.marker.is_file())

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
        start = source.index('claude_handover_warning=""\n')
        end = source.index("# Installation success alone cannot prove")
        data = {"claude_code_owner": owner} if owner else {}
        rendered = subprocess.run(
            [chezmoi, "--config", str(config), "--source", str(REPO),
             "--override-data", json.dumps(data), "execute-template"],
            input=source[start:end], text=True, capture_output=True, timeout=30,
            env=dict(self.env, PATH=os.environ["PATH"]))
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        return rendered.stdout

    def summary(self):
        """The update summary's Warning and Result lines, with other counts at zero."""
        source = UPDATE_RUN.read_text(encoding="utf-8")
        start = source.index('if [[ "$brew_warning_count" -gt 0 || "$pnpm_discovery_warning_count" -gt 0 \\\n')
        end = source.index("printf '\\nResult\\n  SUCCESS%s\\n' \"$result_suffix\"\n")
        text = source[start:end] + "printf '\\nResult\\n  SUCCESS%s\\n' \"$result_suffix\"\n"
        self.assertNotIn("{{", text)
        zeros = ("brew_warning_count pnpm_discovery_warning_count owner_review_count "
                 "brew_cask_action_review_count machine_app_action_count brew_deprecated_count "
                 "brew_disabled_count brew_deferred_running_count").split()
        return "".join(f"{name}=0\n" for name in zeros) + text

    def run_block(self, owner, status, interactive, summary=False):
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
                  + block + 'echo "warning=$claude_handover_warning"\n'
                  + (self.summary() if summary else ""))
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

    def test_undone_handover_reaches_the_warning_summary(self):
        result, _ = self.run_block("homebrew", 76, interactive=False, summary=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\nWarning\n  Claude Code             handover undone · the login shell did not "
                      "resolve Homebrew's claude; check shell overrides\n", result.stdout)
        self.assertIn("\nResult\n  SUCCESS · 1 WARNING(S)\n", result.stdout)
        result, _ = self.run_block("homebrew", 75, interactive=False, summary=True)
        self.assertNotIn("Warning", result.stdout)
        self.assertIn("\nResult\n  SUCCESS\n", result.stdout)

    def test_owner_and_terminal_reach_the_helper(self):
        result, calls = self.run_block(None, 0, interactive=True)
        self.assertEqual(calls, ["auto homebrew stdin-tty=1"])
        self.assertIn("warning=\n", result.stdout)
        result, calls = self.run_block("native", 0, interactive=False)
        self.assertEqual(calls, ["auto native stdin-tty=0"])

    def test_skip_is_quiet_and_undone_failure_or_interrupt_is_surfaced(self):
        result, _ = self.run_block("homebrew", 75, interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning=\n", result.stdout)
        # Undone: the link is already back, so no Rollback advice.
        result, _ = self.run_block("homebrew", 76, interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning=handover undone · the login shell did not resolve Homebrew's claude; "
                      "check shell overrides", result.stdout)
        self.assertNotIn("Rollback", result.stdout + result.stderr)
        result, _ = self.run_block("homebrew", 1, interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning=automatic handover did not finish · see the Rollback line above", result.stdout)
        self.assertIn("automatic handover did not finish (exit 1)", result.stderr)
        for status in (129, 130, 143):
            result, _ = self.run_block("homebrew", status, interactive=False)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertNotIn("warning=", result.stdout)

    def test_no_native_link_never_calls_the_helper(self):
        self.install("2.4.2")
        self.script(self.bin / "claude", 'echo "2.4.1 (Claude Code)"')  # not a symlink
        result, calls = self.run_block("homebrew", 0, interactive=False)
        self.assertEqual(calls, [])
        self.assertIn("warning=\n", result.stdout)


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

    def test_non_printable_binary_path_is_not_printed(self):
        self.install("2.4.2")
        self.write_settings({"providerInstances": {
            "escape": self.claude_instance("/tmp/\u001b]0;owned\u0007claude"),
            "bidi": self.claude_instance("/opt/\u202eclaude"),
            "slash": self.claude_instance("C:\\claude"),
        }})
        output = self.report()
        for instance in ("escape", "bidi", "slash"):
            self.assertIn(f"Claude instance {instance} has a Binary path with non-printable characters", output)
        self.assertNotIn("\u001b", output)
        self.assertNotIn("\u202e", output)
        self.assertNotIn("owned", output)

    def test_unobservable_login_shell_is_reported(self):
        self.install("2.4.2")
        self.t3.mkdir()
        output = self.report(extra={"LOGIN_SHELL_FAIL": "1"})
        self.assertIn("login-shell PATH T3 Code reads could not be observed", output)

    def caps_report(self):
        command = ["/bin/bash", "-c", 'set -euo pipefail; . "$1"; gw_t3_claude_subagent_caps_report',
                   "test", str(LIB)]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_subagent_caps_set_missing_different_and_sensitive(self):
        def env(**values):
            return [{"name": name, "value": value, "sensitive": False} for name, value in values.items()]
        concurrent, depth = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
        mtime, text = self.write_settings({"providerInstances": {
            "capped": self.claude_instance(environment=[
                {"name": "ANTHROPIC_API_KEY", "value": "sk-never-print-this", "sensitive": True},
                *env(**{concurrent: "20", depth: "1"}),
                *env(**{concurrent: "4"})]),  # the last entry wins, as in T3
            "uncapped": self.claude_instance(),
            "loose": self.claude_instance(environment=env(**{concurrent: "4", depth: "31337"})),
            # How T3 stores a sensitive value: redacted in place, or a secret reference.
            "hidden": self.claude_instance(environment=[
                {"name": concurrent, "value": "", "sensitive": True, "valueRedacted": True},
                {"name": depth, "value": "", "sensitive": True, "secret": {"id": "never-print-ref"}}]),
            "off": self.claude_instance(enabled=False),
            "grok": {"driver": "grok"},
        }})
        output = self.caps_report()
        self.assertIn(f"Claude instance capped sets {concurrent}=4.\n"
                      f"T3 Code: Claude instance capped sets {depth}=1.\n", output)
        self.assertNotIn("Providers → capped", output)
        # The built-in instance runs without a providerInstances entry.
        for instance in ("claudeAgent", "uncapped"):
            self.assertIn(f"Claude instance {instance} does not set {concurrent} (Groundwork value: 4)", output)
            self.assertIn(f"Claude instance {instance} does not set {depth}", output)
        self.assertIn(f"Claude instance loose sets {depth} to a value other than 1", output)
        for name, want in ((concurrent, 4), (depth, 1)):
            self.assertIn(f"Claude instance hidden has {name} stored as a sensitive value or secret, "
                          f"so Groundwork cannot confirm it is {want}.", output)
        for instance in ("claudeAgent", "uncapped", "loose", "hidden"):
            self.assertIn(f"Fix it in T3 Code → Settings → Providers → {instance} → Environment variables: "
                          f"{concurrent}=4 and {depth}=1.", output)
        self.assertIn("Claude instance off is disabled; subagent caps not checked.", output)
        self.assertNotIn("Providers → off", output)
        self.assertNotIn("grok", output)
        for value in ("sk-never-print-this", "never-print-ref", "31337", "20"):
            self.assertNotIn(value, output)
        # Report only: T3's settings are never written.
        self.assertEqual((self.settings.stat().st_mtime_ns, self.settings.read_text()), (mtime, text))

    def test_subagent_caps_without_t3_or_settings(self):
        self.assertIn("not found; subagent caps not applicable", self.caps_report())
        self.t3.mkdir()
        output = self.caps_report()
        self.assertIn("Claude instance claudeAgent does not set CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", output)
        self.assertIn("Providers → claudeAgent → Environment variables", output)

    def test_subagent_caps_follow_how_t3_enables_an_instance(self):
        self.write_settings({
            "providerInstances": {
                "claudeAgent": {"driver": "claudeAgent", "config": {"enabled": False}},
                "project_only": self.claude_instance(enabled=False),
            },
            # Disabled globally but enabled for one project: it still runs there.
            "projectSettingsOverrides": {"p1": {"providerInstances": {"project_only": {"enabled": True}}},
                                         "p2": None},
        })
        output = self.caps_report()
        self.assertIn("Claude instance claudeAgent is disabled; subagent caps not checked.", output)
        self.assertNotIn("Providers → claudeAgent", output)
        self.assertIn("Claude instance project_only does not set CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", output)
        self.assertIn("Fix it in T3 Code → Settings → Providers → project_only → Environment variables", output)

    def test_subagent_caps_unrecognized_settings_are_reported(self):
        mtime, text = self.write_settings({"providerInstances": {
            "c": self.claude_instance(environment={"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"})}})
        output = self.caps_report()
        self.assertIn("not in a format Groundwork recognizes, so the Claude subagent caps were not checked", output)
        self.assertEqual((self.settings.stat().st_mtime_ns, self.settings.read_text()), (mtime, text))

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
        self.assertIn("T3 Code warning: Claude instance claudeAgent does not set "
                      "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", result.stdout)
        self.assertRegex(DOCTOR.read_text(), re.compile(r"T3 Code's settings are read, never changed"))


if __name__ == "__main__":
    unittest.main()
