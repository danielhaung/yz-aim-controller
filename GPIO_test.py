#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GPIO_test.py  (python3-gpiod v1)
--------------------------------
功能：
- 持續顯示 8 路 GPI 狀態 + 偵測變化
- 同時輪循 GPO1~GPO8：每秒切換一次 ON/OFF（0=ON, 1=OFF）
"""

import time
import signal
import gpiod

CHIP_NAME = "gpiochip0"

# 8DI / 8DO 對應 line
GPI_LINES = [56, 57, 58, 59, 60, 61, 62, 63]
GPO_LINES = [48, 49, 50, 51, 52, 53, 54, 55]

# 讀取輪詢間隔（秒）
POLL_INTERVAL = 0.2

# GPO 切換節奏（秒）
GPO_TOGGLE_INTERVAL = 1.0

# 你的系統定義：0=ON(導通), 1=OFF(斷開)
ON = 0
OFF = 1

running = True
def stop(sig, frame):
    global running
    print("\n🛑 GPIO test stop")
    running = False

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

def main():
    print("🔌 GPIO Test (gpiod v1 API)")
    print("Chip :", CHIP_NAME)
    print("GPI  :", GPI_LINES)
    print("GPO  :", GPO_LINES)
    print("-" * 60)

    chip = gpiod.Chip(CHIP_NAME)

    # --- GPI: 一次取得多條線，設定輸入 ---
    gpi_lines = chip.get_lines(GPI_LINES)
    gpi_lines.request(consumer="gpio-test-gpi", type=gpiod.LINE_REQ_DIR_IN)

    # --- GPO: 每條線獨立 request（v1 沒有 batch output 的 set_values 很方便）---
    gpo_objs = []
    for idx, line_no in enumerate(GPO_LINES, start=1):
        line = chip.get_line(line_no)
        # 預設全部 OFF
        line.request(
            consumer=f"gpio-test-gpo{idx}",
            type=gpiod.LINE_REQ_DIR_OUT,
            default_val=OFF
        )
        gpo_objs.append(line)

    last_gpi_vals = [None] * len(GPI_LINES)

    gpo_idx = 0                 # 目前輪到哪一顆 GPO
    gpo_state_on = False        # False=OFF, True=ON（以 0/1 寫入）
    next_toggle_ts = time.time() + GPO_TOGGLE_INTERVAL

    tick = 0
    try:
        while running:
            now = time.time()

            # ====== 1) 讀取 GPI + 變化偵測 ======
            vals = gpi_lines.get_values()  # list of 0/1

            for i, v in enumerate(vals):
                if last_gpi_vals[i] is None:
                    last_gpi_vals[i] = v
                elif v != last_gpi_vals[i]:
                    print(f"⚡ GPI{i+1} change: {last_gpi_vals[i]} → {v}")
                    last_gpi_vals[i] = v

            # 每秒輸出一次整體狀態
            if tick % int(1 / POLL_INTERVAL) == 0:
                bits = " ".join(f"GPI{i+1}:{v}" for i, v in enumerate(vals))
                value = sum(v << i for i, v in enumerate(vals))
                print(f"[STATE] {bits}  (0x{value:02X})")

            # ====== 2) 輪循切換 GPO：同一顆 ON->OFF 完再換下一顆 ======
            if now >= next_toggle_ts:
                # 先確保全部 OFF（避免多顆同時 ON）
                for line in gpo_objs:
                    line.set_value(OFF)

                if not gpo_state_on:
                    # Phase A：同一顆先 ON
                    gpo_objs[gpo_idx].set_value(ON)
                    print(f"[GPO] GPO{gpo_idx+1} (line {GPO_LINES[gpo_idx]}) => ON(0)")
                    gpo_state_on = True
                else:
                    # Phase B：同一顆再 OFF，然後換下一顆
                    gpo_objs[gpo_idx].set_value(OFF)
                    print(f"[GPO] GPO{gpo_idx+1} (line {GPO_LINES[gpo_idx]}) => OFF(1)")
                    gpo_state_on = False
                    gpo_idx = (gpo_idx + 1) % len(gpo_objs)

                next_toggle_ts = now + GPO_TOGGLE_INTERVAL


            tick += 1
            time.sleep(POLL_INTERVAL)

    finally:
        # 清場：全部 GPO OFF
        try:
            for line in gpo_objs:
                try:
                    line.set_value(OFF)
                except Exception:
                    pass
                try:
                    line.release()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            gpi_lines.release()
        except Exception:
            pass
        try:
            chip.close()
        except Exception:
            pass

        print("✅ GPIO Test End")

if __name__ == "__main__":
    main()
