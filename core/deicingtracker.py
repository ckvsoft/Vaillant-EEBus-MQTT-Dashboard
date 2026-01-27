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

    def start(self, now):
        self.active = True
        self.start_time = now
        self.log.info("🧊 Enteisen gestartet")
        self.ebus.write_value("700", "OpMode", "0")
        self.socketio.emit("update_led", {"title": "Deicing", "value": "on", "start_time": now})

    def stop(self, now):
        duration = now - self.start_time
        self.log.info(f"🧊 Enteisen beendet ({duration/60:.1f} min)")
        self.ebus.write_value("700", "OpMode", "2")
        self.active = False
        self.start_time = None
        self.socketio.emit("update_led", {"title": "Deicing", "value": "off", "start_time": None})
        if self.stop_callback:
            self.stop_callback(duration, self.start_time)