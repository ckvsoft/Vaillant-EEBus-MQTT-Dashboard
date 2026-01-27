
import re
import threading
import paho.mqtt.client as mqtt
from flask import Flask, render_template, send_from_directory, Response
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import time
import json
import os

from core.deicingtracker import DeicingTracker
from core.log import Logger
from core.ebusdirect import EbusDirect

# Flask App initialisieren
app = Flask(__name__, static_url_path='/js', static_folder='js', template_folder='templates')
socketio = SocketIO(app, async_mode="threading")

# Logger initialisieren
logger_instance = Logger(log_filename="vaillant2.log")  # Erstelle das Logger-Objekt
LOG_FILE_PATH = logger_instance.get_log_file()  # Hole den Logfile-Pfad direkt von der Logger-Instanz

# Jetzt kannst du den Logger verwenden
log = logger_instance.get_logger()  # Hol dir den eigentlichen Logger

# MQTT Callback-Funktionen
def on_connect(client, _userdata, _flags, reason_code, _properties):
    log.info(f"Verbunden mit Code: {reason_code}")
    for topic in mqtt_values:
        client.subscribe(topic)
        log.info(f"Abonniert: {topic}")

def on_message(_client, _userdata, msg):

    topic = msg.topic
    payload = msg.payload.decode()

    try:
        # Zugriff auf die Konfiguration für dieses Topic
        topic_config = mqtt_values.get(topic)

        if topic_config:
            topic_type = topic_config.get("type")
            title = topic_config.get("title")
            value = topic_config.get("value")

            if topic_type == "text":
                data_type = mqtt_values.get(topic, {}).get("data_type", "string")
                payload_str = str(payload)

                # Prüfen auf das Muster split(index, separator, type)
                match = re.match(r"split\((\d+),\s*'(.+)',\s*(\w+)\)", data_type)

                if match:
                    index = int(match.group(1))
                    separator = match.group(2)
                    sub_type = match.group(3)

                    try:
                        parts = payload_str.split(separator)
                        extracted = parts[index].strip()

                        if sub_type == "float":
                            formatted_value = "{:.2f}".format(float(extracted))
                        elif sub_type == "int":
                            formatted_value = str(int(float(extracted)))
                        else:
                            formatted_value = extracted
                    except (ValueError, IndexError):
                        formatted_value = "N/A"

                # Fallback für deine bisherigen Typen
                elif data_type == "float":
                    try:
                        formatted_value = "{:.2f}".format(float(payload))
                    except ValueError:
                        formatted_value = "N/A"
                elif data_type == "int":
                    try:
                        formatted_value = str(int(payload))
                    except ValueError:
                        formatted_value = "N/A"
                else:
                    formatted_value = payload_str

                if value != formatted_value:
                    topic_config["value"] = formatted_value
                    socketio.emit('update_text', {'title': title, 'value': formatted_value})
                    log.debug(f"Update Text Topic: {topic} value: {formatted_value}")

            elif topic_type == "gauge":
                try:
                    new_value = float(payload)
                except ValueError:
                    new_value = 0

                if value != new_value:
                    topic_config["value"] = new_value
                    is_integer = topic_config.get("isInteger")
                    min_range, max_range = topic_config.get("range", (0, 100))
                    color_ranges = topic_config.get('color_ranges', [])
                    socketio.emit('update_gauge', {
                        'title': title, 'value': new_value,
                        'min_range': min_range, 'max_range': max_range,
                        'isInteger': is_integer,
                        'color_ranges': color_ranges
                    })
                    log.debug(f"Update Gauge Topic: {topic} value: {new_value}")

            elif topic_type == "led":
                status = payload.split(";")[-1].strip()

                if topic_config.get("is_processing", False):
                    log.info(f"Verarbeitung für Topic {topic} läuft bereits.")
                    return

                if value != status:
                    log.debug(f"Topic {topic}, prev value: {value}, curr value {status}.")
                    topic_config["is_processing"] = True  # Sperre für Verarbeitung
                    topic_config["value"] = status

                    # Falls ein direkter Wechsel zwischen "hwc" und "on" passiert
                    if (value == "hwc" and status == "on") or (value == "on" and status == "hwc"):
                        if topic_config.get("start_time"):
                            log.info(f"switch from {value} to {status}")
                            start_time = float(topic_config["start_time"])
                            now = datetime.now()
                            elapsed = (now.timestamp() - start_time) / 3600  # Stunden
                            update_runtime(elapsed, start_time)

                            runtime["total"] += elapsed
                            hwc["switch"] = True
                            hwc["sub"] += 1
                            topic_config["start_time"] = ""

                    if status in ["on", "hwc"]:
                        # Zähler nicht hochzählen, wenn ein direkter wechsel war. Das zählt nicht als Kompressor start
                        if not hwc["switch"]:
                            counter["today"] += 1
                            c = counter.get("today")
                            log.info(f"start run {c} - {status}")

                        if status == "hwc":
                            hwc["status"] = True
                        if not topic_config.get("start_time"):
                            topic_config["start_time"] = str(datetime.now().timestamp())

                    elif status not in ["on", "hwc"]:
                        hwc["switch"] = False
                        if topic_config.get("start_time"):
                            start_time = float(topic_config["start_time"])
                            now = datetime.now()
                            elapsed = (now.timestamp() - start_time) / 3600
                            update_runtime(elapsed, start_time)

                            runtime["total"] += elapsed
                            topic_config["start_time"] = ""
                            hwc["sub"] = 0
                            hwc["switch"] = False
                            c = counter.get("today")
                            log.info(f"stop run {c} - {status} - elapsed: {elapsed}")


                    counter["total"] = ebus.read_value('hmu', 'CompressorStarts')
                    socketio.emit('update_led', {
                        'title': title,
                        'value': status,
                        'start_time': topic_config.get("start_time"),
                    })
                    rt = {
                        "today": format_runtime(runtime.get("today", 0)),
                        "yesterday": format_runtime(runtime.get("yesterday", 0)),
                        "runs_today": format_runs(runtime.get("runs", {}).get("today", {})),
                        "runs_yesterday": format_runs(runtime.get("runs", {}).get("yesterday", {}))
                    }

                    socketio.emit('update_counter', counter)
                    socketio.emit('update_runtime', rt)

                    save_values(counter, "data.json")
                    save_values(runtime, "runtime.json")
                    log.debug(f"Update LED Topic: {topic} status: {status}")
                    topic_config["is_processing"] = False  # Verarbeitung abgeschlossen

            else:
                log.warning(f"Unbekanntes Topic: {topic}")
        else:
            log.warning(f"Kein gültiger Eintrag für das Topic: {topic}")

    except Exception as e:
        log.error(f"Fehler beim Verarbeiten von {topic}: {payload} -> {e}")
        log.error(runtime["runs"])

def update_runtime(elapsed, start_time):
    """Aktualisiert die Laufzeiten sauber mit Startzeit [hh:mm] und elapsed Stunden."""
    timestamp = float(start_time)
    dt = datetime.fromtimestamp(timestamp)
    time_str = dt.strftime("%H:%M")  # hh:mm Format

    cnt = counter.get("today", 0)
    sub_id = hwc.get("sub", 0)
    run_id = str(cnt if cnt > 0 else counter.get("yesterday", 1))
    if sub_id > 0:
        run_id = f"{run_id}.{sub_id}"

    # Bestimme Zieltag
    target_day = "yesterday" if cnt == 0 and elapsed > 0 else "today"
    runtime["runs"].setdefault(target_day, {})
    runtime["runs"][target_day][run_id] = {
        "time": time_str,
        "elapsed_hours": elapsed,
        "hwc": hwc["status"]
    }

    # Gesamtstunden addieren
    runtime[target_day] += elapsed

    hwc["status"] = False

def save_values(data, filename="data.json"):
    try:
        with open(filename, "w") as file:
            json.dump(data, file, indent=4)
    except Exception as e:
        log.error(f"Fehler beim Speichern: {e}")


def load_config(config_file="config.json", default_file="default_config.json"):
    """Lädt die Konfiguration und ergänzt fehlende Werte mit Standardwerten."""
    try:
        with open(default_file, "r") as file:
            default_config = json.load(file)
    except FileNotFoundError:
        log.warning(f"Warnung: Standardkonfigurationsdatei '{default_file}' nicht gefunden.")
        default_config = {}
    except Exception as e:
        log.error(f"Fehler beim Laden der Standardkonfiguration: {e}")
        default_config = {}

    try:
        with open(config_file, "r") as file:
            user_config = json.load(file)
    except FileNotFoundError:
        log.info(f"Info: Konfigurationsdatei '{config_file}' nicht gefunden. Standardwerte werden verwendet.")
        user_config = {}
    except Exception as e:
        log.error(f"Fehler beim Laden der Konfigurationsdatei: {e}")
        user_config = {}

    # Rekursive Zusammenführung der Konfigurationen
    def merge_dicts(default, override):
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(default.get(key), dict):
                default[key] = merge_dicts(default[key], value)
            else:
                default[key] = value
        return default

    return merge_dicts(default_config, user_config)

def load_values(filename="data.json"):
    """Lädt gespeicherte Werte aus einer JSON-Datei."""
    try:
        with open(filename, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        log.warning(f"Datei {filename} nicht gefunden. Standardwerte werden verwendet.")
        return {}
    except Exception as e:
        log.error(f"Fehler beim Laden der Werte aus {filename}: {e}")
        return None


def reset_counter():
    while True:
        now = datetime.now()
        # Warte bis Mitternacht
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_to_sleep = (next_midnight - now).total_seconds()
        time.sleep(time_to_sleep)

        # Verschiebe "today" zu "yesterday" und setze zurück
        counter["yesterday"] = counter["today"]
        counter["today"] = 0

        runtime["yesterday"] = runtime["today"]
        runtime["today"] = 0.0

        runtime["runs"]["yesterday"] = runtime["runs"]["today"]
        runtime["runs"]["today"] = {}

        # Speichere die Werte
        save_values(counter, "data.json")
        save_values(runtime, "runtime.json")

        rt = {
            "today": format_runtime(runtime.get("today", 0)),
            "yesterday": format_runtime(runtime.get("yesterday", 0)),
            "runs_today": format_runs(runtime.get("runs", {}).get("today", {})),
            "runs_yesterday": format_runs(runtime.get("runs", {}).get("yesterday", {}))
        }

        # Sende aktualisierte Werte an die Webseite
        socketio.emit('update_counter', counter)
        socketio.emit('update_runtime', rt)


def format_log_line(line):
    """Formatierung der Log-Zeile mit Farbzuweisung für den Text in [ ] und Zeilenumbrüchen."""

    line = line.strip()
    # Farbzuweisung für die Log-Level in [ ]
    line = re.sub(r'(\[I[^\]]*\])', r'<span style="color: green;">\1</span>', line)
    line = re.sub(r'(\[D[^\]]*\])', r'<span style="color: blue;">\1</span>', line)
    line = re.sub(r'(\[E[^\]]*\])', r'<span style="color: red;">\1</span>', line)

    # Zeilenumbruch sicherstellen
    return f'{line}<br>'


def read_log_file():
    """Funktion, die das Logfile liest und kontinuierlich neue Zeilen sendet."""
    with open(LOG_FILE_PATH, 'r') as f:
        f.seek(0, os.SEEK_END)  # Setzt den Dateizeiger ans Ende des Logfiles
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)  # Warten auf neue Zeilen
                continue
            formatted_line = format_log_line(line)  # Formatierung der Zeile
            yield f"data: {formatted_line}\n\n"  # Sende die Log-Zeile an den Client

def read_entire_log_file():
    """Funktion, die das gesamte Logfile beim ersten Aufruf liest."""
    with open(LOG_FILE_PATH, 'r') as f:
        for line in f:
            formatted_line = format_log_line(line)  # Formatierung der Zeile
            yield f"data: {formatted_line}\n\n"  # Sende jede Zeile an den Client

@app.route('/update_log')
def update_log():
    """Route, um den Logfile-Stream mit SSE an den Client zu senden."""
    def stream_logs():
        # Das gesamte Logfile senden
        yield from read_entire_log_file()
        # Danach nur neue Logzeilen (wie tail -f)
        yield from read_log_file()

    return Response(stream_logs(), content_type='text/event-stream')

@app.route('/logger')
def logger():
    return render_template('logs.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/')
def index():
    gauges = []
    texts = []
    leds = []  # Neue Liste für LEDs
    for topic, data in mqtt_values.items():
        title = data["title"]
        value = data["value"]

        # Farbbereiche einlesen, wenn sie vorhanden sind
        color_ranges = data.get("color_ranges", [])

        if data["type"] == "gauge":
            is_integer = data["isInteger"]
            min_range, max_range = data["range"]
            gauges.append({
                "title": title,
                "value": value,
                "min_range": min_range,
                "max_range": max_range,
                "color_ranges": color_ranges,
                "isInteger": is_integer
            })
        elif data["type"] == "text":
            texts.append(f"{title}: {value}")
        elif data["type"] == "led":
            # LEDs zur Liste hinzufügen
            leds.append({
                "title": title,
                "value": value,
                'start_time': str(mqtt_values[topic].get("start_time", ""))
            })
            leds.append({
                "title": "Enteisen",
                "value": "on" if deicing_tracker.active else "off",
                "start_time": deicing_tracker.start_time
            })

    rt = {
        "today": format_runtime(runtime.get("today", 0)),
        "yesterday": format_runtime(runtime.get("yesterday", 0)),
        "runs_today": format_runs(runtime.get("runs", {}).get("today", {})),
        "runs_yesterday": format_runs(runtime.get("runs", {}).get("yesterday", {})),
    }
    # Übergabe der LEDs an das Template
    return render_template('index.html', gauges=gauges, texts=texts, leds=leds, counter=counter, runtime=rt)


def format_runtime(hours):
    total_minutes = int(hours * 60)
    return f"{total_minutes // 60} Std {total_minutes % 60} Min"

def format_runs(runs):
    formatted_runs = []
    for key, value in runs.items():
        try:
            # neuer Stil: Dict mit "time", "elapsed_hours", "hwc"
            if isinstance(value, dict):
                time_str = value.get("time", "??:??")
                elapsed = float(value.get("elapsed_hours", 0))
                prefix = "HWC " if value.get("hwc") else ""
            else:
                # alter Stil: "hwc:0.5" oder "0.5"
                if isinstance(value, str) and value.startswith("hwc:"):
                    elapsed = float(value.split(":")[1].replace(",", ".").strip())
                    prefix = "HWC "
                else:
                    elapsed = float(value)
                    prefix = ""
                time_str = "??:??"  # keine Startzeit vorhanden bei alten Daten

            minutes = int(elapsed * 60)
            seconds = int((elapsed * 3600) % 60)
            formatted_runs.append(f'{key}: [{time_str}] {prefix}{minutes} Min {seconds:02d} Sek')

        except Exception:
            # absoluter Fallback, falls etwas anderes kommt
            formatted_runs.append(f'{key}: Ungültiger Wert')

    return ', '.join(formatted_runs)

def ebus_dispatcher(circuit, name, value):
    log.info(f"🔥 DISPATCHER: {circuit} {name} = {value}")

    handler = EBUS_HANDLERS.get((circuit, name))
    if handler:
        handler(value)

def deicing_stop_callback(duration, start_time):
    count = sum(1 for k in runtime["runs"]["today"] if str(k).startswith("D")) + 1
    run_id = f"D{count}"
    runtime["runs"]["today"][run_id] = {
        "time": time.strftime("%H:%M", time.localtime(start_time)),
        "elapsed_hours": duration / 3600
    }
    save_values(runtime, "runtime.json")

config = load_config()
mqtt_config = config.get("mqtt_config", {})
mqtt_client = mqtt.Client( protocol=mqtt.MQTTv5, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

if __name__ == '__main__':
    print(f"PROCESS START: {os.getpid()}")
    hwc = {"status": False, "switch": False, "sub": 0}
    defrost = {"status": False}

    # Zähler für "on" und "hwc"
    runtime = load_values("runtime.json")

    if runtime is None or len(runtime) == 0:
        runtime = {
            "today": 0.0,
            "yesterday": 0.0,
            "total": 0.0,
            "runs": {"today": {}, "yesterday": {}}
        }
    else:
        runtime.setdefault("runs", {})
        runtime["runs"].setdefault("today", {})
        runtime["runs"].setdefault("yesterday", {})

    counter = load_values("data.json") or {
        "today": 0,
        "yesterday": 0,
        "total": 0,
    }

    # Zugriff auf die MQTT-Werte mit Typen und anderen Informationen
    mqtt_values = config.get("mqtt_values", {})

    if mqtt_config.get("username", None) is not None:
        mqtt_client.username_pw_set(mqtt_config.get("username"), mqtt_config.get("password", ""))
    mqtt_client.connect(mqtt_config.get("host", "localhost"), mqtt_config.get("port", 1883), 60, clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY)

    # Start the poller thread with the list from config
    ebus_polling_list = config.get("ebus_polling", [])
    ebus = EbusDirect()
    deicing_tracker = DeicingTracker(ebus, socketio, stop_callback=deicing_stop_callback)

    function_map = {
        "update_deicing": deicing_tracker.update,
        "update_status": deicing_tracker.update_defroster_stat
    }
    # Assuming 'config' is your already loaded JSON data
    # We initialize the EBUS_HANDLERS dictionary
    EBUS_HANDLERS = {}

    # Populate the dictionary from the loaded config
    for entry in config.get("ebus_handlers_cfg", []):
        device = entry.get("device")
        event = entry.get("event")
        func_name = entry.get("func")

        # Get the actual function reference from our map
        target_func = function_map.get(func_name)

        if device and event and target_func:
            # Construct the key as a tuple (device, event)
            EBUS_HANDLERS[(device, event)] = target_func
        else:
            # Skip invalid or missing configuration entries
            log.warning(f"Skipping invalid handler config: {device}, {event}")

    threading.Thread(target=ebus.ebus_poller, args=(config["ebus_polling"], ebus_dispatcher), daemon=True).start()
    counter["total"] = ebus.read_value('hmu', 'CompressorStarts')

    threading.Thread(target=reset_counter, daemon=True).start()
    threading.Thread(target=mqtt_client.loop_forever,daemon=True).start()
    socketio.run(app, debug=False, host='0.0.0.0', port=5000, use_reloader=False, log_output=True,allow_unsafe_werkzeug=True)
