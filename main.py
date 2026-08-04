#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import argparse
import threading
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from pymodbus.client import ModbusSerialClient
from motor_controller import MotorController
from hand_controller import HandController
import json
import subprocess

GPO_SET = Path("/home/robot/yz-aim-controller/GPO_set.json")


VOICE_DIR = Path("/home/robot/yz-aim-controller/voice")
AUDIO_DEV = "plughw:CARD=CD002AUDIO,DEV=0"   # ✅ 你測到會出聲的裝置
MPG123 = "/usr/bin/mpg123"

def play_mp3(name: str, blocking: bool = False) -> bool:
    mp3 = (VOICE_DIR / name) if not name.startswith("/") else Path(name)
    if not mp3.exists():
        print(f"⚠️ 找不到語音檔：{mp3}")
        return False

    cmd = [MPG123, "-q", "-o", "alsa", "-a", AUDIO_DEV, str(mp3)]
    try:
        if blocking:
            subprocess.run(cmd, check=True)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"⚠️ 播放失敗：{e}")
        return False

 


def write_atomic_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

def set_gpo1(value: int):
    """
    只更新 GPO_set.json 的 GPO["1"]，其他 key 保留原值
    """
    value = int(value)

    # 讀現有內容（若不存在/壞掉就用預設）
    base = {"GPO": {str(i): None for i in range(1, 9)}}
    try:
        if GPO_SET.exists():
            cur = json.loads(GPO_SET.read_text(encoding="utf-8"))
            if isinstance(cur, dict) and isinstance(cur.get("GPO"), dict):
                # merge：保留既有 key
                for i in range(1, 9):
                    k = str(i)
                    if k in cur["GPO"]:
                        base["GPO"][k] = cur["GPO"][k]
    except Exception:
        pass

    # 只改 1
    base["GPO"]["1"] = value

    write_atomic_json(GPO_SET, base)





def blink_gpo1(stop_event):
    state = 0
    while not stop_event.is_set():
        set_gpo1(state)
        state = 1 - state
        time.sleep(1.0)
# =========================
#  Part 1) Robot main (consumer) : reads angles.txt and drives motors + hands
# =========================

_PARSE_RE = re.compile(
    r"""^\s*
        (?P<body>[-\d\s,]+?)                                  # angles CSV/space
        (?:\s*\(\s*(?P<L>\d+)\s*,\s*(?P<R>\d+)\s*\)\s*)?      # optional (L,R)
        (?:\s*\#(?P<tag>\d+)\s*)?                             # optional: #7 at end
        \s*$""",
    re.X
)


def start_mp3(name: str) -> Optional[subprocess.Popen]:
    mp3 = (VOICE_DIR / name) if not name.startswith("/") else Path(name)
    if not mp3.exists():
        print(f"⚠️ 找不到語音檔：{mp3}")
        return None
    try:
        return subprocess.Popen(
            [MPG123, "-q", "-o", "alsa", "-a", AUDIO_DEV, str(mp3)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"⚠️ 播放失敗：{e}")
        return None




def parse_angles_line(line: str, angle_count: int):
    m = _PARSE_RE.match(line.strip())
    if not m:
        raise ValueError("格式不符：角度 + 可選 (L,R) + 可選行尾 #tag")

    tag = int(m.group("tag")) if m.group("tag") is not None else None

    body = m.group("body")
    toks = [t for t in re.split(r"[,\s]+", body.strip()) if t != ""]
    if len(toks) != angle_count:
        raise ValueError(f"角度數量錯誤：{len(toks)}，應為 {angle_count}。")

    angles = [int(float(x)) for x in toks]
    L = int(m.group("L")) if m.group("L") is not None else None
    R = int(m.group("R")) if m.group("R") is not None else None
    return angles, L, R, tag




def proportional_speed(distance_deg, max_distance_deg, max_rpm, ratio=0.8):
    if max_distance_deg <= 0:
        return int(max_rpm * ratio)
    v = int((distance_deg / max_distance_deg) * max_rpm * ratio)
    return max(1, min(v, max_rpm))

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

class RobotRuntime:
    def __init__(self, args, ready_event: threading.Event, stop_event: threading.Event):
        self.args = args
        self.ready_event = ready_event
        self.stop_event = stop_event
        self._voice_proc = None
        self._voice_tag_playing = None
        self.client: Optional[ModbusSerialClient] = None
        self.hand: Optional[HandController] = None
        self.motors: List[MotorController] = []

        self.previous_angles: Optional[List[int]] = None

    def init_all(self):
        # 1) connect Modbus
        self.client = ModbusSerialClient(port=self.args.modbus_port,
                                         baudrate=self.args.modbus_baud,
                                         timeout=self.args.modbus_timeout)
        if not self.client.connect():
            raise RuntimeError(f"無法連接身體埠 {self.args.modbus_port} @ {self.args.modbus_baud}")
        print(f"✅ 已連線身體：{self.args.modbus_port} @ {self.args.modbus_baud}")

        # 2) create motors (你原本只開 1 顆，其他註解保留；你可自行加回來)
        self.motors = [
            # 大頭    -20～-50
            MotorController(self.client, slave_id=1, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),        
            # # 脖子    -90～-90
            MotorController(self.client, slave_id=2, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000), 
            # # 右肩前後-90～-90
            MotorController(self.client, slave_id=3, gear_ratio=120, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),    # 50×20 = 1000 ✅
            # # 右肩上下-60～-20
            MotorController(self.client, slave_id=4, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),   # 120×20 = 2400 → 1500 ❌
            # # 右臂旋轉60～-20
            MotorController(self.client, slave_id=5, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000), 
            # # 右手軸彎曲-90～0
            MotorController(self.client, slave_id=6, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 右手腕控制-90～-90
            MotorController(self.client, slave_id=7, gear_ratio=50, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 左肩前後-90～-90
            MotorController(self.client, slave_id=8, gear_ratio=120, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),    # 50×20 = 1000 ✅
            # # 左肩上下-20～-60
            MotorController(self.client, slave_id=9, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),   # 120×20 = 2400 → 1500 ❌
            # # 左臂旋轉-60～-20
            MotorController(self.client, slave_id=10, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000), 
            # # 左手軸彎曲-90～0
            MotorController(self.client, slave_id=11, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 左手腕控制-90～-90
            MotorController(self.client, slave_id=12, gear_ratio=50, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 腰部旋轉20～-20
            MotorController(self.client, slave_id=13, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 右髖上下30～-30
            MotorController(self.client, slave_id=14, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 右髖左右-20～0
            MotorController(self.client, slave_id=15, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),  # 100×20 = 2000 → 1500 ❌
            # # 右膝蓋-30～0
            MotorController(self.client, slave_id=16, gear_ratio=120, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 右腳踝30～-30 
            MotorController(self.client, slave_id=17, gear_ratio=50, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 左髖上下30～-30
            MotorController(self.client, slave_id=18, gear_ratio=100, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 左髖左右0～20
            MotorController(self.client, slave_id=19, gear_ratio=120, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 左膝蓋30～0
            MotorController(self.client, slave_id=20, gear_ratio=120, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
            # # 左腳踝30～-30
            MotorController(self.client, slave_id=21, gear_ratio=50, speed=1200, accel=2000, speed_kp=12000, speed_ki=10, pos_kp=5000),
    ]

        # 角度數必須 >= motors 數（否則會 index error）
        if self.args.angle_count < len(self.motors):
            raise RuntimeError(f"--angle-count({self.args.angle_count}) 必須 >= motors數({len(self.motors)})")

        # 3) connect hand
        self.hand = HandController(port=self.args.hand_port,
                                   baud=self.args.hand_baud,
                                   open_immediately=True)
        print(f"✅ 已連線手：{self.args.hand_port} @ {self.args.hand_baud}")
        try:
            print("[INFO] Hand:", self.hand.describe())
        except Exception:
            pass

        # 4) ready signal
        print("ROBOT_MAIN_READY", flush=True)
        self.ready_event.set()

    def run_loop(self):
        assert self.client is not None
        assert self.hand is not None

        angles_file = self.args.angles

        while not self.stop_event.is_set():
            try:
                with open(angles_file, "r", encoding="utf-8") as f:
                    raw = f.readline().strip()
            except FileNotFoundError:
                time.sleep(0.2)
                continue

            if not raw:
                time.sleep(0.05)
                continue

            try:
                angle_list, L_idx, R_idx, tag = parse_angles_line(raw, self.args.angle_count)

                TAG_VOICE = {
                    1: "1welcome.mp3",
                    2: "2welcome_M.mp3",
                    3: "3傳動減速機_品牌介紹.mp3",
                }

                if tag is not None and tag in TAG_VOICE:
                    is_playing = (self._voice_proc is not None and self._voice_proc.poll() is None)

                    if is_playing:
                        if self._voice_tag_playing == tag:
                            # 同一個 tag 還在播：不重播
                            pass
                        else:
                            # 不同 tag 來了：打斷上一首
                            try:
                                self._voice_proc.terminate()
                                try:
                                    self._voice_proc.wait(timeout=0.2)
                                except subprocess.TimeoutExpired:
                                    self._voice_proc.kill()
                            except Exception:
                                pass

                            self._voice_proc = start_mp3(TAG_VOICE[tag])
                            self._voice_tag_playing = tag
                    else:
                        # 沒在播：直接播
                        self._voice_proc = start_mp3(TAG_VOICE[tag])
                        self._voice_tag_playing = tag


            except Exception as e:
                print(f"❌ 解析失敗：{e}")
                time.sleep(0.1)
                continue


            # 首輪：只記錄角度（不做差值速度比例），可選擇也下手勢
            if self.previous_angles is None:
                self.previous_angles = angle_list[:]
                print("📌 初始角度已記錄")
                if L_idx is not None and R_idx is not None:
                    print(f"🤝 首輪手勢：L={L_idx}, R={R_idx}")
                    try:
                        self.hand.hand_move(L_idx, R_idx, duration=600)
                    except Exception as e:
                        print(f"⚠️ hand_move 失敗：{e}")

                # 清空 angles.txt
                try:
                    with open(angles_file, "w", encoding="utf-8") as f:
                        f.write("")
                except Exception:
                    pass
                continue

            # 只控制 motors 數量那幾個角度
            distances = [abs(angle_list[i] - self.previous_angles[i]) for i in range(len(self.motors))]
            max_distance = max(distances) if distances else 0

            threads = []
            if max_distance > 0:
                for i, motor in enumerate(self.motors):
                    curr = angle_list[i]
                    prev = self.previous_angles[i]
                    dist = abs(curr - prev)
                    if dist == 0:
                        continue
                    speed = proportional_speed(dist, max_distance,
                                               getattr(motor, "max_rpm", 1500),
                                               ratio=self.args.speed_ratio)
                    t = threading.Thread(target=move_and_monitor,
                                         args=(motor, curr, speed, self.args.tolerance))
                    t.start()
                    threads.append(t)

            # 同步下發手勢（若有）
            if L_idx is not None and R_idx is not None:
                def _hand_job():
                    try:
                        self.hand.hand_move(L_idx, R_idx, self.args.hand_duration_ms)
                    except Exception as e:
                        print(f"⚠️ hand_move 失敗：{e}")
                threading.Thread(target=_hand_job, daemon=True).start()

            for t in threads:
                while t.is_alive() and not self.stop_event.is_set():
                    t.join(timeout=0.1)

            # 如果 feeder 已要求結束，就不要再印「等待下一筆…」了，直接退出
            if self.stop_event.is_set():
                break

            self.previous_angles = angle_list[:]

            # 清空 angles.txt 讓 feeder 知道可送下一筆
            try:
                with open(angles_file, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception:
                pass

            print("✅ 本輪完成，等待下一筆…")
            time.sleep(0.01)


    def close(self):
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        try:
            if self.hand:
                self.hand.close()
        except Exception:
            pass


# =========================
#  Part 2) Feeder (producer) : move.txt -> angles.txt, waits for angles.txt empty
# =========================

SECTION_RE = re.compile(r"^\s*(\d+)\s*\.\s*(.+?)\s*$")

FRAME_RE = re.compile(r"""
    ^\s*
    (?P<angles>-?\d+(?:\s*,\s*-?\d+)*)          # CSV ints
    \s*
    (?:\(\s*(?P<L>\d+)\s*,\s*(?P<R>\d+)\s*\))?  # optional (L,R)
    \s*
    (?:\#(?P<tag>\d+)\s*)?                      # optional #tag at end
    \s*$
""", re.X)


def parse_lr(s: Optional[str]) -> Optional[Tuple[int,int]]:
    if s is None:
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 2:
        raise ValueError("gesture 需為 'L,R' 兩個整數")
    return int(parts[0]), int(parts[1])

def normalize_frame(angles: List[int], L: Optional[int], R: Optional[int], tag: Optional[int] = None) -> str:
    base = ",".join(str(a) for a in angles)
    if L is not None and R is not None:
        base += f"({L},{R})"
    if tag is not None:
        base += f"#{tag}"
    return base


def parse_move_file(path: Path,
                    expected_n: int,
                    default_lr: Optional[Tuple[int,int]] = None,
                    force_lr: Optional[Tuple[int,int]] = None
                    ) -> Dict[Tuple[int, str], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path.resolve()}")

    sections: Dict[Tuple[int, str], List[str]] = {}
    cur_key = None

    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue

            m = SECTION_RE.match(line)
            if m:
                idx = int(m.group(1))
                title = m.group(2).strip()
                cur_key = (idx, title)
                sections[cur_key] = []
                continue

            m = FRAME_RE.match(line)
            if not m:
                continue

            tag = m.group("tag")
            tag = int(tag) if tag is not None else None


            if cur_key is None:
                cur_key = (0, "Default")
                sections.setdefault(cur_key, [])

            angles_str = m.group("angles")
            L = m.group("L")
            R = m.group("R")
            L = int(L) if L is not None else None
            R = int(R) if R is not None else None

            angles = [int(a.strip()) for a in angles_str.split(",") if a.strip() != ""]

            if len(angles) != expected_n:
                print(f"[warn] 欄位數 {len(angles)} != 預期 {expected_n}：{line}")

            if force_lr is not None:
                L, R = force_lr
            elif (L is None or R is None) and default_lr is not None:
                L, R = default_lr

            sections[cur_key].append(normalize_frame(angles, L, R, tag))


    if not sections:
        raise ValueError("move.txt 沒有解析出任何段落/角度行。")

    return dict(sorted(sections.items(), key=lambda kv: kv[0][0]))

def is_file_empty(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        if path.stat().st_size == 0:
            return True
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip() == ""
    except OSError:
        return False

def wait_until_empty(path: Path, poll: float, stop_event: threading.Event, timeout: float = 30.0) -> bool:
    """等待 angles.txt 被清空（代表 consumer 已處理完最後一筆）"""
    t0 = time.time()
    while not is_file_empty(path):
        if stop_event.is_set():
            return False
        if time.time() - t0 > timeout:
            print(f"[feeder][warn] 等待 {path.name} 清空逾時 {timeout}s，仍強制結束。")
            return False
        time.sleep(poll)
    return True

def write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text.strip() + "\n")
    os.replace(tmp, path)

def clear_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("")

def feed_frames(frames: List[str], angles_path: Path, poll: float,
                stop_event: threading.Event,
                dry_run: bool = False,
                section_idx: Optional[int] = None):
    for idx, payload in enumerate(frames, 1):
        if stop_event.is_set():
            return
        print(f"[wait] 第 {idx}/{len(frames)} 筆，等待 {angles_path.name} 為空…")
        while not is_file_empty(angles_path):
            if stop_event.is_set():
                return
            time.sleep(poll)

        tagged_payload = payload

        if dry_run:
            print(f"[dry-run] 將寫入：{tagged_payload}")
        else:
            write_atomic(angles_path, tagged_payload)
            print(f"[feed] -> {angles_path.name} : {tagged_payload}")


class FeederRuntime:
    def __init__(self, args, ready_event: threading.Event, stop_event: threading.Event):
        self.args = args
        self.ready_event = ready_event
        self.stop_event = stop_event

    def run(self):
        # 等待 robot ready
        print("[feeder] 等待 ROBOT_MAIN_READY…")
        self.ready_event.wait()
        if self.stop_event.is_set():
            return
        print("[feeder] ✅ Robot ready，開始餵資料")

        move_path = Path(self.args.move)
        angles_path = Path(self.args.angles)

        default_lr = parse_lr(self.args.default_gesture) if self.args.default_gesture else None
        force_lr   = parse_lr(self.args.force_gesture)   if self.args.force_gesture   else None

        sections = parse_move_file(move_path,
                                   expected_n=self.args.angles_n,
                                   default_lr=default_lr,
                                   force_lr=force_lr)

        if self.args.list:
            print("可用段落：")
            for (idx, title), frames in sections.items():
                print(f"  {idx}. {title}  ({len(frames)} 筆)")
            return

        selected = list(sections.items())
        if self.args.section:
            key = self.args.section.strip()

            def match(kv):
                (idx, title), _ = kv
                return str(idx) == key or key in title

            selected = [kv for kv in selected if match(kv)]
            if not selected:
                print(f"[feeder][error] 找不到符合 --section='{self.args.section}' 的段落。")
                print("可用段落：")
                for (idx, title), frames in sections.items():
                    print(f"  {idx}. {title}  ({len(frames)} 筆)")
                return

        if self.args.clear_first:
            clear_file(angles_path)
            print(f"[feeder] 已清空 {angles_path}")

        total = sum(len(frames) for _, frames in selected)
        print(f"[feeder] 段落={len(selected)} 段，共 {total} 筆，目標={angles_path}")

        for (idx, title), frames in selected:
            print(f"\n[section] {idx}. {title}  （{len(frames)} 筆）")
            feed_frames(frames, angles_path, self.args.poll,
                        stop_event=self.stop_event,
                        dry_run=self.args.dry_run,
                        section_idx=idx)

        print("\n[feeder] ✅ 全部餵完。")

        if self.args.exit_when_done:
            print("[feeder] exit_when_done=ON，等待最後一筆被清空後結束…")
            wait_until_empty(angles_path, self.args.poll, self.stop_event, timeout=self.args.exit_timeout)
            print("[feeder] ✅ stop_event SET，準備結束整個程式")
            self.stop_event.set()




# =========================
#  Main
# =========================

def build_argparser():
    ap = argparse.ArgumentParser(description="整合：Robot main 初始化完成後，才開始 feeder 送 move.txt 到 angles.txt")

    # ports
    ap.add_argument("--modbus-port", default="/dev/ttyS0")
    ap.add_argument("--hand-port", default="/dev/ttyS1")
    ap.add_argument("--modbus-baud", type=int, default=19200)
    ap.add_argument("--hand-baud", type=int, default=115200)
    ap.add_argument("--modbus-timeout", type=float, default=1.0)

    # files
    ap.add_argument("--move", default="move.txt")
    ap.add_argument("--angles", default="angles.txt")

    # counts
    ap.add_argument("--angles-n", type=int, default=21, help="move.txt 每行角度數（你資料是 21）")
    ap.add_argument("--angle-count", type=int, default=21, help="Robot 解析 angles.txt 角度數（要跟 angles-n 對齊）")

    # feeder controls
    ap.add_argument("--poll", type=float, default=0.10)
    ap.add_argument("--section", type=str, default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clear-first", action="store_true")
    ap.add_argument("--default-gesture", type=str, default=None)
    ap.add_argument("--force-gesture", type=str, default=None)
    ap.add_argument("--exit-when-done", action="store_true",
                    help="feeder 送完就結束整個程式（也會關閉 Modbus/Hand）")
    ap.add_argument("--exit-timeout", type=float, default=60.0,
                    help="exit-when-done 時，等待最後一筆 angles.txt 被清空的最長秒數")

    # robot tuning
    ap.add_argument("--tolerance", type=int, default=100)
    ap.add_argument("--speed-ratio", type=float, default=0.8)
    ap.add_argument("--hand-duration-ms", type=int, default=800)

    return ap

def main():
    args = build_argparser().parse_args()
    args.exit_when_done = True

    print(f"✅ 身體埠 (Modbus) → {args.modbus_port} @ {args.modbus_baud}")
    print(f"✅ 手埠   (Hand)   → {args.hand_port}   @ {args.hand_baud}")
    print(f"📄 move={args.move}  angles={args.angles}")
    print(f"🔢 angles_n(move)={args.angles_n}  angle_count(robot)={args.angle_count}")

    # 啟動就閃燈
    blink_stop = threading.Event()
    blink_thread = threading.Thread(target=blink_gpo1, args=(blink_stop,), daemon=True)
    blink_thread.start()

    ready_event = threading.Event()
    stop_event = threading.Event()

    robot = RobotRuntime(args, ready_event, stop_event)
    feeder = FeederRuntime(args, ready_event, stop_event)

    try:
        robot.init_all()

        t_robot = threading.Thread(target=robot.run_loop)
        t_feed  = threading.Thread(target=feeder.run)

        t_robot.start()
        t_feed.start()

        while not stop_event.is_set():
            time.sleep(0.05)

        t_feed.join(timeout=args.exit_timeout + 2.0)
        t_robot.join(timeout=args.exit_timeout + 2.0)

    except KeyboardInterrupt:
        print("🛑 使用者中斷執行")
        stop_event.set()

    except Exception as e:
        print(f"❌ 啟動失敗：{e}")
        stop_event.set()

        # 失敗當下：先停閃燈，避免覆寫
        blink_stop.set()
        time.sleep(0.2)
        blink_thread.join(timeout=1.0)

        # 失敗也常亮
        set_gpo1(1)
        return

    finally:
        blink_stop.set()
        time.sleep(0.2)
        if blink_thread.is_alive():
            blink_thread.join(timeout=1.0)
        set_gpo1(1)
        robot.close()

if __name__ == "__main__":

    main()