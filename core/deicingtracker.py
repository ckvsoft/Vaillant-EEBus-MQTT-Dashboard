import time
from core.log import Logger

class DeicingTracker:
    def __init__(self, ebus, socketio, callback=None):
        logger_instance = Logger()
        self.log = logger_instance.get_logger()
        self.active = False
        self.start_time = None
        self.ebus = ebus
        self.socketio = socketio
        self.callback = callback

    def update(self, value):
        is_deicing = str(value).lower() in ["1", "yes", "true"]

        if is_deicing and not self.active:
            self.start()
        elif not is_deicing and self.active:
            self.stop()

    def update_defroster_stat(self, value):
        """Changes the visual state (fan/run) without resetting the timer."""
        if not self.active:
            return

        is_defroster = str(value).lower() in ["on"]
        status_value = "run" if is_defroster else "fan"

        # We broadcast the original start_time so the frontend timer stays consistent
        self.socketio.emit("update_led", {
            "title": "Enteisen",
            "value": status_value,
            "start_time": self.start_time
        })

    def start(self):
        self.active = True
        self.start_time = time.time()  # Set once and keep it
        self.log.info("🧊 Enteisen gestartet")
        if self.callback:
            self.callback('start', 0, self.start_time)

        # Set mode to manual during deicing
        self.ebus.write_value("700", "OpMode", "0")

        self.socketio.emit("update_led", {
            "title": "Enteisen",
            "value": "fan",
            "start_time": self.start_time
        })

    def stop(self):
        now = time.time()
        duration = now - self.start_time

        if self.callback:
            self.callback('stop', duration, self.start_time)

        self.log.info(f"🧊 Enteisen beendet ({duration / 60:.1f} min)")

        # Restore automatic mode
        self.ebus.write_value("700", "OpMode", "1")

        self.socketio.emit("update_led", {
            "title": "Enteisen",
            "value": "off",
            "start_time": None
        })

        self.active = False
        self.start_time = None
