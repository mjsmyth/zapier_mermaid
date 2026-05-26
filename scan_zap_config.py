# scan_zap_config.py
"""Scan a Zapier JSON export and report (or add) any new providers / action
modules that are missing from zapier_node_config.yaml.

Usage
-----
    python3 scan_zap_config.py <zap_file>          # dry-run: report only
    python3 scan_zap_config.py <zap_file> --write  # add stubs to YAML
"""

import argparse
import json
import pathlib
import re
import shutil
import yaml
from datetime import datetime


_CONFIG_PATH = pathlib.Path(__file__).parent / "zapier_node_config.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_api(selected_api: str) -> str:
    """Strip @version suffix: 'GoogleDriveCLIAPI@1.18.2' → 'GoogleDriveCLIAPI'."""
    return selected_api.split("@")[0]


def _infer_provider(api_name: str) -> str:
    """Best-effort human name from an API key, e.g. 'GoogleDriveCLIAPI' → 'Google Drive'."""
    name = re.sub(r"CLIAPI$", "", api_name)
    name = re.sub(r"V\d+$", "", name)             # strip trailing version (V2, V3 …)
    # Split on camelCase boundaries
    words = re.sub(r"([A-Z][a-z])", r" \1", name).split()
    return " ".join(words).strip() or api_name


def _infer_display_name(api_name: str, action: str, config: dict) -> str:
    """Return '<Provider> – <Action Title>', using existing _meta if available."""
    existing_meta = config.get(api_name, {}).get("_meta", {})
    provider = existing_meta.get("provider") or _infer_provider(api_name)
    action_title = action.replace("_", " ").title()
    return f"{provider} – {action_title}"


def _infer_node_type(type_of: str, parent_id) -> str:
    """Infer node_type from JSON fields.

    Rules
    -----
    parent_id is None  →  trigger  (root / entry node)
    type_of == "read"  →  search   (lookup step)
    else               →  action
    """
    if parent_id is None:
        return "trigger"
    if type_of == "read":
        return "search"
    return "action"


# ---------------------------------------------------------------------------
# YAML config helpers
# ---------------------------------------------------------------------------

def _load_config_raw() -> tuple[str, dict]:
    """Return (header_comment, parsed_dict).

    The header is the unbroken run of '#' lines at the top of the file;
    it is preserved verbatim when we write back.
    """
    text = _CONFIG_PATH.read_text()
    header_lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith("#"):
            header_lines.append(line)
        else:
            break
    header = "".join(header_lines)
    return header, yaml.safe_load(text)


def _known_pairs(config: dict) -> set[tuple[str, str]]:
    """All (api_name, action) pairs already registered in the config."""
    pairs: set[tuple[str, str]] = set()
    for api_name, api_data in config.items():
        if api_name == "providers":
            continue
        for action_name in api_data:
            if action_name != "_meta":
                pairs.add((api_name, action_name))
    return pairs


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_zap_file(zap_path: pathlib.Path) -> list[dict]:
    """Return a list of {'api', 'action', 'type_of', 'parent_id'} dicts for
    every node across all zaps (including 'off' zaps)."""
    with open(zap_path) as f:
        data = json.load(f)

    nodes = []
    for zap in data.get("zaps", []):
        for node in zap.get("nodes", {}).values():
            nodes.append({
                "api": _normalize_api(node["selected_api"]),
                "action": node["action"],
                "type_of": node.get("type_of", "write"),
                "parent_id": node.get("parent_id"),
            })
    return nodes


def find_gaps(nodes: list[dict], config: dict) -> list[dict]:
    """Return new entries: list of {'api', 'action', 'node_type'} dicts."""
    known = _known_pairs(config)
    seen: set[tuple[str, str]] = set()
    gaps = []
    for n in nodes:
        key = (n["api"], n["action"])
        if key not in known and key not in seen:
            seen.add(key)
            gaps.append({
                "api": n["api"],
                "action": n["action"],
                "node_type": _infer_node_type(n["type_of"], n["parent_id"]),
            })
    return gaps


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _stub_yaml_lines(gap: dict, config: dict) -> list[str]:
    """Render a 4-line YAML stub for a single action."""
    display = _infer_display_name(gap["api"], gap["action"], config)
    return [
        f"  {gap['action']}:",
        f'    display_name: "{display}"',
        f"    node_type: {gap['node_type']}",
        "    params: []",
    ]


def print_report(gaps: list[dict], config: dict, zap_path: pathlib.Path, nodes: list[dict]) -> None:
    known = _known_pairs(config)
    known_apis = {api for api, _ in known}

    new_apis = sorted({g["api"] for g in gaps if g["api"] not in known_apis})
    new_actions = [g for g in gaps if g["api"] in known_apis]

    file_pairs = {(n["api"], n["action"]) for n in nodes}
    already_known = len(file_pairs) - len(gaps)
    print(f"\nScanning: {zap_path}")
    print(f"Found {len(file_pairs)} unique (api, action) pairs across all zaps.\n")
    print(f"  ✅  {already_known} already in config")

    if not gaps:
        print("\nNothing to add — config is up to date.")
        return

    if new_apis:
        print(f"  \U0001f195  {len(new_apis)} new provider(s):")
        for api in new_apis:
            count = sum(1 for g in gaps if g["api"] == api)
            provider = _infer_provider(api)
            print(f"      {api}  (inferred provider: \"{provider}\", {count} action(s))")

    if new_actions:
        print(f"  \U0001f195  {len(new_actions)} new action(s) on existing provider(s):")
        for g in new_actions:
            print(f"      {g['api']} / {g['action']}  (node_type: {g['node_type']})")

    print("\n--- Suggested YAML additions ---\n")

    # Group by API for readability
    by_api: dict[str, list[dict]] = {}
    for g in gaps:
        by_api.setdefault(g["api"], []).append(g)

    for api_name, api_gaps in sorted(by_api.items()):
        is_new_api = api_name not in known_apis
        if is_new_api:
            provider = _infer_provider(api_name)
            print(f"# New provider block")
            print(f"{api_name}:")
            print(f"  _meta:")
            print(f'    provider: "{provider}"  # TODO: verify')
            print(f'    emoji: "⚙️"  # TODO: update')
        else:
            print(f"# Add to existing {api_name} block:")

        for g in sorted(api_gaps, key=lambda x: x["action"]):
            for line in _stub_yaml_lines(g, config):
                print(line)
        print()

    print("Run with --write to apply these additions to zapier_node_config.yaml.")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def backup_config() -> pathlib.Path:
    """Copy zapier_node_config.yaml to a timestamped .bak file and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = _CONFIG_PATH.with_suffix(f".yaml.bak.{timestamp}")
    shutil.copy2(_CONFIG_PATH, backup_path)
    return backup_path


def apply_gaps(gaps: list[dict], config: dict) -> None:
    """Mutate *config* in-place, inserting stub entries for every gap."""
    known_apis = {api for api, _ in _known_pairs(config)}

    for gap in gaps:
        api_name = gap["api"]
        action = gap["action"]
        stub = {
            "display_name": _infer_display_name(api_name, action, config),
            "node_type": gap["node_type"],
            "params": [],
        }

        if api_name not in known_apis:
            # Brand-new provider — create the full block
            config[api_name] = {
                "_meta": {
                    "provider": _infer_provider(api_name),
                    "emoji": "⚙️",
                },
                action: stub,
            }
            known_apis.add(api_name)
        else:
            config[api_name][action] = stub


def write_config(gaps: list[dict], config: dict) -> None:
    """Insert stub entries directly into the YAML file text, preserving all existing formatting."""
    text = _CONFIG_PATH.read_text()
    known_apis = {api for api, _ in _known_pairs(config)}

    by_api: dict[str, list[dict]] = {}
    for gap in gaps:
        by_api.setdefault(gap["api"], []).append(gap)

    for api_name, api_gaps in sorted(by_api.items()):
        stub_lines = []
        for gap in sorted(api_gaps, key=lambda x: x["action"]):
            stub_lines.extend(_stub_yaml_lines(gap, config))
        stub_text = "\n".join(stub_lines) + "\n"

        if api_name in known_apis:
            # Find the end of the existing API block and insert the stub before the next top-level key
            lines = text.splitlines(keepends=True)
            insert_at = len(lines)
            in_block = False
            for i, line in enumerate(lines):
                if line.rstrip("\n") == f"{api_name}:":
                    in_block = True
                    continue
                if in_block and line.strip() and not line[0].isspace() and not line.startswith("#"):
                    insert_at = i
                    break
            lines.insert(insert_at, stub_text)
            text = "".join(lines)
        else:
            # New provider — append a full block to the end of the file
            provider = _infer_provider(api_name)
            block = (
                f"\n{api_name}:\n"
                f"  _meta:\n"
                f'    provider: "{provider}"  # TODO: verify\n'
                f'    emoji: "⚙️"  # TODO: update\n'
            )
            block += "\n".join(stub_lines) + "\n"
            text += block

    _CONFIG_PATH.write_text(text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan a Zapier JSON export and report/add missing config entries."
    )
    parser.add_argument("zap_file", help="Path to the Zapier JSON export file")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Add stub entries to zapier_node_config.yaml (a backup is made first)",
    )
    args = parser.parse_args()

    zap_path = pathlib.Path(args.zap_file)
    if not zap_path.exists():
        parser.error(f"File not found: {zap_path}")

    header, config = _load_config_raw()
    nodes = scan_zap_file(zap_path)
    gaps = find_gaps(nodes, config)

    print_report(gaps, config, zap_path, nodes)

    if args.write:
        if not gaps:
            print("\nNothing to write.")
            return
        backup_path = backup_config()
        print(f"\nBackup saved → {backup_path.name}")
        write_config(gaps, config)
        print(f"Updated  → {_CONFIG_PATH.name}")


if __name__ == "__main__":
    main()
