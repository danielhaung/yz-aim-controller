#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional

MOVE_PATH_DEFAULT = "move.txt"
ANGLES_PATH_DEFAULT = "angles.txt"

# 節標題：如 "1.Right arm（右手臂動）"
SECTION_RE = re.compile(r"^\s*(\d+)\s*\.\s*(.+?)\s*$")

# 角度行（允許尾端 (L,R) 手勢）
# 例： "0,0,...,0"   或   "0,0,...,0(1,0)"
FRAME_RE = re.compile(r"""
    ^\s*
    (?P<angles>-?\d+(?:\s*,\s*-?\d+)*)       # 逗號分隔整數
    \s*
    (?:\(\s*(?P<L>\d+)\s*,\s*(?P<R>\d+)\s*\))?  # 選擇性 (L,R)
    \s*$
""", re.X)

def parse_lr(s: Optional[str]) -> Optional[Tuple[int,int]]:
    if s is None:
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 2:
        raise ValueError("gesture 需為 'L,R' 兩個整數")
    return int(parts[0]), int(parts[1])

def normalize_frame(angles: List[int], L: Optional[int], R: Optional[int]) -> str:
    base = ",".join(str(a) for a in angles)
    if L is None or R is None:
        return base
    return f"{base}({L},{R})"

def parse_move_file(path: Path,
                    expected_n: int,
                    default_lr: Optional[Tuple[int,int]] = None,
                    force_lr: Optional[Tuple[int,int]] = None
                    ) -> Dict[Tuple[int, str], List[str]]:
    """
    將 move.txt 解析成：
      { (section_number, section_title) : [ "a1,...,aN", "a1,...,aN(L,R)", ... ] }

    - 每筆角度個數需等於 expected_n（預設 19），否則警告但仍保留原行
    - 行尾可含 (L,R)；若 --force-gesture 指定了，會覆蓋成指定手勢
      否則若 --default-gesture 指定了且該行沒有手勢，會補上
    - 允許段落間空行與註解文字；只收集符合 FRAME_RE 的行
    """
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
                # 其他說明/註解行略過
                continue

            if cur_key is None:
                cur_key = (0, "Default")
                sections.setdefault(cur_key, [])

            angles_str = m.group("angles")
            L = m.group("L")
            R = m.group("R")
            L = int(L) if L is not None else None
            R = int(R) if R is not None else None

            # 解析角度
            try:
                angles = [int(a.strip()) for a in angles_str.split(",") if a.strip() != ""]
            except ValueError as e:
                print(f"[warn] 角度清單解析失敗，略過：{line}；原因：{e}")
                continue

            # 檢查數量
            if len(angles) != expected_n:
                print(f"[warn] 欄位數 {len(angles)} != 預期 {expected_n}：{line}")

            # 套用 force/default 手勢規則
            if force_lr is not None:
                L, R = force_lr
            elif (L is None or R is None) and default_lr is not None:
                L, R = default_lr

            payload = normalize_frame(angles, L, R)
            sections[cur_key].append(payload)

    if not sections:
        raise ValueError("move.txt 沒有解析出任何段落/角度行。")

    # 依段號排序
    return dict(sorted(sections.items(), key=lambda kv: kv[0][0]))

def is_file_empty(path: Path) -> bool:
    """angles.txt 是否為『空』：不存在、檔案大小 0、或內容全空白"""
    if not path.exists():
        return True
    try:
        if path.stat().st_size == 0:
            return True
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip() == ""
    except OSError:
        # I/O 競態，保守視為非空
        return False

def write_atomic(path: Path, text: str):
    """原子寫入，避免讀到半成品"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text.strip() + "\n")
    os.replace(tmp, path)

def clear_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("")

def feed_frames(frames: List[str], angles_path: Path, poll: float, dry_run: bool = False):
    """逐筆餵入 frames：等 angles.txt 為空時，寫入下一筆"""
    for idx, payload in enumerate(frames, 1):
        print(f"[wait] 第 {idx}/{len(frames)} 筆，等待 {angles_path.name} 為空…")
        while not is_file_empty(angles_path):
            time.sleep(poll)
        if dry_run:
            print(f"[dry-run] 將寫入：{payload}")
        else:
            write_atomic(angles_path, payload)
            print(f"[feed] -> {angles_path.name} : {payload}")

def main():
    ap = argparse.ArgumentParser(description="餵角度：當 angles.txt 為空時，從 move.txt 寫入下一筆。支援尾端 (L,R) 手勢。")
    ap.add_argument("--move", default=MOVE_PATH_DEFAULT, help="move.txt 路徑（含分段與角度行）")
    ap.add_argument("--angles", default=ANGLES_PATH_DEFAULT, help="angles.txt 路徑（被控制程式讀取）")
    ap.add_argument("--poll", type=float, default=0.10, help="監看間隔秒數")
    ap.add_argument("--section", type=str, default=None,
                    help="只餵某一段（可填數字編號，如 3；或標題關鍵字的一部分，如 '右腳動'）")
    ap.add_argument("--list", action="store_true", help="僅列出可用段落，不餵資料")
    ap.add_argument("--dry-run", action="store_true", help="僅顯示將要寫入的內容，不實際寫檔")
    ap.add_argument("--clear-first", dest="clear_first", action="store_true", help="開始前先清空 angles.txt")

    # 新增：角度數量與手勢策略
    ap.add_argument("--angles-n", type=int, default=21, help="每行預期的角度數量（預設 19）")
    ap.add_argument("--default-gesture", type=str, default=None,
                    help="預設手勢 'L,R'（只有當該行沒寫手勢時才會補上）")
    ap.add_argument("--force-gesture", type=str, default=None,
                    help="強制手勢 'L,R'（不論該行是否有手勢，一律覆蓋）")

    args = ap.parse_args()

    move_path = Path(args.move)
    angles_path = Path(args.angles)

    default_lr = parse_lr(args.default_gesture) if args.default_gesture else None
    force_lr   = parse_lr(args.force_gesture)   if args.force_gesture   else None

    sections = parse_move_file(move_path, expected_n=args.angles_n,
                               default_lr=default_lr, force_lr=force_lr)

    # 列出段落
    if args.list:
        print("可用段落：")
        for (idx, title), frames in sections.items():
            print(f"  {idx}. {title}  ({len(frames)} 筆)")
        return

    # 過濾段落
    selected: List[Tuple[Tuple[int, str], List[str]]] = list(sections.items())
    if args.section:
        key = args.section.strip()

        def match(kv):
            (idx, title), _ = kv
            return str(idx) == key or key in title

        selected = [kv for kv in selected if match(kv)]
        if not selected:
            print(f"[error] 找不到符合 --section='{args.section}' 的段落。可用清單：")
            for (idx, title), frames in sections.items():
                print(f"  {idx}. {title}  ({len(frames)} 筆)")
            return

    if args.clear_first:
        clear_file(angles_path)
        print(f"[info] 已清空 {angles_path}")

    # 開始餵
    total = sum(len(frames) for _, frames in selected)
    print(f"[info] 總共 {len(selected)} 段、{total} 筆角度。目標檔：{angles_path.name}")
    for (idx, title), frames in selected:
        print(f"\n[section] {idx}. {title}  （{len(frames)} 筆）")
        feed_frames(frames, angles_path, args.poll, dry_run=args.dry_run)
    print("\n[done] 全部餵完。")

if __name__ == "__main__":
    main()

