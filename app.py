from __future__ import unicode_literals
from flask import Flask, request, abort
from linebot import WebhookHandler, LineBotApi
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent
import schedule
import threading
import time
from datetime import date

import os

from db_manager import DBManager
import conversation as cs
from defaults import DEFAULT_FACTORIES, DEFAULT_ROLES

# Line bot鑰匙
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
# ----------------------------------------------------

app = Flask(__name__)
handler = WebhookHandler(CHANNEL_SECRET)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

# 資料庫
db = DBManager()
db.seed_factories(DEFAULT_FACTORIES)

# ----------------- 常用函式 --------------------
def reply_text(reply_token, text):
    line_bot_api.reply_message(reply_token, TextSendMessage(text=text))

def push_text(user_id, text):
    line_bot_api.push_message(user_id, TextSendMessage(text=text))


# ----------------- Webhook --------------------
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


# ----------------- Follow Event --------------------
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    push_text(
        user_id,
        "哈囉！我是儲能巡檢助手。\n輸入「註冊」即可開始註冊。"
    )


# ----------------- 訊息事件 --------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    # 是否在註冊流程中
    st = cs.get_state(user_id)
    if st:
        handle_registration(event, st)
        return

    # ---- 指令 ----
    if msg == "註冊":
        cs.start_registration(user_id)
        reply_text(event.reply_token, "開始註冊流程。\n請輸入你的姓名：")
        return

    if msg == "我的任務":
        show_today_tasks(event, user_id)
        return

    reply_text(event.reply_token, "我不懂你說什麼。\n可使用：\n• 註冊\n• 我的任務")


# ----------------- 註冊流程 --------------------
def handle_registration(event, state):
    user_id = event.source.user_id
    reply_token = event.reply_token
    step = state["step"]
    msg = event.message.text.strip()

    # STEP 1：姓名
    if step == 1:
        # 存姓名
        cs.set_temp(user_id, "name", msg)
        cs.advance(user_id)

        # 問角色
        reply_text(
            reply_token,
            "請輸入你的角色（輸入數字）：\n" +
            "\n".join(f"{i+1}. {r}" for i, r in enumerate(DEFAULT_ROLES))
        )
        return

    # STEP 2：角色
    if step == 2:
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(DEFAULT_ROLES):
                role = DEFAULT_ROLES[idx]
                cs.set_temp(user_id, "role", role)
                cs.advance(user_id)

                # 問廠區
                factories = db.get_factories()
                reply_text(
                    reply_token,
                    "請選擇主要廠區（輸入數字）：\n" +
                    "\n".join(f"{i+1}. {f}" for i, f in enumerate(factories))
                )
                return

        reply_text(reply_token, "輸入錯誤，請重新輸入角色的『數字』。")
        return

    # STEP 3：廠區
    if step == 3:
        factories = db.get_factories()
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(factories):
                factory = factories[idx]
                cs.set_temp(user_id, "factory", factory)
                cs.advance(user_id)

                # 問優先級
                reply_text(
                    reply_token,
                    "請設定你在此廠區的優先級（輸入數字）：\n"
                    "1. 第一優先（主要負責）\n"
                    "2. 第二優先\n"
                    "3. 第三優先"
                )
                return

        reply_text(reply_token, "輸入錯誤，請重新輸入廠區的『數字』。")
        return

    # STEP 4：優先級
    if step == 4:
        if msg not in ["1", "2", "3"]:
            reply_text(reply_token, "請輸入 1、2 或 3 來設定優先級。")
            return

        priority = int(msg)

        # 把暫存資料拿出來
        name = cs.get_temp(user_id, "name")
        role = cs.get_temp(user_id, "role")
        factory = cs.get_temp(user_id, "factory")

        # 建立 factory_priority dict（之後一個人要多廠區時，可以再用 update_user 去加）
        fp = {factory: priority}

        # 寫入 DB
        db.add_user(
            user_id=user_id,
            name=name,
            factory_priority=fp,
            role=role
        )

        priority_text = {1: "第一優先", 2: "第二優先", 3: "第三優先"}[priority]

        reply_text(
            reply_token,
            "註冊完成！\n"
            f"姓名：{name}\n"
            f"角色：{role}\n"
            f"廠區：{factory}\n"
            f"優先級：{priority_text}"
        )

        # 清掉註冊流程狀態
        cs.clear(user_id)
        return


# ----------------- 查詢任務 --------------------
def show_today_tasks(event, user_id):
    today = date.today().isoformat()
    tasks = [t for t in db.get_tasks_by_date(today) if t["assigned_user_id"] == user_id]

    if not tasks:
        reply_text(event.reply_token, "今天沒有任務。")
        return

    lines = []
    for t in tasks:
        lines.append(
            f"任務ID {t['id']}\n"
            f"廠區：{t['factory']}\n"
            f"機台：{t['machine']}\n"
            f"狀態：{t['status']}\n"
        )

    reply_text(event.reply_token, "\n".join(lines))


# ----------------- 任務派送（依優先級） --------------------
def assign_daily_tasks():
    today = date.today().isoformat()
    factories = db.get_factories()
    users = db.get_all_users()

    for fac in factories:
        candidates = []

        # 找所有負責此廠區的維修員
        for user in users:
            role = user.get("role", "")
            fp = user.get("factory_priority", {})

            if role != "維修員":
                continue

            if fac in fp:   # 此人負責這個廠區
                candidates.append((user, fp[fac]))

        if not candidates:
            continue

        # 依照優先級排序（小 → 大）
        candidates.sort(key=lambda x: x[1])
        chosen = candidates[0][0]  # 取最優先者

        # 模擬派任
        machine = f"逆變器-{fac[-1]}01"
        task = db.create_task(
            factory=fac,
            machine=machine,
            assigned_user_id=chosen["user_id"],
            task_type="例行巡檢",
            date_str=today
        )

        # 推播任務
        push_text(
            chosen["user_id"],
            f"📌 今日任務\n廠區：{fac}\n機台：{machine}\n任務ID：{task['id']}\n完成後回覆：完成 {task['id']}"
        )


# ----------------- 背景排程 --------------------
def schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(1)


schedule.every().day.at("08:30").do(assign_daily_tasks)
# 若要測試立即派任：取消註解下一行
# schedule.every(1).minutes.do(assign_daily_tasks)


# ----------------- 主程式 --------------------
if __name__ == "__main__":
    print("目前廠區：", db.get_factories())
    print("目前使用者：", db.get_all_users())

    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=5000, debug=True)