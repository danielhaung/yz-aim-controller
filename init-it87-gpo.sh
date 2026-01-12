#!/bin/bash
#
# ============================================================
#   init-it87-gpo.sh  （極簡版：只聽 GPO_set.json）
#
#   ✅ 功能
#   - 持續讀取 /home/robot/yz-aim-controller/GPO_set.json
#   - 若其中某個 GPO i 被寫成 0/1，就立刻 gpioset 對應線路
#   - 寫完後把該值清回 null（避免重複觸發）
#   - 同時輸出 GPIO.json（記錄目前 GPI/GPO）
#
#   🔧 修改 / 佈署（標準流程）
#   Step 1：在 repo 內修改
#       ~/yz-aim-controller/init-it87-gpo.sh
#
#   Step 2：複製到系統執行路徑
#       cd ~/yz-aim-controller
#       sudo cp init-it87-gpo.sh /usr/local/bin/init-it87-gpo.sh
#       sudo chmod +x /usr/local/bin/init-it87-gpo.sh
#
#   Step 3：重啟服務
#       sudo systemctl restart init-it87-gpo.service
#       sudo systemctl status init-it87-gpo.service
#
#   Step 4：測試（寫入一次性命令）
#       cat > ~/yz-aim-controller/GPO_set.json <<EOF
#       {"GPO":{"1":0,"2":null,"3":null,"4":null,"5":null,"6":null,"7":null,"8":null}}
#       EOF
#
# ============================================================

set -euo pipefail

CHIP="gpiochip0"
BASE_DIR="/home/robot/yz-aim-controller"
JSON_STATE="${BASE_DIR}/GPIO.json"
JSON_SET="${BASE_DIR}/GPO_set.json"

# IT87 腳位映射（你的實際 mapping）
GPO_LINES=(48 49 50 51 52 53 54 55)     # GPO1~8
GPI_LINES=(56 57 58 59 60 61 62 63)     # GPI1~8

LOOP_SLEEP=0.1

mkdir -p "$BASE_DIR"

# 初始化 JSON_STATE
if [ ! -f "$JSON_STATE" ]; then
cat > "$JSON_STATE" <<EOF
{
  "timestamp": "",
  "GPI": {"1":0,"2":0,"3":0,"4":0,"5":0,"6":0,"7":0,"8":0},
  "GPO": {"1":1,"2":1,"3":1,"4":1,"5":1,"6":1,"7":1,"8":1}
}
EOF
fi

# 初始化 JSON_SET
if [ ! -f "$JSON_SET" ]; then
cat > "$JSON_SET" <<EOF
{
  "GPO": {"1":null,"2":null,"3":null,"4":null,"5":null,"6":null,"7":null,"8":null}
}
EOF
fi

while true; do
  # ---- 讀 GPI 狀態（只記錄，不做任何邏輯）----
  for i in {1..8}; do
    line=${GPI_LINES[$((i-1))]}
    v=$(gpioget "$CHIP" "$line" 2>/dev/null || echo 0)
    eval GPI_$i=$v
  done

  # ---- 讀取並套用 GPO_set.json（唯一控制來源）----
  changed=0
  for i in {1..8}; do
    val=$(jq -r ".GPO.\"$i\"" "$JSON_SET" 2>/dev/null || echo "null")
    if [ "$val" = "0" ] || [ "$val" = "1" ]; then
      line=${GPO_LINES[$((i-1))]}
      gpioset "$CHIP" "$line"="$val"
      eval GPO_$i=$val
      changed=1
    fi
  done

  # ---- 若有變更：把 JSON_SET 清回 null（避免重複觸發）----
  if [ "$changed" -eq 1 ]; then
cat > "$JSON_SET" <<EOF
{
  "GPO": {"1":null,"2":null,"3":null,"4":null,"5":null,"6":null,"7":null,"8":null}
}
EOF
  fi

  # ---- 寫入 JSON_STATE（回報目前狀態）----
  ts=$(date --iso-8601=seconds)

cat > "$JSON_STATE" <<EOF
{
  "timestamp": "$ts",
  "GPI": {"1": ${GPI_1:-0},"2": ${GPI_2:-0},"3": ${GPI_3:-0},"4": ${GPI_4:-0},"5": ${GPI_5:-0},"6": ${GPI_6:-0},"7": ${GPI_7:-0},"8": ${GPI_8:-0}},
  "GPO": {"1": ${GPO_1:-1},"2": ${GPO_2:-1},"3": ${GPO_3:-1},"4": ${GPO_4:-1},"5": ${GPO_5:-1},"6": ${GPO_6:-1},"7": ${GPO_7:-1},"8": ${GPO_8:-1}}
}
EOF

  sleep "$LOOP_SLEEP"
done
