# Remote access on Mac, Linux, and WSL

The [shared Tailscale guide](https://github.com/jasondockery/groundwork-core/blob/main/docs/tailscale.md) owns tailnet policy, MFA, device approval, MagicDNS, key expiry, private tunnels, and two-way acceptance. This page owns setup for this repository's shared provisioning engine. Omarchy uses its dedicated repository and never applies this engine.

## Desktop Mac

The Brewfile installs `tailscale-app`. That installer needs an administrator password. When you run the apply from a terminal, Groundwork asks once at the start. When no terminal can ask, the app is set aside, the rest of setup continues, and the next `chezmoi apply` from a terminal installs it. Launch Tailscale, sign in locally, approve its network extension and device when requested, and enable MagicDNS in the tailnet. The app manages split DNS; Groundwork no longer forces `/etc/resolver/ts.net`. During an apply, only the exact old Groundwork resolver is moved to a root-owned `/etc/groundwork-tailscale-resolver.*` recovery directory. Custom resolver files and symlinks stay untouched.

For inbound terminal access, enable System Settings → General → Sharing → Remote Login and select only the local users who need access. The macOS GUI app cannot serve Tailscale SSH. Use normal OpenSSH over the device's MagicDNS name, with your existing per-account SSH keys and the shared guide's network grant. Keep local SSH ownership separate from GitHub account authentication. Screen Sharing is an optional, separate service; restrict its allowed users and reach it through Tailscale.

Do not install the headless formula alongside the desktop cask. Use the app to diagnose sign-in and DNS, then test `tailscale status` and a connection from another approved machine before relying on remote recovery.

## Headless Mac and Linux

The shared engine installs Homebrew on supported headless Macs and x86_64/ARM64 Linux, then installs the `tailscale` formula. Choose the service owner before starting a daemon; do not start a Homebrew daemon alongside an existing native service.

For a Homebrew-owned installation, start the service with the full executable path so sudo does not need Homebrew on its PATH:

```bash
sudo "$(command -v brew)" services start tailscale
sudo "$(command -v tailscale)" up --timeout=5m
```

For Linux without Homebrew, first install the stable package using the [official instructions for your distribution and release](https://pkgs.tailscale.com/stable/) ([Linux installation guide](https://tailscale.com/docs/install/linux)). This is an alternative for a machine using native packages; Groundwork does not install that native package automatically. On an Ubuntu host with systemd, enable its native service and then sign in:

```bash
sudo systemctl enable --now tailscaled
sudo tailscale up --timeout=5m
```

Use this host-service path on a real machine with its init system, not inside a development container. WSL uses the Windows-host steps below unless you deliberately enroll the distribution separately. A headless Mac adopted without Homebrew needs Homebrew for the formula path, or an administrator-managed [open-source macOS daemon installation](https://tailscale.com/docs/concepts/macos-variants#open-source-tailscaled-variant).

Open the sign-in URL and complete device approval. Preserve existing options if `up` requests them; avoid `--reset`. Review the shared guide's SSH check-mode policy before enabling incoming Tailscale SSH:

```bash
sudo "$(command -v tailscale)" set --ssh
tailscale status
```

The macOS open-source daemon and Linux can serve Tailscale SSH. It handles port 22 on the Tailscale interface; an internet-facing SSH port, router forwarding, Funnel, and an exit node are unnecessary for machine-to-machine terminal access. Keep an existing remote session open while testing changes through a second connection.

Homebrew owns Herdr and the common coding CLIs on supported headless machines. The Herdr fallback hook only installs a missing command and leaves existing package ownership intact. Provider sign-in and remote sessions still require local setup.

## Windows and WSL2

Use [groundwork-windows](https://github.com/jasondockery/groundwork-windows) for its Windows-host Tailscale/OpenSSH steps and WSL2 entrypoint. The host and a separately enrolled WSL distribution are different destinations. Applying the Linux engine inside WSL does not enable Windows services or grant host permissions.

## Acceptance

From each machine, use `tailscale ping MACHINE`, then `ssh LOCAL_USER@MACHINE`, replacing the placeholders. Confirm `hostname` in the remote shell. Ping proves the network path; it does not prove SSH policy. Repeat in both directions, then attach to tmux or Herdr. Keep T3 Code Nightly on loopback and use the shared guide's tunnel with the actual listening port. Test after sleep or reboot before calling a machine remotely accepted. Authentication, policy approval, and physical wake are local acceptance steps, not installer claims.
