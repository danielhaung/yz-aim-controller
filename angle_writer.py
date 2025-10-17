import random
import time
import os

FILENAME = "angles.txt"
MOTOR_COUNT = 2

def generate_random_angles():
    return [random.randint(-45, 45) for _ in range(MOTOR_COUNT)]

def write_angles(angles):
    with open(FILENAME, "w") as f:
        f.write(",".join(str(a) for a in angles))
    print(f"📝 寫入角度：{angles}")

print("📡 監控 angles.txt 中...")

while True:
    if os.path.exists(FILENAME):
        with open(FILENAME, "r") as f:
            content = f.read().strip()
        if content == "":
            print("🕒 angles.txt 為空，3 秒後寫入新角度...")
            time.sleep(1)
            new_angles = generate_random_angles()
            write_angles(new_angles)
    else:
        print("⚠️ angles.txt 不存在，正在建立...")
        with open(FILENAME, "w") as f:
            f.write("")

    time.sleep(1)


