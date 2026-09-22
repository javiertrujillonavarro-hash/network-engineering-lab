from netmiko import ConnectHandler

device = {
    "device_type": "cisco_ios",
    "host": "192.168.1.37",
    "username": "admin",
    "password": "Tu_Password",
    "port": 22,
}

print("Conectando al router...")

connection = ConnectHandler(**device)

print("Conectado correctamente")

output = connection.send_command("show running-config")

print(output)

connection.disconnect()

print("Conexión cerrada")