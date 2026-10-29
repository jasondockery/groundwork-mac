#!/usr/bin/env python3
"""Render Groundwork's Brave policy from the shared spec.

core/browser/brave.json is the only list of policy overrides and extension
offers. This module does not keep a second copy. It drops nothing that the
spec includes, and it writes only name and value into the profile.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import sys
import xml.parsers.expat
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


def policy_booleans(mapping: dict) -> dict[str, bool]:
    """Brave policy booleans. Payload metadata and non-booleans are not policies."""
    found: dict[str, bool] = {}
    for key, value in mapping.items():
        if isinstance(key, str) and not key.startswith("Payload") and isinstance(value, bool):
            found[key] = value
    return found


_PLIST_ERRORS = (
    plistlib.InvalidFileException,
    ValueError,
    TypeError,
    OverflowError,
    xml.parsers.expat.ExpatError,
)


def extract_plist_xml(text: str) -> str | None:
    """The first XML plist, ignoring text before it and after ``</plist>``.

    ``profiles show -output stdout-xml`` prints the plist and then a status
    sentence (``There are N configuration profiles installed``). A warning
    may also precede the document. Neither is part of the plist.
    """
    xml_at = text.find("<?xml")
    plist_at = text.find("<plist")
    starts = [index for index in (xml_at, plist_at) if index != -1]
    if not starts:
        return None
    start = min(starts)
    end = text.find("</plist>", start)
    if end == -1:
        return None
    return text[start : end + len("</plist>")]


def profiles_document(profiles_output: str) -> dict | None:
    """The profiles plist, or None when the output is not one."""
    xml_text = extract_plist_xml(profiles_output)
    if xml_text is None:
        return None
    try:
        document = plistlib.loads(xml_text.encode("utf-8"))
    except _PLIST_ERRORS:
        return None
    if not isinstance(document, dict):
        return None
    return document


def rendered_policy_booleans(rendered: str) -> dict[str, bool] | None:
    try:
        data = plistlib.loads(rendered.encode("utf-8"))
    except _PLIST_ERRORS:
        return None
    if not isinstance(data, dict):
        return None
    content = data.get("PayloadContent")
    found: dict[str, bool] = {}
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                found.update(policy_booleans(item))
    elif isinstance(content, dict):
        found.update(policy_booleans(content))
    return found


def _walk_profiles(node: object, found: list[dict]) -> None:
    if isinstance(node, dict):
        if node.get("ProfileIdentifier") == PROFILE_IDENTIFIER:
            found.append(node)
        for value in node.values():
            _walk_profiles(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk_profiles(value, found)


def profile_payload_booleans(profile: dict) -> dict[str, bool]:
    """Booleans from this profile's payload only, not from any other profile.

    ``profiles show -output stdout-xml`` nests each profile under
    ProfileIdentifier and its payloads under ProfileItems. Direct
    com.brave.Browser settings are keys of that item's PayloadContent, beside
    PayloadType. A dump that omits PayloadContent leaves those same bools
    beside PayloadType. Managed-preferences values sit under
    PayloadContentManagedPreferences and are not this policy set.
    """
    found: dict[str, bool] = {}
    items = profile.get("ProfileItems")
    if not isinstance(items, list):
        return found
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("PayloadContent")
        if isinstance(content, dict):
            found.update(policy_booleans(content))
        elif isinstance(content, list):
            for nested in content:
                if not isinstance(nested, dict):
                    continue
                nested_content = nested.get("PayloadContent")
                if isinstance(nested_content, dict):
                    found.update(policy_booleans(nested_content))
                else:
                    found.update(policy_booleans(nested))
        else:
            found.update(policy_booleans(item))
    return found


def payload_match_status(rendered: str | None, profiles_output: str) -> int:
    """0 when that profile's policy set equals this render.

    1: a profiles plist was read and com.groundwork.brave.browser is absent.
    3: that profile is present and its policy set is not exactly this render.
    2: the output is not a plist. That is unknown, not acceptance.
    4: the output is empty.
    """
    if not profiles_output.strip():
        return 4
    document = profiles_document(profiles_output)
    if document is None:
        return 2
    found: list[dict] = []
    _walk_profiles(document, found)
    if not found:
        return 1
    if len(found) != 1:
        return 3
    installed = profile_payload_booleans(found[0])
    if rendered is None:
        return 3
    expected = rendered_policy_booleans(rendered)
    if expected is None:
        return 2
    if installed == expected:
        return 0
    return 3


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
    payload.add_argument("--mobileconfig", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except (argparse.ArgumentError, UsageError):
        return 64
    try:
        if args.command == "payload-matches":
            rendered = None
            if args.mobileconfig is not None:
                try:
                    rendered = args.mobileconfig.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as error:
                    print(f"groundwork-brave-browser: {error}", file=sys.stderr)
                    return 1
            profiles_output = sys.stdin.read()
            status = payload_match_status(rendered, profiles_output)
            if (
                status == 2
                and profiles_output.strip()
                and profiles_document(profiles_output) is None
            ):
                print(
                    "groundwork-brave-browser: profiles output could not be read.",
                    file=sys.stderr,
                )
            return status
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
