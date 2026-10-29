#!/usr/bin/env python3
"""Render Groundwork's Brave policy from the shared spec.

core/browser/brave.json is the only list of policy overrides and extension
offers. This module does not keep a second copy. It drops nothing that the
spec includes, and it writes only name and value into the profile.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
BITWARDEN_WHEN = "Bitwarden is the password manager."
PROFILE_IDENTIFIER = "com.groundwork.brave.browser"
PAYLOAD_IDENTIFIER = "com.groundwork.brave.browser.policies"
PROFILE_UUID = "6f0e2c4a-9b17-4d58-8e31-0a7c5b2d4e60"
PAYLOAD_UUID = "6f0e2c4a-9b17-4d58-8e31-0a7c5b2d4e61"
BRAVE_PAYLOAD_TYPE = "com.brave.Browser"
EXTENSION_ID = r"^[a-p]{32}$"


class SpecError(Exception):
    """The shared spec is missing, malformed, or not safe to render."""


class UsageError(Exception):
    """The command line is not a valid invocation."""


def load_spec(path: Path) -> dict:
    if not path.is_file():
        raise SpecError(f"Brave spec is missing: {path}")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SpecError(f"Brave spec could not be read: {path}") from error
    if not isinstance(spec, dict):
        raise SpecError("Brave spec must be a JSON object")
    if spec.get("schemaVersion") != SCHEMA_VERSION:
        raise SpecError(
            f"Brave spec schemaVersion must be {SCHEMA_VERSION}"
        )
    if not isinstance(spec.get("policies"), list):
        raise SpecError("Brave spec policies must be a list")
    if not isinstance(spec.get("extensions"), list):
        raise SpecError("Brave spec extensions must be a list")
    default = spec.get("default")
    if not isinstance(default, dict):
        raise SpecError("Brave spec default must be an object")
    desktop_ids = default.get("desktopIds")
    if not isinstance(desktop_ids, dict) or not isinstance(
        desktop_ids.get("macos"), str
    ):
        raise SpecError("Brave spec default.desktopIds.macos must be a string")
    return spec


def handler_name(spec: dict) -> str:
    bundle_id = spec["default"]["desktopIds"]["macos"]
    if "." not in bundle_id or bundle_id.endswith("."):
        raise SpecError(f"Brave macOS bundle id is not usable: {bundle_id}")
    handler = bundle_id.rsplit(".", 1)[-1].lower()
    if not handler or not handler.isascii() or not handler.isalnum():
        raise SpecError(f"Brave default-browser handler is not usable: {handler}")
    return handler


def _policy_applies(entry: dict, password_manager: str) -> bool:
    if "when" not in entry:
        return True
    condition = entry["when"]
    if condition == BITWARDEN_WHEN:
        return password_manager == "bitwarden"
    raise SpecError(f"unknown Brave policy condition: {condition!r}")


def applicable_policies(spec: dict, password_manager: str) -> list[dict]:
    if password_manager not in {"bitwarden", "1password", "none"}:
        raise SpecError(f"unknown password manager: {password_manager}")
    policies = []
    seen = set()
    for entry in spec["policies"]:
        if not isinstance(entry, dict):
            raise SpecError("a Brave policy entry is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name.isascii() or not name.isidentifier():
            raise SpecError(f"Brave policy name is not usable: {name!r}")
        if name in seen:
            raise SpecError(f"Brave policy name is duplicated: {name}")
        seen.add(name)
        if "value" not in entry or not isinstance(entry["value"], bool):
            raise SpecError(f"Brave policy {name} must have a boolean value")
        if "reason" not in entry or not isinstance(entry["reason"], str) or not entry["reason"]:
            raise SpecError(f"Brave policy {name} is missing its reason")
        if not isinstance(entry.get("upstreamDefault"), bool):
            raise SpecError(f"Brave policy {name} must have a boolean upstreamDefault")
        if entry["upstreamDefault"] == entry["value"]:
            raise SpecError(
                f"Brave policy {name} restates the upstream default and is not a Groundwork choice"
            )
        if not _policy_applies(entry, password_manager):
            continue
        policies.append({"name": name, "value": entry["value"]})
    return policies


_BOOLEAN_POLICY = re.compile(
    r"<key>([^<]+)</key>\s*<(true|false)\s*/>",
    re.IGNORECASE,
)


def boolean_policy_values(text: str) -> dict[str, bool] | None:
    """Non-metadata boolean keys. None when one key is both true and false."""
    found: dict[str, bool] = {}
    for name, raw in _BOOLEAN_POLICY.findall(text):
        name = name.strip()
        if not name or name.startswith("Payload"):
            continue
        value = raw.lower() == "true"
        if name in found and found[name] is not value:
            return None
        found[name] = value
    return found


def payload_match_status(rendered: str, profiles_output: str) -> int:
    """0 when the installed payload matches this render, 1 when the profile
    identifier is absent, 3 when the identifier is present but the policy
    values are not this render.
    """
    if PROFILE_IDENTIFIER not in profiles_output:
        return 1
    expected = boolean_policy_values(rendered)
    installed = boolean_policy_values(profiles_output)
    if not expected or installed is None:
        return 3
    for name, value in expected.items():
        if installed.get(name) is not value:
            return 3
    return 0


def extension_offers(spec: dict) -> list[dict]:
    import re

    offers = []
    seen = set()
    for entry in spec["extensions"]:
        if not isinstance(entry, dict):
            raise SpecError("a Brave extension entry is not an object")
        install = entry.get("install")
        if install != "offer":
            raise SpecError(
                f"Brave extension install must be offer, not {install!r}"
            )
        extension_id = entry.get("id")
        if not isinstance(extension_id, str) or re.fullmatch(EXTENSION_ID, extension_id) is None:
            raise SpecError(f"Brave extension id is not usable: {extension_id!r}")
        if extension_id in seen:
            raise SpecError(f"Brave extension id is duplicated: {extension_id}")
        seen.add(extension_id)
        update_url = entry.get("updateUrl")
        if (
            not isinstance(update_url, str)
            or not update_url.startswith("https://")
            or any(character.isspace() for character in update_url)
            or '"' in update_url
        ):
            raise SpecError(f"Brave extension update URL is not usable: {update_url!r}")
        name = entry.get("name")
        if not isinstance(name, str) or not name or "\n" in name:
            raise SpecError(f"Brave extension name is not usable: {name!r}")
        offers.append(
            {"name": name, "id": extension_id, "updateUrl": update_url}
        )
    return offers


def render_mobileconfig(policies: list[dict]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        "<dict>",
        "  <key>PayloadContent</key>",
        "  <array>",
        "    <dict>",
        "      <key>PayloadDisplayName</key>",
        "      <string>Brave Browser</string>",
        "      <key>PayloadIdentifier</key>",
        f"      <string>{PAYLOAD_IDENTIFIER}</string>",
        "      <key>PayloadType</key>",
        f"      <string>{BRAVE_PAYLOAD_TYPE}</string>",
        "      <key>PayloadUUID</key>",
        f"      <string>{PAYLOAD_UUID}</string>",
        "      <key>PayloadVersion</key>",
        "      <integer>1</integer>",
    ]
    for policy in policies:
        value = "true" if policy["value"] else "false"
        lines.append(f"      <key>{policy['name']}</key>")
        lines.append(f"      <{value}/>")
    lines.extend(
        [
            "    </dict>",
            "  </array>",
            "  <key>PayloadDisplayName</key>",
            "  <string>Groundwork Brave Browser</string>",
            "  <key>PayloadDescription</key>",
            "  <string>Brave policies from the shared Groundwork spec. Installing this profile needs your approval in System Settings.</string>",
            "  <key>PayloadIdentifier</key>",
            f"  <string>{PROFILE_IDENTIFIER}</string>",
            "  <key>PayloadRemovalDisallowed</key>",
            "  <false/>",
            "  <key>PayloadScope</key>",
            "  <string>User</string>",
            "  <key>PayloadType</key>",
            "  <string>Configuration</string>",
            "  <key>PayloadUUID</key>",
            f"  <string>{PROFILE_UUID}</string>",
            "  <key>PayloadVersion</key>",
            "  <integer>1</integer>",
            "</dict>",
            "</plist>",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brave_browser.py", add_help=True, exit_on_error=False
    )

    def usage_error(message: str) -> None:
        parser.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise UsageError(message)

    parser.error = usage_error  # type: ignore[method-assign]
    sub = parser.add_subparsers(dest="command", required=True)

    def add_spec(command: argparse.ArgumentParser, password: bool = False) -> None:
        command.add_argument("--spec", required=True, type=Path)
        if password:
            command.add_argument("--password-manager", required=True)

    add_spec(sub.add_parser("handler", help="print the defaultbrowser handler"))
    add_spec(
        sub.add_parser("policies", help="print applicable policies as JSON"),
        password=True,
    )
    add_spec(
        sub.add_parser("mobileconfig", help="print a com.brave.Browser configuration profile"),
        password=True,
    )
    add_spec(sub.add_parser("extensions", help="print extension offers as JSON"))
    payload = sub.add_parser(
        "payload-matches",
        help="exit 0 when profiles output contains this render's policy values",
    )
    payload.add_argument("--mobileconfig", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except (argparse.ArgumentError, UsageError):
        return 64
    try:
        if args.command == "payload-matches":
            try:
                rendered = args.mobileconfig.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                print(f"groundwork-brave-browser: {error}", file=sys.stderr)
                return 1
            return payload_match_status(rendered, sys.stdin.read())
        spec = load_spec(args.spec)
        if args.command == "handler":
            print(handler_name(spec))
        elif args.command == "policies":
            json.dump(applicable_policies(spec, args.password_manager), sys.stdout)
            print()
        elif args.command == "mobileconfig":
            policies = applicable_policies(spec, args.password_manager)
            sys.stdout.write(render_mobileconfig(policies))
        elif args.command == "extensions":
            json.dump(extension_offers(spec), sys.stdout)
            print()
        else:
            return 64
    except SpecError as error:
        print(f"groundwork-brave-browser: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
