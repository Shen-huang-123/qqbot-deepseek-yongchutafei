"""
QQ 剪贴板桥接 - 当前可用方案
监控剪贴板，复制QQ消息后自动获取AI回复
用法：python clipboard_bridge.py
"""
import time
import pyperclip
import requests

API = "http://127.0.0.1:8765"
last = ""

print("=" * 40)
print("  QQ ChatBot 剪贴板助手")
print("=" * 40)
print("  1. QQ 里 Ctrl+C 复制别人消息")
print("  2. 自动获取 AI 回复到剪贴板")
print("  3. Ctrl+V 贴回 QQ")
print("  Ctrl+C 在终端退出")
print("=" * 40)

try:
    while True:
        try:
            cur = pyperclip.paste()
        except:
            time.sleep(0.5)
            continue

        if cur and cur != last and len(cur.strip()) > 1:
            last = cur
            print(f"\n📩 {cur[:80]}...")
            try:
                r = requests.post(f"{API}/", json={
                    "post_type": "message", "sender": {"user_id": "qq"},
                    "raw_message": cur.strip()
                }, timeout=30)
                reply = r.json().get("reply", "无响应")
            except Exception as e:
                reply = f"错误: {e}"
            print(f"🤖 {reply[:150]}")
            pyperclip.copy(reply)
            print("   ✅ 已复制，Ctrl+V 贴回QQ")
        time.sleep(0.8)
except KeyboardInterrupt:
    print("\n已退出")
