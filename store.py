"""ฐานข้อมูลของระบบ (SQLite ไฟล์ data/app.db)
ตาราง: users (บัญชี) / activities (ตารางกิจกรรม + บันทึก) / activity_photos (รูปกิจกรรม ย่อขนาดและตัด EXIF แล้ว)
/ chat_messages (ประวัติแชต)
- รหัสผ่านเก็บเป็น hash (PBKDF2-SHA256 + salt แยกต่อคน) ไม่เก็บรหัสจริง
- ข้อมูลสุขภาพเก็บแค่ ใช่/ไม่ใช่ ว่าแพ้ฝุ่นหรือไม่ ผู้ใช้ลบข้อมูลและบัญชีเองได้ (PDPA)
ต่อยอดเป็น Azure SQL ได้โดยแก้เฉพาะไฟล์นี้ (ชื่อฟังก์ชันเดิม)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager

import pandas as pd

import config as C

ALLOWED_DOMAIN = "@kmitl.ac.th"
_ITER = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
    sensitive INTEGER DEFAULT 0, consent_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL, start TEXT NOT NULL, hours INTEGER NOT NULL, intensity TEXT NOT NULL,
    sensitive INTEGER DEFAULT 0, verdict_at_save TEXT, prepare TEXT DEFAULT '[]', checked TEXT DEFAULT '[]',
    ai_note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL, conv_id TEXT);
CREATE TABLE IF NOT EXISTS activity_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id TEXT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, data BLOB NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_act_user ON activities(user_id, start);
CREATE INDEX IF NOT EXISTS ix_chat_user ON chat_messages(user_id, id);
"""


@contextmanager
def _db():
    con = sqlite3.connect(C.DB_FILE)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


_READY = False


def init():
    global _READY
    if _READY and C.DB_FILE.exists():
        return
    with _db() as con:
        con.executescript(SCHEMA)
        cols = [r["name"] for r in con.execute("PRAGMA table_info(chat_messages)")]
        if "conv_id" not in cols:                      # ฐานข้อมูลรุ่นเก่า -> เพิ่มคอลัมน์ห้องแชต
            con.execute("ALTER TABLE chat_messages ADD COLUMN conv_id TEXT")
        con.execute("UPDATE chat_messages SET conv_id = 'c-old-' || user_id WHERE conv_id IS NULL")
        acols = [r["name"] for r in con.execute("PRAGMA table_info(activities)")]
        if "setting" not in acols:                     # outdoor / indoor
            con.execute("ALTER TABLE activities ADD COLUMN setting TEXT DEFAULT 'outdoor'")
        if "note" not in acols:                        # บันทึกเพิ่มเติมของผู้ใช้
            con.execute("ALTER TABLE activities ADD COLUMN note TEXT")
        if "reminded" not in acols:                    # ส่งอีเมลเตือนแล้วหรือยัง
            con.execute("ALTER TABLE activities ADD COLUMN reminded INTEGER DEFAULT 0")
        ucols = [r["name"] for r in con.execute("PRAGMA table_info(users)")]
        if "reset_hash" not in ucols:                  # รหัสยืนยันสำหรับลืมรหัสผ่าน (เก็บแบบแฮช)
            con.execute("ALTER TABLE users ADD COLUMN reset_hash TEXT")
            con.execute("ALTER TABLE users ADD COLUMN reset_exp TEXT")
            con.execute("ALTER TABLE users ADD COLUMN reset_tries INTEGER DEFAULT 0")
        if "daily_alert" not in ucols:                 # สรุปอากาศตอนเช้า (ส่งเฉพาะวันที่อากาศไม่ดี)
            con.execute("ALTER TABLE users ADD COLUMN daily_alert INTEGER DEFAULT 1")
            con.execute("ALTER TABLE users ADD COLUMN daily_sent TEXT")
        if "email_remind" not in ucols:                # ผู้ใช้เปิดรับอีเมลเตือนไหม
            con.execute("ALTER TABLE users ADD COLUMN email_remind INTEGER DEFAULT 1")
        con.execute("CREATE INDEX IF NOT EXISTS ix_chat_conv ON chat_messages(user_id, conv_id, id)")
    _READY = True


def _now() -> str:
    return C.now_local().strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================== บัญชีผู้ใช้
def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def _check(password: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


def register(email: str, password: str, sensitive: bool = False) -> dict:
    email = (email or "").strip().lower()
    if not email.endswith(ALLOWED_DOMAIN) or email.count("@") != 1 or len(email) <= len(ALLOWED_DOMAIN):
        raise ValueError(f"ใช้ได้เฉพาะอีเมลที่ลงท้ายด้วย {ALLOWED_DOMAIN}")
    if len(password or "") < 8:
        raise ValueError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")
    init()
    uid = uuid.uuid4().hex
    try:
        with _db() as con:
            con.execute("INSERT INTO users (id, email, pw_hash, sensitive, consent_at, created_at) VALUES (?,?,?,?,?,?)",
                        (uid, email, _hash(password), int(sensitive), _now(), _now()))
    except sqlite3.IntegrityError:
        raise ValueError("อีเมลนี้สมัครไว้แล้ว ลองเข้าสู่ระบบแทน")
    return get_user(uid)


def login(email: str, password: str) -> dict:
    init()
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    if not row or not _check(password or "", row["pw_hash"]):
        raise ValueError("อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    return get_user(row["id"])


RESET_MINUTES = 15


def start_reset(email: str) -> str | None:
    """สร้างรหัส 6 หลักสำหรับตั้งรหัสผ่านใหม่ คืนรหัส (ไว้ส่งอีเมล) หรือ None ถ้าไม่มีบัญชีนี้
    ในฐานข้อมูลเก็บเฉพาะแฮชของรหัส และหมดอายุใน 15 นาที"""
    import secrets
    init()
    email = (email or "").strip().lower()
    with _db() as con:
        row = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return None
        code = f"{secrets.randbelow(1_000_000):06d}"
        exp = (C.now_local() + pd.Timedelta(minutes=RESET_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("UPDATE users SET reset_hash = ?, reset_exp = ?, reset_tries = 0 WHERE id = ?",
                    (_hash(code), exp, row["id"]))
    return code


def finish_reset(email: str, code: str, new_password: str) -> dict:
    init()
    email = (email or "").strip().lower()
    if len(new_password or "") < 8:
        raise ValueError("รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    bad = ValueError("รหัสยืนยันไม่ถูกต้องหรือหมดอายุแล้ว กดส่งรหัสใหม่อีกครั้ง")
    if not row or not row["reset_hash"] or (row["reset_tries"] or 0) >= 5:
        raise bad
    if pd.Timestamp(row["reset_exp"]) < C.now_local():
        raise bad
    if not _check((code or "").strip(), row["reset_hash"]):
        with _db() as con:
            con.execute("UPDATE users SET reset_tries = reset_tries + 1 WHERE id = ?", (row["id"],))
        raise bad
    with _db() as con:
        con.execute("UPDATE users SET pw_hash = ?, reset_hash = NULL, reset_exp = NULL, reset_tries = 0 WHERE id = ?",
                    (_hash(new_password), row["id"]))
    return get_user(row["id"])


def get_user(uid: str) -> dict | None:
    init()
    with _db() as con:
        row = con.execute("SELECT id, email, sensitive, consent_at, created_at FROM users WHERE id = ?",
                          (uid,)).fetchone()
    return dict(row) | {"sensitive": bool(row["sensitive"])} if row else None


def set_sensitive(uid: str, value: bool):
    with _db() as con:
        con.execute("UPDATE users SET sensitive = ? WHERE id = ?", (int(value), uid))


def delete_user(uid: str):
    """ลบบัญชีพร้อมกิจกรรมและประวัติแชตทั้งหมด"""
    with _db() as con:
        con.execute("DELETE FROM users WHERE id = ?", (uid,))


def counts(uid: str) -> dict:
    with _db() as con:
        a = con.execute("SELECT COUNT(*) FROM activities WHERE user_id = ?", (uid,)).fetchone()[0]
        c = con.execute("SELECT COUNT(*) FROM chat_messages WHERE user_id = ?", (uid,)).fetchone()[0]
    return {"activities": a, "messages": c}


# ======================================================================== ตารางกิจกรรม
def _act(row) -> dict:
    d = dict(row)
    d["prepare"], d["checked"] = json.loads(d["prepare"] or "[]"), json.loads(d["checked"] or "[]")
    d["sensitive"] = bool(d["sensitive"])
    d["start_ts"] = pd.Timestamp(d["start"])
    d["end_ts"] = d["start_ts"] + pd.Timedelta(hours=d["hours"])
    d["indoor"] = d.get("setting") == "indoor"
    return d


def add_activity(uid: str, title: str, start, hours: int, intensity: str, sensitive: bool,
                 verdict: str, prepare: list[str], ai_note: str | None = None, setting: str = "outdoor") -> str | None:
    """คืน id ของกิจกรรมใหม่ หรือ None ถ้ามีกิจกรรมชื่อและเวลาเดียวกันอยู่แล้ว"""
    init()
    start_s = pd.Timestamp(start).strftime("%Y-%m-%d %H:%M")
    with _db() as con:                       # กันบันทึกซ้ำ (ชื่อและเวลาเดียวกัน)
        dup = con.execute("SELECT id FROM activities WHERE user_id = ? AND title = ? AND start = ?",
                          (uid, title.strip()[:60], start_s)).fetchone()
    if dup:
        return None
    aid = uuid.uuid4().hex[:12]
    with _db() as con:
        con.execute("INSERT INTO activities (id, user_id, title, start, hours, intensity, sensitive, "
                    "verdict_at_save, prepare, checked, ai_note, created_at, setting) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, uid, title.strip()[:60] or "กิจกรรมกลางแจ้ง", pd.Timestamp(start).strftime("%Y-%m-%d %H:%M"),
                     int(hours), intensity, int(sensitive), verdict, json.dumps(prepare, ensure_ascii=False),
                     "[]", ai_note, _now(), setting if setting in ("outdoor", "indoor") else "outdoor"))
    return aid


def list_activities(uid: str, include_past: bool = False) -> list[dict]:
    init()
    with _db() as con:
        rows = [_act(r) for r in con.execute("SELECT * FROM activities WHERE user_id = ? ORDER BY start", (uid,))]
    if include_past:
        return rows
    now = C.now_local()
    return [r for r in rows if r["end_ts"] > now]


def past_activities(uid: str, limit: int = 10) -> list[dict]:
    now = C.now_local()
    return [r for r in list_activities(uid, include_past=True) if r["end_ts"] <= now][-limit:][::-1]


def set_prepare(aid: str, uid: str, prepare: list[str], checked: list[str]):
    """แก้รายการสิ่งที่ต้องเตรียม (เพิ่ม/ลบ) พร้อมรายการที่ติ๊กแล้ว"""
    prepare = [p.strip()[:80] for p in prepare if p and p.strip()][:20]
    checked = [c for c in checked if c in prepare]
    with _db() as con:
        con.execute("UPDATE activities SET prepare = ?, checked = ? WHERE id = ? AND user_id = ?",
                    (json.dumps(prepare, ensure_ascii=False), json.dumps(checked, ensure_ascii=False), aid, uid))


def set_checked(aid: str, uid: str, checked: list[str]):
    with _db() as con:
        con.execute("UPDATE activities SET checked = ? WHERE id = ? AND user_id = ?",
                    (json.dumps(checked, ensure_ascii=False), aid, uid))


def move_activity(aid: str, uid: str, new_start, verdict: str, prepare: list[str]):
    with _db() as con:
        con.execute("UPDATE activities SET start = ?, verdict_at_save = ?, prepare = ?, checked = '[]', ai_note = NULL, reminded = 0 "
                    "WHERE id = ? AND user_id = ?",
                    (pd.Timestamp(new_start).strftime("%Y-%m-%d %H:%M"), verdict,
                     json.dumps(prepare, ensure_ascii=False), aid, uid))


def set_email_remind(uid: str, value: bool):
    init()
    with _db() as con:
        con.execute("UPDATE users SET email_remind = ? WHERE id = ?", (int(value), uid))


def get_email_remind(uid: str) -> bool:
    init()
    with _db() as con:
        r = con.execute("SELECT email_remind FROM users WHERE id = ?", (uid,)).fetchone()
    return bool(r and r["email_remind"])


def set_daily_alert(uid: str, value: bool):
    init()
    with _db() as con:
        con.execute("UPDATE users SET daily_alert = ? WHERE id = ?", (int(value), uid))


def get_daily_alert(uid: str) -> bool:
    init()
    with _db() as con:
        r = con.execute("SELECT daily_alert FROM users WHERE id = ?", (uid,)).fetchone()
    return bool(r and r["daily_alert"])


def daily_due(day: str) -> list[dict]:
    """ผู้ใช้ที่เปิดรับสรุปเช้าและยังไม่ได้เช็กของวันนี้"""
    init()
    with _db() as con:
        rows = con.execute("SELECT id, email, sensitive FROM users WHERE daily_alert = 1 "
                           "AND (daily_sent IS NULL OR daily_sent <> ?)", (day,)).fetchall()
    return [{**dict(r), "sensitive": bool(r["sensitive"])} for r in rows]


def mark_daily(uid: str, day: str):
    with _db() as con:
        con.execute("UPDATE users SET daily_sent = ? WHERE id = ?", (day, uid))


def due_reminders(minutes: int = 60) -> list[dict]:
    """กิจกรรมที่จะเริ่มภายใน `minutes` นาที ยังไม่เคยเตือน และเจ้าของเปิดรับอีเมล"""
    init()
    now = C.now_local()
    lo, hi = now.strftime("%Y-%m-%d %H:%M"), (now + pd.Timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
    with _db() as con:
        rows = con.execute(
            "SELECT a.*, u.email FROM activities a JOIN users u ON u.id = a.user_id "
            "WHERE a.reminded = 0 AND u.email_remind = 1 AND a.start > ? AND a.start <= ?", (lo, hi)).fetchall()
    return [_act(r) for r in rows]


def mark_reminded(aid: str):
    with _db() as con:
        con.execute("UPDATE activities SET reminded = 1 WHERE id = ?", (aid,))


def update_activity(aid: str, uid: str, title: str | None = None, note: str | None = None):
    """แก้ชื่อกิจกรรมและบันทึกเพิ่มเติม (เช่น ค่าใช้จ่าย ระยะที่วิ่ง)"""
    with _db() as con:
        if title is not None and title.strip():
            con.execute("UPDATE activities SET title = ? WHERE id = ? AND user_id = ?", (title.strip()[:60], aid, uid))
        if note is not None:
            con.execute("UPDATE activities SET note = ? WHERE id = ? AND user_id = ?", (note.strip()[:1000] or None, aid, uid))


MAX_PHOTOS = 3


def add_photo(aid: str, uid: str, raw: bytes) -> bool:
    """ย่อรูปให้ด้านยาวไม่เกิน 1280 px เป็น JPEG แล้วเก็บ (สูงสุด 3 รูปต่อกิจกรรม) คืน False ถ้าเต็มแล้ว"""
    import io
    from PIL import Image, ImageOps
    with _db() as con:
        n = con.execute("SELECT COUNT(*) FROM activity_photos WHERE activity_id = ? AND user_id = ?", (aid, uid)).fetchone()[0]
        own = con.execute("SELECT 1 FROM activities WHERE id = ? AND user_id = ?", (aid, uid)).fetchone()
    if n >= MAX_PHOTOS or not own:
        return False
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")   # ตัดข้อมูล EXIF (เช่น พิกัด GPS) ทิ้ง
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82, optimize=True)
    with _db() as con:
        con.execute("INSERT INTO activity_photos (activity_id, user_id, data, created_at) VALUES (?,?,?,?)",
                    (aid, uid, buf.getvalue(), _now()))
    return True


def list_photos(aid: str, uid: str) -> list[dict]:
    with _db() as con:
        return [dict(r) for r in con.execute(
            "SELECT id, data FROM activity_photos WHERE activity_id = ? AND user_id = ? ORDER BY id", (aid, uid))]


def photo_counts(uid: str) -> dict:
    with _db() as con:
        return {r[0]: r[1] for r in con.execute(
            "SELECT activity_id, COUNT(*) FROM activity_photos WHERE user_id = ? GROUP BY activity_id", (uid,))}


def delete_photo(pid: int, uid: str):
    with _db() as con:
        con.execute("DELETE FROM activity_photos WHERE id = ? AND user_id = ?", (pid, uid))


def delete_activity(aid: str, uid: str):
    with _db() as con:
        con.execute("DELETE FROM activities WHERE id = ? AND user_id = ?", (aid, uid))


# ======================================================================== ประวัติแชต
def new_conv_id() -> str:
    return "c-" + uuid.uuid4().hex[:12]


def add_message(uid: str, role: str, content: str, conv_id: str):
    init()
    with _db() as con:
        con.execute("INSERT INTO chat_messages (user_id, role, content, created_at, conv_id) VALUES (?,?,?,?,?)",
                    (uid, role, content, _now(), conv_id))


def list_conversations(uid: str, limit: int = 30) -> list[dict]:
    """ห้องแชตของผู้ใช้ เรียงจากล่าสุด: conv_id, title (คำถามแรก), last_at, n"""
    init()
    with _db() as con:
        rows = con.execute("""
            SELECT conv_id, MAX(created_at) AS last_at, COUNT(*) AS n,
                   (SELECT content FROM chat_messages m2 WHERE m2.user_id = m.user_id AND m2.conv_id = m.conv_id
                    AND m2.role = 'user' ORDER BY m2.id LIMIT 1) AS title
            FROM chat_messages m WHERE user_id = ? GROUP BY conv_id ORDER BY MAX(id) DESC LIMIT ?""",
                           (uid, limit)).fetchall()
    return [dict(r) for r in rows]


def list_messages(uid: str, conv_id: str | None = None, limit: int = 60) -> list[dict]:
    init()
    with _db() as con:
        if conv_id:
            rows = con.execute("SELECT role, content, created_at FROM chat_messages WHERE user_id = ? AND conv_id = ? "
                               "ORDER BY id DESC LIMIT ?", (uid, conv_id, limit)).fetchall()
        else:
            rows = con.execute("SELECT role, content, created_at FROM chat_messages WHERE user_id = ? "
                               "ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    return [dict(r) for r in rows][::-1]


def delete_conversation(uid: str, conv_id: str):
    with _db() as con:
        con.execute("DELETE FROM chat_messages WHERE user_id = ? AND conv_id = ?", (uid, conv_id))


def clear_messages(uid: str):
    with _db() as con:
        con.execute("DELETE FROM chat_messages WHERE user_id = ?", (uid,))
