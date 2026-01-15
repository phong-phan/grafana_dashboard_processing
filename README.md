# Grafana Dashboard Customizer

![Grafana Customizer](README_master_image.jpg)

A Python script designed to automate the customization of Grafana dashboards when using with CheckMK for different customer deployments. It handles the replacement of hostnames, updating of datasource UIDs from multiple datasources, and modification of site names across single or multiple dashboard files.

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

### 2. Edit Configuration

Open the generated `config.json` and define your mappings.

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

### 3. Apply Changes

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
