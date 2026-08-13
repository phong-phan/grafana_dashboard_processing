# Grafana Dashboard Customizer

![Grafana Customizer](README_master_image.jpg)

A Python script designed to automate the customization of Grafana dashboards when using with CheckMK for different customer deployments.
If you want to reuse your dashboards for different customer deployments, this script is for you.
It handles the replacement of hostnames, updating of datasource UIDs from multiple datasources, and modification of site names across single or multiple dashboard files.

## Features

- **Dynamic Hostname Replacement**: Map current hostnames to new target hostnames.
- **Host Removal**: Automatically remove dashboard panels and targets associated with hosts that are not present in the new deployment. This helps to remove panels and targets associated with hosts that are not present in the new deployment so that Grafana can display data immediately.
- **Datasource UID Updates**: Update UIDs for specific datasource types (e.g., `checkmk-cloud-datasource`, `yesoreyeram-infinity-datasource`) globally.
- **Site Name Updates**: Update the CheckMK site name in query specifications.
- **Panel Transformation Updates**: Update the Match/Replace regex used by "Rename fields by regex" panel transformations (commonly used to strip a customer-specific host-name prefix from legends) globally.
- **Value Mapping Updates**: Update the Value/Display text pairs used by panel value mappings (e.g. relabeling an IP address with a customer-specific hostname, or restyling a status label) wherever they occur.
- **Data Pull URL Updates**: Update the URL used by `yesoreyeram-infinity-datasource` CSV/HTTP targets (e.g. a customer-specific CSV export endpoint) globally.
- **Panel Title Review**: Surface every hand-typed panel title for review, since these aren't otherwise touched by any of the automated replacements above.
- **Text Panel Content Updates**: Update the hand-typed HTML/markdown body of "Text" panels (e.g. a dashboard header that hardcodes a customer/site name) wherever it occurs.
- **Batch Processing**: Process entire directories of dashboards in one go.
- **No External Dependencies**: Runs with standard Python 3 libraries.

## Web UI

For a side-by-side editor (detected value on the left, replacement box on the right) instead of hand-editing `config.json`, run the bundled local web app:

```bash
python3 app.py
```

This opens `http://127.0.0.1:8765` in your browser (stdlib only, no `pip install` needed). Upload one or more dashboard JSON files, edit the site name, datasource UIDs, hosts (rename, remove, or blank out), panel transformation Match/Replace regexes, value mapping Value/Display text pairs, data pull URLs, panel titles, and text panel content in the browser, then either download `config.json` for reuse with the CLI or click "Apply & download dashboard(s)" to get the customized file(s) directly (zipped if multiple).

Options: `--port <n>` to change the port, `--host 0.0.0.0` to expose it to your LAN instead of just localhost, `--no-browser` to skip auto-opening a tab.

## Usage

The script operates in two modes: `generate-config` and `apply`.

### 1. Generate Configuration

First, scan your dashboard(s) to generate a configuration file listing all detected hosts and datasources.

**Single File:**

```bash
python3 grafana_customizer.py generate-config source_dashboard.json config.json
```

**Batch (Directory):**

```bash
python3 grafana_customizer.py generate-config ./dashboards_dir config.json
```

### 2. Map Hosts (Optional)

If you have a large number of new hosts, you can map them automatically via a text file (one host per line) to update your configuration file. Hosts are mapped **positionally**: the 1st line fills the `replace_with` of the 1st host entry, the 2nd line the 2nd entry, and so on.

- If the hosts file has **fewer** lines than existing host entries, the leftover host entries are set to `replace_with: null`, which marks them for **removal** when you run `apply`.
- If the hosts file has **more** lines than existing host entries, the extra hosts are appended as new entries. During `apply`, these extra hosts cause the existing query targets in each panel to be duplicated (one copy per extra host) so the panel queries data for all hosts.

You can also optionally specify the Target Site and Datasource UID at the top of the text file using `SITE=` and `UID=` prefixes:

```text
SITE=NEW_CHECKMK_SITE
UID=NEW_DATASOURCE_UID
new-host-01
new-host-02
```

```bash
python3 grafana_customizer.py map-hosts NEW_HOSTS.txt config.json --out mapped_config.json
```

### 3. Edit Configuration

Open the generated/mapped `config.json` and refine your mappings if necessary.

```json
{
  "datasources": [
    {
      "type": "checkmk-cloud-datasource",
      "uid": { "current": "OLD_UID", "replace_with": "NEW_UID" }
    }
  ],
  "site_name": {
    "current": "old_site",
    "replace_with": "new_site"
  },
  "hosts": [
    {
      "current": "OLD-HOST-01",
      "replace_with": "NEW-HOST-01"
    },
    {
      "current": "OLD-HOST-02",
      "replace_with": null
    }
  ],
  "transformations": [
    {
      "current": { "regex": "OLD-PREFIX-.*-(.*)", "renamePattern": "$1" },
      "replace_with": { "regex": "NEW-PREFIX-.*-(.*)", "renamePattern": "$1" }
    }
  ],
  "value_mappings": [
    {
      "current": { "value": "192.168.1.50", "text": "OLD-CUSTOMER-HOST-01" },
      "replace_with": { "value": "10.0.0.50", "text": "NEW-CUSTOMER-HOST-01" }
    }
  ],
  "urls": [
    {
      "current": "http://old-export-server/export/data.csv",
      "replace_with": "http://new-export-server/export/data.csv"
    }
  ],
  "panel_titles": [
    {
      "current": "Old Panel Title",
      "replace_with": "New Panel Title"
    }
  ],
  "text_content": [
    {
      "current": "<center><h1>OLD-CUSTOMER Status</h1></center>",
      "replace_with": "<center><h1>NEW-CUSTOMER Status</h1></center>"
    }
  ]
}
```

- **Rename**: Set `replace_with` to the new hostname.
- **Remove**: Set `replace_with` to `null` or `""` to remove the host and its associated panels.
- **Site**: `site_name.replace_with` is applied to **every** `site` field found in the dashboard(s), regardless of its current value — there is no per-site matching against `site_name.current`.
- **Transformations**: Applies only to panel transformations with `"id": "renameByRegex"` ("Rename fields by regex" in the Grafana UI). Each entry's `current.regex`/`current.renamePattern` is matched exactly against what's in the dashboard(s); matching entries get replaced with `replace_with.regex`/`replace_with.renamePattern` wherever they occur, across all panels.
- **Value Mappings**: Applies only to panel value mappings with `"type": "value"` ("Value mappings" in the Grafana UI, condition type "Value"). Each entry's `current.value`/`current.text` is matched exactly against what's in the dashboard(s); matching entries get replaced with `replace_with.value`/`replace_with.text` (the mapped value itself and its display text can both change, e.g. to relabel an IP with a new customer's hostname) wherever they occur. Any `color`/`index` styling on the mapping is preserved.
- **URLs**: Applies only to `yesoreyeram-infinity-datasource` targets with a `url` field (e.g. CSV/HTTP data pulls). Each entry's `current` URL is matched exactly against what's in the dashboard(s) and replaced with `replace_with`.
- **Panel Titles**: Every panel's `title` is listed (skipping blank ones) so you can review them, since panel titles are hand-typed and not touched by any other replacement. Entries matching `current` exactly get renamed to `replace_with` on every panel sharing that title.
- **Text Content**: Applies only to `"type": "text"` panels' `options.content` (the HTML/markdown body). Each entry's `current` is matched exactly against what's in the dashboard(s) and replaced with `replace_with` wherever it occurs — useful for headers that hardcode a customer or site name.

### 4. Apply Changes

Apply the configuration to generate the customized dashboards.

**Single File:**

```bash
python3 grafana_customizer.py apply source_dashboard.json config.json output_dashboard.json
```

**Batch (Directory):**

```bash
python3 grafana_customizer.py apply ./dashboards_dir config.json ./output_dir
```

## Requirements

- Python 3.x
