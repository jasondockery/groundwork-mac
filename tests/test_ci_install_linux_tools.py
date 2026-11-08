#!/usr/bin/env python3
"""The Linux CI tool install recovers when the chezmoi website installer fails."""
import hashlib
import os
import stat
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci-install-linux-tools"

FAKE_UNAME = """#!/bin/sh
if [ "$1" = "-m" ]; then
  echo x86_64
  exit 0
fi
exec /usr/bin/uname "$@"
"""

FAKE_SUDO = """#!/bin/sh
exec "$@"
"""

FAKE_APT = """#!/bin/sh
exit 0
"""

FAKE_CURL = r"""#!/usr/bin/env bash
set -euo pipefail
out=""
url=""
args=("$@")
printf '%s\n' "$*" >>"$CURL_ARGV"
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    -o)
      i=$((i + 1))
      out="${args[$i]}"
      ;;
    --config)
      i=$((i + 1))
      cat "${args[$i]}" >>"$CURL_CONFIG_LOG"
      ;;
    -H)
      i=$((i + 1))
      ;;
    -*)
      ;;
    *)
      url="${args[$i]}"
      ;;
  esac
  i=$((i + 1))
done
printf '%s\n' "$url" >>"$CURL_LOG"
if [[ -n "${FIXTURE_CURL_FAIL:-}" && "$url" == *"$FIXTURE_CURL_FAIL"* ]]; then
  echo "curl: (22) fixture failure" >&2
  exit 22
fi
if [[ "$url" == *get.chezmoi.io* ]]; then
  cp "$FIXTURE_INSTALLER" "$out"
  exit 0
fi
if [[ "$url" == *"/releases/latest" ]]; then
  cp "$FIXTURE_RELEASE" "$out"
  exit 0
fi
if [[ "$url" == *"/assets/222" ]]; then
  cp "$FIXTURE_SUMS" "$out"
  exit 0
fi
if [[ "$url" == *"/assets/111" ]]; then
  cp "$FIXTURE_TARBALL" "$out"
  exit 0
fi
echo "unexpected curl url: $url" >&2
exit 1
"""


class CiInstallLinuxToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="groundwork-ci-install-")
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.fake = self.root / "fake-bin"
        self.bin.mkdir()
        self.fake.mkdir()
        self._write(self.fake / "uname", FAKE_UNAME)
        self._write(self.fake / "sudo", FAKE_SUDO)
        self._write(self.fake / "apt-get", FAKE_APT)
        self._write(self.fake / "curl", FAKE_CURL)
        self.curl_log = self.root / "curl.log"
        self.curl_log.write_text("")
        self.curl_argv = self.root / "curl-argv.log"
        self.curl_argv.write_text("")
        self.curl_config = self.root / "curl-config.log"
        self.curl_config.write_text("")

        payload = self.root / "payload"
        payload.mkdir()
        tool = payload / "chezmoi"
        tool.write_text("#!/bin/sh\necho chezmoi-from-api\n")
        tool.chmod(0o755)
        tarball = self.root / "chezmoi.tar.gz"
        with tarfile.open(tarball, "w:gz") as archive:
            archive.add(tool, arcname="chezmoi")
        digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
        sums = self.root / "checksums.txt"
        sums.write_text(f"{digest}  chezmoi_9.9.9_linux_amd64.tar.gz\n")
        release = self.root / "release.json"
        release.write_text(
            '{"tag_name":"v9.9.9","assets":['
            '{"name":"chezmoi_9.9.9_linux_amd64.tar.gz",'
            '"url":"https://api.github.com/repos/twpayne/chezmoi/releases/assets/111"},'
            '{"name":"chezmoi_9.9.9_checksums.txt",'
            '"url":"https://api.github.com/repos/twpayne/chezmoi/releases/assets/222"}'
            "]}"
        )
        self.tarball = tarball
        self.sums = sums
        self.release = release

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, path, text):
        path.write_text(textwrap.dedent(text))
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _env(self, installer):
        env = os.environ.copy()
        for key in ("GITHUB_TOKEN", "GH_TOKEN"):
            env.pop(key, None)
        env.update(
            {
                "PATH": f"{self.fake}:{env['PATH']}",
                "CI_INSTALL_BIN_DIR": str(self.bin),
                "TMPDIR": str(self.root),
                "CURL_LOG": str(self.curl_log),
                "CURL_ARGV": str(self.curl_argv),
                "CURL_CONFIG_LOG": str(self.curl_config),
                "FIXTURE_INSTALLER": str(installer),
                "FIXTURE_RELEASE": str(self.release),
                "FIXTURE_SUMS": str(self.sums),
                "FIXTURE_TARBALL": str(self.tarball),
            }
        )
        return env

    def _run(self, installer):
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env=self._env(installer),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_script_parses(self):
        syntax = subprocess.run(
            ["bash", "-n", str(SCRIPT)], text=True, capture_output=True, check=False
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_website_installer_is_used_when_it_succeeds(self):
        installer = self.root / "installer-ok.sh"
        self._write(
            installer,
            """
            #!/bin/sh
            dest=""
            while [ $# -gt 0 ]; do
              if [ "$1" = "-b" ]; then
                dest="$2"
                shift 2
                continue
              fi
              shift
            done
            printf '%s\\n' '#!/bin/sh' 'echo chezmoi-from-installer' > "$dest/chezmoi"
            chmod 755 "$dest/chezmoi"
            """,
        )
        result = self._run(installer)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.bin / "chezmoi").read_text().splitlines()[1],
            "echo chezmoi-from-installer",
        )
        urls = self.curl_log.read_text().splitlines()
        self.assertEqual(urls, ["get.chezmoi.io"])

    def test_api_install_runs_when_the_website_installer_fails(self):
        installer = self.root / "installer-fail.sh"
        self._write(installer, "#!/bin/sh\necho website-installer-failed >&2\nexit 22\n")
        result = self._run(installer)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("installing chezmoi from the GitHub API", result.stderr)
        installed = subprocess.run(
            [str(self.bin / "chezmoi")], text=True, capture_output=True, check=False
        )
        self.assertEqual(installed.stdout.strip(), "chezmoi-from-api")
        urls = self.curl_log.read_text().splitlines()
        self.assertIn("get.chezmoi.io", urls)
        self.assertIn("https://api.github.com/repos/twpayne/chezmoi/releases/latest", urls)
        self.assertTrue(any(url.endswith("/assets/111") for url in urls))
        self.assertTrue(any(url.endswith("/assets/222") for url in urls))

    def _failing_installer(self):
        installer = self.root / "installer-fail.sh"
        self._write(installer, "#!/bin/sh\necho website-installer-failed >&2\nexit 22\n")
        return installer

    def test_failed_retry_does_not_log_the_github_token(self):
        token = "fixture-secret-token"
        env = self._env(self._failing_installer())
        env["GITHUB_TOKEN"] = token
        env["FIXTURE_CURL_FAIL"] = "/releases/latest"
        env["CI_INSTALL_RETRY_DELAY_SECONDS"] = "0"
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("failed after 4 attempts", result.stderr)
        self.assertNotIn(token, result.stdout)
        self.assertNotIn(token, result.stderr)
        self.assertNotIn("Authorization", result.stderr)
        self.assertNotIn(token, self.curl_argv.read_text())
        self.assertIn(f'header = "Authorization: Bearer {token}"', self.curl_config.read_text())
        self.assertFalse((self.bin / "chezmoi").exists())

    def test_bad_checksum_does_not_install(self):
        self.sums.write_text("0000000000000000000000000000000000000000000000000000000000000000  chezmoi_9.9.9_linux_amd64.tar.gz\n")
        result = self._run(self._failing_installer())
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("did NOT match", result.stderr)
        self.assertIn("installing chezmoi from the GitHub API", result.stderr)
        self.assertFalse((self.bin / "chezmoi").exists())

    def test_checksum_file_that_omits_the_archive_does_not_install(self):
        digest = hashlib.sha256(self.tarball.read_bytes()).hexdigest()
        self.sums.write_text(f"{digest}  not-the-archive.tar.gz\n")
        result = self._run(self._failing_installer())
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("installing chezmoi from the GitHub API", result.stderr)
        self.assertNotIn("FAILED", result.stderr)
        self.assertFalse((self.bin / "chezmoi").exists())


if __name__ == "__main__":
    unittest.main()
