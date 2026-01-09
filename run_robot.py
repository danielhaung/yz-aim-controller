#!/usr/bin/env python3
# /home/agv/yz-aim-controller/run_robot.py
import os
import subprocess
import time

BASE_DIR = "/home/agv/yz-aim-controller"
VENV_PY  = os.path.join(BASE_DIR, "venv", "bin", "python")

# ==== 可調參數 ====
READY_TOKEN        = "ROBOT_MAIN_READY"  # main.py 就緒時會 print 的字串
MAX_WAIT_READY_SEC = 60                  # 最長等待 main.py 就緒時間
RETRY_DELAY_SEC    = 3                   # main.py 失敗後，重試前等待秒數


def start_main():
    """啟動 main.py，回傳 Popen 物件"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    print("[ROBOT] starting main.py ...")
    p = subprocess.Popen(
        [VENV_PY, "main.py"],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    return p


def wait_main_ready(proc: subprocess.Popen) -> bool:
    """
    監看 main.py 的輸出：
      - 在 MAX_WAIT_READY_SEC 內看到 READY_TOKEN → True
      - main.py 提前退出 / 超時 → False
    """
    print(f"[ROBOT] waiting for '{READY_TOKEN}' from main.py ...")
    t0 = time.time()

    while True:
        # main.py 掛掉 → 視為失敗
        if proc.poll() is not None:
            print("[ROBOT] main.py exited before ready, rc =", proc.returncode)
            return False

        line = proc.stdout.readline()
        if line:
            line = line.rstrip("\r\n")
            print("[main.py]", line)
            if READY_TOKEN in line:
                print("[ROBOT] main.py reported READY")
                return True

        # 超時
        if time.time() - t0 > MAX_WAIT_READY_SEC:
            print("[ROBOT] wait for READY timeout")
            return False

        time.sleep(0.1)


def stop_main(proc: subprocess.Popen):
    """優雅地結束 main.py，必要時強制 kill"""
    if proc.poll() is not None:
        return  # 已經結束

    print("[ROBOT] stopping main.py ...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print("[ROBOT] main.py did not exit, killing ...")
        proc.kill()


def run_auto_move():
    """執行 auto_move.py，回傳 exit code"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    print("[ROBOT] running auto_move.py ...")
    rc = subprocess.call(
        [VENV_PY, "auto_move.py"],
        cwd=BASE_DIR,
        env=env,
    )
    print("[ROBOT] auto_move.py exited with", rc)
    return rc


def main():
    # === 1. 不斷重試 main.py，直到「就緒」為止 ===
    while True:
        proc = start_main()
        ok = wait_main_ready(proc)

        if ok:
            # 準備好了 → 跳出 retry 迴圈
            break

        # 準備失敗 → 關掉 main.py，稍後重試
        stop_main(proc)
        print(f"[ROBOT] main.py FAIL, retry in {RETRY_DELAY_SEC} sec ...")
        time.sleep(RETRY_DELAY_SEC)

    # === 2. main.py 就緒 → 執行 auto_move.py ===
    rc_auto = run_auto_move()

    # === 3. auto_move.py 結束 → 關掉 main.py → 全部結束 ===
    stop_main(proc)
    print("[ROBOT] mission finished, auto_move rc =", rc_auto)
    return rc_auto


if __name__ == "__main__":
    raise SystemExit(main())
