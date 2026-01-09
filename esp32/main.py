# main.py — 綠燈狀態 + 按鈕一次性觸發 Modbus coil
#           + 由 PC 的 HR[0] 回報「任務完成」

import time
from machine import Pin
from modbus import RS485, crc16, ModbusRTUMaster   # 直接使用你原本 modbus.py 裡的 RS485 & ModbusRTUMaster

# === RS485 / Modbus Master 設定 ===
UART_ID = 1
BAUD = 115200
TX_PIN = 17
RX_PIN = 16
USE_DIR   = True
DE_RE_PIN = 4
DIR_SW_US = 400

SLAVE_ID  = 1      # PC 端 esp32_modbus.py 的 Unit ID
COIL_ADDR = 0      # 我們在 PC 端用的就是 coil 0
HR_DONE_ADDR = 0   # 對應 PC 那邊 HR_MISSION_DONE = 0

# 建立 RS485 + Modbus Master 物件（全域使用）
rs = RS485(UART_ID, BAUD, TX_PIN, RX_PIN, USE_DIR, DE_RE_PIN, DIR_SW_US)
mb = ModbusRTUMaster(rs, timeout_ms=500, debug=False)


def trigger_pc_mission():
    """
    發一筆 Modbus RTU: Write Single Coil (Function 0x05)
    寫入：slave=SLAVE_ID, coil=COIL_ADDR, value=ON (FF00)
    這個 frame 會被 PC 那邊的 esp32_modbus.py 收到，進而啟動 robot-runner.service
    """
    try:
        slave = SLAVE_ID
        addr = COIL_ADDR
        # Modbus FC 5：0xFF00 = ON, 0x0000 = OFF
        value = 0xFF00

        req = bytes([
            slave & 0xFF,
            0x05,                       # Function Code: Write Single Coil
            (addr >> 8) & 0xFF,
            addr & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
        c = crc16(req)
        frame = req + bytes([c & 0xFF, (c >> 8) & 0xFF])

        # 只送出 request，不特別等回應（PC 端有收到就會啟動服務）
        rs.write(frame)
        print(">>> Modbus TX: write single coil addr=%d ON (slave=%d)" % (addr, slave))
    except Exception as e:
        print("!!! Modbus trigger error:", e)


# === 綠燈 ===
GREEN_PIN = 13
green = Pin(GREEN_PIN, Pin.OUT)

# === 按鈕 ===
BTN_PIN = 33
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)   # 按鈕 → GND

DEBOUNCE_MS   = 200
BOOT_IGNORE_MS = 800

# === LED 閃爍設定 ===
BOOT_TIME_MS  = 5000      # 前 5 秒為「未開機」
SLOW_BLINK_MS = 8000      # 慢閃週期
FAST_BLINK_MS = 2000       # 快閃週期

# === 狀態 ===
STATE_IDLE    = 0   # 開機完成、未觸發（快閃）
STATE_RUNNING = 1   # 已觸發、程式運行中（長亮）

_state = STATE_IDLE
_pressed_flag = False
_press_ts = 0

_boot_ts = time.ticks_ms()
_run_start_ts = None   # 只是用來標記“這次任務已經啟動”，避免誤判


# --- 按鈕 IRQ ---
def _btn_irq_handler(pin):
    global _pressed_flag, _press_ts
    now = time.ticks_ms()

    # 開機短時間內忽略
    if time.ticks_diff(now, _boot_ts) < BOOT_IGNORE_MS:
        return

    # 只處理按下（下降沿）
    if btn.value() == 0:
        _pressed_flag = True
        _press_ts = now

btn.irq(trigger=Pin.IRQ_FALLING, handler=_btn_irq_handler)


# --- 程式是否跑完？ ---
def is_program_done():
    """
    改成問 PC：HR[0] == 1 就代表任務真的跑完
    """
    global _run_start_ts

    if _run_start_ts is None:
        # 尚未啟動任務，不需要查
        return False

    try:
        regs = mb.read_holding_registers(SLAVE_ID, HR_DONE_ADDR, 1)  # 從 HR[0] 讀 1 筆
        done_flag = regs[0]

        if done_flag != 0:
            print(">>> PC 回報任務完成 (HR0=%d)" % done_flag)
            # 如果你想讓 PC 知道 ESP32 已收到，也可以在這裡回寫一個 ack
            return True

    except Exception as e:
        print("!!! 讀取 PC 任務完成旗標失敗:", e)

    return False


# --- LED 顯示 ---
def update_green_led():
    now = time.ticks_ms()

    # (1) 開機未完成：慢閃
    if time.ticks_diff(now, _boot_ts) < BOOT_TIME_MS:
        t = now % SLOW_BLINK_MS
        green.value(1 if t < (SLOW_BLINK_MS // 2) else 0)
        return

    # (2) 已被觸發 & 程式運行中：綠燈長亮
    if _state == STATE_RUNNING:
        green.on()
        return

    # (3) 開機完成 & 未觸發：快閃
    t = now % FAST_BLINK_MS
    green.value(1 if t < (FAST_BLINK_MS // 2) else 0)


def main():
    global _pressed_flag, _state, _run_start_ts

    green.off()
    print("ESP32 booting...")

    while True:
        now = time.ticks_ms()

        # === 1. 按鈕事件處理 ===
        if _pressed_flag:
            # 等待按鈕放開 + 去彈跳
            if btn.value() == 1 and time.ticks_diff(now, _press_ts) > DEBOUNCE_MS:
                # 只在「未觸發狀態」接受這次觸發
                if _state == STATE_IDLE:
                    _state = STATE_RUNNING
                    _run_start_ts = time.ticks_ms()
                    print(">>> BUTTON TRIGGERED! 程式開始運行")

                    # ★ 在這裡通知 PC：寫 Modbus Coil 0 = 1
                    trigger_pc_mission()

                _pressed_flag = False

        # === 2. 若正在運行，檢查程式是否跑完（問 PC 的 HR[0]） ===
        if _state == STATE_RUNNING:
            if is_program_done():
                print(">>> PROGRAM DONE! 回到未觸發狀態")
                _state = STATE_IDLE
                _run_start_ts = None

        # === 3. 更新綠燈狀態 ===
        update_green_led()

        time.sleep_ms(20)


main()

