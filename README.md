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
- **Batch Processing**: Process entire directories of dashboards in one go.
- **No External Dependencies**: Runs with standard Python 3 libraries.

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
  ]
}
```

- **Rename**: Set `replace_with` to the new hostname.
- **Remove**: Set `replace_with` to `null` or `""` to remove the host and its associated panels.
- **Site**: `site_name.replace_with` is applied to **every** `site` field found in the dashboard(s), regardless of its current value — there is no per-site matching against `site_name.current`.

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
