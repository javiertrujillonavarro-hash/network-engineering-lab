from netmiko import ConnectHandler
from datetime import datetime
from pathlib import Path


device = {
    "device_type": "cisco_ios",
    "host": "192.168.1.37",
    "username": "admin",
    "password": "Tu_Password",
    "port": 22,
}


# Directorio donde está este script
backup_dir = Path(__file__).parent

# Fecha y hora del backup
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Nombre del archivo
backup_file = backup_dir / f"R1_{timestamp}.cfg"


print(f"Conectando a {device['host']}...")

connection = ConnectHandler(**device)

print("Conexión establecida")

print("Obteniendo configuración...")

config = connection.send_command("show running-config")

# Guardar configuración
backup_file.write_text(config, encoding="utf-8")

print(f"Backup guardado en:")
print(backup_file)

connection.disconnect()

print("Conexión cerrada")
print("Backup completado correctamente.")