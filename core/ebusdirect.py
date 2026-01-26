import socket
import time

from core.log import Logger

logger_instance = Logger(log_filename="ebusdirect.log")
LOG_FILE_PATH = logger_instance.get_log_file()

log = logger_instance.get_logger()  # Hol dir den eigentlichen Logger

class EbusDirect:
    def __init__(self, host="127.0.0.1", port=8888):
        log.info(f"Start EBUS Socket host: {host} port: {port}")
        self.host = host
        self.port = port

    def write_value(self, circuit, name, value):
        try:
            cmd = f"write -c {circuit} {name} {value}\n"
            log.debug(f"write ebus: {cmd}")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                s.connect((self.host, self.port))
                s.sendall(cmd.encode())
                return s.recv(1024).decode().strip()
        except:
            return None

    def read_value(self, circuit, name):
        # read -f -c hmu CompressorStarts\n
        cmd = f"read -f -c {circuit} {name}\n"
        log.debug(f"read ebus: {cmd}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.host, self.port))
                s.sendall(cmd.encode())
                response = s.recv(1024).decode().strip()
                return response
        except Exception as e:
            log.error(f"EBUS Socket Fehler bei {name}: {e}")
            return None

    def ebus_poller(self, polling_list, callback=None):
        if not polling_list:
            log.warning("EBUS-Poller: Keine Werte in der Konfiguration gefunden.")
            return

        while True:
            for item in polling_list:
                circuit = item.get("circuit")
                name = item.get("name")
                if circuit and name:
                    value = self.read_value(circuit, name)

                    if callback:
                        callback(circuit, name, value)

                    time.sleep(1)

            time.sleep(30)
