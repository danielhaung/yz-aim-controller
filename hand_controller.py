import time, serial, glob, os

def find_serial_port():
    """自動尋找可用的 CH340 / FTDI 串口"""
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    for path in by_id:
        if any(k in path.lower() for k in ["ch340", "ftdi", "usb-serial"]):
            return path
    return "/dev/ttyUSB0"

PORT = find_serial_port()
BAUD = 115200

def open_serial():
    ser = serial.Serial(
        port=PORT, baudrate=BAUD,
        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
        timeout=0.2, write_timeout=0.2
    )
    time.sleep(0.2)
    return ser

def send_cmd(ser, cmd: str):
    """自動補 CRLF 並送出"""
    if not cmd.endswith('\r\n'):
        cmd += '\r\n'
    ser.write(cmd.encode('ascii'))
    ser.flush()

def move_servo(ser, servo_id: int, pos: int, duration: int = 500):
    """移動單一舵機"""
    cmd = f"#{servo_id}P{pos}T{duration}"
    send_cmd(ser, cmd)

def move_multiple(ser, moves: list, duration: int = 500):
    """
    moves = [(id, pos), ...]
    同步移動多個舵機
    """
    cmd = ''.join(f"#{i}P{p}" for i, p in moves)
    cmd += f"T{duration}"
    send_cmd(ser, cmd)

if __name__ == "__main__":
    print(f"[INFO] Using port: {PORT}")
    ser = open_serial()

    # # === 測試 ===
    # # 1. 初始化位置
    # for i in range(10):
    #     move_servo(ser, i, 1500, 800)
    # time.sleep(1.5)

    # 2. 多舵機同步動作
    move_multiple(ser, [(0, 2500), (1, 2500), (2, 1800), (3, 1200)], duration=800)
    time.sleep(2)
    move_multiple(ser, [(0, 500), (1, 500), (2, 1800), (3, 1200)], duration=800)
    time.sleep(2)
    move_multiple(ser, [(0, 2500), (1, 2500), (2, 1800), (3, 1200)], duration=800)
    # # 3. 播放一個動作序列
    # for step in [
    #     [(0, 1200), (1, 1800), (2, 1500)],
    #     [(0, 1800), (1, 1200), (2, 1600)],
    #     [(0, 1500), (1, 1500), (2, 1500)],
    # ]:
    #     move_multiple(ser, step, duration=600)
    time.sleep(0.7)

    ser.close()
    print("[OK] Done.")
