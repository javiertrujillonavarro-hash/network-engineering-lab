import os
import re
import json
from pathlib import Path
from datetime import datetime

import yaml
from dotenv import load_dotenv
from netmiko import ConnectHandler


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

USERNAME = os.getenv("CISCO_USERNAME")
PASSWORD = os.getenv("CISCO_PASSWORD")

SCRIPT_DIR = Path(__file__).parent
INVENTORY_FILE = SCRIPT_DIR.parent / "backup" / "inventory.yaml"
REPORT_DIR = SCRIPT_DIR / "reports"
PAGES_DIR = SCRIPT_DIR.parent.parent / "docs"
PAGES_DIR.mkdir(exist_ok=True)

REPORT_DIR.mkdir(exist_ok=True)

CPU_WARNING = 70
CPU_CRITICAL = 90

MEMORY_WARNING = 70
MEMORY_CRITICAL = 90


# ============================================================
# COLORS
# ============================================================

RESET = "\033[0m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"


def status_ok(text):
    return f"{GREEN}{text}{RESET}"


def status_warning(text):
    return f"{YELLOW}{text}{RESET}"


def status_critical(text):
    return f"{RED}{text}{RESET}"


# ============================================================
# CPU
# ============================================================

def get_cpu(connection):

    output = connection.send_command("show processes cpu | include CPU utilization")

    match = re.search(
        r"five seconds:\s+(\d+)%", output
    )

    if match:
        return int(match.group(1))

    match = re.search(
        r"CPU utilization.*?(\d+)%", output
    )

    if match:
        return int(match.group(1))

    return None


# ============================================================
# MEMORY
# ============================================================

def get_memory(connection):

    output = connection.send_command("show processes memory | include Processor")

    match = re.search(
        r"Processor Pool Total:\s+(\d+)\s+Used:\s+(\d+)", output
    )

    if match:

        total = int(match.group(1))
        used = int(match.group(2))

        if total > 0:
            return round((used / total) * 100, 1)

    return None


# ============================================================
# INTERFACES
# ============================================================

def get_interfaces(connection):

    output = connection.send_command("show ip interface brief")

    interfaces = []

    for line in output.splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("Interface"):
            continue

        parts = line.split()

        if len(parts) < 6:
            continue

        interface = parts[0]

        protocol = parts[-1]

        if parts[-3] == "administratively":

            status = "administratively"

        else:

            status = parts[-2]

        interfaces.append(
            {
                "interface": interface,
                "status": status,
                "protocol": protocol,
            }
        )

    return interfaces


def analyze_interfaces(interfaces):

    up = 0
    admin_down = 0
    operational_down = 0

    for interface in interfaces:

        status = interface["status"]
        protocol = interface["protocol"]

        if status == "up" and protocol == "up":

            up += 1

        elif status == "administratively":

            admin_down += 1

        else:

            operational_down += 1

    return {
        "up": up,
        "administratively_down": admin_down,
        "operational_down": operational_down,
    }


# ============================================================
# BGP
# ============================================================

def get_bgp(connection):

    output = connection.send_command(
        "show ip bgp summary",
        use_textfsm=False
    )

    if (
        "BGP router identifier" not in output
        and "BGP table version" not in output
    ):
        return None

    neighbors = 0
    established = 0

    for line in output.splitlines():

        parts = line.split()

        if len(parts) < 9:
            continue

        if re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):

            neighbors += 1

            last = parts[-1]

            if last.isdigit():

                established += 1

    return {
        "neighbors": neighbors,
        "established": established,
    }


# ============================================================
# OSPF
# ============================================================

def get_ospf(connection):

    output = connection.send_command(
        "show ip ospf neighbor"
    )

    if (
        "OSPF not enabled" in output
        or "not running" in output
    ):
        return None

    neighbors = 0

    for line in output.splitlines():

        parts = line.split()

        if len(parts) >= 6:

            if re.match(
                r"^\d+\.\d+\.\d+\.\d+$",
                parts[0]
            ):

                neighbors += 1

    return {
        "neighbors": neighbors
    }


# ============================================================
# DEVICE ANALYSIS
# ============================================================

def analyze_device(device):

    name = device["name"]
    host = device["host"]
    platform = device.get("platform", "cisco_ios")

    result = {

        "name": name,
        "host": host,
        "platform": platform,

        "status": "DOWN",

        "cpu": None,
        "memory": None,

        "interfaces": {
            "up": 0,
            "administratively_down": 0,
            "operational_down": 0,
        },

        "bgp": None,
        "ospf": None,

        "alerts": [],

    }

    print()
    print("-" * 78)
    print(f"{CYAN}{name} ({host}){RESET}")
    print("-" * 78)

    try:

        connection = ConnectHandler(

            device_type=platform,
            host=host,
            username=USERNAME,
            password=PASSWORD,

            conn_timeout=10,
            auth_timeout=10,
            banner_timeout=10,

        )

        result["status"] = "UP"

        # CPU

        cpu = get_cpu(connection)

        result["cpu"] = cpu

        if cpu is not None:

            if cpu >= CPU_CRITICAL:

                result["alerts"].append(
                    f"CPU CRITICAL: {cpu}%"
                )

            elif cpu >= CPU_WARNING:

                result["alerts"].append(
                    f"CPU WARNING: {cpu}%"
                )

        # MEMORY

        memory = get_memory(connection)

        result["memory"] = memory

        if memory is not None:

            if memory >= MEMORY_CRITICAL:

                result["alerts"].append(
                    f"MEMORY CRITICAL: {memory}%"
                )

            elif memory >= MEMORY_WARNING:

                result["alerts"].append(
                    f"MEMORY WARNING: {memory}%"
                )

        # INTERFACES

        interfaces = get_interfaces(connection)

        interface_summary = analyze_interfaces(
            interfaces
        )

        result["interfaces"] = interface_summary

        if interface_summary["operational_down"] > 0:

            result["alerts"].append(
                f"Operational interfaces DOWN: "
                f"{interface_summary['operational_down']}"
            )

        # BGP

        result["bgp"] = get_bgp(connection)

        # OSPF

        result["ospf"] = get_ospf(connection)

        connection.disconnect()

    except Exception as error:

        result["status"] = "DOWN"

        result["alerts"].append(
            f"SSH/connection error: {str(error)}"
        )

    # ========================================================
    # CONSOLE
    # ========================================================

    if result["status"] == "DOWN":

        print(
            status_critical(
                "STATUS: DOWN"
            )
        )

    else:

        print(
            status_ok(
                "STATUS: UP"
            )
        )

    print(
        f"CPU: {result['cpu']}%"
    )

    print(
        f"Memory: {result['memory']}%"
    )

    print(
        "Interfaces: "
        f"UP={result['interfaces']['up']} "
        f"ADMIN-DOWN={result['interfaces']['administratively_down']} "
        f"OP-DOWN={result['interfaces']['operational_down']}"
    )

    if result["bgp"] is None:

        print("BGP: N/A")

    else:

        print(
            f"BGP: "
            f"{result['bgp']['established']}/"
            f"{result['bgp']['neighbors']}"
        )

    if result["ospf"] is None:

        print("OSPF: N/A")

    else:

        print(
            f"OSPF neighbors: "
            f"{result['ospf']['neighbors']}"
        )

    if result["alerts"]:

        for alert in result["alerts"]:

            print(
                status_warning(
                    f"ALERT: {alert}"
                )
            )

    return result


# ============================================================
# HTML DASHBOARD
# ============================================================

def generate_dashboard(report):

    rows = ""

    for device in report["devices"]:

        if device["status"] == "UP":
            status_class = "ok"
            status_text = "UP"
        else:
            status_class = "critical"
            status_text = "DOWN"

        alerts = "<br>".join(device["alerts"])

        if not alerts:
            alerts = "None"

        bgp = "N/A"

        if device["bgp"] is not None:

            bgp = (
                f"{device['bgp']['established']}/"
                f"{device['bgp']['neighbors']}"
            )

        ospf = "N/A"

        if device["ospf"] is not None:

            ospf = str(
                device["ospf"]["neighbors"]
            )

        rows += f"""
        <tr>
            <td><strong>{device['name']}</strong></td>
            <td>{device['host']}</td>
            <td>
                <span class="status {status_class}">
                    {status_text}
                </span>
            </td>
            <td>{device['cpu']}%</td>
            <td>{device['memory']}%</td>
            <td>{device['interfaces']['up']}</td>
            <td>{device['interfaces']['administratively_down']}</td>
            <td>{device['interfaces']['operational_down']}</td>
            <td>{bgp}</td>
            <td>{ospf}</td>
            <td>{alerts}</td>
        </tr>
        """

    status = report["summary"]["status"]

    if status == "HEALTHY":

        global_class = "ok"

    elif status == "WARNING":

        global_class = "warning"

    else:

        global_class = "critical"

    html = f"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta http-equiv="refresh" content="300">

<title>Network Health Dashboard</title>

<style>

body {{
    font-family: Arial, sans-serif;
    margin: 30px;
    background: #f4f6f8;
    color: #222;
}}

h1 {{
    margin-bottom: 5px;
}}

.timestamp {{
    color: #666;
    margin-bottom: 25px;
}}

.global {{
    padding: 18px;
    border-radius: 8px;
    margin-bottom: 25px;
    font-size: 22px;
    font-weight: bold;
}}

.ok {{
    color: #0a7a35;
}}

.warning {{
    color: #a66a00;
}}

.critical {{
    color: #b00020;
}}

.status {{
    font-weight: bold;
}}

table {{
    border-collapse: collapse;
    width: 100%;
    background: white;
}}

th, td {{
    border: 1px solid #ddd;
    padding: 10px;
    text-align: center;
}}

th {{
    background: #222;
    color: white;
}}

tr:nth-child(even) {{
    background: #f7f7f7;
}}

.summary {{
    display: flex;
    gap: 15px;
    margin-bottom: 25px;
}}

.card {{
    background: white;
    padding: 20px;
    border-radius: 8px;
    min-width: 130px;
    box-shadow: 0 1px 4px rgba(0,0,0,.15);
}}

.card-title {{
    font-size: 13px;
    color: #777;
}}

.card-value {{
    font-size: 28px;
    font-weight: bold;
}}

</style>

</head>

<body>

<h1>Network Health Dashboard</h1>

<div class="timestamp">
Last update: {report['timestamp']}
</div>

<div class="global {global_class}">
Network Status: {status}
</div>

<div class="summary">

<div class="card">
<div class="card-title">Devices UP</div>
<div class="card-value">
{report['summary']['devices_up']}
</div>
</div>

<div class="card">
<div class="card-title">Devices DOWN</div>
<div class="card-value">
{report['summary']['devices_down']}
</div>
</div>

<div class="card">
<div class="card-title">Interfaces UP</div>
<div class="card-value">
{report['summary']['interfaces_up']}
</div>
</div>

<div class="card">
<div class="card-title">Operational DOWN</div>
<div class="card-value">
{report['summary']['interfaces_operational_down']}
</div>
</div>

<div class="card">
<div class="card-title">Alerts</div>
<div class="card-value">
{report['summary']['alerts']}
</div>
</div>

</div>

<table>

<thead>

<tr>

<th>Device</th>
<th>IP</th>
<th>Status</th>
<th>CPU</th>
<th>Memory</th>
<th>UP</th>
<th>Admin DOWN</th>
<th>Op DOWN</th>
<th>BGP</th>
<th>OSPF</th>
<th>Alerts</th>

</tr>

</thead>

<tbody>

{rows}

</tbody>

</table>

</body>

</html>
"""

    dashboard_file = PAGES_DIR / "index.html"

    dashboard_file.write_text(
        html,
        encoding="utf-8"
    )

    return dashboard_file


# ============================================================
# MAIN
# ============================================================

print()
print("=" * 78)
print("NETWORK HEALTH MONITOR")
print("=" * 78)

with open(
    INVENTORY_FILE,
    "r",
    encoding="utf-8"
) as file:

    inventory = yaml.safe_load(file)

devices = inventory["devices"]

results = []

for device in devices:

    results.append(
        analyze_device(device)
    )


# ============================================================
# SUMMARY
# ============================================================

devices_up = sum(
    1
    for device in results
    if device["status"] == "UP"
)

devices_down = len(results) - devices_up

interfaces_up = sum(
    device["interfaces"]["up"]
    for device in results
)

interfaces_admin_down = sum(
    device["interfaces"]["administratively_down"]
    for device in results
)

interfaces_operational_down = sum(
    device["interfaces"]["operational_down"]
    for device in results
)

total_alerts = sum(
    len(device["alerts"])
    for device in results
)

if devices_down > 0:

    network_status = "CRITICAL"

elif total_alerts > 0:

    network_status = "WARNING"

else:

    network_status = "HEALTHY"


timestamp = datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)

timestamp_file = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)


report = {

    "timestamp": timestamp,

    "summary": {

        "status": network_status,

        "devices_total": len(results),

        "devices_up": devices_up,

        "devices_down": devices_down,

        "interfaces_up": interfaces_up,

        "interfaces_admin_down": interfaces_admin_down,

        "interfaces_operational_down":
            interfaces_operational_down,

        "alerts": total_alerts,

    },

    "devices": results,

}


# ============================================================
# JSON
# ============================================================

json_file = (
    REPORT_DIR
    / f"network_health_{timestamp_file}.json"
)

json_latest = (
    REPORT_DIR
    / "network_health_latest.json"
)

with open(
    json_file,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        report,
        file,
        indent=4,
        ensure_ascii=False
    )

with open(
    json_latest,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        report,
        file,
        indent=4,
        ensure_ascii=False
    )


# ============================================================
# TXT
# ============================================================

txt_file = (
    REPORT_DIR
    / f"network_health_{timestamp_file}.txt"
)

txt_latest = (
    REPORT_DIR
    / "network_health_latest.txt"
)

lines = []

lines.append(
    "NETWORK HEALTH REPORT"
)

lines.append(
    "=" * 78
)

lines.append(
    f"Timestamp: {timestamp}"
)

lines.append(
    f"Network Status: {network_status}"
)

lines.append("")

for device in results:

    lines.append(
        f"{device['name']} "
        f"{device['host']} "
        f"{device['status']}"
    )

    lines.append(
        f"CPU: {device['cpu']}%"
    )

    lines.append(
        f"Memory: {device['memory']}%"
    )

    lines.append(
        "Interfaces: "
        f"UP={device['interfaces']['up']} "
        f"ADMIN-DOWN="
        f"{device['interfaces']['administratively_down']} "
        f"OP-DOWN="
        f"{device['interfaces']['operational_down']}"
    )

    if device["bgp"] is None:

        lines.append(
            "BGP: N/A"
        )

    else:

        lines.append(
            f"BGP: "
            f"{device['bgp']['established']}/"
            f"{device['bgp']['neighbors']}"
        )

    if device["ospf"] is None:

        lines.append(
            "OSPF: N/A"
        )

    else:

        lines.append(
            f"OSPF neighbors: "
            f"{device['ospf']['neighbors']}"
        )

    if device["alerts"]:

        lines.append(
            "Alerts:"
        )

        for alert in device["alerts"]:

            lines.append(
                f"  - {alert}"
            )

    lines.append("")


txt_content = "\n".join(lines)

txt_file.write_text(
    txt_content,
    encoding="utf-8"
)

txt_latest.write_text(
    txt_content,
    encoding="utf-8"
)


# ============================================================
# DASHBOARD
# ============================================================

dashboard_file = generate_dashboard(
    report
)


# ============================================================
# FINAL OUTPUT
# ============================================================

print()
print("=" * 78)

if network_status == "CRITICAL":

    print(
        status_critical(
            "NETWORK STATUS: CRITICAL"
        )
    )

elif network_status == "WARNING":

    print(
        status_warning(
            "NETWORK STATUS: WARNING"
        )
    )

else:

    print(
        status_ok(
            "NETWORK STATUS: HEALTHY"
        )
    )

print("=" * 78)

print()

print(
    f"JSON report : {json_file}"
)

print(
    f"JSON latest : {json_latest}"
)

print(
    f"TXT report  : {txt_file}"
)

print(
    f"TXT latest  : {txt_latest}"
)

print(
    f"Dashboard   : {dashboard_file}"
)

print()