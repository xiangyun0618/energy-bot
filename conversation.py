# conversation_state.py
# 以簡單 dict 在記憶中追蹤使用者註冊步驟（重啟會消失；日後可改為 DB）
state = {}  # user_id -> {"step": int, "temp": {...}}

def start_registration(user_id):
    state[user_id] = {"step": 1, "temp": {}}

def get_state(user_id):
    return state.get(user_id)

def advance(user_id):
    if user_id in state:
        state[user_id]["step"] += 1

def set_temp(user_id, key, value):
    if user_id not in state:
        start_registration(user_id)
    state[user_id]["temp"][key] = value

def get_temp(user_id, key, default=None):
    return state.get(user_id, {}).get("temp", {}).get(key, default)

def clear(user_id):
    if user_id in state:
        del state[user_id]
