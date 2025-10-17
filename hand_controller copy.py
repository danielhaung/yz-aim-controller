# -*- coding: utf-8 -*-
import time, serial, glob, os
from typing import List, Tuple, Dict, Optional

class HandController:
    """
    10 指舵機控制：
    - 左手 5 支（預設 ID: 0~4），右手 5 支（預設 ID: 5~9）
    - 以手勢索引 (preset) 控制：hand_move(left_idx, right_idx, duration)
    - 以百分比 (0~100%) 轉 PWM：個別舵機可調 MIN/MAX 與 INVERT
    - 指令格式：#<id>P<pwm>T<duration>，多條合併同步下發
    """

    # --------- 預設手勢庫：索引 -> [拇, 食, 中, 無名, 小] 百分比（0=張開、100=握拳）---------
    DEFAULT_PRESETS: Dict[int, Dict] = {
        0: {"name": "fist/握拳",     "pcts": [ 100, 100, 100, 100, 100 ]},
        1: {"name": "one/數字比1",   "pcts": [ 100,   0,  100, 100, 100]},
        2: {"name": "two/數字比2",   "pcts": [ 100,   0,    0, 100, 100 ]},  # 依你上則貼文設定
        3: {"name": "three/數字比3", "pcts": [ 100, 100,    0,   0,   0]},
        4: {"name": "four/數字比4",  "pcts": [ 100,   0,    0,   0,   0]},
        5: {"name": "five/數字比5",  "pcts": [   0,   0,    0,   0,   0]},
        6: {"name": "six/數字比6",   "pcts": [   0, 100,  100, 100,   0]},
        7: {"name": "seven/數字比7", "pcts": [   0,   0,  100,  100, 100]},
        8: {"name": "eight/數字比8", "pcts": [   0,   0,    0,  100, 100]},
    }

    @staticmethod
    def find_serial_port() -> str:
        """自動尋找可用的 CH340 / FTDI 串口（Linux by-id 優先；否則回退 ttyUSB0）"""
        by_id = sorted(glob.glob("/dev/serial/by-id/*"))
        for path in by_id:
            if any(k in path.lower() for k in ["ch340", "ftdi", "usb-serial"]):
                return path
        # 若在 Windows，請自行傳入如 "COM3"
        return "/dev/ttyUSB1"

    def __init__(
        self,
        port: Optional[str] = None,
        baud: int = 115200,
        left_ids: Optional[List[int]] = None,
        right_ids: Optional[List[int]] = None,
        servo_calib: Optional[Dict[int, Dict]] = None,
        presets: Optional[Dict[int, Dict]] = None,
        open_immediately: bool = True,
        rx_timeout: float = 0.2,
        tx_timeout: float = 0.2,
    ):
        self.port = port or self.find_serial_port()
        self.baud = baud
        self.rx_timeout = rx_timeout
        self.tx_timeout = tx_timeout

        # 預設左右手 ID
        self.left_ids  = left_ids  or [0, 1, 2, 3, 4]
        self.right_ids = right_ids or [5, 6, 7, 8, 9]

        # 舵機校正參數（依你提供）
        self.servo_calib: Dict[int, Dict] = servo_calib or {
            0: {"MIN": 800, "MAX": 2000, "INVERT": True},
            1: {"MIN": 800, "MAX": 2000, "INVERT": False},
            2: {"MIN": 800, "MAX": 2000, "INVERT": False},
            3: {"MIN": 800, "MAX": 2000, "INVERT": False},
            4: {"MIN": 800, "MAX": 2000, "INVERT": False},
            5: {"MIN": 800, "MAX": 2000, "INVERT": False},
            6: {"MIN": 800, "MAX": 2000, "INVERT": False},
            7: {"MIN": 800, "MAX": 2000, "INVERT": False},
            8: {"MIN": 800, "MAX": 2000, "INVERT": False},
            9: {"MIN": 800, "MAX": 2000, "INVERT": False},
        }

        # 手勢庫
        self.presets: Dict[int, Dict] = dict(self.DEFAULT_PRESETS)
        if presets:
            self.presets.update(presets)

        self.ser: Optional[serial.Serial] = None
        if open_immediately:
            self.open()

    # ---------- 連線生命週期 ----------
    def open(self):
        if self.ser and self.ser.is_open:
            return
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.rx_timeout,
            write_timeout=self.tx_timeout,
        )
        time.sleep(0.2)  # 轉換器穩定時間

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def __enter__(self):
        if not (self.ser and self.ser.is_open):
            self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---------- 低階 I/O ----------
    def _send_cmd(self, cmd: str):
        """自動補 CRLF 並送出"""
        if not self.ser:
            raise RuntimeError("Serial not open. Call open() first.")
        if not cmd.endswith("\r\n"):
            cmd += "\r\n"
        self.ser.write(cmd.encode("ascii"))
        self.ser.flush()

    # ---------- 校正 & 轉換 ----------
    def _pct_to_pwm(self, servo_id: int, pct: float) -> int:
        """
        將 0~100% 的開合百分比轉為 PWM。
        規則：pct=0% -> MIN，pct=100% -> MAX；INVERT=True 則反向。
        """
        c = self.servo_calib.get(servo_id, {"MIN": 500, "MAX": 2500, "INVERT": False})
        pct = max(0.0, min(100.0, float(pct)))
        if c.get("INVERT", False):
            pct = 100.0 - pct
        pwm = c["MIN"] + (c["MAX"] - c["MIN"]) * (pct / 100.0)
        # 再做一層總夾（有些控制器容忍 500~2500）
        return int(max(500, min(2500, round(pwm))))

    # ---------- 高階 API ----------
    def move_servo(self, servo_id: int, pos: int, duration: int = 500):
        """移動單一舵機（pos 建議 500~2500）"""
        pos = int(max(500, min(2500, pos)))
        self._send_cmd(f"#{servo_id}P{pos}T{duration}")

    def move_multiple(self, moves: List[Tuple[int, int]], duration: int = 500):
        """
        moves = [(id, pos), ...] 同步移動多個舵機
        """
        parts = []
        for i, p in moves:
            p = int(max(500, min(2500, p)))
            parts.append(f"#{i}P{p}")
        self._send_cmd(''.join(parts) + f"T{duration}")

    def _hand_side_moves(self, hand_ids: List[int], preset_idx: int) -> List[Tuple[int, int]]:
        preset = self.presets.get(preset_idx)
        if not preset:
            raise ValueError(f"Unknown hand preset index: {preset_idx}")
        pcts = preset["pcts"]
        if len(hand_ids) != 5 or len(pcts) != 5:
            raise ValueError("hand ids 或 preset pcts 必須長度為 5")
        return [(sid, self._pct_to_pwm(sid, pct)) for sid, pct in zip(hand_ids, pcts)]

    def hand_move(self, left_idx: int, right_idx: int, duration: int = 800):
        """
        hand_move(0,0) -> 左右同時握拳
        hand_move(1,1) -> 左右同時張開
        以此類推
        """
        moves = self._hand_side_moves(self.left_ids, left_idx) + \
                self._hand_side_moves(self.right_ids, right_idx)
        self.move_multiple(moves, duration=duration)

    # ---------- 設定/管理 ----------
    def set_calib(self, servo_id: int, min_pwm: Optional[int] = None,
                  max_pwm: Optional[int] = None, invert: Optional[bool] = None):
        """更新單支舵機的校正參數"""
        c = self.servo_calib.setdefault(servo_id, {"MIN": 500, "MAX": 2500, "INVERT": False})
        if min_pwm is not None:
            c["MIN"] = int(min_pwm)
        if max_pwm is not None:
            c["MAX"] = int(max_pwm)
        if invert is not None:
            c["INVERT"] = bool(invert)

    def set_hand_ids(self, left_ids: List[int], right_ids: List[int]):
        if len(left_ids) != 5 or len(right_ids) != 5:
            raise ValueError("left_ids / right_ids 長度都必須為 5")
        self.left_ids = list(left_ids)
        self.right_ids = list(right_ids)

    def add_or_update_preset(self, idx: int, name: str, pcts: List[float]):
        if len(pcts) != 5:
            raise ValueError("pcts 長度必須為 5")
        self.presets[idx] = {"name": name, "pcts": list(pcts)}

    def list_presets(self) -> Dict[int, Dict]:
        return dict(self.presets)

    def describe(self) -> str:
        """回傳目前配置（方便除錯）"""
        return (
            f"Port={self.port}, Baud={self.baud}\n"
            f"Left IDs={self.left_ids}, Right IDs={self.right_ids}\n"
            f"Presets={ {k:v['name'] for k,v in self.presets.items()} }"
        )


# ===================== 使用示例 =====================
if __name__ == "__main__":
    # 建議用 with，自動關閉 serial
    with HandController(open_immediately=True) as hand:
        print("[INFO] Connected:", hand.describe())

        # 左右同時握拳
        hand.hand_move(0, 0, duration=800)
        time.sleep(1.2)


        # 左右同時數字比1
        hand.hand_move(1, 1, duration=800)
        time.sleep(1.2)

        # 左右同時數字比2
        hand.hand_move(2, 0, duration=800)
        time.sleep(1.2)



