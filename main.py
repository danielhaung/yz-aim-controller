from pymodbus.client import ModbusSerialClient
from motor_controller import MotorController
import glob
import serial
import sys
import threading
import random
import time


def find_serial_port():
    ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyS*')
    for port in ports:
        try:
            with serial.Serial(port=port, baudrate=19200, timeout=1) as ser:
                print(f"🔌 發現可用串口：{port}")
                return port
        except (OSError, serial.SerialException):
            continue
    return None


def setup_motor(motor):
    pass  # 已在 __init__ 設定，這裡不再重複




def calculate_speed_for_uniform_duration(angle_deg, max_angle, max_rpm=1500, duration_sec=0.5, ratio=0.8):
    if max_angle == 0:
        return int(max_rpm * ratio)  # 避免除以0，直接給一個保守值
    rpm = int(round((angle_deg / max_angle) * max_rpm * ratio))
    return min(rpm, max_rpm)


def move_and_monitor(motor, angle, tolerance=100):  # tolerance: 脈衝誤差容許值
    motor.move_to_angle(angle)
    target_pulses = int(round(angle / 360.0 * motor.pulses_per_rev * motor.gear_ratio))

    for _ in range(100):  # 最多嘗試100次，避免無限等待
        current_pulses = motor.read_position()
        if abs(current_pulses - target_pulses) <= tolerance:
            break
        time.sleep(0.05)  # 等 50ms 再讀一次

def broadcast_move_all(client, motors, angle_deg, speed=200, accel=2000):
    pulses = int(round(angle_deg / 360.0 * 32768 * motors[0].gear_ratio))
    configs = []
    for m in motors:
        configs.append({"address": m.slave_id, "position": pulses, "speed": speed, "accel": accel})
    cmd = build_sync_command(configs)
    client.socket.write(cmd)


if __name__ == "__main__":
    port = find_serial_port()
    if not port:
        print("❌ 找不到可用的串口")
        sys.exit(1)

    client = ModbusSerialClient(port=port, baudrate=19200, timeout=1)
    if not client.connect():
        print(f"❌ 無法連接到 {port}")
        sys.exit(1)

motors = [
    #右肩前後90～-90
    MotorController(client, slave_id=3, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),    # 50×20 = 1000 ✅
    # #右肩上下60～-20
    MotorController(client, slave_id=4, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),   # 120×20 = 2400 → 1500 ❌
    # #右臂旋轉60～-20
    MotorController(client, slave_id=5, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000), 
    # #右手軸彎曲90～0
    MotorController(client, slave_id=6, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #右手腕控制90～-90
    MotorController(client, slave_id=7, gear_ratio=50, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    # #左肩前後90～-90
    MotorController(client, slave_id=8, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),    # 50×20 = 1000 ✅
    # #左肩上下20～-60
    MotorController(client, slave_id=9, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),   # 120×20 = 2400 → 1500 ❌
    # #左臂旋轉60～-20
    MotorController(client, slave_id=10, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000), 
    # #左手軸彎曲-90～0
    MotorController(client, slave_id=11, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    # 左手腕控制90～-90
    MotorController(client, slave_id=12, gear_ratio=50, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #腰部旋轉20～-20
    MotorController(client, slave_id=13, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #右髖上下30～-30
    MotorController(client, slave_id=14, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #右髖左右-20～0
    MotorController(client, slave_id=15, gear_ratio=100, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),  # 100×20 = 2000 → 1500 ❌
    #右膝蓋-30～0
    MotorController(client, slave_id=16, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #右腳踝30～-30 
    MotorController(client, slave_id=17, gear_ratio=50, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #左髖上下30～-30
    MotorController(client, slave_id=18, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #左髖左右0～20
    MotorController(client, slave_id=19, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #左膝蓋30～0
    MotorController(client, slave_id=20, gear_ratio=120, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    #左腳踝30～-30
    MotorController(client, slave_id=21, gear_ratio=50, speed=1300, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
]


try:
    previous_angles = None  # 第一次執行無法計算距離

    while True:
        with open("angles.txt", "r") as f:
            raw = f.readline().strip()
            if not raw:
                print("⚠️ angles.txt 是空的，等待下一輪...")
                time.sleep(1)
                continue

            try:
                angle_list = [int(a.strip()) for a in raw.split(",") if a.strip() != ""]
            except ValueError as e:
                print(f"❌ 無效格式：{e}，請檢查 angles.txt")
                time.sleep(1)
                continue

        if previous_angles is None:
            previous_angles = angle_list.copy()
            print("📌 初始角度已記錄，等待下一輪差值計算")
            time.sleep(1)
            continue
        # 計算每顆馬達移動距離（目前 - 上一次）
        distances = [abs(angle_list[i] - previous_angles[i]) for i in range(len(motors))]
        max_distance = max(distances)

        if max_distance == 0:
            print("⚠️ 所有馬達角度無變化，跳過執行")
            time.sleep(1)
            continue

        threads = []
        print("🎯 自動讀取 angles.txt 中...")

        for i, motor in enumerate(motors):
            current = angle_list[i]
            previous = previous_angles[i]
            distance = abs(current - previous)

            if distance == 0:
                print(f"  ➤ ID {motor.slave_id}: 保持在 {current}°，不執行")
                continue

            # 比例速度換算，讓全部同時到位
            speed = int((distance / max_distance) * motor.max_rpm * 0.8)
            speed = min(speed, motor.max_rpm)

            print(f"  ➤ ID {motor.slave_id}: 從 {previous}° → {current}°，距離 {distance}°，速度 {speed} RPM")
            t = threading.Thread(target=move_and_monitor, args=(motor, current, speed))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        previous_angles = angle_list.copy()

        # 清空 angles.txt
        with open("angles.txt", "w") as f:
            f.write("")

        print("✅ 本輪執行完畢，已清空 angles.txt，等待更新...")
        time.sleep(0.1)

except KeyboardInterrupt:
    print("🛑 使用者中斷執行")

finally:
    client.close()