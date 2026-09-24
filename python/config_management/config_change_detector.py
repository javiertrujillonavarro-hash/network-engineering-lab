import os
import subprocess
import difflib
from pathlib import Path
from datetime import datetime

import yaml
from dotenv import load_dotenv
from netmiko import ConnectHandler


# ============================================================
# PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent

ENV_FILE = PROJECT_DIR / ".env"
INVENTORY_FILE = PROJECT_DIR / "python" / "backup" / "inventory.yaml"

CONFIG_DIR = PROJECT_DIR / "configs"
DIFF_DIR = PROJECT_DIR / "reports" / "config_changes"

CONFIG_DIR.mkdir(exist_ok=True)
DIFF_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_FILE)

USERNAME = os.getenv("CISCO_USERNAME")
PASSWORD = os.getenv("CISCO_PASSWORD")


# ============================================================
# FUNCTIONS
# ============================================================

def load_inventory():
    """Load devices from inventory.yaml."""

    with open(INVENTORY_FILE, "r", encoding="utf-8") as file:
        inventory = yaml.safe_load(file)

    return inventory["devices"]


def normalize_config(config):
    """
    Normalize configuration before comparison.

    Removes dynamic/noise lines that should not trigger
    a configuration change.
    """

    ignored_patterns = [
        "ntp clock-period",
        "Building configuration",
        "Current configuration",
        "^!",
    ]

    lines = []

    for line in config.splitlines():

        stripped = line.strip()

        if not stripped:
            continue

        ignored = False

        for pattern in ignored_patterns:

            if pattern.startswith("^"):

                if stripped.startswith(pattern[1:]):
                    ignored = True
                    break

            elif pattern in stripped:
                ignored = True
                break

        if not ignored:
            lines.append(line.rstrip())

    return "\n".join(lines) + "\n"


def get_device_config(device):
    """Connect to Cisco device and retrieve running configuration."""

    name = device["name"]
    ip = device["host"]
    platform = device.get("platform", "cisco_ios")

    print("-" * 70)
    print(f"Device : {name}")
    print(f"IP     : {ip}")
    print("-" * 70)

    connection = None

    try:

        print("Connecting...")

        connection = ConnectHandler(
            device_type=platform,
            host=ip,
            username=USERNAME,
            password=PASSWORD,
            port=device.get("port", 22),
            timeout=15,
            banner_timeout=30,
            auth_timeout=15,
        )
        print("[OK] SSH connection")

        print("Getting running configuration...")

        config = connection.send_command(
            "show running-config",
            read_timeout=60,
        )

        print("[OK] Configuration collected")

        return normalize_config(config)

    except Exception as error:

        print(f"[ERROR] {name}: {error}")
        return None

    finally:

        if connection:

            connection.disconnect()
            print("[OK] Connection closed")


def compare_config(device_name, new_config):
    """
    Compare current configuration against stored configuration.
    """

    device_dir = CONFIG_DIR / device_name
    device_dir.mkdir(parents=True, exist_ok=True)

    current_file = device_dir / "current.cfg"

    # --------------------------------------------------------
    # First execution = baseline
    # --------------------------------------------------------

    if not current_file.exists():

        current_file.write_text(
            new_config,
            encoding="utf-8",
        )

        print(f"[BASELINE] {device_name}")

        return False, None

    old_config = current_file.read_text(
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # No change
    # --------------------------------------------------------

    if old_config == new_config:

        print(f"[NO CHANGE] {device_name}")

        return False, None

    # --------------------------------------------------------
    # Configuration changed
    # --------------------------------------------------------

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    history_dir = device_dir / "history"
    history_dir.mkdir(exist_ok=True)

    history_file = (
        history_dir
        / f"{device_name}_{timestamp}.cfg"
    )

    history_file.write_text(
        new_config,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Generate unified diff
    # --------------------------------------------------------

    diff = list(
        difflib.unified_diff(
            old_config.splitlines(),
            new_config.splitlines(),
            fromfile=f"{device_name}/previous.cfg",
            tofile=f"{device_name}/current.cfg",
            lineterm="",
        )
    )

    diff_text = "\n".join(diff) + "\n"

    diff_file = (
        DIFF_DIR
        / f"{device_name}_{timestamp}.diff"
    )

    diff_file.write_text(
        diff_text,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Update current configuration
    # --------------------------------------------------------

    current_file.write_text(
        new_config,
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print(f"CONFIGURATION CHANGE DETECTED: {device_name}")
    print("=" * 70)
    print(diff_text)
    print("=" * 70)

    print(f"Current : {current_file}")
    print(f"History : {history_file}")
    print(f"Diff    : {diff_file}")

    return True, diff_file


def git_commit_and_push(changed_devices):
    """
    Commit configuration changes and push to GitHub.
    """

    if not changed_devices:
        print()
        print("[GIT] No configuration changes detected.")
        return

    print()
    print("=" * 70)
    print("GITHUB CONFIGURATION MANAGEMENT")
    print("=" * 70)

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    device_list = ", ".join(changed_devices)

    commit_message = (
        f"Network configuration change: "
        f"{device_list} - {timestamp}"
    )

    try:

        print("[GIT] Adding configuration changes...")

        subprocess.run(
            [
                "git",
                "add",
                "configs",
                "reports/config_changes",
            ],
            cwd=PROJECT_DIR,
            check=True,
        )

        print("[GIT] Creating commit...")

        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                commit_message,
            ],
            cwd=PROJECT_DIR,
            check=True,
        )

        print("[GIT] Pushing to GitHub...")

        subprocess.run(
            [
                "git",
                "push",
                "origin",
                "main",
            ],
            cwd=PROJECT_DIR,
            check=True,
        )

        print()
        print("[OK] Configuration change pushed to GitHub")

    except subprocess.CalledProcessError as error:

        print(
            f"[ERROR] Git operation failed: {error}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("       CISCO CONFIGURATION CHANGE DETECTOR")
    print("=" * 70)
    print()

    devices = load_inventory()

    print(
        f"Devices in inventory: {len(devices)}"
    )

    print()

    changed_devices = []

    for device in devices:

        config = get_device_config(device)

        if config is None:
            continue

        changed, diff_file = compare_config(
            device["name"],
            config,
        )

        if changed:
            changed_devices.append(
                device["name"]
            )

        print()

    # --------------------------------------------------------
    # Git
    # --------------------------------------------------------

    git_commit_and_push(
        changed_devices
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("CONFIGURATION MANAGEMENT SUMMARY")
    print("=" * 70)

    print(
        f"Devices checked : {len(devices)}"
    )

    print(
        f"Changes detected: {len(changed_devices)}"
    )

    if changed_devices:

        print(
            "Changed devices : "
            + ", ".join(changed_devices)
        )

    else:

        print(
            "Status          : NO CONFIGURATION CHANGES"
        )

    print("=" * 70)
    print()


if __name__ == "__main__":
    main()