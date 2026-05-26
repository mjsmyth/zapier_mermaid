# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repo processes Zapier JSON export files and generates Mermaid diagram documentation for Zaps. The main script parses the JSON, extracts node/step metadata, and renders it as flowchart Markdown via a Mustache template.

## Running the script

```bash
python3 create_zapier_mermaid.py <zap_file>
```

Example:
```bash
python3 create_zapier_mermaid.py zapfile_maryjane_monday.json
```

Output is written to `output/zapier-<title-slug>.md` — one file per active (non-`"off"`) Zap, where the slug is the lowercased, hyphenated Zap title. Warnings and errors are logged to `zapier_mermaid.log`.

Dependencies: `pystache` (Mustache templating) and `pyyaml` (config file). Install with:
```bash
conda install pystache pyyaml
```

## Zapier JSON structure

All JSON files share the same schema:
```
{
  "metadata": { "version": "gdpr_v1" },
  "zaps": [
    {
      "id": <int>,
      "title": <str>,
      "status": "on" | "off",
      "nodes": {
        "<node_id>": {
          "parent_id": <int|null>,   // null = trigger (root node)
          "root_id": <int|null>,     // null = trigger; otherwise points to trigger node
          "action": <str>,           // e.g. "file_in_folder_v2", "util_line_item"
          "selected_api": <str>,     // e.g. "GoogleDriveCLIAPI@1.18.2"
          "type_of": "read"|"write",
          "meta": {
            "stepTitle": <str>,
            "parammap": { ... }      // human-readable param labels
          },
          "params": {
            "my_dict": { ... }       // key-value pairs; values may reference prior steps
          }
        }
      }
    }
  ]
}
```

**Step references:** `params.my_dict` values use `{{=gives["<node_id>"]["<field>"]}}` syntax to reference outputs from earlier steps. These field names are extracted as `step_inputs` and become edge labels in the diagram.

## Architecture

### Data flow

```
JSON file → zap_dict["zaps"]
  └─ skip zaps with status "off"
  └─ process_zap(zap, zap_doc, output_path)
       └─ process_node() per node → populates zap_doc["nodes"][node_id]
            ├─ extracts: parent_id, root_id, stepTitle, selected_api, action, parammap
            ├─ dispatches to NODE_CONFIG / _SPECIAL_HANDLERS for app-specific fields
            └─ step_inputs: field names from gives[...] references → become edge labels
       └─ build_render_context(zap_doc) → flat context dict for Mustache
            ├─ assigns sequential IDs: N1, N2, N3, ...
            ├─ collapses BranchingAPI/filter nodes onto edges (not rendered as nodes)
            └─ sorts branch path edges: "success/yes" first, "error/no" last
       └─ pystache.render(TEMPLATE, context) → writes output/<stem>_output_NN.md
```

The `parent_id` chain defines graph edges. `step_inputs` on a child becomes the label on the edge from its parent.

### Config-driven node dispatch (`zapier_node_config.yaml`)

All known `(api_name, action)` pairs are registered in `zapier_node_config.yaml`. The script loads this into three dicts:

- `NODE_CONFIG` — keyed on `(api_name, action)`; each entry has `display_name`, `node_type`, `params` (field extractions), `constants`, and optionally `special`
- `NODE_CONFIG_META` — keyed on `api_name`; holds `provider` and `emoji` for label building
- `PROVIDER_COLORS` — keyed on provider name; holds the Mermaid `style` string

`_normalize_api()` strips the version suffix from `selected_api` before lookup. Unrecognised `(api, action)` pairs log a warning but don't abort.

**To add a new Zapier integration:** add an entry to `zapier_node_config.yaml` under the api name. No Python changes are needed unless the handler logic must be conditional (e.g., checking action type or iterating a sub-dict). In that case, add a function to `_SPECIAL_HANDLERS` in `create_zapier_mermaid.py` and reference it via `special: _your_handler_name` in the YAML.

### Output format (`zapier_mermaid.mustache`)

Each output file is Markdown with YAML frontmatter (title, deprecated, hidden, robots), a summary table, and a fenced `mermaid graph TD` block. Regular nodes use `[" "]` syntax; branch/path nodes use `{" "}` (diamond shape). Edges use `-->|label|` with `step_inputs` as the label. Each node gets a `style` directive with provider-specific fill color from `PROVIDER_COLORS`.

## Files

| File | Description |
|------|-------------|
| `zapfiles_maryjane.json` | Mary Jane's personal Zaps (raw export) |
| `zapfiles_maryjane_pretty.json` | Same as above, pretty-printed |
| `zapfile_maryjane_monday.json` | Subset: only the Monday-related Zap |
| `zapfile_maryjane_monday_pretty.json` | Same as above, pretty-printed |
| `zapfile_company.json` | Full company Zap export (29 Zaps) |
| `zapier_node_config.yaml` | Registry of all known Zapier API/action pairs and provider styles |
| `zapier_mermaid.mustache` | Mustache template that produces the Mermaid Markdown output |
| `zapier_mermaid.md` | Hand-crafted reference example of the target output format |
