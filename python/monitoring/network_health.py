import os
import re
from pathlib import Path

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


# Thresholds
CPU_WARNING = 70
CPU_CRITICAL = 90

MEMORY_WARNING = 70
MEMORY_CRITICAL = 90


# ============================================================
# COLORS / STATUS
# ============================================================

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


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

    output = connection.send_command(
        "show processes cpu | include CPU utilization"
    )

    match = re.search(
        r"five minutes:\s+(\d+)%",
        output
    )

    if match:
        return int(match.group(1))

    return None


# ============================================================
# MEMORY
# ============================================================

def get_memory(connection):

    output = connection.send_command(
        "show processes memory | include Processor Pool"
    )

    match = re.search(
        r"Processor Pool Total:\s+(\d+).*?Used:\s+(\d+)",
        output,
        re.S,
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

    output = connection.send_command(
        "show ip interface brief"
    )

    interfaces = []

    for line in output.splitlines():

        if not line.strip():
            continue

        if line.startswith("Interface"):
            continue

        parts = line.split()

        if len(parts) < 6:
            continue

        interface = parts[0]
        ip_address = parts[1]
        status = parts[-2]
        protocol = parts[-1]

        interfaces.append(
            {
                "interface": interface,
                "ip": ip_address,
                "status": status,
                "protocol": protocol,
            }
        )

    return interfaces


# ============================================================
# INTERFACE ANALYSIS
# ============================================================

def analyze_interfaces(interfaces):

    up = 0
    admin_down = 0
    operational_down = 0

    problems = []

    for interface in interfaces:

        status = interface["status"]
        protocol = interface["protocol"]

        if status == "up" and protocol == "up":

            up += 1

        elif status == "administratively" and protocol == "down":

            admin_down += 1

        else:

            operational_down += 1

            problems.append(interface)

    return (
        up,
        admin_down,
        operational_down,
        problems,
    )


# ============================================================
# BGP
# ============================================================

def get_bgp(connection):

    output = connection.send_command(
        "show ip bgp summary"
    )

    if (
        "BGP router identifier" not in output
        and "BGP table version" not in output
    ):
        return None, None

    established = 0
    down = 0

    for line in output.splitlines():

        parts = line.split()

        if len(parts) < 3:
            continue

        if re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):

            last_field = parts[-1]

            if last_field.isdigit():
                established += 1

            else:
                down += 1

    return established, down


# ============================================================
# OSPF
# ============================================================

def get_ospf(connection):

    output = connection.send_command(
        "show ip ospf neighbor"
    )

    if not output.strip():

        return None, None

    if (
        "Neighbor ID" not in output
        and "Neighbor" not in output
    ):

        return None, None

    established = 0
    down = 0

    for line in output.splitlines():

        if "FULL" in line:

            established += 1

        elif any(
            state in line
            for state in [
                "DOWN",
                "INIT",
                "EXSTART",
                "EXCHANGE",
                "LOADING",
            ]
        ):

            down += 1

    return established, down


# ============================================================
# DEVICE STATUS
# ============================================================

def analyze_device(result):

    alerts = []

    # Device connectivity

    if result["status"] == "DOWN":

        alerts.append(
            "CRITICAL: Device unreachable"
        )

        return alerts

    # CPU

    cpu = result["cpu"]

    if cpu is not None:

        if cpu >= CPU_CRITICAL:

            alerts.append(
                f"CRITICAL: CPU {cpu}%"
            )

        elif cpu >= CPU_WARNING:

            alerts.append(
                f"WARNING: CPU {cpu}%"
            )

    # Memory

    memory = result["memory"]

    if memory is not None:

        if memory >= MEMORY_CRITICAL:

            alerts.append(
                f"CRITICAL: Memory {memory}%"
            )

        elif memory >= MEMORY_WARNING:

            alerts.append(
                f"WARNING: Memory {memory}%"
            )

    # Interfaces

    for interface in result["interface_problems"]:

        alerts.append(
            f"WARNING: {interface['interface']} "
            f"{interface['status']}/{interface['protocol']}"
        )

    # BGP

    if result["bgp_up"] is not None:

        if result["bgp_down"] > 0:

            alerts.append(
                f"CRITICAL: "
                f"{result['bgp_down']} BGP neighbor(s) down"
            )

    # OSPF

    if result["ospf_up"] is not None:

        if result["ospf_down"] > 0:

            alerts.append(
                f"CRITICAL: "
                f"{result['ospf_down']} OSPF neighbor(s) not FULL"
            )

    return alerts


# ============================================================
# LOAD INVENTORY
# ============================================================

with open(
    INVENTORY_FILE,
    "r",
    encoding="utf-8"
) as file:

    inventory = yaml.safe_load(file)


devices = inventory["devices"]


# ============================================================
# HEADER
# ============================================================

print()

print("=" * 78)
print("                         NETWORK HEALTH V2")
print("=" * 78)

print()

print(
    f"Devices in inventory: {len(devices)}"
)

print()


# ============================================================
# HEALTH CHECK
# ============================================================

results = []


for device_info in devices:

    name = device_info["name"]
    host = device_info["host"]
    platform = device_info["platform"]

    print("-" * 78)

    print(
        f"Device : {name}"
    )

    print(
        f"IP     : {host}"
    )

    print("-" * 78)

    device = {
        "device_type": platform,
        "host": host,
        "username": USERNAME,
        "password": PASSWORD,
        "port": 22,
    }

    connection = None

    result = {
        "name": name,
        "host": host,
        "status": "DOWN",
        "cpu": None,
        "memory": None,
        "interfaces": [],
        "interfaces_up": 0,
        "interfaces_admin_down": 0,
        "interfaces_down": 0,
        "interface_problems": [],
        "bgp_up": None,
        "bgp_down": None,
        "ospf_up": None,
        "ospf_down": None,
    }

    try:

        print(
            "Connecting..."
        )

        connection = ConnectHandler(
            **device
        )

        result["status"] = "UP"

        print(
            status_ok(
                "[OK] SSH connection"
            )
        )

        # CPU

        result["cpu"] = get_cpu(
            connection
        )

        # MEMORY

        result["memory"] = get_memory(
            connection
        )

        # INTERFACES

        interfaces = get_interfaces(
            connection
        )

        result["interfaces"] = interfaces

        (
            result["interfaces_up"],
            result["interfaces_admin_down"],
            result["interfaces_down"],
            result["interface_problems"],
        ) = analyze_interfaces(
            interfaces
        )

        # BGP

        (
            result["bgp_up"],
            result["bgp_down"],
        ) = get_bgp(
            connection
        )

        # OSPF

        (
            result["ospf_up"],
            result["ospf_down"],
        ) = get_ospf(
            connection
        )

        print(
            status_ok(
                "[OK] Health data collected"
            )
        )

    except Exception as error:

        print(
            status_critical(
                f"[ERROR] {error}"
            )
        )

    finally:

        if connection:

            connection.disconnect()

            print(
                "[OK] Connection closed"
            )

    # Analyze

    result["alerts"] = analyze_device(
        result
    )

    results.append(
        result
    )

    print()


# ============================================================
# SUMMARY
# ============================================================

print()

print("=" * 78)
print("                           SUMMARY")
print("=" * 78)

print()

print(
    f"{'DEVICE':<10}"
    f"{'STATUS':<10}"
    f"{'CPU':<8}"
    f"{'MEM':<8}"
    f"{'INT':<12}"
    f"{'BGP':<10}"
    f"{'OSPF':<10}"
)

print("-" * 78)


for result in results:

    if result["status"] == "UP":

        if result["alerts"]:

            status = status_warning(
                "WARNING"
            )

        else:

            status = status_ok(
                "UP"
            )

    else:

        status = status_critical(
            "DOWN"
        )

    cpu = (
        f"{result['cpu']}%"
        if result["cpu"] is not None
        else "-"
    )

    memory = (
        f"{result['memory']}%"
        if result["memory"] is not None
        else "-"
    )

    interfaces = (
        f"{result['interfaces_up']} UP / "
        f"{result['interfaces_down']} DOWN"
    )

    if result["bgp_up"] is None:

        bgp = "N/A"

    else:

        bgp = (
            f"{result['bgp_up']} UP / "
            f"{result['bgp_down']} DOWN"
        )

    if result["ospf_up"] is None:

        ospf = "N/A"

    else:

        ospf = (
            f"{result['ospf_up']} UP / "
            f"{result['ospf_down']} DOWN"
        )

    print(
        f"{result['name']:<10}"
        f"{status:<19}"
        f"{cpu:<8}"
        f"{memory:<8}"
        f"{interfaces:<12}"
        f"{bgp:<10}"
        f"{ospf:<10}"
    )


# ============================================================
# ALERTS
# ============================================================

print()

print("=" * 78)
print("                            ALERTS")
print("=" * 78)

print()

total_alerts = 0


for result in results:

    if not result["alerts"]:
        continue

    print(
        f"{result['name']}:"
    )

    for alert in result["alerts"]:

        total_alerts += 1

        if "CRITICAL" in alert:

            print(
                status_critical(
                    f"  🔴 {alert}"
                )
            )

        else:

            print(
                status_warning(
                    f"  🟡 {alert}"
                )
            )

    print()


# ============================================================
# FINAL STATUS
# ============================================================

devices_up = sum(
    1
    for result in results
    if result["status"] == "UP"
)

devices_down = len(results) - devices_up


print("=" * 78)

print(
    f"Devices UP       : {devices_up}"
)

print(
    f"Devices DOWN     : {devices_down}"
)

print(
    f"Total alerts     : {total_alerts}"
)

print("=" * 78)

print()


if devices_down > 0:

    print(
        status_critical(
            "🔴 NETWORK STATUS: CRITICAL"
        )
    )

elif total_alerts > 0:

    print(
        status_warning(
            "🟡 NETWORK STATUS: WARNING"
        )
    )

else:

    print(
        status_ok(
            "🟢 NETWORK STATUS: HEALTHY"
        )
    )

print()