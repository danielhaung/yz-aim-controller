from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException, ConnectionException
import sys
import glob
import time
import serial

def find_available_serial_port():
    ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyS*')
    for port in ports:
        try:
            with serial.Serial(port=port, baudrate=19200, timeout=1) as ser:
                print(f"🔌 發現可用串口：{port}")
                return port
        except (OSError, serial.SerialException):
            continue
    return None

def set_modbus_enable(client, slave_id, enable: bool):
    address = 0x00
    value = 0x0001 if enable else 0x0000
    result = client.write_register(address, value, slave=slave_id)
    if result.isError():
        print(f"[ID {slave_id}] ❌ Modbus {'啟用' if enable else '關閉'}失敗")
        return False
    print(f"[ID {slave_id}] ✅ Modbus {'啟用' if enable else '關閉'}成功")
    return True

import json
import os

def set_driver_enable(client, slave_id, enable: bool, pulses_per_rev=32768, gear_ratio=1.0):
    """
    啟用/關閉驅動器：
    - 只控制 0x01 暫存器的使能狀態
    - 啟用時僅顯示目前位置與角度（不做位置還原與移動）
    """
    import time

    # 設定驅動器開關
    address = 0x01
    value = 0x0001 if enable else 0x0000
    result = client.write_register(address=address, value=value, slave=slave_id)

    if result.isError():
        print(f"[ID {slave_id}] ❌ 驅動器{'啟用' if enable else '關閉'}失敗")
        return False

    print(f"[ID {slave_id}] ✅ 驅動器{'啟用' if enable else '關閉'}成功")

    # 若啟用，顯示目前位置與角度
    if enable:
        pos_res = client.read_holding_registers(address=0x16, count=2, slave=slave_id)
        if not pos_res.isError():
            low, high = pos_res.registers
            pos = (high << 16) | low
            if pos >= (1 << 31):
                pos -= (1 << 32)
            angle = pos / (pulses_per_rev * gear_ratio) * 360
            print(f"📍 啟用時位置：{pos} 脈波（{angle:.2f}°）")
        else:
            print("⚠️ 無法讀取目前位置")
    return True



def move_absolute(client, slave_id, position: int):
    if position < 0:
        position = (1 << 32) + position
    low = position & 0xFFFF
    high = (position >> 16) & 0xFFFF
    result = client.write_registers(0x16, [low, high], slave=slave_id)
    if result.isError():
        print(f"[ID {slave_id}] ❌ 移動失敗")
        return False
    print(f"[ID {slave_id}] ✅ 移動到位置 {position}")
    return True

import time
import json
import os

def read_position(client, slave_id, target_position=None, pulses_per_rev=32768, gear_ratio=1.0):
    status = {
        "position": "❌",
        "error_code": "❌",
        "current": "❌",
        "actual_speed": "❌",
        "voltage": "❌",
        "temperature": "❌",
        "stall_time": "❌",
        "output_limit": "❌",
        "angle_now": "❌",
        "angle_target": "❌"
    }

    pos = None

    # 讀取位置（0x16/0x17）
    res = client.read_holding_registers(address=0x16, count=2, slave=slave_id)
    if not res.isError():
        low, high = res.registers
        pos = (high << 16) | low
        if pos >= (1 << 31):
            pos -= (1 << 32)
        status["position"] = f"{pos}"
        angle_now = pos / (pulses_per_rev * gear_ratio) * 360
        status["angle_now"] = f"{angle_now:.2f} °"

        # ✅ 保存位置至檔案
        position_file = "last_position.json"
        with open(position_file, "w", encoding="utf-8") as f:
            json.dump({"position": pos, "angle": angle_now}, f)

    time.sleep(0.05)

    if target_position is not None:
        angle_target = target_position / (pulses_per_rev * gear_ratio) * 360
        status["angle_target"] = f"{angle_target:.2f} °"

    def try_read(addr, key, transform=lambda x: x):
        res = client.read_holding_registers(address=addr, count=1, slave=slave_id)
        if not res.isError():
            status[key] = transform(res.registers[0])
        time.sleep(0.05)

    try_read(0x0E, "error_code", str)
    try_read(0x0F, "current", lambda x: f"{x / 2000:.3f} A")
    try_read(0x10, "actual_speed", lambda x: f"{(x - 65536 if x >= 0x8000 else x) / 10:.1f} r/min")
    try_read(0x11, "voltage", lambda x: f"{x / 327:.2f} V")
    try_read(0x12, "temperature", lambda x: f"{x} °C")
    try_read(0x18, "stall_time", lambda x: f"{x % 10} 秒" if x % 10 > 0 else "不報警")
    try_read(0x18, "output_limit", lambda x: f"{(x // 10) / 10:.1f}%")

    print(f"""
📡 [ID {slave_id}] 馬達狀態概覽
────────────────────────────────────
📍 當前位置        ：{status['position']}
📐 目前角度        ：{status['angle_now']}
🎯 目標角度        ：{status['angle_target']}
🔁 實際速度        ：{status['actual_speed']}
⚡ 系統電流        ：{status['current']}
🔋 系統電壓        ：{status['voltage']}
🌡️ 系統溫度        ：{status['temperature']}
🔒 最大靜止輸出限制：{status['output_limit']}
⏱️ 堵轉保護時間    ：{status['stall_time']}
🚨 錯誤代碼        ：{status['error_code']}
────────────────────────────────────
""")

    return pos if pos is not None else None

import time
import sys
import select
import termios
import tty

def stop_motor(client, slave_id):
    """
    關閉驅動器使能，達到馬達立即停止的效果。
    """
    print("🛑 強制中止馬達動作中...")
    client.write_register(0x01, 0, slave=slave_id)
    time.sleep(0.3)
    client.write_register(0x01, 1, slave=slave_id)

def wait_until_reached(client, slave_id, target_position, tolerance=50, timeout=5.0):
    prev_position = None
    start_time = time.time()

    print("⏳ 正在移動馬達，📥 按下任意鍵可中止...")

    # 啟用非阻塞模式
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            # ✅ 偵測鍵盤輸入立即中止動作
            if select.select([sys.stdin], [], [], 0)[0]:
                print("🛑 偵測到鍵盤輸入，中止移動與驅動")
                stop_motor(client, slave_id)
                return False

            current_position = read_position(client, slave_id, target_position=target_position)
            if current_position is None:
                print("⚠️ 無法讀取位置，中止等待")
                stop_motor(client, slave_id)
                return False

            distance = abs(current_position - target_position)
            print(f"📏 距離目標：{distance}（容差 ±{tolerance}）")

            if distance <= tolerance:
                print(f"✅ 已到位（目前位置：{current_position}）")
                return True

            if prev_position is None or abs(prev_position - target_position) > distance:
                start_time = time.time()

            if time.time() - start_time > timeout:
                print(f"⏰ 逾時未到達目標（目前位置：{current_position}）")
                stop_motor(client, slave_id)
                return False

            prev_position = current_position
            time.sleep(0.2)

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)




def move_angle_loop(client, slave_id, pulses_per_rev=32768, gear_ratio=1.0):
    print(f"🟢 控制馬達 ID {slave_id}，輸入角度（如 180.0, -180），輸入 q 離開")
    print(f"⚙️ 一圈 = {pulses_per_rev} 脈波，減速比 = {gear_ratio}")

    MAX_ANGLE = 360  # 限制最多 10 圈，3600°

    while True:
        user_input = input("👉 請輸入角度（°）或 q 離開： ").strip()

        if user_input.lower() == 'q':
            print("👋 已離開控制模式")
            break

        try:
            angle = float(user_input)
        except ValueError:
            print("⚠️ 請輸入有效數字（如 180.0）")
            continue

        # ✅ 加入異常角度防呆
        if abs(angle) > MAX_ANGLE:
            print(f"⚠️ 輸入角度過大（超過 ±{MAX_ANGLE}°），請重新輸入")
            continue

        pulses = angle_to_pulse(angle, pulses_per_rev, gear_ratio)
        success = move_absolute(client, slave_id, pulses)
        if success:
            wait_until_reached(client, slave_id, pulses)


def config_motor_parameters(client, slave_id, speed=None, accel=None,
                            speed_kp=None, speed_ki=None, pos_kp=None,
                            stall_output_limit=None, stall_time=None):
    def handle_param(name, reg, value, min_val, max_val, unit=""):
        if value is not None:
            if not (min_val <= value <= max_val):
                print(f"⚠️ {name} 設定值 {value} 超出範圍 {min_val}~{max_val}，已跳過")
                return
            result = client.write_register(reg, value, slave=slave_id)
            if result.isError():
                print(f"❌ {name} 寫入失敗")
            else:
                print(f"✅ {name} 設定為 {value} {unit}")
        else:
            result = client.read_holding_registers(address=reg, count=1, slave=slave_id)
            if result.isError():
                print(f"❌ 無法讀取 {name}")
            else:
                print(f"📖 目前 {name} 為 {result.registers[0]} {unit}")

    print(f"\n⚙️ [ID {slave_id}] 運動參數設定中...")
    handle_param("電機目標速度", 0x02, speed, 0, 1000, "r/min")
    handle_param("電機加速度", 0x03, accel, 0, 60098, "r/min/s")
    handle_param("速度環比例系數", 0x05, speed_kp, 0, 10000)
    handle_param("速度環積分時間", 0x06, speed_ki, 2, 2000, "ms")
    handle_param("位置環比例系數", 0x07, pos_kp, 60, 30000)

    if stall_output_limit is not None and stall_time is not None:
        if not (0 <= stall_output_limit <= 60.9) or not (0 <= stall_time <= 9):
            print("⚠️ 堵轉參數超出範圍，靜止輸出限制應為 0~60.9%，堵轉時間 0~9 秒")
        else:
            combined_val = int(stall_output_limit * 10) + stall_time
            result = client.write_register(0x18, combined_val, slave=slave_id)
            if result.isError():
                print("❌ 堵轉保護參數寫入失敗")
            else:
                print(f"✅ 靜止輸出限制設定為 {stall_output_limit:.1f}%，堵轉保護時間為 {stall_time} 秒")

def set_gear_ratio(client, slave_id, numerator=None, denominator=None, default_numerator=1, default_denominator=1):
    def safe_set_register(reg_addr, value, name):
        if not isinstance(value, int) or value <= 0:
            print(f"⚠️ {name} 設定錯誤，使用預設值")
            return client.write_register(reg_addr, default_numerator if reg_addr == 0x08 else default_denominator, slave=slave_id)
        else:
            return client.write_register(reg_addr, value, slave=slave_id)

    print(f"\n⚙️ [ID {slave_id}] 設定電子齒輪比")
    result_n = safe_set_register(0x08, numerator, "電子齒輪分子")
    result_d = safe_set_register(0x09, denominator, "電子齒輪分母")
    if result_n.isError() or result_d.isError():
        print("❌ 電子齒輪比設定失敗")
    else:
        print(f"✅ 設定完成：分子 = {numerator or default_numerator}, 分母 = {denominator or default_denominator}")

def angle_to_pulse(angle_deg: float, pulses_per_rev: int = 32768, gear_ratio: float = 1.0) -> int:
    pulses = angle_deg / 360.0 * pulses_per_rev * gear_ratio
    return int(round(pulses))

# ===== 主程式開始 =====

port = find_available_serial_port()
if not port:
    print("❌ 找不到任何可用的串口裝置（如 /dev/ttyUSB0）")
    sys.exit(1)

try:
    client = ModbusSerialClient(port=port, baudrate=19200, timeout=1)
    if not client.connect():
        print(f"❌ 無法開啟串口 {port}，請確認裝置是否連接。")
        sys.exit(1)
except Exception as e:
    print(f"❌ 發生連線例外錯誤：{e}")
    sys.exit(1)

try:
    set_modbus_enable(client, 1, True)
    set_driver_enable(client, 1, True)
    config_motor_parameters(
    client, 1,
    speed=200,
    accel=3000,
    speed_kp=2000,
    speed_ki=150,
    stall_output_limit=100.0,
    stall_time=3
)
    set_gear_ratio(client, 1, numerator=1, denominator=1)
    move_angle_loop(client, 1, pulses_per_rev=32768, gear_ratio=1.0)
    read_position(client, 1)
except ConnectionException as e:
    print(f"❌ 通訊異常：{e}")
except ModbusIOException as e:
    print(f"❌ Modbus I/O 錯誤：{e}")
finally:
    client.close()