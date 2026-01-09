#!/usr/bin/env python3
# ESP32 ←→ PC Modbus RTU
# 收到 Coil 0 = 1 → 啟動 robot-runner.service
# robot-runner 結束 → 在 HR[0] 寫入 1 告訴 ESP32「任務完成」

import os
import time
import logging
import subprocess
from threading import Thread

# 兼容 pymodbus 2.x / 3.x+
try:
    from pymodbus.server.sync import StartSerialServer  # 舊版路徑
except ImportError:
    from pymodbus.server import StartSerialServer       # 新版路徑

from pymodbus.datastore import (
    ModbusSlaveContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.device import ModbusDeviceIdentification

# ================== 基本設定 ==================
PORT = os.environ.get(
    "RS485_PORT",
    "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG028CF0-if00-port0"
)
BAUD      = int(os.environ.get("RS485_BAUD", "115200"))
PARITY    = os.environ.get("RS485_PARITY", "N")   # N / E / O
BYTESIZE  = int(os.environ.get("RS485_BYTESIZE", "8"))
STOPBITS  = int(os.environ.get("RS485_STOPBITS", "1"))
SLAVE_ID  = int(os.environ.get("UNIT_ID", "1"))

# Coil / HR 定義
COIL_START_MISSION = 0      # Coil[0] = 啟動任務
HR_MISSION_DONE    = 0      # HR[0]  = 任務完成旗標

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("esp32_modbus_simple")

# ================== 建立資料區 ==================
store = ModbusSlaveContext(
    di = ModbusSequentialDataBlock(0, [0] * 64),   # 10001+
    co = ModbusSequentialDataBlock(0, [0] * 64),   # 00001+
    hr = ModbusSequentialDataBlock(0, [0] * 64),   # 40001+
    ir = ModbusSequentialDataBlock(0, [0] * 64),   # 30001+
)

# multi-slave 模式，但只掛一個 SLAVE_ID
context = ModbusServerContext(slaves={SLAVE_ID: store}, single=False)


def get_coil(addr: int) -> int:
    """讀取單一 coil 值 (0 or 1)"""
    return context[SLAVE_ID].getValues(1, addr, count=1)[0]


def set_coil(addr: int, val: int):
    """寫入單一 coil 值"""
    context[SLAVE_ID].setValues(1, addr, [1 if val else 0])


def get_hr(addr: int) -> int:
    """讀取單一 Holding Register"""
    return context[SLAVE_ID].getValues(3, addr, count=1)[0]  # 3 = HR


def set_hr(addr: int, val: int):
    """寫入單一 Holding Register"""
    context[SLAVE_ID].setValues(3, addr, [val])


# ================== 動作 ==================
def start_robot_mission():
    """
    啟動 robot-runner.service，結束後在 HR[0] 寫 1 通知 ESP32
    """
    cmd = ["systemctl", "start", "robot-runner.service"]
    log.warning("Executing: %s", " ".join(cmd))
    try:
        rc = subprocess.call(cmd)
        log.info("robot-runner.service exited with rc=%d", rc)

        # ★ 任務結束 → 回報任務完成
        set_hr(HR_MISSION_DONE, 1)

    except Exception as e:
        log.exception("start_robot_mission failed: %s", e)


def coil_watcher():
    """
    背景執行緒：監看 START_MISSION 這顆 coil
    偵測 0→1 上升沿 → 啟動任務
    """
    last = -1
    log.info("coil_watcher started, watching coil %d", COIL_START_MISSION)

    while True:
        try:
            val = get_coil(COIL_START_MISSION)

            if val == 1 and last == 0:
                log.info(
                    "Coil %d rising edge detected → start robot mission",
                    COIL_START_MISSION
                )

                # 清掉 coil 避免重複觸發
                set_coil(COIL_START_MISSION, 0)

                # 任務開始前，先把「完成旗標」清為 0
                set_hr(HR_MISSION_DONE, 0)

                # 開一條 Thread 去跑任務
                Thread(target=start_robot_mission, daemon=True).start()

            last = val
        except Exception as e:
            log.exception("coil_watcher error: %s", e)

        time.sleep(0.1)


def main():
    # 啟動監看執行緒
    Thread(target=coil_watcher, daemon=True).start()

    # Modbus 裝置資訊（隨便填即可）
    identity = ModbusDeviceIdentification()
    identity.VendorName  = 'LIMING-ROBOT'
    identity.ProductCode = 'PC-SLAVE'
    identity.VendorUrl   = 'http://127.0.0.1'
    identity.ProductName = 'Robot PC Modbus RTU Slave'
    identity.ModelName   = 'ESP32 Trigger Backend'
    identity.MajorMinorRevision = '1.0'

    log.info(
        "Starting Modbus RTU slave on %s @ %d %s%d%s (Unit ID=%d)",
        PORT, BAUD, PARITY, BYTESIZE, STOPBITS, SLAVE_ID
    )

    # 啟動 Modbus RTU Server（阻塞）
    StartSerialServer(
        context,
        identity=identity,
        port=PORT,
        baudrate=BAUD,
        parity=PARITY,
        bytesize=BYTESIZE,
        stopbits=STOPBITS,
        timeout=1,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Fatal error in main: %s", e)
        raise


