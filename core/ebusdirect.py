import socket
import time
from core.log import Logger

class EbusDirect:
    def __init__(self, host="127.0.0.1", port=8888):
        logger_instance = Logger()
        self.log = logger_instance.get_logger()

        self.log.info(f"Starting EBUS Socket host: {host} port: {port}")
        self.host = host
        self.port = port

    def write_value(self, circuit, name, value, retries=3, verify=True):
        """
        Writes a value to the EBUS and optionally verifies if it was set correctly.
        """
        for attempt in range(1, retries + 1):
            try:
                cmd = f"write -c {circuit} {name} {value}\n"
                self.log.debug(f"EBUS write (Attempt {attempt}): {cmd.strip()}")

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(3)
                    s.connect((self.host, self.port))
                    s.sendall(cmd.encode())
                    response = s.recv(1024).decode().strip()

                # ebusd usually responds with "done" or the value itself on success
                if "done" in response.lower() or response == str(value):
                    if verify:
                        # Brief pause to allow the bus/device to process the update
                        time.sleep(0.5)
                        current_val = self.read_value(circuit, name)

                        # Comparison: Convert to string for basic check,
                        # but be aware of float formatting (e.g., 20 vs 20.0)
                        if current_val == str(value):
                            self.log.info(f"Successfully written and verified: {name}={value}")
                            return True
                        else:
                            self.log.warning(f"Verification failed for {name}: Expected {value}, got {current_val}")
                    else:
                        self.log.info(f"Write successful (unverified): {name}={value}")
                        return True
                else:
                    self.log.error(f"ebusd returned error: {response}")

            except Exception as e:
                self.log.error(f"Socket error during write (Attempt {attempt}): {e}")

            # Incremental backoff before retrying
            time.sleep(1 * attempt)

        self.log.error(f"Failed to write {name} after {retries} attempts.")
        return False

    def read_value(self, circuit, name):
        """
        Reads a value from the EBUS.
        """
        # Using -f to force a read from the bus rather than the ebusd cache
        cmd = f"read -f -c {circuit} {name}\n"
        self.log.debug(f"EBUS read: {cmd.strip()}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.host, self.port))
                s.sendall(cmd.encode())
                response = s.recv(1024).decode().strip()

                # Check for error responses from ebusd (e.g., ERR: ...)
                if "err" in response.lower():
                    self.log.error(f"ebusd read error for {name}: {response}")
                    return None

                return response
        except Exception as e:
            self.log.error(f"EBUS socket error reading {name}: {e}")
            return None

    def ebus_poller(self, polling_list, callback=None):
        """
        Periodically polls values from the EBUS.
        """
        if not polling_list:
            self.log.warning("EBUS Poller: No items found in configuration.")
            return

        self.log.info("Starting EBUS polling loop...")
        while True:
            for item in polling_list:
                circuit = item.get("circuit")
                name = item.get("name")
                if circuit and name:
                    value = self.read_value(circuit, name)

                    if callback:
                        callback(circuit, name, value)

                    # Small delay between individual reads to reduce bus load
                    time.sleep(1)

            # Wait before starting the next full polling cycle
            time.sleep(30)