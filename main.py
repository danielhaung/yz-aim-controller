# -*- coding: utf-8 -*-
import re
import sys
import time
import threading
import subprocess
import glob

from pymodbus.client import ModbusSerialClient
from motor_controller import MotorController
from hand_controller import HandController   # 你提供的 class

# ===== 依序號自動找串口 =====
# BG02QP86 = 身體 (Modbus)
# BG02QKD5 = 手 (HandController)
BODY_SERIAL = "BG02QP86"
HAND_SERIAL = "BG02QKD5"

def find_port_by_serial(target_serial: str):
    """根據 FTDI 序號找到對應的 /dev/ttyUSB*，找不到回傳 None"""
    ports = glob.glob("/dev/ttyUSB*")
    for port in ports:
        cmd = ["udevadm", "info", "-a", "-n", port]
        try:
            info = subprocess.check_output(
                cmd, text=True, stderr=subprocess.DEVNULL
            )
        except Exception:
            continue

        if f'ATTRS{{serial}}=="{target_serial}"' in info:
            return port
    return None

# 自動解析兩個實際的 port
MODBUS_PORT = find_port_by_serial(BODY_SERIAL)
HAND_PORT   = find_port_by_serial(HAND_SERIAL)
MODBUS_BAUD = 19200
HAND_BAUD   = 115200

if MODBUS_PORT is None or HAND_PORT is None:
    print("❌ 找不到指定序號的 FTDI 裝置：")
    print("   身體序號:", BODY_SERIAL, "→", MODBUS_PORT)
    print("   手序號  :", HAND_SERIAL, "→", HAND_PORT)
    sys.exit(1)

print(f"✅ 身體埠 (Modbus) → {MODBUS_PORT} (serial={BODY_SERIAL})")
print(f"✅ 手埠   (Hand)   → {HAND_PORT} (serial={HAND_SERIAL})")

# ===== 解析 angles.txt =====
ANGLE_COUNT = 1
_PARSE_RE = re.compile(
    r"""^\s*
        (?P<body>[-\d\s,]+?)                      # 角度
        (?:\s*\(\s*(?P<L>\d+)\s*,\s*(?P<R>\d+)\s*\)\s*)?   # 選填 (L,R)
        \s*$""", re.X
)

def parse_angles_line(line: str):
    m = _PARSE_RE.match(line.strip())
    if not m:
        raise ValueError("格式不符：請提供角度，或 角度 後接 (L,R)。")
    body = m.group("body")
    toks = [t for t in re.split(r"[,\s]+", body.strip()) if t != ""]
    if len(toks) != ANGLE_COUNT:
        raise ValueError(f"角度數量錯誤：{len(toks)}，應為 {ANGLE_COUNT}。")
    angles = [int(float(x)) for x in toks]
    L = int(m.group("L")) if m.group("L") is not None else None
    R = int(m.group("R")) if m.group("R") is not None else None
    return angles, L, R

# ===== 馬達移動與監控 =====
def move_and_monitor(motor: MotorController, angle_deg: float, speed_rpm=None, tolerance=100):
    try:
        if speed_rpm is not None:
            if hasattr(motor, "set_speed_rpm"):
                motor.set_speed_rpm(int(speed_rpm))
            elif hasattr(motor, "speed"):
                motor.speed = int(speed_rpm)

        if not hasattr(motor, "move_to_angle"):
            raise RuntimeError("MotorController 需實作 move_to_angle(angle_deg)")
        motor.move_to_angle(angle_deg)

        target_pulses = int(round(angle_deg / 360.0 * motor.pulses_per_rev * motor.gear_ratio))
        for _ in range(100):  # 100*50ms = 5s
            current_pulses = motor.read_position()
            if abs(current_pulses - target_pulses) <= tolerance:
                break
            time.sleep(0.05)
    except Exception as e:
        print(f"❌ ID {getattr(motor, 'slave_id', '?')} move_and_monitor error: {e}")

def proportional_speed(distance_deg, max_distance_deg, max_rpm, ratio=0.8):
    if max_distance_deg <= 0:
        return int(max_rpm * ratio)
    v = int((distance_deg / max_distance_deg) * max_rpm * ratio)
    return max(1, min(v, max_rpm))

# ===== 主程式 =====
def main(angles_file="angles.txt"):
    # 1) 連 Modbus（身體）
    client = ModbusSerialClient(port=MODBUS_PORT, baudrate=MODBUS_BAUD, timeout=1)
    if not client.connect():
        print(f"❌ 無法連接身體埠 {MODBUS_PORT} @ {MODBUS_BAUD}")
        sys.exit(1)
    print(f"✅ 已連線身體：{MODBUS_PORT} @ {MODBUS_BAUD}")

    # 2) 建立馬達列表（沿用你的設定）
    motors = [
        # 左臂旋轉-60～-20
        MotorController(client, slave_id=10, gear_ratio=100, speed=1300,
                        accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    ]

    # 3) 手勢序列埠
    hand = HandController(port=HAND_PORT, baud=HAND_BAUD, open_immediately=True)
    print(f"✅ 已連線手：{HAND_PORT} @ {HAND_BAUD}")
    print("[INFO] Hand:", hand.describe())
    
    # 👉 這裡宣告：機器人主程式已經初始化完成、進入待命狀態
    print("ROBOT_MAIN_READY", flush=True)
    previous_angles = None

    try:
        while True:
            try:
                with open(angles_file, "r") as f:
                    raw = f.readline().strip()
            except FileNotFoundError:
                print(f"⚠️ 找不到 {angles_file}，1 秒後重試…")
                time.sleep(1)
                continue

            if not raw:
                time.sleep(0.1)
                continue

            try:
                angle_list, L_idx, R_idx = parse_angles_line(raw)
            except Exception as e:
                print(f"❌ 解析失敗：{e}")
                time.sleep(0.5)
                continue

            if previous_angles is None:
                previous_angles = angle_list[:]
                print("📌 初始角度已記錄，等待下一輪差值計算")
                if L_idx is not None and R_idx is not None:
                    print(f"🤝 首輪手勢：L={L_idx}, R={R_idx}")
                    hand.hand_move(L_idx, R_idx, duration=600)
                with open(angles_file, "w") as f:
                    f.write("")
                time.sleep(0.2)
                continue

            distances = [abs(angle_list[i] - previous_angles[i]) for i in range(len(motors))]
            max_distance = max(distances)

            threads = []
            if max_distance > 0:
                for i, motor in enumerate(motors):
                    curr = angle_list[i]
                    prev = previous_angles[i]
                    dist = abs(curr - prev)
                    if dist == 0:
                        continue
                    speed = proportional_speed(dist, max_distance,
                                               getattr(motor, "max_rpm", 1500), ratio=0.8)
                    t = threading.Thread(target=move_and_monitor, args=(motor, curr, speed))
                    t.start()
                    threads.append(t)

            # 同步下發手勢（若有）
            if L_idx is not None and R_idx is not None:
                threading.Thread(target=hand.hand_move, args=(L_idx, R_idx, 800)).start()

            for t in threads:
                t.join()

            previous_angles = angle_list[:]
            with open(angles_file, "w") as f:
                f.write("")
            print("✅ 本輪完成，等待下一筆…")
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("🛑 使用者中斷執行")
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            hand.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
