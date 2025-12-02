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
    
    # 只有管理員可以維護廠區與設備
    user = db.get_user(user_id)

    # 新增廠區：格式「新增廠區 北區二廠」
    if msg.startswith("新增廠區"):
        if not user or user.get("role") != "管理員":
            reply_text(event.reply_token, "只有管理員可以新增廠區。")
            return

        name = msg.replace("新增廠區", "", 1).strip()
        if not name:
            reply_text(event.reply_token, "請在『新增廠區』後面加上名稱，例如：新增廠區 北區二廠")
            return

        ok = db.add_factory(name)
        if ok:
            reply_text(event.reply_token, f"已新增廠區：{name}")
        else:
            reply_text(event.reply_token, f"新增失敗，可能廠區已存在：{name}")
        return

    # 刪除廠區：格式「刪除廠區 北區二廠」
    if msg.startswith("刪除廠區"):
        if not user or user.get("role") != "管理員":
            reply_text(event.reply_token, "只有管理員可以刪除廠區。")
            return

        name = msg.replace("刪除廠區", "", 1).strip()
        if not name:
            reply_text(event.reply_token, "請在『刪除廠區』後面加上名稱，例如：刪除廠區 北區二廠")
            return

        ok = db.delete_factory(name)
        if ok:
            reply_text(event.reply_token, f"已刪除廠區：{name}")
        else:
            reply_text(event.reply_token, f"刪除失敗，找不到廠區：{name}")
        return
    
    # 新增設備：格式「新增設備 廠區名 設備名稱」
    # 範例：新增設備 北區廠 PCS-01
    if msg.startswith("新增設備"):
        if not user or user.get("role") != "管理員":
            reply_text(event.reply_token, "只有管理員可以新增設備。")
            return

        parts = msg.split()
        if len(parts) < 3:
            reply_text(event.reply_token, "格式錯誤，請用：新增設備 廠區名 設備名稱\n例如：新增設備 北區廠 PCS-01")
            return

        factory = parts[1]
        eq_name = " ".join(parts[2:])

        eq = db.add_equipment(factory, eq_name)
        if eq:
            reply_text(event.reply_token, f"已新增設備：{factory} / {eq_name}（ID: {eq['id']}）")
        else:
            reply_text(event.reply_token, "新增設備失敗，請確認輸入。")
        return

    # 刪除設備：格式「刪除設備 ID」
    # 範例：刪除設備 3
    if msg.startswith("刪除設備"):
        if not user or user.get("role") != "管理員":
            reply_text(event.reply_token, "只有管理員可以刪除設備。")
            return

        parts = msg.split()
        if len(parts) != 2 or not parts[1].isdigit():
            reply_text(event.reply_token, "格式錯誤，請用：刪除設備 設備ID\n例如：刪除設備 3")
            return

        eq_id = int(parts[1])
        ok = db.delete_equipment(eq_id)
        if ok:
            reply_text(event.reply_token, f"已刪除設備（ID: {eq_id}）。")
        else:
            reply_text(event.reply_token, f"刪除失敗，找不到設備 ID: {eq_id}")
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
        cs.set_temp(user_id, "name", msg)
        cs.advance(user_id)

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

                factories = db.get_factories()
                reply_text(
                    reply_token,
                    "請選擇主要廠區（輸入數字）：\n" +
                    "\n".join(f"{i+1}. {f}" for i, f in enumerate(factories))
                )
                return

        reply_text(reply_token, "輸入錯誤，請重新輸入角色的『數字』。")
        return

    # STEP 3：主要廠區
    if step == 3:
        factories = db.get_factories()
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(factories):
                factory = factories[idx]
                cs.set_temp(user_id, "primary_factory", factory)
                cs.advance(user_id)

                reply_text(
                    reply_token,
                    "請設定在【主要廠區】的優先級（輸入數字）：\n"
                    "1. 第一優先（主要負責）\n"
                    "2. 第二優先\n"
                    "3. 第三優先"
                )
                return

        reply_text(reply_token, "輸入錯誤，請重新輸入廠區的『數字』。")
        return

    # STEP 4：主要廠區優先級
    if step == 4:
        if msg not in ["1", "2", "3"]:
            reply_text(reply_token, "請輸入 1、2 或 3 來設定優先級。")
            return

        cs.set_temp(user_id, "primary_priority", int(msg))
        cs.advance(user_id)

        reply_text(
            reply_token,
            "是否還要設定【第二優先廠區】？\n"
            "若有請回覆「是」，沒有請回覆「否」。"
        )
        return

    # STEP 5：是否有第二優先
    if step == 5:
        msg_norm = msg.strip()
        if msg_norm in ["是", "有", "Y", "y"]:
            cs.advance(user_id)

            factories = db.get_factories()
            primary_factory = cs.get_temp(user_id, "primary_factory")
            # 排除已選的主要廠區
            options = [f for f in factories if f != primary_factory]

            if not options:
                # 沒其他廠區可以選，就直接完成
                _finish_registration_without_second(user_id, reply_token)
                return

            cs.set_temp(user_id, "second_options", options)

            reply_text(
                reply_token,
                "請選擇第二優先廠區（輸入數字）：\n" +
                "\n".join(f"{i+1}. {f}" for i, f in enumerate(options))
            )
            return

        elif msg_norm in ["否", "沒有", "N", "n"]:
            _finish_registration_without_second(user_id, reply_token)
            return

        else:
            reply_text(reply_token, "請回覆「是」或「否」。")
            return

    # STEP 6：第二優先廠區
    if step == 6:
        options = cs.get_temp(user_id, "second_options") or []
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(options):
                second_factory = options[idx]
                cs.set_temp(user_id, "second_factory", second_factory)
                cs.advance(user_id)

                reply_text(
                    reply_token,
                    "請設定【第二優先廠區】的優先級（輸入數字）：\n"
                    "1. 第一優先\n"
                    "2. 第二優先\n"
                    "3. 第三優先"
                )
                return

        reply_text(reply_token, "輸入錯誤，請重新輸入第二優先廠區的『數字』。")
        return

    # STEP 7：第二優先廠區優先級，然後完成註冊
    if step == 7:
        if msg not in ["1", "2", "3"]:
            reply_text(reply_token, "請輸入 1、2 或 3 來設定優先級。")
            return

        cs.set_temp(user_id, "second_priority", int(msg))
        _finish_registration_with_second(user_id, reply_token)
        return


# ----------------- 註冊完成（只有主要廠區） --------------------
def _finish_registration_without_second(user_id, reply_token):
    name = cs.get_temp(user_id, "name")
    role = cs.get_temp(user_id, "role")
    primary_factory = cs.get_temp(user_id, "primary_factory")
    primary_priority = cs.get_temp(user_id, "primary_priority")

    fp = {primary_factory: primary_priority}

    db.add_user(
        user_id=user_id,
        name=name,
        factory_priority=fp,
        role=role
    )

    priority_text = {1: "第一優先", 2: "第二優先", 3: "第三優先"}[primary_priority]

    reply_text(
        reply_token,
        "註冊完成！\n"
        f"姓名：{name}\n"
        f"角色：{role}\n"
        f"主要廠區：{primary_factory}\n"
        f"優先級：{priority_text}"
    )

    cs.clear(user_id)


# ----------------- 註冊完成（有第二優先） --------------------
def _finish_registration_with_second(user_id, reply_token):
    name = cs.get_temp(user_id, "name")
    role = cs.get_temp(user_id, "role")
    primary_factory = cs.get_temp(user_id, "primary_factory")
    primary_priority = cs.get_temp(user_id, "primary_priority")
    second_factory = cs.get_temp(user_id, "second_factory")
    second_priority = cs.get_temp(user_id, "second_priority")

    fp = {
        primary_factory: primary_priority,
        second_factory: second_priority
    }

    db.add_user(
        user_id=user_id,
        name=name,
        factory_priority=fp,
        role=role
    )

    map_p = {1: "第一優先", 2: "第二優先", 3: "第三優先"}
    reply_text(
        reply_token,
        "註冊完成！\n"
        f"姓名：{name}\n"
        f"角色：{role}\n"
        f"主要廠區：{primary_factory}（{map_p[primary_priority]}）\n"
        f"第二優先廠區：{second_factory}（{map_p[second_priority]}）"
    )

    cs.clear(user_id)


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
    print("Render auto deploy test")

    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=5000, debug=True)