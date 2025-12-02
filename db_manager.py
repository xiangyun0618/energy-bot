import os
import json
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
FACTORIES_FILE = os.path.join(DATA_DIR, "factories.json")
EQUIPMENTS_FILE = os.path.join(DATA_DIR, "equipments.json")


# ------------------- 共用讀寫 -------------------
def _load(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return default


def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ------------------- 主類別 -------------------
class DBManager:
    def __init__(self):
        self.users = _load(USERS_FILE, [])      # list of dicts
        self.tasks = _load(TASKS_FILE, [])      # list of dicts
        self.factories = _load(FACTORIES_FILE, [])  # list of strings
        self.equipments = _load(EQUIPMENTS_FILE, [])   # list of dicts


    # ===================== 使用者 =====================
    def add_user(self, user_id, name=None, factory_priority=None, role=None):
        """
        factory_priority 格式：
        { "北區廠": 1, "東區廠": 2 }
        """
        if self.get_user(user_id):
            return False
        
        user = {
            "user_id": user_id,
            "name": name or "",
            "factory_priority": factory_priority or {},  # dict
            "role": role or ""
        }
        self.users.append(user)
        self._save_users()
        return True

    def get_user(self, user_id):
        for u in self.users:
            if u["user_id"] == user_id:
                return u
        return None

    def get_all_users(self):
        return list(self.users)

    def _save_equipments(self):
        _save(EQUIPMENTS_FILE, self.equipments)

    def update_user(self, user_id, **kwargs):
        """
        kwargs 可傳:
        name="翔允"
        role="維修員"
        factory_priority={"北區廠":1, "南區廠":2}
        （會自動 merge）
        """
        user = self.get_user(user_id)
        if not user:
            return False
        
        for key, value in kwargs.items():
            if key == "factory_priority":
                # 重要：支援合併 + 更新優先級
                if isinstance(value, dict):
                    for fac, pri in value.items():
                        user["factory_priority"][fac] = pri
            elif key in user:
                user[key] = value
        
        self._save_users()
        return True

    # ===================== 廠區 =====================
    def seed_factories(self, names):
        """若無廠區資料，則初始化"""
        if not self.factories:
            self.factories = names
            self._save_factories()

    def get_factories(self):
        return list(self.factories)

    def add_factory(self, name: str):
        """新增廠區名稱，如果已存在就回 False"""
        name = name.strip()
        if not name:
            return False
        if name in self.factories:
            return False
        self.factories.append(name)
        self._save_factories()
        return True

    def delete_factory(self, name: str):
        """刪除廠區，若不存在回 False"""
        name = name.strip()
        if name not in self.factories:
            return False
        self.factories.remove(name)
        self._save_factories()
        return True


    # ===================== 任務 =====================
    def create_task(self, factory, machine, assigned_user_id, task_type="巡檢", date_str=None):
        """建立任務"""
        if date_str is None:
            date_str = date.today().isoformat()

        task = {
            "id": len(self.tasks) + 1,
            "factory": factory,
            "machine": machine,
            "assigned_user_id": assigned_user_id,
            "task_type": task_type,
            "date": date_str,
            "status": "待執行"
        }
        self.tasks.append(task)
        self._save_tasks()
        return task

    def get_tasks_by_date(self, date_str):
        return [t for t in self.tasks if t["date"] == date_str]

    def update_task_status(self, task_id, status):
        for t in self.tasks:
            if t["id"] == task_id:
                t["status"] = status
                self._save_tasks()
                return True
        return False

    def add_equipment(self, factory: str, name: str, eq_type: str = ""):
        """新增設備，回傳設備物件"""
        factory = factory.strip()
        name = name.strip()
        if not factory or not name:
            return None

        # 建 ID（簡單用長度+1）
        eq_id = len(self.equipments) + 1
        eq = {
            "id": eq_id,
            "factory": factory,
            "name": name,
            "type": eq_type
        }
        self.equipments.append(eq)
        self._save_equipments()
        return eq

    def delete_equipment(self, eq_id: int):
        """用 id 刪除設備"""
        for i, e in enumerate(self.equipments):
            if e["id"] == eq_id:
                self.equipments.pop(i)
                self._save_equipments()
                return True
        return False

    def list_equipments(self, factory: str | None = None):
        if not factory:
            return list(self.equipments)
        return [e for e in self.equipments if e["factory"] == factory]


    # ===================== 儲存 =====================
    def _save_users(self):
        _save(USERS_FILE, self.users)

    def _save_tasks(self):
        _save(TASKS_FILE, self.tasks)

    def _save_factories(self):
        _save(FACTORIES_FILE, self.factories)
