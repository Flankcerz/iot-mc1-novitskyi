#!/usr/bin/env python3
"""Симулятор охоронної системи (варіант 3). Один процес, дев'ять клієнтів MQTT,
кожен зі своїм користувачем, паролем і Last Will."""
import argparse, hashlib, json, os, random, threading, time
from pathlib import Path
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("MQTT_HOST", "localhost")
PORT = 8883
CA = ROOT / "certs" / "ca.crt"


def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


ENV = load_env(ROOT / ".env")
PIN = ENV["KEYPAD_PIN"]


class Device:
    def __init__(self, user, base):
        self.user, self.base = user, base
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{user}")
        self.client.username_pw_set(user, ENV[f"MQTT_PASS_{user.upper()}"])
        self.client.tls_set(ca_certs=str(CA))
        # Last Will: якщо процес впаде без DISCONNECT, брокер сам опублікує offline
        self.client.will_set(f"{base}/status", "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = lambda c, u, m: self.on_message(m)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[{self.user}] помилка підключення: {reason_code}")
            return
        client.publish(f"{self.base}/status", "online", qos=1, retain=True)
        self.on_ready(client)
        print(f"[{self.user}] online")

    def on_ready(self, client):
        pass

    def on_message(self, msg):
        pass

    def start(self):
        self.client.connect(HOST, PORT, keepalive=30)
        self.client.loop_start()

    def publish(self, sub, payload, qos=1, retain=False):
        self.client.publish(f"{self.base}/{sub}", json.dumps(payload), qos=qos, retain=retain)

    def telemetry(self, value, unit=""):
        self.publish("telemetry", {"value": value, "unit": unit, "ts": int(time.time())})


class Contact(Device):
    """Геркон дверей/вікон і датчик руху: бінарний стан + періодичний heartbeat."""
    def __init__(self, user, base, closed="CLOSED", opened="OPEN"):
        super().__init__(user, base)
        self.closed, self.opened, self.value = closed, opened, closed

    def set(self, active):
        self.value = self.opened if active else self.closed
        self.telemetry(self.value)

    def tick(self):
        self.telemetry(self.value)


class Smoke(Device):
    """Оптична густина диму, %/м: фон + шум + плавний тренд до цільового рівня."""
    def __init__(self, user, base):
        super().__init__(user, base)
        self.level = self.target = 0.10

    def tick(self):
        self.level += (self.target - self.level) * 0.15 + random.gauss(0, 0.01)
        self.level = max(0.0, self.level)
        self.telemetry(round(self.level, 2), "%/m")


class Keypad(Device):
    def on_ready(self, client):
        client.subscribe("home/system/mode/state", qos=1)

    def on_message(self, msg):
        print(f"[keypad] режим тепер: {msg.payload.decode()}")

    def enter_pin(self, pin):
        # У мережу йде лише SHA-256 від PIN, сам код ні в топіках, ні в логах не з'являється
        digest = hashlib.sha256(pin.encode()).hexdigest()
        self.telemetry(digest, "sha256")
        print("[keypad] PIN введено (****)")

    def set_mode(self, mode):
        self.client.publish("home/system/mode/set", json.dumps({"state": mode}), qos=1)
        print(f"[keypad] запит режиму {mode}")


class Actuator(Device):
    def __init__(self, user, base, allowed, initial):
        super().__init__(user, base)
        self.allowed, self.state = allowed, initial

    def on_ready(self, client):
        client.subscribe(f"{self.base}/set", qos=1)
        self.report()

    def report(self):
        self.publish("state", {"state": self.state, "ts": int(time.time())}, retain=True)

    def on_message(self, msg):
        try:
            new = json.loads(msg.payload)["state"]
        except (ValueError, KeyError, TypeError):
            print(f"[{self.user}] некоректна команда")
            return
        if new in self.allowed:
            self.state = new
            print(f"[{self.user}] -> {new}")
            self.report()


def build():
    return {
        "door": Contact("door", "home/entrance/door"),
        "window1": Contact("window1", "home/livingroom/window1"),
        "window2": Contact("window2", "home/bedroom/window2"),
        "motion": Contact("motion", "home/yard/motion", "OFF", "ON"),
        "smoke": Smoke("smoke", "home/hall/smoke"),
        "keypad": Keypad("keypad", "home/hall/keypad"),
        "siren": Actuator("siren", "home/hall/siren", {"ON", "OFF"}, "OFF"),
        "lock": Actuator("lock", "home/entrance/lock", {"LOCKED", "UNLOCKED"}, "LOCKED"),
        "light": Actuator("light", "home/yard/light", {"ON", "OFF"}, "OFF"),
    }


# ---- Сценарії для демонстрації правил ----
def sc_intrusion(d):            # правило 1: двері при охороні, PIN не введено
    d["keypad"].set_mode("ARMED"); time.sleep(3); d["door"].set(True)

def sc_intrusion_pin(d):        # правило 1: правильний PIN вчасно
    sc_intrusion(d); time.sleep(10); d["keypad"].enter_pin(PIN)

def sc_intrusion_wrong_pin(d):  # правило 1: хибний PIN
    sc_intrusion(d); time.sleep(10); d["keypad"].enter_pin("0000")

def sc_window(d):               # правило 1: вікно при охороні
    d["keypad"].set_mode("ARMED"); time.sleep(3); d["window1"].set(True)

def sc_fire(d):                 # правило 2: дим за будь-якого режиму
    d["smoke"].target = 6.0; time.sleep(45); d["smoke"].target = 0.10

def sc_night_motion(d):         # правило 3: рух на подвір'ї
    d["motion"].set(True); time.sleep(5); d["motion"].set(False)

def sc_disarm(d):
    d["keypad"].enter_pin(PIN); d["keypad"].set_mode("HOME")

def sc_reset(d):
    for k in ("door", "window1", "window2"):
        d[k].set(False)
    d["keypad"].set_mode("HOME")


SCENARIOS = {
    "normal": lambda d: None,
    "intrusion": sc_intrusion, "intrusion_pin": sc_intrusion_pin,
    "intrusion_wrong_pin": sc_intrusion_wrong_pin, "window": sc_window,
    "fire": sc_fire, "night_motion": sc_night_motion,
    "disarm": sc_disarm, "reset": sc_reset,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="normal")
    args = parser.parse_args()

    devices = build()
    for dev in devices.values():
        dev.start()
    time.sleep(3)
    threading.Thread(target=SCENARIOS[args.scenario], args=(devices,), daemon=True).start()

    n = 0
    try:
        while True:
            devices["smoke"].tick()
            if n % 5 == 0:
                for k in ("door", "window1", "window2", "motion"):
                    devices[k].tick()
            n += 1
            time.sleep(2)
    except KeyboardInterrupt:
        # Свідомо без disconnect(): емуляція аварії, брокер надішле Last Will "offline"
        print("Аварійне завершення, очікуємо Last Will")
        os._exit(0)


if __name__ == "__main__":
    main()