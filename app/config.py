"""配置加载：合并 secrets.json 与默认值。"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
SECRETS_FILE = os.path.join(CONFIG_DIR, "secrets.json")
SESSION_FILE = os.path.join(ROOT, "data", "session.json")

DEFAULTS = {
    "username": "",
    "password": "",
    "semester": "",
    "poll_seconds": 600,
    "access_code": "",
    "port": 8787,
    "bind": "127.0.0.1",
    "max_week": 30,
    "pattern": "student-login",
    "entry": "",              # 可选：覆盖默认 CAS 入口
    "auto_login": True,
    "retry_minutes": 15,      # 会话失效后的重试间隔
    "term_start": "",         # 第 1 周的星期一，格式 YYYY-MM-DD；留空则由课表推断
    "section_times": [],      # 可选：覆盖默认节次时间表

    # ---- 安全防护 ----
    "rate_per_minute": 180,   # 单 IP 每分钟请求上限
    "rate_hard_limit": 600,   # 单 IP 每分钟硬上限
    "auth_max_fails": 8,      # 口令错误多少次后临时封禁
    "auth_ban_minutes": 15,   # 临时封禁时长（分钟）

    # ---- 管理后台独立门禁 ----
    # 管理后台（/admin 和 /api/admin/*）用这个口令，和给同学的 access_code 分开。
    # 这样同学就算知道了班级口令，也进不了管理后台。
    # 留空 = 退回用 access_code（不会把自己锁在外面）。
    # 页面入口不在网站任何地方显示，只能手动输网址。
    "admin_password": "",
}


class Config(dict):
    @property
    def root(self):
        return ROOT

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {k: v for k, v in self.items() if not k.startswith("_")}
        with open(SECRETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def update_file(updates, path=None):
    """只改文件里指定的几个键，保留其它内容（含 _ 开头的注释）。"""
    p = path or SECRETS_FILE
    raw = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    raw.update(updates)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return raw


def load(path=None):
    cfg = Config(DEFAULTS)
    p = path or SECRETS_FILE
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as f:
            raw = json.load(f)
        # 忽略以下划线开头的说明字段
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            cfg[k] = v
    # 环境变量可覆盖（便于在 iPhone 上不落盘密码）
    if os.environ.get("KT_USERNAME"):
        cfg["username"] = os.environ["KT_USERNAME"]
    if os.environ.get("KT_PASSWORD"):
        cfg["password"] = os.environ["KT_PASSWORD"]
    if os.environ.get("KT_ACCESS_CODE"):
        cfg["access_code"] = os.environ["KT_ACCESS_CODE"]
    return cfg
