# create_zapier_mermaid.py
'''python script to create mermaid diagrams from zapier json files'''

import argparse
import ast
import json
import logging
import pathlib
import re
import yaml
import pystache


_LOG_PATH = pathlib.Path(__file__).parent / "zapier_mermaid.log"
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_PATH),
    ],
)

_CONFIG_PATH = pathlib.Path(__file__).parent / "zapier_node_config.yaml"
_TEMPLATE_PATH = pathlib.Path(__file__).parent / "zapier_mermaid.mustache"


def _load_node_config():
    with open(_CONFIG_PATH) as f:
        raw = yaml.safe_load(f)
    providers = raw.pop("providers", {})
    flat = {}
    meta = {}
    for api_name, actions in raw.items():
        for action_name, entry in actions.items():
            if action_name == "_meta":
                meta[api_name] = entry
            else:
                flat[(api_name, action_name)] = entry
    return flat, meta, providers


NODE_CONFIG, NODE_CONFIG_META, PROVIDER_COLORS = _load_node_config()

with open(_TEMPLATE_PATH) as _f:
    TEMPLATE = _f.read()


def _normalize_api(selected_api):
    return selected_api.split("@")[0]


def _handle_filter(zap, node_id, node_doc):
    params = zap["nodes"][node_id].get("params", {})
    criteria = params.get("filter_criteria")
    if isinstance(criteria, dict):
        node_doc["node_filter_fields"] = list(criteria.keys())
    elif isinstance(criteria, list):
        node_doc["node_filter_fields"] = criteria
    else:
        node_doc["node_filter_fields"] = []


def _handle_webhook(zap, node_id, node_doc):
    params = zap["nodes"][node_id].get("params", {})
    action = zap["nodes"][node_id].get("action")
    if action == "inbound_v2":
        node_doc["node_inbound"] = True
    else:
        node_doc["node_url"] = params.get("url")


def _handle_generic(config_entry, zap, node_id, node_doc):
    raw_params = zap["nodes"][node_id].get("params", {})
    for field in config_entry.get("params", []):
        value = raw_params.get(field["source_key"])
        if "truncate" in field and value:
            value = value[: field["truncate"]]
        node_doc[field["target_key"]] = value
    for key, value in config_entry.get("constants", {}).items():
        node_doc[key] = value


_SPECIAL_HANDLERS = {
    "_handle_filter": _handle_filter,
    "_handle_webhook": _handle_webhook,
}


def _build_node_label(node, api_name, seen_providers):
    api_meta = NODE_CONFIG_META.get(api_name, {})
    emoji = api_meta.get("emoji", "⚙️")
    config_entry = NODE_CONFIG.get((api_name, node.get("action", "")), {})
    step_title = node["stepTitle"] or config_entry.get("display_name", "")
    provider = api_meta.get("provider", "")
    parts = [f"{emoji} {step_title}"]
    if provider and provider.lower() not in step_title.lower() and provider not in seen_providers:
        parts.append(f"[{provider}]")
        seen_providers.add(provider)

    try:
        parammap = ast.literal_eval(node.get("parammap", "{}"))
        if parammap:
            first_key, first_val = next(iter(parammap.items()))
            parts.append(f"({first_key.capitalize()}: {first_val})")
    except (ValueError, SyntaxError):
        pass

    if node.get("params"):
        parts.append(node["params"])

    return "<br/>".join(parts)


def _is_branch_filter(node):
    return (
        _normalize_api(node["selected_api"]) == "BranchingAPI"
        and node["action"] == "filter"
    )


def build_render_context(zap_doc):
    all_nodes = zap_doc["nodes"]

    # BranchingAPI/filter nodes (path conditions) are collapsed onto edges, not rendered as nodes
    branch_filter_ids = {nid for nid, n in all_nodes.items() if _is_branch_filter(n)}

    visible_ids = [nid for nid in all_nodes if nid not in branch_filter_ids]
    id_to_letter = {nid: f"N{i + 1}" for i, nid in enumerate(visible_ids)}

    nodes = []
    seen_providers = set()
    for i, node_id in enumerate(visible_ids):
        node = all_nodes[node_id]
        api_name = _normalize_api(node["selected_api"])
        provider = NODE_CONFIG_META.get(api_name, {}).get("provider", "")
        node_style = PROVIDER_COLORS.get(provider, {}).get("style", "fill:#888888,stroke:#333,stroke-width:1px,color:#fff")
        label = _build_node_label(node, api_name, seen_providers)
        letter = f"N{i + 1}"
        is_branch = node.get("node_branch", False)
        if is_branch:
            node_line = f'    {letter}{{"{label}"}}'
        else:
            node_line = f'    {letter}["{label}"]'
        nodes.append({
            "letter": letter,
            "node_line": node_line,
            "label": label,
            "style": node_style
        })

    edges = []
    # branch path edges collected per branch node for sorting: {branch_str: [(path_eval_index, line)]}
    branch_path_edges = {}

    for node_id, node in all_nodes.items():
        if node_id in branch_filter_ids:
            continue
        parent_id = node.get("parent_id")
        if parent_id is None:
            continue
        parent_str = str(parent_id)

        # If parent is a branch filter, skip over it and use its stepTitle as the edge label
        if parent_str in branch_filter_ids:
            filter_node = all_nodes[parent_str]
            edge_label = filter_node.get("stepTitle") or ""
            branch_id = filter_node.get("parent_id")
            if branch_id is None:
                continue
            branch_str = str(branch_id)
            if branch_str not in id_to_letter or node_id not in id_to_letter:
                continue
            path_eval_index = filter_node.get("path_eval_index", 0)
            if edge_label:
                line = f"    {id_to_letter[branch_str]} -->|{edge_label}| {id_to_letter[node_id]}"
            else:
                line = f"    {id_to_letter[branch_str]} --> {id_to_letter[node_id]}"
            label_lower = edge_label.lower()
            if label_lower in ("success", "yes"):
                position = 0
            elif label_lower in ("error", "no"):
                position = 2
            else:
                position = 1
            branch_path_edges.setdefault(branch_str, []).append((position, path_eval_index, line))
        else:
            if parent_str not in id_to_letter or node_id not in id_to_letter:
                continue
            step_inputs = node.get("step_inputs", "")
            edge_label = ""
            if step_inputs:
                try:
                    fields = ast.literal_eval(step_inputs)
                    edge_label = ", ".join(fields)
                except (ValueError, SyntaxError):
                    pass
            if edge_label:
                line = f"    {id_to_letter[parent_str]} -->|{edge_label}| {id_to_letter[node_id]}"
            else:
                line = f"    {id_to_letter[parent_str]} --> {id_to_letter[node_id]}"
            edges.append({"line": line})

    for branch_str in branch_path_edges:
        for _, __, line in sorted(branch_path_edges[branch_str]):
            edges.append({"line": line})

    return {
        "title": zap_doc["title"],
        "id": zap_doc["id"],
        "status": zap_doc["status"],
        "nodes": nodes,
        "edges": edges,
    }


def process_node(zap, node, zap_doc):
    zap_doc["nodes"][node] = {}
    zap_doc["nodes"][node]["parent_id"] = zap["nodes"][node]["parent_id"]
    zap_doc["nodes"][node]["root_id"] = zap["nodes"][node]["root_id"]
    zap_doc["nodes"][node]["stepTitle"] = zap["nodes"][node]["meta"].get("stepTitle")
    zap_doc["nodes"][node]["selected_api"] = zap["nodes"][node]["selected_api"]
    zap_doc["nodes"][node]["action"] = zap["nodes"][node]["action"]
    zap_doc["nodes"][node]["parammap"] = str(zap["nodes"][node]["meta"].get("parammap", {}))

    raw_params = zap["nodes"][node].get("params", {})
    if "path_eval_index" in raw_params:
        zap_doc["nodes"][node]["path_eval_index"] = raw_params["path_eval_index"]

    if "my_dict" in zap["nodes"][node]["params"]:
        zap_doc["nodes"][node]["params"] = "Params: " + ", ".join(zap["nodes"][node]["params"]["my_dict"].keys())
        params_values = " ".join(zap["nodes"][node]["params"]["my_dict"].values())
        if "gives" in params_values:
            zap_doc["nodes"][node]["step_inputs"] = "shouldn't be blank"
            zap_doc["nodes"][node]["step_inputs"] = str(re.findall(r'gives\[\"[0-9]{9,9}\"]\[\"([a-zA-Z]+?)\"]', params_values))

    api_name = _normalize_api(zap["nodes"][node]["selected_api"])
    action = zap["nodes"][node]["action"]
    config_entry = NODE_CONFIG.get((api_name, action))
    if not config_entry:
        logging.warning("Unhandled node: %s / %s", api_name, action)
    if config_entry:
        special = config_entry.get("special")
        if special:
            _SPECIAL_HANDLERS[special](zap, node, zap_doc["nodes"][node])
        else:
            _handle_generic(config_entry, zap, node, zap_doc["nodes"][node])


def process_zap(zap, zap_doc, output_path):
    zap_doc["id"] = zap["id"]
    zap_doc["title"] = zap["title"]
    zap_doc["status"] = zap["status"]
    zap_doc["nodes"] = {}
    for node in zap["nodes"].keys():
        process_node(zap, node, zap_doc)
    context = build_render_context(zap_doc)
    output_path.write_text(pystache.render(TEMPLATE, context))


def main():
    parser = argparse.ArgumentParser(description="Generate Mermaid diagrams from a Zapier JSON export.")
    parser.add_argument("zap_file", help="Path to the Zapier JSON export file")
    args = parser.parse_args()
    zap_path = pathlib.Path(args.zap_file)
    output_dir = zap_path.parent / "output"
    output_dir.mkdir(exist_ok=True)
    with open(zap_path) as f:
        zap_dict = json.load(f)
    zap_doc = {}
    for zap in zap_dict["zaps"]:
        if zap.get("status") == "off":
            continue
        title_slug = re.sub(r'[^a-z0-9]+', '-', zap.get("title", "unknown").lower()).strip('-')
        output_path = output_dir / f"zapier-{title_slug}.md"
        try:
            process_zap(zap, zap_doc, output_path)
            logging.info("Wrote %s", output_path)
        except Exception as e:
            logging.error("Failed to process zap %s (%s): %s", zap.get("id"), zap.get("title"), e)


if __name__ == "__main__":
    main()
