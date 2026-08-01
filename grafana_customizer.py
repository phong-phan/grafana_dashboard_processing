import argparse
import glob
import json
import os
import sys


def scan_dashboard(dashboard_data):
    """
    Scans the dashboard for hostnames, datasource UIDs, and site names.
    Returns a dictionary with the findings.
    """
    hosts = set()
    # Store datasources as a dictionary of type -> set(uids)
    datasources = {}
    sites = set()

    def walk_json(node):
        if isinstance(node, dict):
            # Check for Datasource UID
            if "datasource" in node and isinstance(node["datasource"], dict):
                ds_type = node["datasource"].get("type")
                ds_uid = node["datasource"].get("uid")

                if ds_type and ds_uid and ds_uid != "-- Grafana --":
                    if ds_type not in datasources:
                        datasources[ds_type] = set()
                    datasources[ds_type].add(ds_uid)

            # Check for requestSpec (where host_name and site usually live)
            if "requestSpec" in node and isinstance(node["requestSpec"], dict):
                spec = node["requestSpec"]
                if "host_name" in spec:
                    hosts.add(spec["host_name"])
                if "site" in spec:
                    sites.add(spec["site"])

            for key, value in node.items():
                walk_json(value)
        elif isinstance(node, list):
            for item in node:
                walk_json(item)

    walk_json(dashboard_data)

    # Convert sets to sorted lists for output
    formatted_datasources = []
    for ds_type, uids in datasources.items():
        for uid in sorted(list(uids)):
            formatted_datasources.append({"type": ds_type, "uid": uid})

    return {
        "hosts": sorted(list(hosts)),
        "datasources": formatted_datasources,
        "sites": sorted(list(sites)),
    }


def generate_config(input_path, config_path):
    """
    Generates a configuration file based on the dashboard content.
    Accepts a single file or a directory.
    """
    files_to_scan = []
    if os.path.isdir(input_path):
        files_to_scan = glob.glob(os.path.join(input_path, "*.json"))
        print(
            f"Scanning directory '{input_path}'. Found {len(files_to_scan)} JSON files."
        )
    elif os.path.isfile(input_path):
        files_to_scan = [input_path]
    else:
        print(f"Error: Input path '{input_path}' not found.")
        sys.exit(1)

    all_hosts = set()
    all_sites = set()
    all_datasources = {}  # type -> set(uids)

    for file_path in files_to_scan:
        try:
            with open(file_path, "r") as f:
                dashboard_data = json.load(f)
                result = scan_dashboard(dashboard_data)

                all_hosts.update(result["hosts"])
                all_sites.update(result["sites"])

                for ds in result["datasources"]:
                    if ds["type"] not in all_datasources:
                        all_datasources[ds["type"]] = set()
                    all_datasources[ds["type"]].add(ds["uid"])

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to process '{file_path}': {e}")

    config = {
        "instructions": "Map 'current' values to 'replace_with'. To remove a host, leave 'replace_with' as null or empty string.",
        "datasources": [],
        "site_name": {
            "current": sorted(list(all_sites))[0] if all_sites else "",
            "replace_with": sorted(list(all_sites))[0] if all_sites else "",
        },
        "hosts": [],
    }

    # Populate datasources
    for ds_type, uids in all_datasources.items():
        for uid in sorted(list(uids)):
            config["datasources"].append(
                {"type": ds_type, "uid": {"current": uid, "replace_with": uid}}
            )

    # Populate hosts
    for host in sorted(list(all_hosts)):
        config["hosts"].append({"current": host, "replace_with": host})

    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Configuration file generated at '{config_path}'.")
        print(
            "Please edit this file to define your mappings before running the 'apply' command."
        )
    except IOError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)


def apply_changes(input_path, config_path, output_path):
    """
    Applies the configuration changes to the dashboard(s).
    Accepts single file -> single file OR directory -> directory.
    """
    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

    apply_config_to_dashboards(input_path, config_data, output_path)


def apply_config_to_dashboards(input_path, config_data, output_path):
    """
    Applies the configuration changes to the dashboard(s).
    """
    # Prepare mappings
    host_map = {}
    for item in config_data.get("hosts", []):
        current = item.get("current")
        if current:
            host_map[current] = item.get("replace_with")

    # hosts to remove completely (mapped to "")
    hosts_to_remove = {
        current for current, replacement in host_map.items() if replacement == ""
    }

    # hosts to replace with null (mapped to None)
    hosts_to_nullify = {
        current for current, replacement in host_map.items() if replacement is None
    }

    extra_hosts = [
        item["replace_with"]
        for item in config_data.get("hosts", [])
        if not item.get("current") and item.get("replace_with")
    ]
    target_site = config_data.get("site_name", {}).get("replace_with")

    ds_map = {}  # type -> { current_uid: replace_with }
    for ds in config_data.get("datasources", []):
        ds_type = ds["type"]
        current_uid = ds["uid"]["current"]
        new_uid = ds["uid"]["replace_with"]
        if ds_type not in ds_map:
            ds_map[ds_type] = {}
        ds_map[ds_type][current_uid] = new_uid

    # Determine files to process
    files_to_process = []
    is_dir_mode = False

    if os.path.isdir(input_path):
        is_dir_mode = True
        files_to_process = glob.glob(os.path.join(input_path, "*.json"))
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        elif not os.path.isdir(output_path):
            print(
                f"Error: Input is a directory, but output '{output_path}' is not a directory."
            )
            sys.exit(1)
    elif os.path.isfile(input_path):
        files_to_process = [input_path]
    else:
        print(f"Error: Input path '{input_path}' not found.")
        sys.exit(1)

    def transform_node(node):
        """
        Recursively transforms the JSON node.
        Returns True if the node should be kept, False if it should be removed.
        """
        if isinstance(node, dict):
            # 1. Update Datasource UID
            if "datasource" in node and isinstance(node["datasource"], dict):
                ds_type = node["datasource"].get("type")
                ds_uid = node["datasource"].get("uid")

                if ds_type and ds_uid and ds_type in ds_map:
                    if ds_uid in ds_map[ds_type]:
                        node["datasource"]["uid"] = ds_map[ds_type][ds_uid]

            # 2. Update Site and Hostname in requestSpec
            if "requestSpec" in node and isinstance(node["requestSpec"], dict):
                spec = node["requestSpec"]

                # Update Site
                if "site" in spec and target_site:
                    spec["site"] = target_site

                # Update Hostname
                if "host_name" in spec:
                    current_host = spec["host_name"]
                    if current_host in hosts_to_remove:
                        return False  # Signal to remove this node
                    if current_host in hosts_to_nullify:
                        spec["host_name"] = None
                    elif current_host in host_map:
                        spec["host_name"] = host_map[current_host]

            # 3. Recursively process children

            # Handle 'targets' list
            if "targets" in node and isinstance(node["targets"], list):
                new_targets = []
                unmatched_count = 0
                explicit_removed_count = 0

                for target in node["targets"]:
                    # Check target's host_name
                    target_host = None
                    if isinstance(target, dict) and "requestSpec" in target and isinstance(target["requestSpec"], dict):
                        target_host = target["requestSpec"].get("host_name")

                    if target_host in hosts_to_remove:
                        explicit_removed_count += 1
                    elif target_host in hosts_to_nullify:
                        unmatched_count += 1
                    else:
                        if transform_node(target):
                            new_targets.append(target)

                # Duplicate targets for extra hosts if there are targets with hostnames
                if extra_hosts and new_targets:
                    # Find the last host in terms of order in new_targets
                    last_host = None
                    for t in reversed(new_targets):
                        if "requestSpec" in t and isinstance(t["requestSpec"], dict):
                            h = t["requestSpec"].get("host_name")
                            if h:
                                last_host = h
                                break

                    # If we found a last host, use its targets as the prototype
                    if last_host:
                        prototype_targets = [
                            t for t in new_targets
                            if "requestSpec" in t and isinstance(t["requestSpec"], dict) and t["requestSpec"].get("host_name") == last_host
                        ]

                        existing_ref_ids = set()
                        for t in new_targets:
                            if "refId" in t:
                                existing_ref_ids.add(t["refId"])

                        def get_next_ref_id(existing_ids):
                            candidates = [chr(i) for i in range(65, 91)] + [
                                chr(i) + chr(j)
                                for i in range(65, 91)
                                for j in range(65, 91)
                            ]
                            for c in candidates:
                                if c not in existing_ids:
                                    return c
                            return "ZZZ"

                        import copy
                        for extra_host in extra_hosts:
                            for proto_t in prototype_targets:
                                new_t = copy.deepcopy(proto_t)
                                new_ref_id = get_next_ref_id(existing_ref_ids)
                                new_t["refId"] = new_ref_id
                                existing_ref_ids.add(new_ref_id)
                                new_t["requestSpec"]["host_name"] = extra_host
                                new_targets.append(new_t)

                node["targets"] = new_targets

                # Remove panel only if it had targets and all were explicitly removed via "" mapping
                if not new_targets and "type" in node and node["type"] != "row":
                    if explicit_removed_count > 0 and unmatched_count == 0:
                        return False

            # Handle 'panels' list
            if "panels" in node and isinstance(node["panels"], list):
                new_panels = []
                for panel in node["panels"]:
                    if transform_node(panel):
                        new_panels.append(panel)
                node["panels"] = new_panels

            # Process other keys
            for key, value in node.items():
                if key not in ["targets", "panels"]:
                    transform_node(value)

            return True

        elif isinstance(node, list):
            for item in node:
                transform_node(item)
            return True

        return True

    count = 0
    for file_path in files_to_process:
        try:
            with open(file_path, "r") as f:
                dashboard_data = json.load(f)

            transform_node(dashboard_data)

            if is_dir_mode:
                filename = os.path.basename(file_path)
                dest_path = os.path.join(output_path, filename)
            else:
                dest_path = output_path

            with open(dest_path, "w") as f:
                json.dump(dashboard_data, f, indent=2)
            count += 1

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error processing '{file_path}': {e}")

    print(f"Successfully processed {count} files.")


def map_hosts(hosts_file, config_file, output_config_file=None):
    """
    Reads a text file with a list of new hosts and optional SITE= and UID= parameters,
    and updates the config.json.
    """
    try:
        with open(hosts_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
    except IOError as e:
        print(f"Error reading {hosts_file}: {e}")
        sys.exit(1)

    new_hosts = []
    new_site = None
    new_uid = None

    for line in lines:
        if line.startswith("SITE="):
            new_site = line.split("=", 1)[1].strip()
        elif line.startswith("UID="):
            new_uid = line.split("=", 1)[1].strip()
        elif not line.startswith("#"):
            new_hosts.append(line)

    try:
        with open(config_file, "r") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading {config_file}: {e}")
        sys.exit(1)

    # Update site
    if new_site is not None and "site_name" in config:
        config["site_name"]["replace_with"] = new_site

    # Update uids
    if new_uid is not None and "datasources" in config:
        for ds in config["datasources"]:
            ds["uid"]["replace_with"] = new_uid

    hosts_list = config.get("hosts", [])

    for i, h in enumerate(hosts_list):
        if i < len(new_hosts):
            h["replace_with"] = new_hosts[i]
        else:
            h["replace_with"] = None

    if len(new_hosts) > len(hosts_list):
        for extra in new_hosts[len(hosts_list) :]:
            hosts_list.append({"current": None, "replace_with": extra})

    config["hosts"] = hosts_list

    out_file = output_config_file if output_config_file else config_file
    try:
        with open(out_file, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Successfully mapped {len(new_hosts)} hosts into '{out_file}'.")
        if new_site:
            print(f"Updated site to: {new_site}")
        if new_uid:
            print(f"Updated datasources UID to: {new_uid}")
    except IOError as e:
        print(f"Error writing to {out_file}: {e}")
        sys.exit(1)


def apply_direct(input_path, hosts_file, output_path):
    """
    Directly scans, maps, and applies changes in one step.
    """
    files_to_scan = []
    if os.path.isdir(input_path):
        files_to_scan = glob.glob(os.path.join(input_path, "*.json"))
        print(f"Scanning directory '{input_path}'. Found {len(files_to_scan)} JSON files.")
    elif os.path.isfile(input_path):
        files_to_scan = [input_path]
    else:
        print(f"Error: Input path '{input_path}' not found.")
        sys.exit(1)

    all_hosts = set()
    all_sites = set()
    all_datasources = {}

    for file_path in files_to_scan:
        try:
            with open(file_path, "r") as f:
                dashboard_data = json.load(f)
                result = scan_dashboard(dashboard_data)
                all_hosts.update(result["hosts"])
                all_sites.update(result["sites"])
                for ds in result["datasources"]:
                    if ds["type"] not in all_datasources:
                        all_datasources[ds["type"]] = set()
                    all_datasources[ds["type"]].add(ds["uid"])
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to process '{file_path}': {e}")

    try:
        with open(hosts_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
    except IOError as e:
        print(f"Error reading {hosts_file}: {e}")
        sys.exit(1)

    new_hosts = []
    new_site = None
    new_uid = None

    for line in lines:
        if line.startswith("SITE="):
            new_site = line.split("=", 1)[1].strip()
        elif line.startswith("UID="):
            new_uid = line.split("=", 1)[1].strip()
        elif not line.startswith("#"):
            new_hosts.append(line)

    config_data = {
        "datasources": [],
        "site_name": {
            "current": sorted(list(all_sites))[0] if all_sites else "",
            "replace_with": new_site if new_site is not None else (sorted(list(all_sites))[0] if all_sites else "")
        },
        "hosts": []
    }

    for ds_type, uids in all_datasources.items():
        for uid in sorted(list(uids)):
            config_data["datasources"].append({
                "type": ds_type,
                "uid": {
                    "current": uid,
                    "replace_with": new_uid if new_uid is not None else uid
                }
            })

    sorted_all_hosts = sorted(list(all_hosts))
    for i, host in enumerate(sorted_all_hosts):
        if i < len(new_hosts):
            config_data["hosts"].append({
                "current": host,
                "replace_with": new_hosts[i]
            })
        else:
            config_data["hosts"].append({
                "current": host,
                "replace_with": None
            })

    if len(new_hosts) > len(sorted_all_hosts):
        for extra in new_hosts[len(sorted_all_hosts):]:
            config_data["hosts"].append({
                "current": None,
                "replace_with": extra
            })

    print(f"Direct Mapping Summary:")
    print(f"  Detected source hosts: {len(sorted_all_hosts)}")
    print(f"  Target hosts provided: {len(new_hosts)}")
    if new_site:
        print(f"  Target site: {new_site}")
    if new_uid:
        print(f"  Target datasource UID: {new_uid}")

    apply_config_to_dashboards(input_path, config_data, output_path)


def main():
    parser = argparse.ArgumentParser(description="Grafana Dashboard Customizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Generate Config Command
    parser_gen = subparsers.add_parser(
        "generate-config",
        help="Generate a configuration file from a dashboard or directory",
    )
    parser_gen.add_argument(
        "input_path", help="Path to the source dashboard JSON file or directory"
    )
    parser_gen.add_argument(
        "config_file", help="Path to save the generated JSON config file"
    )

    # Apply Command
    parser_apply = subparsers.add_parser(
        "apply", help="Apply configuration to create new dashboard(s)"
    )
    parser_apply.add_argument(
        "input_path", help="Path to the source dashboard JSON file or directory"
    )
    parser_apply.add_argument(
        "config_file", help="Path to the JSON config file with mappings"
    )
    parser_apply.add_argument(
        "output_path",
        help="Path to save the new dashboard JSON file or output directory",
    )

    # Map Hosts Command
    parser_map = subparsers.add_parser(
        "map-hosts", help="Map new hosts from a text file into the config.json"
    )
    parser_map.add_argument(
        "hosts_file",
        help="Path to the text file containing the new hosts (one per line)",
    )
    parser_map.add_argument(
        "config_file", help="Path to the JSON config file to update"
    )
    parser_map.add_argument(
        "--out",
        dest="output_config_file",
        help="Optional path to save the updated config. If omitted, overwrites the config_file.",
    )

    # Apply Direct Command
    parser_direct = subparsers.add_parser(
        "apply-direct", help="Directly scan, map, and apply hosts from a text file to dashboard(s)"
    )
    parser_direct.add_argument(
        "input_path", help="Path to the source dashboard JSON file or directory"
    )
    parser_direct.add_argument(
        "hosts_file",
        help="Path to the text file containing the new hosts (one per line)",
    )
    parser_direct.add_argument(
        "output_path",
        help="Path to save the new dashboard JSON file or output directory",
    )

    args = parser.parse_args()

    if args.command == "generate-config":
        generate_config(args.input_path, args.config_file)
    elif args.command == "apply":
        apply_changes(args.input_path, args.config_file, args.output_path)
    elif args.command == "map-hosts":
        map_hosts(args.hosts_file, args.config_file, args.output_config_file)
    elif args.command == "apply-direct":
        apply_direct(args.input_path, args.hosts_file, args.output_path)


if __name__ == "__main__":
    main()
