#!/usr/bin/env python3
"""The commit identity guard installs at user level, preserves user choices, and is idempotent.

Every test runs against a fixture HOME. The pinned guard is core/commit-guard.
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "home/dot_local/share/groundwork/lib/commit-identity-install.sh"
GUARD = REPO / "core/commit-guard/commit-identity-guard.sh"
DOCTOR = REPO / "home/dot_local/bin/executable_groundwork-doctor"
RUN_AFTER = REPO / "home/run_after_24-commit-identity-guard.sh.tmpl"


OWNED = {
    "ssh": "git@github.com:jasondockery/fixture.git",
    "https": "https://github.com/jasondockery/fixture.git",
    "ssh-url": "ssh://git@github.com/jasondockery/fixture.git",
    "mixed-case": "https://github.com/JasonDockery/fixture.git",
    "alias": "git@github-personal:jasondockery/x.git",
    "alias-mixed-case": "git@github-personal:JasonDockery/x.git",
}
EMPLOYER = "git@github.com:example-employer/fixture.git"
NOT_OWNED = {
    "alias-employer": "git@github-personal:EmployerCorp/x.git",
    "alias-longer-owner": "git@github-personal:jasondockery2/x",
    "https-longer-owner": "https://github.com/jasondockery2/x.git",
}
BAD_MESSAGE = "m\n\nCo-authored-by: A <a@example.com>"


class CommitIdentityInstallTests(unittest.TestCase):
    def setUp(self):
        if not GUARD.exists():
            if os.environ.get("CI"):
                self.fail("core submodule is not checked out")
            self.skipTest("core submodule is not checked out")
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-commit-guard-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.gw = self.home / ".config/groundwork"
        self.hooks = self.gw / "git-hooks"
        self.settings = self.home / ".claude/settings.json"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def run_install(self, **extra):
        env = dict(self.env, **extra)
        return subprocess.run(
            ["bash", str(INSTALL), "--guard", str(GUARD)],
            env=env, text=True, capture_output=True, timeout=30,
        )

    def git(self, *args, cwd=None, **extra):
        env = dict(self.env, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com")
        env.update(extra)
        return subprocess.run(["git", *args], cwd=cwd or self.home, env=env,
                              text=True, capture_output=True, timeout=30)

    def snapshot(self):
        out = {}
        for path in sorted(self.home.rglob("*")):
            if path.is_symlink():
                out[str(path)] = ("link", os.readlink(path))
            elif path.is_file():
                out[str(path)] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
        return out

    def make_repo(self, remote=OWNED["ssh"], name="repo"):
        repo = self.home / name
        repo.mkdir()
        self.git("init", "-q", "-b", "main", cwd=repo)
        if remote:
            self.git("remote", "add", "origin", remote, cwd=repo)
        (repo / "f").write_text("x")
        self.git("add", "f", cwd=repo)
        return repo

    def test_install_sets_hooks_denylist_and_attribution(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.hooks / "commit-identity-guard.sh"), str(GUARD))
        for name in ("commit-msg", "pre-push", "pre-commit"):
            self.assertEqual(os.readlink(self.hooks / name), "dispatch")
        self.assertTrue(os.access(self.hooks / "dispatch", os.X_OK))
        self.assertEqual(self.git("config", "--global", "core.hooksPath").stdout.strip(), "")
        include = (self.gw / "commit-guard.gitconfig").read_text()
        self.assertIn(str(self.hooks), include)
        includes = self.git("config", "--file", str(self.home / ".config/git/config"),
                            "--get-regexp", r"^includeif\..*\.path$").stdout.splitlines()
        self.assertEqual(len(includes), 4)
        self.assertFalse((self.home / ".gitconfig").exists())
        self.assertEqual((self.gw / "commit-denylist").read_text(), "")
        self.assertEqual(json.loads(self.settings.read_text()), {"attribution": {"commit": "", "pr": ""}})

    def test_installed_hook_blocks_coauthor_and_keeps_repo_hook(self):
        self.run_install()
        repo = self.make_repo()
        marker = self.home / "repo-hook-ran"
        hook = repo / ".git/hooks/pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        bad = self.git("commit", "-q", "-m", "msg\n\nCo-authored-by: Someone <s@example.com>", cwd=repo)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Co-authored-by", bad.stderr)
        self.assertIn("commit-guard-off", bad.stderr)
        self.assertTrue(marker.exists(), "the repository's own pre-commit hook still runs")
        good = self.git("commit", "-q", "-m", "clean message", cwd=repo)
        self.assertEqual(good.returncode, 0, good.stderr)

    def test_denylist_value_blocks_identity_without_repo_supplied_values(self):
        self.run_install()
        (self.gw / "commit-denylist").write_text("blocked-fixture-name\n")
        repo = self.make_repo()
        result = self.git("commit", "-q", "-m", "m", cwd=repo, GIT_AUTHOR_NAME="Blocked-Fixture-Name")
        self.assertNotEqual(result.returncode, 0)

    def test_existing_hookspath_is_preserved(self):
        (self.home / ".gitconfig").write_text("[core]\n\thooksPath = /somewhere/else\n")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already set to /somewhere/else", result.stdout)
        self.assertEqual(self.git("config", "--global", "core.hooksPath").stdout.strip(), "/somewhere/else")
        self.assertFalse((self.home / ".config/git/config").exists())
        self.assertEqual((self.home / ".gitconfig").read_text(), "[core]\n\thooksPath = /somewhere/else\n")

    def test_gitconfig_hookspath_set_later_overrides_ours(self):
        self.run_install()
        (self.home / ".gitconfig").write_text("[core]\n\thooksPath = /mine\n")
        self.assertEqual(self.git("config", "--global", "core.hooksPath").stdout.strip(), "/mine")

    def test_existing_attribution_is_preserved(self):
        self.settings.parent.mkdir(parents=True)
        original = {"model": "x", "attribution": {"commit": "Mine", "other": 1}, "hooks": {"a": [1]}}
        self.settings.write_text(json.dumps(original))
        self.run_install()
        merged = json.loads(self.settings.read_text())
        self.assertEqual(merged["attribution"], {"commit": "Mine", "other": 1, "pr": ""})
        self.assertEqual(merged["model"], "x")
        self.assertEqual(merged["hooks"], {"a": [1]})

    def test_fully_set_attribution_is_not_rewritten(self):
        self.settings.parent.mkdir(parents=True)
        text = json.dumps({"attribution": {"commit": "A", "pr": "B"}})
        self.settings.write_text(text)
        self.run_install()
        self.assertEqual(self.settings.read_text(), text)
        self.assertEqual(list(self.settings.parent.glob("settings.json.bak.*")), [])

    def test_json_merge_keeps_keys_and_numbered_backups(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('{"env": {"A": "1"}, "permissions": {"allow": ["x"]}}')
        self.settings.chmod(0o600)
        self.run_install()
        first = json.loads(self.settings.read_text())
        self.assertEqual(first["env"], {"A": "1"})
        self.assertEqual(first["permissions"], {"allow": ["x"]})
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        self.assertEqual(json.loads((self.settings.parent / "settings.json.bak.1").read_text())["env"], {"A": "1"})
        # A second merge needs a key to fill, so a numbered backup does not overwrite the first.
        self.settings.write_text('{"attribution": {}, "k": 1}')
        self.run_install()
        self.assertTrue((self.settings.parent / "settings.json.bak.2").exists())
        self.assertTrue((self.settings.parent / "settings.json.bak.1").exists())

    def test_invalid_settings_json_is_left_untouched(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("{not json")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.settings.read_text(), "{not json")
        self.assertIn("not a JSON object", result.stdout)

    def test_existing_denylist_is_not_touched(self):
        self.gw.mkdir(parents=True)
        (self.gw / "commit-denylist").write_text("keep-me\n")
        self.run_install()
        self.assertEqual((self.gw / "commit-denylist").read_text(), "keep-me\n")

    def test_rerun_changes_nothing_and_prints_nothing(self):
        self.run_install()
        before = self.snapshot()
        again = self.run_install()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout, "")
        self.assertEqual(self.snapshot(), before)

    def test_xdg_config_home_is_honored(self):
        xdg = Path(self.temp.name) / "xdg"
        result = self.run_install(XDG_CONFIG_HOME=str(xdg))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((xdg / "groundwork/commit-denylist").exists())
        self.assertTrue((xdg / "groundwork/git-hooks/pre-push").is_symlink())
        self.assertFalse((self.home / ".config/groundwork").exists())

    def test_opt_out_installs_nothing(self):
        self.gw.mkdir(parents=True)
        (self.gw / "commit-guard-off").write_text("")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("opted out", result.stdout)
        self.assertFalse(self.hooks.exists())
        self.assertFalse(self.settings.exists())
        self.assertFalse((self.gw / "commit-denylist").exists())

    def test_opt_out_flag_and_env_disable_installed_hooks(self):
        self.run_install()
        repo = self.make_repo()
        msg = "m\n\nCo-authored-by: A <a@example.com>"
        env_off = self.git("commit", "-q", "-m", msg, cwd=repo, GROUNDWORK_COMMIT_GUARD="off")
        self.assertEqual(env_off.returncode, 0, env_off.stderr)
        (repo / "g").write_text("y")
        self.git("add", "g", cwd=repo)
        (self.gw / "commit-guard-off").write_text("")
        flag_off = self.git("commit", "-q", "-m", msg, cwd=repo)
        self.assertEqual(flag_off.returncode, 0, flag_off.stderr)

    def test_pre_push_blocks_and_forwards_stdin_to_repo_hook(self):
        self.run_install()
        remote = self.home / "remote.git"
        self.git("init", "-q", "--bare", str(remote))
        repo = self.make_repo(remote=str(remote))
        self.git("remote", "add", "owned", OWNED["ssh"], cwd=repo)
        self.git("commit", "-q", "-m", "ok", cwd=repo)
        seen = self.home / "stdin-seen"
        hook = repo / ".git/hooks/pre-push"
        hook.write_text(f"#!/bin/sh\ncat > {seen}\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        pushed = self.git("push", "-q", "origin", "main", cwd=repo)
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        self.assertIn("refs/heads/main", seen.read_text())
        (repo / "g").write_text("y")
        self.git("add", "g", cwd=repo)
        self.git("commit", "-q", "--no-verify", "-m", "x\n\nco-authored-by: A <a@example.com>", cwd=repo)
        blocked = self.git("push", "-q", "origin", "main", cwd=repo)
        self.assertNotEqual(blocked.returncode, 0)

    def test_every_owned_url_form_is_blocked(self):
        self.run_install()
        for form, url in OWNED.items():
            repo = self.make_repo(remote=url, name="repo-" + form)
            result = self.git("commit", "-q", "-m", BAD_MESSAGE, cwd=repo)
            self.assertNotEqual(result.returncode, 0, form)
            self.assertIn("Co-authored-by", result.stderr, form)

    def test_employer_remote_and_other_repos_are_untouched(self):
        self.run_install()
        cases = [("employer", EMPLOYER), ("no-remote", None)] + list(NOT_OWNED.items())
        for name, remote in cases:
            repo = self.make_repo(remote=remote, name=name)
            result = self.git("commit", "-q", "-m", BAD_MESSAGE, cwd=repo)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.git("config", "--get", "core.hooksPath", cwd=repo).stdout.strip(), "")

    def test_userinfo_urls_are_not_matched(self):
        self.run_install()
        repo = self.make_repo(remote="https://user@github.com/jasondockery/x.git")
        self.assertEqual(self.git("commit", "-q", "-m", BAD_MESSAGE, cwd=repo).returncode, 0)

    def test_no_remote_commit_allowed_but_pre_push_catches_it_once_owned(self):
        self.run_install()
        remote = self.home / "remote.git"
        self.git("init", "-q", "--bare", str(remote))
        repo = self.make_repo(remote=str(remote))
        self.assertEqual(self.git("commit", "-q", "-m", BAD_MESSAGE, cwd=repo).returncode, 0)
        self.git("remote", "add", "owned", OWNED["https"], cwd=repo)
        blocked = self.git("push", "-q", "origin", "main", cwd=repo)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("Co-authored-by", blocked.stderr)

    def test_old_git_warns_and_activates_nothing(self):
        real = subprocess.run(["which", "git"], env=self.env, text=True, capture_output=True).stdout.strip()
        fakebin = Path(self.temp.name) / "fakebin"
        fakebin.mkdir()
        shim = fakebin / "git"
        shim.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "git version 2.30.2"; exit 0; fi\nexec {real} "$@"\n')
        shim.chmod(0o755)
        result = self.run_install(PATH=f"{fakebin}:{self.env['PATH']}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git 2.36 or newer", result.stdout)
        self.assertFalse((self.gw / "commit-guard.gitconfig").exists())
        self.assertFalse((self.home / ".config/git/config").exists())

    def test_missing_guard_target_warns(self):
        self.run_install()
        link = self.hooks / "commit-identity-guard.sh"
        link.unlink()
        link.symlink_to(self.home / "nowhere")
        repo = self.make_repo()
        result = self.git("commit", "-q", "-m", BAD_MESSAGE, cwd=repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pinned commit identity guard is missing", result.stderr)

    def test_previous_global_hookspath_from_this_installer_is_removed(self):
        xdg = self.home / ".config/git/config"
        xdg.parent.mkdir(parents=True)
        self.git("config", "--file", str(xdg), "core.hooksPath", str(self.hooks))
        self.run_install()
        self.assertEqual(self.git("config", "--global", "core.hooksPath").stdout.strip(), "")

    def test_doctor_lists_owned_repos_that_bypass_the_guard(self):
        self.run_install()
        code = self.home / "code"
        code.mkdir()
        bypass = code / "husky-repo"
        bypass.mkdir()
        self.git("init", "-q", cwd=bypass)
        self.git("remote", "add", "origin", OWNED["ssh"], cwd=bypass)
        self.git("config", "core.hooksPath", ".husky", cwd=bypass)
        fine = code / "plain-repo"
        fine.mkdir()
        self.git("init", "-q", cwd=fine)
        self.git("remote", "add", "origin", OWNED["ssh"], cwd=fine)
        result = subprocess.run(["bash", str(DOCTOR), "--commit-identity"], env=dict(self.env), text=True,
                                capture_output=True, timeout=30)
        self.assertIn("bypassed by its own core.hooksPath: " + str(bypass), result.stdout)
        self.assertNotIn(str(fine), result.stdout)

    def test_installer_writes_no_names_or_denylist_values(self):
        self.run_install()
        self.assertEqual((self.gw / "commit-denylist").stat().st_size, 0)
        written = sorted(
            str(p.relative_to(self.home)) for p in self.home.rglob("*") if p.is_file() and not p.is_symlink()
        )
        self.assertEqual(
            written,
            [".claude/settings.json", ".config/git/config", ".config/groundwork/commit-denylist",
             ".config/groundwork/commit-guard.gitconfig", ".config/groundwork/git-hooks/dispatch"],
        )
        for rel in written:
            text = (self.home / rel).read_text()
            if rel.endswith("settings.json") or rel.endswith("commit-guard.gitconfig"):
                self.assertNotIn("@", text, rel)

    def test_run_after_template_points_at_the_pinned_guard(self):
        result = subprocess.run(
            ["chezmoi", "--source", str(REPO), "execute-template"],
            input=RUN_AFTER.read_text(), text=True, capture_output=True, timeout=15,
            env=dict(self.env),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("core/commit-guard/commit-identity-guard.sh", result.stdout)
        self.assertIn("commit-identity-install.sh", result.stdout)

    def test_doctor_section_reports_guard_output(self):
        self.run_install()
        env = dict(self.env)
        result = subprocess.run(["bash", str(DOCTOR), "--commit-identity"], env=env, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("== Commit identity ==", result.stdout)
        self.assertIn("hooks apply to repositories with a github.com remote owned by this user", result.stdout)
        self.assertIn("Claude Code attribution commit and pr are empty", result.stdout)

    def test_doctor_reports_opt_out_and_missing_install(self):
        self.gw.mkdir(parents=True)
        (self.gw / "commit-guard-off").write_text("")
        result = subprocess.run(["bash", str(DOCTOR), "--commit-identity"], env=dict(self.env), text=True,
                                capture_output=True, timeout=30)
        self.assertIn("opted out", result.stdout)
        self.assertIn("not installed", result.stdout)


if __name__ == "__main__":
    unittest.main()
