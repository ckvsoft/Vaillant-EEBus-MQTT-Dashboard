import time

from core.log import Logger

class DeicingTracker:
    def __init__(self, ebus, socketio, stop_callback=None):
        logger_instance = Logger()
        self.log = logger_instance.get_logger()
        self.prev_status = None
        self.active = False
        self.start_time = None
        self.ebus = ebus
        self.socketio = socketio
        self.stop_callback = stop_callback

    def update(self, value):
        is_deicing = str(value).lower() in ["1", "yes", "true"]
        now = time.time()

        if is_deicing and not self.active:
            self.start(now)
        elif not is_deicing and self.active:
            self.stop(now)

    def update_defroster_stat(self, value):
        is_defroster = str(value).lower() in ["on"]
        if is_defroster and self.active:
            self.socketio.emit("update_led", {"title": "Enteisen", "value": "run", "start_time": self.start_time})
        elif not is_defroster and self.active:
            self.socketio.emit("update_led", {"title": "Enteisen", "value": "fan", "start_time": self.start_time})

    def start(self, now):
        self.active = True
        self.start_time = now
        self.log.info("🧊 Enteisen gestartet")
        self.ebus.write_value("700", "OpMode", "0")
        self.socketio.emit("update_led", {"title": "Enteisen", "value": "fan", "start_time": now})

    def stop(self, now):
        duration = now - self.start_time
        self.log.info(f"🧊 Enteisen beendet ({duration/60:.1f} min)")
        self.ebus.write_value("700", "OpMode", "1")
        self.active = False
        self.start_time = None
        self.socketio.emit("update_led", {"title": "Enteisen", "value": "off", "start_time": None})
        if self.stop_callback:
            self.stop_callback(duration, self.start_time)