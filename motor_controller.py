from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusIOException, ConnectionException
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.constants import Endian
import time
import json
import os
import sys
import select
import termios
import tty




class MotorController:
    def __init__(self, client: ModbusSerialClient, slave_id: int, pulses_per_rev=32768, gear_ratio=1.0,
                speed=None, accel=None, speed_kp=None, speed_ki=None, pos_kp=None,
                stall_output_limit=None, stall_time=None,
                gear_num=11000, gear_den=1):
        self.client = client
        self.slave_id = slave_id
        self.pulses_per_rev = pulses_per_rev
        self.gear_ratio = gear_ratio
        self.max_rpm = speed if speed is not None else 1500
        self.accel = accel  # ✅ 請確認這一行存在
        self.speed = speed       # ✅ 加上這行
        # 啟用 Modbus & 驅動器
        self.enable_modbus()
        self.enable_driver()

        # 設定運動參數
        self.config_parameters(
            speed=speed,
            accel=accel,
            speed_kp=speed_kp,
            speed_ki=speed_ki,
            pos_kp=pos_kp,
            stall_output_limit=stall_output_limit,
            stall_time=stall_time
        )

        # 設定電子齒輪比
        self.set_gear_ratio(numerator=gear_num, denominator=gear_den)

    def set_gear_ratio_value(self, gear_ratio: float):
        self.gear_ratio = gear_ratio
        print(f"⚙️ 減速比已設定為 {gear_ratio}")

    def enable_modbus(self, enable: bool = True):
        address = 0x00
        value = 0x0001 if enable else 0x0000
        result = self.client.write_register(address, value, slave=self.slave_id)
        if result.isError():
            print(f"[ID {self.slave_id}] ❌ Modbus {'啟用' if enable else '關閉'}失敗")
            return False
        print(f"[ID {self.slave_id}] ✅ Modbus {'啟用' if enable else '關閉'}成功")
        return True

    def enable_driver(self, enable: bool = True):
        address = 0x01
        value = 0x0001 if enable else 0x0000
        result = self.client.write_register(address=address, value=value, slave=self.slave_id)

        if result.isError():
            print(f"[ID {self.slave_id}] ❌ 驅動器{'啟用' if enable else '關閉'}失敗")
            return False

        print(f"[ID {self.slave_id}] ✅ 驅動器{'啟用' if enable else '關閉'}成功")

        if enable:
            self.read_position()
        return True

    def config_parameters(self, speed=None, accel=None, speed_kp=None, speed_ki=None, pos_kp=None,
                          stall_output_limit=None, stall_time=None):
        def handle_param(name, reg, value, min_val, max_val, unit=""):
            if value is not None:
                if not (min_val <= value <= max_val):
                    print(f"⚠️ {name} 設定值 {value} 超出範圍 {min_val}~{max_val}，已跳過")
                    return
                result = self.client.write_register(reg, value, slave=self.slave_id)
                if result.isError():
                    print(f"❌ {name} 寫入失敗")
                else:
                    print(f"✅ {name} 設定為 {value} {unit}")

        handle_param("電機目標速度", 0x02, speed, 0, 1500, "r/min")
        handle_param("電機加速度", 0x03, accel, 0, 60098, "r/min/s")
        handle_param("速度環比例系數", 0x05, speed_kp, 0, 10000)
        handle_param("速度環積分時間", 0x06, speed_ki, 2, 2000, "ms")
        handle_param("位置環比例系數", 0x07, pos_kp, 60, 30000)

        if stall_output_limit is not None and stall_time is not None:
            if not (0 <= stall_output_limit <= 60.9) or not (0 <= stall_time <= 9):
                print("⚠️ 堵轉參數超出範圍，靜止輸出限制應為 0~60.9%，堵轉時間 0~9 秒")
            else:
                combined_val = int(stall_output_limit * 10) + stall_time
                self.client.write_register(0x18, combined_val, slave=self.slave_id)

    def set_gear_ratio(self, numerator=11000, denominator=1):
        def safe_set_register(reg_addr, value, name):
            if not isinstance(value, int) or value <= 0:
                print(f"⚠️ {name} 設定錯誤，使用預設值")
                return self.client.write_register(reg_addr, 1, slave=self.slave_id)
            else:
                return self.client.write_register(reg_addr, value, slave=self.slave_id)

        safe_set_register(0x08, numerator, "速度前餽")
        safe_set_register(0x09, denominator, "電子齒輪分母")

    def angle_to_pulse(self, angle_deg):
        pulses = angle_deg / 360.0 * self.pulses_per_rev * self.gear_ratio
        return int(round(pulses))

    def move_absolute(self, position):
        if position < 0:
            position = (1 << 32) + position
        low = position & 0xFFFF
        high = (position >> 16) & 0xFFFF
        result = self.client.write_registers(0x16, [low, high], slave=self.slave_id)
        if result.isError():
            print(f"[ID {self.slave_id}] ❌ 移動失敗")
            return False
        print(f"[ID {self.slave_id}] ✅ 移動到位置 {position}")
        return True

    # def read_position(self):
    #     res = self.client.read_holding_registers(address=0x16, count=2, slave=self.slave_id)
    #     if not res.isError():
    #         low, high = res.registers
    #         pos = (high << 16) | low
    #         if pos >= (1 << 31):
    #             pos -= (1 << 32)
    #         angle = pos / (self.pulses_per_rev * self.gear_ratio) * 360
    #         print(f"📍 當前位置：{pos} 脈波（{angle:.2f}°）")
    #         return pos
    #     print("⚠️ 無法讀取目前位置")
    #     return None


    def read_position(self):
        status = {
            "position": "❌",
            "angle_now": "❌",
            "current": "❌",
            "speed": "❌"
        }

        # 讀取位置（0x16/0x17）
        res = self.client.read_holding_registers(address=0x16, count=2, slave=self.slave_id)
        if not res.isError():
            low, high = res.registers
            pos = (high << 16) | low
            if pos >= (1 << 31):
                pos -= (1 << 32)
            angle = pos / (self.pulses_per_rev * self.gear_ratio) * 360
            status["position"] = f"{pos}"
            status["angle_now"] = f"{angle:.2f}°"
        else:
            print("⚠️ 無法讀取目前位置")
            return None

        # 讀取電流（0x0F）
        res_current = self.client.read_holding_registers(address=0x0F, count=1, slave=self.slave_id)
        if not res_current.isError():
            current_raw = res_current.registers[0]
            current = current_raw / 2000.0  # 換算為安培
            status["current"] = f"{current:.3f} A"

        # 讀取實際速度（0x10）
        res_speed = self.client.read_holding_registers(address=0x10, count=1, slave=self.slave_id)
        if not res_speed.isError():
            raw_speed = res_speed.registers[0]
            if raw_speed >= 0x8000:
                raw_speed -= 0x10000  # 補正為有號數
            speed_rpm = raw_speed / 10.0
            status["speed"] = f"{speed_rpm:.1f} r/min"

        # 顯示所有資訊
        print(f"""
    📍 當前位置        ：{status['position']} 脈波
    📐 目前角度        ：{status['angle_now']}
    ⚡ 系統電流        ：{status['current']}
    🔁 實際轉速        ：{status['speed']}
    """)
        return pos




    def move_to_angle(self, angle_deg):
        pulses = self.angle_to_pulse(angle_deg)
        return self.move_absolute(pulses)

    def stop(self):
        print("🛑 強制中止馬達動作中...")
        self.client.write_register(0x01, 0, slave=self.slave_id)
        time.sleep(0.3)
        self.client.write_register(0x01, 1, slave=self.slave_id)

    def build_sync_command(motor_configs):
        """
        motor_configs: List of dicts, each with keys: address, position, speed, accel
        """
        from pymodbus.utilities import computeCRC
        payload = bytearray()
        payload.extend([0x00, 0x10, 0x00, 0x16])  # Broadcast, Func 0x10, start addr 0x0016
        motor_count = len(motor_configs)
        register_count = motor_count * 4
        payload.extend([(register_count >> 8) & 0xFF, register_count & 0xFF])  # reg count
        byte_count = register_count * 2
        payload.append(byte_count)

        for m in motor_configs:
            pos = m["position"] & 0xFFFFFFFF
            pos_bytes = [ (pos >> 24) & 0xFF, (pos >> 16) & 0xFF, (pos >> 8) & 0xFF, pos & 0xFF ]
            speed = m["speed"]
            accel = m["accel"]
            payload.extend(pos_bytes)
            payload.extend([(speed >> 8) & 0xFF, speed & 0xFF])
            payload.extend([(accel >> 8) & 0xFF, accel & 0xFF])

        crc = computeCRC(payload)
        payload.extend([crc & 0xFF, (crc >> 8) & 0xFF])
        return bytes(payload)
    



    @staticmethod
    def broadcast_control_all(client: ModbusSerialClient, motor_settings: list):
        """
        廣播同步控制所有馬達（最多 100 顆）

        Args:
            client: ModbusSerialClient 實例
            motor_settings: List of dict，格式為：
                [
                    {"position": int, "speed": int, "accel": int},
                    ...
                ]
        """
        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.LITTLE)

        for m in motor_settings:
            pos = m["position"]
            if pos < 0:
                pos = (1 << 32) + pos  # 補正負數為 32 位元正數
            builder.add_32bit_uint(pos)
            builder.add_16bit_uint(m.get("speed", 1000))
            builder.add_16bit_uint(m.get("accel", 3000))

        try:
            result = client.write_registers(
                address=0x16,
                values=builder.to_registers(),
                slave=0,  # 廣播給所有馬達
                expect_response=False
            )
            print(f"📡 廣播控制已發送，目標馬達數：{len(motor_settings)}")
        except Exception as e:
            print(f"❌ 廣播控制失敗：{e}")