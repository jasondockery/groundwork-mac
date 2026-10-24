# iMessage gateway on a desktop Mac

This page is for a desktop Mac that should stay reachable as the iMessage gateway for [Blip](https://github.com/nixfred/blip), an iMessage client on another machine. The client side is [groundwork-omarchy-mac-arm64#21](https://github.com/jasondockery/groundwork-omarchy-mac-arm64/issues/21). Groundwork here only turns on Remote Login and stops system sleep while the Mac is on power. You still click the privacy grants yourself. The role is off until you turn it on.

Blip needs a Mac that is signed in to Messages, with Messages in iCloud on, and that accepts an SSH key. It reads the Messages database and drives Messages through the privacy grants macOS gives `sshd`. Nothing extra runs on the Mac outside that SSH session. System Integrity Protection stays on.

## Why OpenSSH, not Tailscale SSH

Desktop Macs install the Tailscale app. That app cannot serve Tailscale SSH. Use ordinary OpenSSH over the Mac's MagicDNS name, which is the path [Remote access](remote-access.md) already describes. Blip's Full Disk Access grant is on `/usr/libexec/sshd-keygen-wrapper`, and its confined key uses OpenSSH `authorized_keys` options. Tailscale SSH would skip both. This role does not install the open-source tailscaled variant.

## Turn the role on

The preference is `imessage_gateway` in the chezmoi config. It defaults to false, including on a machine that already has Groundwork. Setup does not ask the question. Change it with `groundwork-configure`, then apply. The menu shows the choice on every platform so a saved answer is not dropped, and it tells you the effect is desktop-Mac only.

Linux, WSL, a headless Mac, and Omarchy do not apply the role. Omarchy must not run this engine; its client setup lives in the Omarchy repository.

With the role off, an apply does not call the helper. With it on, a desktop apply runs `groundwork-imessage-gateway prepare`.

## What changes

| Setting | macOS default | This role | Reason |
| --- | --- | --- | --- |
| Remote Login (OpenSSH) | off | on | Blip's only transport. The Tailscale app cannot serve Tailscale SSH. |
| `pmset -c sleep` (on power) | the system sleeps after idle | `0` | A sleeping gateway takes Blip offline. `-c` leaves battery sleep unchanged, so a laptop off the charger does not drain flat. |

`prepare` reads the current on-power sleep value and, the first time it changes it, writes that integer to `~/.local/state/groundwork/imessage-gateway-ac-sleep` (or `$XDG_STATE_HOME/groundwork/` when that variable is set). A later run keeps the original number. `status` prints it.

These stay manual. Groundwork does not set them:

- `pmset -c disablesleep 1` for lid-closed operation. A laptop in a bag would stay awake.
- Screen saver `idleTime 0`, which keeps the screen unlocked.
- Auto-login, FileVault, and wake-on-LAN (`womp`).
- Amphetamine and `caffeinate`.

Privileged steps use Groundwork's administrator-password helper. If the apply has no terminal that can ask, Remote Login and the sleep change are left as they are and the next apply from a terminal tries again. Cancelling the password prompt stops that apply. If `systemsetup` refuses because the terminal lacks Full Disk Access, Groundwork opens System Settings → General → Sharing and does not bypass that privacy check.

## Check without changing anything

```bash
groundwork-imessage-gateway status
```

`status` reports Remote Login (`launchctl print system/com.openssh.sshd`), whether SSH is limited to selected users, on-power and battery sleep (`pmset -g custom`), whether the Tailscale app is running, and the recorded previous sleep value. If `~/.blip/bin/blip-check` exists, status says it is installed and prints the command Blip wants from the client: `ssh <host> 'python3 "$HOME/.blip/bin/blip-check"'`. `<host>` is this Mac's SSH name. That Messages probe can raise the one-time Allow prompt, so status does not run it.

```bash
groundwork-imessage-gateway
```

With no argument, `setup` opens Sharing and Privacy & Security and prints the manual steps. `prepare` is the apply action.

From the client, after Remote Login and your everyday key work:

```bash
ssh GATEWAY_USER@GATEWAY_MAGICDNS_NAME true
```

After `blip-setup` and the two clicks below, `blip-check` should be all green, and a message to your own number should send and arrive.

## Manual steps

1. Sign in to Messages with the Apple ID, and turn on Messages in iCloud.
2. Approve the Tailscale app, its network extension, and the device. Add an owner-scoped grant that lets only the client machine reach this Mac on TCP port 22. Policy lives in the [shared Tailscale guide](https://github.com/jasondockery/groundwork-core/blob/main/docs/tailscale.md).
3. Authorize the client's everyday SSH key for the gateway account. Groundwork does not manage `authorized_keys`. `blip-setup` owns its confined line (`restrict`, no shell, no forwarding, no pty, and a fixed command). Limit Remote Login to the gateway account alone. Groundwork reports that list and does not change it.
4. While `blip-setup` waits on the client:
   - Full Disk Access: add `/usr/libexec/sshd-keygen-wrapper`. In the file picker, press Command-Shift-G and paste that path.
   - Automation → Messages: click Allow within about two minutes. An unanswered prompt is stored as a denial. Recovery is `tccutil reset AppleEvents`, which resets Automation grants for every app, then run `blip-setup` again while you are at the Mac.
5. Optional:
   - From the client, run `ssh <host> 'python3 "$HOME/.blip/bin/blip-check" --markread'` for mark-read and Blip's experimental tapbacks. This Mac is only where the Allow prompt is clicked. The prompt asks for Accessibility and Automation → System Events. Leave tapbacks off unless you want that extra grant.
   - Contacts, if you want Blip to save contacts.
6. Keep the Mac on power, lid open or with an external display attached, at a logged-in desktop.

Full Disk Access is per `sshd-keygen-wrapper`, not per key. After you grant it, every key that can open a shell on that account can read Messages. `blip-setup` needs an everyday key to enroll its confined key, and that everyday key keeps this reach. Keep other authorized keys few. Upstream detail is in [Blip's security notes](https://github.com/nixfred/blip/blob/main/docs/SECURITY.md).

## When the gateway looks offline

| What the Mac is doing | What Blip can do |
| --- | --- |
| Asleep | Blip goes offline. Nothing is lost; it catches up when the Mac wakes. |
| At the login window | Blip can read and cannot send. |
| Locked | Messages keep flowing. Only the per-thread read push stops. |

`sleep 0` does not keep a closed lid awake unless an external display is attached. Do not set `disablesleep` for a laptop that might go in a bag. Wake-on-LAN does not reliably wake a Mac for SSH over Tailscale.

## Undo

Turn the role off and apply before restoring sleep. An apply with the role still on sets on-power sleep back to 0.

1. In `groundwork-configure`, turn the iMessage gateway role off.
2. Run `chezmoi apply`.
3. Restore the recorded on-power sleep value with the checks below.
4. Turn Remote Login off in System Settings → General → Sharing if you no longer want it.

The record must be a regular file and not a symlink. Do not use `cat`; it follows symlinks. Read the file only after that check. Its text, without the recorder's single trailing newline, must match `^(0|[1-9][0-9]{0,5})$`. Pass only that integer to `sudo pmset -c sleep`.

```bash
record="${XDG_STATE_HOME:-$HOME/.local/state}/groundwork/imessage-gateway-ac-sleep"
if [[ -L "$record" || ! -f "$record" ]]; then
  printf 'Refusing to restore sleep: %s must be a regular file and not a symlink.\n' "$record" >&2
else
  value=""
  extra_present=0
  {
    IFS= read -r value || true
    if IFS= read -r _; then
      extra_present=1
    fi
  } < "$record"
  if [[ "$extra_present" -ne 0 || ! "$value" =~ ^(0|[1-9][0-9]{0,5})$ ]]; then
    printf 'Refusing to restore sleep: %s must contain one integer matching ^(0|[1-9][0-9]{0,5})$.\n' "$record" >&2
  else
    sudo pmset -c sleep "$value"
  fi
fi
```

To revoke the privacy grants, open Privacy & Security and remove the `sshd-keygen-wrapper` entries under Full Disk Access and Automation. Also remove Accessibility and Contacts entries if you added them. Groundwork does not edit the privacy database. `tccutil reset AppleEvents` is the broad Automation reset above; it is not limited to this role.

Removing the client is Blip's own procedure: [Removing Blip](https://github.com/nixfred/blip/blob/main/README.md#removing-blip). That removes Blip's confined `authorized_keys` line and `~/.blip`. It does not remove your everyday key, and it does not revoke the `sshd` privacy grants.

## What this role does not do

System Integrity Protection stays on. Groundwork does not install or automate the BlueBubbles server. BlueBubbles can run with System Integrity Protection on, but its Private API (tapbacks, edits, effects, replies) needs that protection off. That path is manual and optional; this role does not take it. Beeper's iMessage connection is on-device in Beeper Desktop for Mac only. OpenBubbles is a separate implementation and is not part of this gateway.
