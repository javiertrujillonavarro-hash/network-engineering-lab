import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from netmiko import ConnectHandler


# ============================================
# CARGAR VARIABLES DE ENTORNO
# ============================================

load_dotenv()

username = os.getenv("CISCO_USERNAME")
password = os.getenv("CISCO_PASSWORD")


# ============================================
# RUTAS
# ============================================

script_dir = Path(__file__).parent

inventory_file = script_dir / "inventory.yaml"

backup_dir = script_dir


# ============================================
# CARGAR INVENTARIO YAML
# ============================================

with open(inventory_file, "r", encoding="utf-8") as file:
    inventory = yaml.safe_load(file)

devices = inventory["devices"]


# ============================================
# INFORMACIÓN INICIAL
# ============================================

print()
print("========================================")
print("       CISCO NETWORK BACKUP")
print("========================================")
print()

print(f"Devices found in inventory: {len(devices)}")
print()


# ============================================
# VARIABLES DE RESULTADO
# ============================================

successful = 0
failed = 0


# ============================================
# PROCESAR DISPOSITIVOS
# ============================================

for device_info in devices:

    name = device_info["name"]
    host = device_info["host"]
    platform = device_info["platform"]

    print("----------------------------------------")
    print(f"Device : {name}")
    print(f"IP     : {host}")
    print("----------------------------------------")

    device = {
        "device_type": platform,
        "host": host,
        "username": username,
        "password": password,
        "port": 22,
    }

    connection = None

    try:

        # ------------------------------------
        # CONEXIÓN
        # ------------------------------------

        print(f"Connecting to {name}...")

        connection = ConnectHandler(**device)

        print(f"[OK] Connected to {name}")

        # ------------------------------------
        # OBTENER RUNNING CONFIG
        # ------------------------------------

        print("Getting running configuration...")

        config = connection.send_command(
            "show running-config"
        )

        # ------------------------------------
        # CREAR NOMBRE DEL BACKUP
        # ------------------------------------

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        backup_file = (
            backup_dir /
            f"{name}_{timestamp}.cfg"
        )

        # ------------------------------------
        # GUARDAR BACKUP
        # ------------------------------------

        backup_file.write_text(
            config,
            encoding="utf-8"
        )

        print(
            f"[OK] Backup saved: {backup_file.name}"
        )

        successful += 1

    except Exception as error:

        print(f"[ERROR] {name}: {error}")

        failed += 1

    finally:

        # ------------------------------------
        # CERRAR CONEXIÓN
        # ------------------------------------

        if connection:

            connection.disconnect()

            print(
                f"[OK] Connection closed: {name}"
            )

    print()


# ============================================
# RESUMEN
# ============================================

print("========================================")
print("           BACKUP SUMMARY")
print("========================================")

print(f"Total devices : {len(devices)}")
print(f"Successful    : {successful}")
print(f"Failed        : {failed}")

print("========================================")
print()

if failed == 0:

    print("BACKUP COMPLETED SUCCESSFULLY")

else:

    print("BACKUP COMPLETED WITH ERRORS")