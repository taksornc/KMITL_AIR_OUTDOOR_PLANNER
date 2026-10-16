"""ส่วนที่ทุกหน้าใช้ร่วมกัน: ธีม ไอคอน ข้อมูล ผู้ใช้ และชิ้นส่วนหน้าจอ"""

import html
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as C
import data_sources as DS
import forecast as F
import store

_ST_VER = tuple(int(x) for x in st.__version__.split(".")[:2])
FULL = {"width": "stretch"} if _ST_VER >= (1, 50) else {"use_container_width": True}

DAYS_FULL = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
DAYS_SHORT = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]
MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
ORANGE = "#E35205"
RAIN_BLUE = "#2F6FDB"
GREY = "#6B7685"
STATUS_COLOR = {"good": "#1E9E5A", "mid": "#C99A06", "caution": "#C99A06", "bad": "#D64545"}
PLOT_FONT = dict(family="Anuphan, sans-serif", size=13, color="#17202B")

# ---------------------------------------------------------------- ไอคอนเส้น (ใช้ชุดเดียวทั้งเว็บ)
_SVG = {
    "dust": '<circle cx="6" cy="7" r="1.6"/><circle cx="12" cy="5" r="1.2"/><circle cx="17.5" cy="8" r="1.8"/>'
            '<circle cx="8.5" cy="13" r="1.3"/><circle cx="14.5" cy="13.5" r="1.7"/><circle cx="5.5" cy="18.5" r="1.2"/>'
            '<circle cx="11.5" cy="19" r="1.6"/><circle cx="18" cy="18" r="1.2"/>',
    "rain": '<path d="M12 3.5c3.2 4.2 5.5 7.4 5.5 10.2a5.5 5.5 0 0 1-11 0c0-2.8 2.3-6 5.5-10.2z"/>',
    "heat": '<path d="M10 4.5a2 2 0 0 1 4 0v9.2a4 4 0 1 1-4 0z"/><path d="M12 10v6"/>',
    "wind": '<path d="M3 9h11a3 3 0 1 0-3-3"/><path d="M3 14h15a3 3 0 1 1-3 3"/>',
    "humid": '<path d="M7 10c1.7 2.2 3 3.9 3 5.4a3 3 0 0 1-6 0c0-1.5 1.3-3.2 3-5.4z"/>'
             '<path d="M16 4c1.7 2.2 3 3.9 3 5.4a3 3 0 0 1-6 0c0-1.5 1.3-3.2 3-5.4z"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "pin": '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.2"/>',
}
_FILLED = {"dust", "rain"}


def icon(kind: str, color: str = "currentColor", size: int = 18) -> str:
    fill = color if kind in _FILLED else "none"
    stroke = "none" if kind == "dust" else color
    return (f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_SVG[kind]}</svg>')


# ====================================================================== ข้อความ
def secret(name, default=None):
    if os.getenv(name):
        return os.getenv(name)
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def gemini():
    """(api_key, model) หรือ (None, None) ถ้ายังไม่ได้ตั้งค่า"""
    key = secret("GEMINI_API_KEY")
    return (key, secret("GEMINI_MODEL", "gemini-2.5-flash")) if key else (None, None)


def day_name(d, short=False) -> str:
    d = pd.Timestamp(d).date()
    diff = (d - C.now_local().date()).days
    rel = {0: "วันนี้", 1: "พรุ่งนี้", 2: "มะรืนนี้"}.get(diff)
    base = f"{DAYS_SHORT[d.weekday()]} {d.day} {MONTHS[d.month]}"
    if short:
        return rel or base
    return f"{rel} ({base})" if rel else base


def until_text(start: pd.Timestamp, end: pd.Timestamp) -> str:
    now = C.now_local()
    if start <= now < end:
        return "กำลังทำอยู่"
    mins = (start - now).total_seconds() / 60
    if mins < 60:
        return f"อีก {max(1, int(mins))} นาที"
    if mins < 48 * 60:
        return f"อีก {int(mins // 60)} ชม."
    return f"อีก {int(mins // 1440)} วัน"


def esc(x) -> str:
    return html.escape(str(x))


# ====================================================================== ผู้ใช้
def user():
    return st.session_state.get("user")


def is_sensitive() -> bool:
    u = user()
    return bool(u["sensitive"]) if u else bool(st.session_state.get("sensitive", False))


def set_sensitive(value: bool):
    st.session_state.sensitive = bool(value)
    u = user()
    if u and u["sensitive"] != bool(value):
        store.set_sensitive(u["id"], value)
        u["sensitive"] = bool(value)


def login_box(reason: str, key: str):
    """ฟอร์มเข้าสู่ระบบ / สมัครสมาชิก แบบฝังในหน้า"""
    st.markdown(f'<div class="panel"><b>{esc(reason)}</b><div class="note" style="margin-top:4px">'
                f'ใช้อีเมล {store.ALLOWED_DOMAIN} ของคุณ ข้อมูลเก็บแยกตามบัญชี และลบเองได้ทุกเมื่อ</div></div>',
                unsafe_allow_html=True)
    t1, t2 = st.tabs(["เข้าสู่ระบบ", "สมัครใช้งาน"])
    with t1, st.form(f"login_{key}"):
        email = st.text_input("อีเมล", placeholder="รหัสนักศึกษา@kmitl.ac.th")
        pw = st.text_input("รหัสผ่าน", type="password")
        if st.form_submit_button("เข้าสู่ระบบ", type="primary"):
            try:
                st.session_state.user = store.login(email, pw)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    with t1, st.expander("ลืมรหัสผ่าน"):
        _forgot_box(key)
    with t2, st.form(f"register_{key}"):
        email = st.text_input("อีเมล", placeholder="รหัสนักศึกษา@kmitl.ac.th", key=f"re_{key}")
        pw = st.text_input("ตั้งรหัสผ่าน (อย่างน้อย 8 ตัว)", type="password", key=f"rp_{key}")
        sens = st.checkbox("ฉันแพ้ฝุ่นหรือเป็นหอบหืด (ใช้ปรับคำแนะนำให้เข้มขึ้น)", value=is_sensitive())
        ok = st.checkbox("ยินยอมให้ระบบเก็บอีเมล ตารางกิจกรรม และประวัติแชต เพื่อใช้ในระบบนี้เท่านั้น "
                         "(ลบได้ทุกเมื่อในหน้าบัญชี)")
        if st.form_submit_button("สมัครและเข้าสู่ระบบ", type="primary"):
            if not ok:
                st.error("ต้องยินยอมการเก็บข้อมูลก่อนสมัคร")
            else:
                try:
                    st.session_state.user = store.register(email, pw, sens)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def _forgot_box(key: str):
    """ลืมรหัสผ่าน: ส่งรหัส 6 หลักไปที่อีเมล สจล. แล้วตั้งรหัสผ่านใหม่"""
    import planner
    if not planner.smtp_ready():
        st.caption("ระบบยังไม่ได้ตั้งค่าการส่งอีเมล ติดต่อผู้ดูแลระบบเพื่อรีเซ็ตรหัสผ่าน")
        return
    sk = f"reset_email_{key}"
    with st.form(f"forgot1_{key}"):
        email = st.text_input("อีเมลที่ใช้สมัคร", placeholder="รหัสนักศึกษา@kmitl.ac.th", key=f"fe_{key}")
        if st.form_submit_button("ส่งรหัสยืนยันไปที่อีเมล"):
            email = (email or "").strip().lower()
            try:
                code = store.start_reset(email)
                if code:
                    planner.send_reset_code(email, code)
                st.session_state[sk] = email
                # ตอบเหมือนกันทุกกรณี ไม่บอกว่าอีเมลนี้มีบัญชีหรือไม่
                st.success("ถ้าอีเมลนี้มีบัญชีอยู่ ระบบส่งรหัส 6 หลักไปแล้ว (ใช้ได้ 15 นาที ถ้าไม่เห็นให้ดูใน Spam)")
            except Exception as e:
                st.error(f"ส่งอีเมลไม่สำเร็จ: {e}")
    if st.session_state.get(sk):
        with st.form(f"forgot2_{key}"):
            code = st.text_input("รหัสยืนยัน 6 หลัก", max_chars=6, key=f"fc_{key}")
            pw1 = st.text_input("รหัสผ่านใหม่ (อย่างน้อย 8 ตัว)", type="password", key=f"fp1_{key}")
            pw2 = st.text_input("ยืนยันรหัสผ่านใหม่", type="password", key=f"fp2_{key}")
            if st.form_submit_button("ตั้งรหัสผ่านใหม่และเข้าสู่ระบบ", type="primary"):
                if pw1 != pw2:
                    st.error("รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน")
                else:
                    try:
                        st.session_state.user = store.finish_reset(st.session_state[sk], code, pw1)
                        st.session_state.pop(sk, None)
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))


# ====================================================================== ข้อมูล (cache อยู่ใน data_sources/forecast แล้ว)
def current():
    try:
        return DS.fetch_current_pm(), None
    except Exception as e:
        return None, str(e)


def forecast():
    try:
        return F.get_forecast(), None
    except F.ModelNotTrained:
        return None, "ยังไม่มีโมเดลพยากรณ์ ให้รันคำสั่ง python train.py ก่อน แล้วเปิดเว็บใหม่"
    except Exception as e:
        return None, f"ดึงข้อมูลพยากรณ์ไม่สำเร็จ ({e}) ลองกด 'ดึงข้อมูลล่าสุด' ในแถบด้านข้าง"


def weather():
    try:
        return F.current_weather(), None
    except Exception as e:
        return None, str(e)


def refresh_all():
    DS.fetch_recent_and_forecast.cache_clear()
    DS.fetch_air4thai_nearest.cache_clear()
    DS.fetch_smartpole.cache_clear()
    F.get_forecast.cache_clear()
    import planner
    for fn in (planner.evaluate, planner.better_times, planner.best_on_same_day):
        fn.cache_clear()


# ====================================================================== ธีม
def inject_css():
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Anuphan:wght@400;500;600;700&display=swap');
:root {{ --ink:#17202B; --muted:#5B6675; --line:#E4E8EE; --soft:#F5F7FA; --brand:{ORANGE}; --rain:{RAIN_BLUE}; }}
html, body, .stApp, .stMarkdown, button, input, textarea, select, label, [data-testid="stWidgetLabel"],
[data-baseweb="tab"], .stNavigation a, [data-testid="stHeader"] a {{ font-family: 'Anuphan', sans-serif !important; }}
.stApp {{ color: var(--ink); }}
.block-container {{ max-width: 1080px; }}
h1, h2, h3 {{ font-family: 'Anuphan', sans-serif !important; color: var(--ink); }}
p, li {{ line-height: 1.65; }}
.ic {{ display:inline-block; vertical-align: -3px; flex-shrink: 0; }}

.brand {{ display:flex; align-items:baseline; gap:12px; flex-wrap: wrap; margin: 2px 0 18px; }}
.brand b {{ font-size: 1.3rem; font-weight: 700; color: var(--brand); white-space: nowrap; }}
.brand span {{ color: var(--muted); font-size: .95rem; }}

.verdict {{ font-size: clamp(1.6rem, 3.4vw, 2.4rem); font-weight: 700; line-height: 1.25; margin: 6px 0 12px; max-width: 28ch; }}
.reading {{ display:flex; align-items:baseline; gap:10px; flex-wrap: wrap; }}
.reading .num {{ font-size: 3.4rem; font-weight: 700; line-height: 1; }}
.reading .unit {{ color: var(--muted); font-size: 1rem; }}
.chip {{ display:inline-block; padding: 2px 11px; border-radius: 999px; color:#fff; font-weight:600; font-size:.88rem; }}
.tag {{ display:inline-flex; align-items:center; gap:5px; padding: 3px 10px; border-radius: 999px;
  background: var(--soft); border: 1px solid var(--line); font-size: .86rem; color: var(--ink); margin: 0 6px 6px 0; }}
.note {{ color: var(--muted); font-size: .86rem; margin-top: 8px; }}
.section-title {{ font-size: 1.15rem; font-weight: 650; margin: 28px 0 10px; }}

.ruler {{ margin: 16px 0 4px; max-width: 640px; }}
.ruler .bar {{ display:grid; grid-template-columns: repeat(5, 1fr); height: 10px; border-radius: 999px; overflow:hidden; }}
.ruler .bar i {{ display:block; }}
.ruler .track {{ position: relative; height: 0; }}
.ruler .pin {{ position:absolute; top: -20px; width: 4px; height: 28px; border-radius: 3px; background: var(--ink);
  transform: translateX(-2px); box-shadow: 0 0 0 3px #fff; }}
.ruler .labels {{ display:grid; grid-template-columns: repeat(5, 1fr); font-size: .78rem; color: var(--muted); margin-top: 6px; }}
.ruler .labels span.on {{ color: var(--ink); font-weight: 700; }}

.metrics {{ display:grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 18px; }}
.metric {{ border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; background:#fff; }}
.metric .k {{ display:flex; align-items:center; gap:6px; color: var(--muted); font-size: .86rem; }}
.metric .v {{ font-size: 1.45rem; font-weight: 650; line-height: 1.3; margin-top: 2px; }}
.metric .s {{ font-size: .86rem; color: var(--muted); }}
.dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align: 1px; }}

.strip {{ display:grid; grid-template-columns: repeat(24, 1fr); gap: 3px; align-items: end; height: 86px; }}
.strip i {{ display:block; border-radius: 4px 4px 2px 2px; min-height: 6px; }}
.strip i.best {{ outline: 2px solid var(--ink); outline-offset: 1px; }}
.rainrow {{ display:grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin-top: 4px; }}
.rainrow i {{ display:block; height: 6px; border-radius: 2px; background: var(--rain); }}
.strip-x {{ display:grid; grid-template-columns: repeat(8, 1fr); font-size: .76rem; color: var(--muted); margin-top: 4px; }}
.legend {{ display:flex; gap: 14px; flex-wrap: wrap; font-size: .82rem; color: var(--muted); margin-top: 6px; }}
.legend span {{ display:inline-flex; align-items:center; gap:5px; }}

.panel {{ border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; background:#fff; }}
.advice {{ border-left: 4px solid var(--brand); background: var(--soft); border-radius: 0 12px 12px 0; padding: 14px 18px; margin-bottom: 14px; }}
.advice .who {{ font-weight: 650; margin-bottom: 4px; }}
.reason {{ display:grid; grid-template-columns: 170px 1fr; gap: 4px 14px; padding: 11px 0; border-bottom: 1px solid var(--line); }}
.reason:last-child {{ border-bottom: none; }}
.reason .t {{ font-weight: 650; display:flex; align-items:center; gap:7px; }}
.reason .m {{ color: var(--muted); }}

.vcard {{ border: 1px solid var(--line); border-radius: 16px; background:#fff; overflow:hidden; }}
.vcard .top {{ padding: 16px 20px 14px; border-left: 8px solid; }}
.vcard .what {{ color: var(--muted); font-size: .92rem; }}
.vcard .big {{ font-size: clamp(1.5rem, 3vw, 2rem); font-weight: 700; line-height: 1.25; margin: 4px 0 2px; }}
.vcard .why {{ font-size: 1.02rem; }}
.vcard .facts3 {{ display:flex; gap: 18px; flex-wrap: wrap; padding: 12px 20px; border-top: 1px solid var(--line); background: var(--soft); }}
.vcard .facts3 span {{ display:inline-flex; align-items:center; gap:6px; font-size: .95rem; }}

.days {{ display:flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }}
.day {{ flex: 1 0 100px; border: 1px solid var(--line); border-radius: 12px; padding: 10px 8px; text-align:center; background:#fff; }}
.day .d {{ font-size: .84rem; color: var(--muted); }}
.day .n {{ font-size: 1.5rem; font-weight: 700; line-height: 1.2; }}
.day .l {{ font-size: .8rem; }}
.day .r {{ font-size: .8rem; color: var(--muted); display:flex; align-items:center; justify-content:center; gap:4px; }}
.finding {{ padding: 12px 0; border-bottom: 1px solid var(--line); }}
.finding:last-child {{ border-bottom: none; }}
.finding .meta {{ color: var(--muted); font-size: .82rem; margin-top: 2px; }}
.score {{ border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; background:#fff; height: 100%; }}
.score .n {{ font-size: 2rem; font-weight: 700; line-height: 1.1; }}
.score .t {{ font-weight: 650; margin-top: 2px; }}
.score .d {{ color: var(--muted); font-size: .86rem; margin-top: 4px; }}

.acard-head {{ display:flex; justify-content: space-between; gap: 10px; align-items: baseline; flex-wrap: wrap; }}
.acard-head .when {{ font-weight: 650; }}
.acard-head .cd {{ color: var(--muted); font-size: .88rem; }}
.acard-title {{ font-size: 1.3rem; font-weight: 700; margin: 2px 0 6px; }}
.warnbar {{ background:#FFF4E5; border:1px solid #F5C77E; color:#8A4B00; border-radius: 10px; padding: 8px 12px; margin: 6px 0 4px; font-size: .92rem; }}
.stButton > button[kind^="primary"], .stFormSubmitButton > button[kind^="primary"] {{ background: var(--brand); border-color: var(--brand); }}
/* ช่องพิมพ์แชต: ลอยอยู่ในกรอบเดียวกับเนื้อหา มีขอบมนและเงา และไล่สีจางด้านบนไม่ให้ทับข้อความ */
[data-testid="stBottom"] {{ max-width: 1080px; margin: 0 auto; background: transparent !important; }}
[data-testid="stBottom"] > div {{ position: relative; background: rgba(255,255,255,.97) !important; border-radius: 0 0 26px 26px; }}
.stApp:has([data-testid="stChatInput"]) .block-container {{ border-radius: 26px 26px 0 0 !important; margin-bottom: 0 !important;
  box-shadow: 0 -2px 30px rgba(15,23,42,.18) !important; min-height: calc(100vh - 112px); }}
.stApp:has([data-testid="stChatInput"]) [data-testid="stMain"] {{ display: flex; flex-direction: column; }}
.stApp:has([data-testid="stChatInput"]) [data-testid="stMainBlockContainer"] {{ flex: 1 0 auto; }}

/* ความลื่น: ไม่ให้หน้าจาง/กระพริบตอนระบบประมวลผล, ทรานซิชันนุ่ม, เลื่อนนุ่ม */
html {{ scroll-behavior: smooth; }}
[data-stale="true"], .stale-element, [data-testid="stElementContainer"][data-stale="true"] {{ opacity: 1 !important; filter: none !important; transition: none !important; }}
[data-testid="stStatusWidget"] {{ visibility: hidden; }}
.stButton > button, .stFormSubmitButton > button, .stLinkButton a, [data-testid="stExpander"] summary,
.metric, .panel, .day, .tag, .score, [data-testid="stChatInput"], .stNavigation a, [data-testid="stHeader"] a {{
  transition: background-color .18s ease, border-color .18s ease, box-shadow .2s ease, transform .18s ease, color .18s ease; }}
.stButton > button:hover, .stFormSubmitButton > button:hover {{ transform: translateY(-1px); box-shadow: 0 4px 14px rgba(15,23,42,.10); }}
.stButton > button:active, .stFormSubmitButton > button:active {{ transform: translateY(0) scale(.98); box-shadow: none; }}
.day:hover, .metric:hover {{ box-shadow: 0 4px 16px rgba(15,23,42,.07); }}
[data-testid="stMainBlockContainer"] > div {{ animation: pagein .28s ease-out; }}
@keyframes pagein {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
[data-testid="stChatMessage"] {{ animation: pagein .25s ease-out; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; scroll-behavior: auto !important; }} }}
[data-testid="stBottomBlockContainer"] {{ max-width: 860px; padding: 8px 2rem 22px !important; margin: 0 auto; }}
[data-testid="stChatInput"] {{ background: #fff !important; border: 1px solid #DCE1E8 !important; border-radius: 22px !important;
  box-shadow: 0 6px 24px rgba(15,23,42,.10), 0 1px 3px rgba(15,23,42,.06); padding: 6px 8px 6px 12px; }}
[data-testid="stChatInput"]:focus-within {{ border-color: #C9CFD8 !important; box-shadow: 0 8px 28px rgba(15,23,42,.14); }}
[data-testid="stChatInput"] > div, [data-testid="stChatInput"] textarea {{ background: transparent !important; border: none !important; }}
[data-testid="stChatInput"] textarea {{ font-size: 1rem; }}
[data-testid="stChatInputSubmitButton"] {{ border-radius: 50% !important; background: var(--brand) !important; color: #fff !important; }}
[data-testid="stChatInputSubmitButton"]:disabled {{ background: #E9ECF1 !important; color: #9AA3AE !important; }}
@media (max-width: 640px) {{
  [data-testid="stBottom"] > div {{ border-radius: 0; }}
  [data-testid="stBottomBlockContainer"] {{ padding: 18px 1rem 14px !important; }}
  .reading .num {{ font-size: 2.8rem; }}
  .reason {{ grid-template-columns: 1fr; }}
  .strip, .rainrow {{ gap: 2px; }}
  .strip {{ height: 66px; }}
  .metrics {{ grid-template-columns: repeat(2, 1fr); }}
  .metric .v {{ font-size: 1.25rem; }}
}}
</style>""", unsafe_allow_html=True)


def theme_css():
    """ชุดตกแต่งหลัก (ขาว/ส้ม กระจกฝ้า ไล่สี) — เรียกหลังพื้นหลังสภาพอากาศ เพื่อให้ทับค่าเดิม"""
    st.markdown("""
<style>
:root { --g1:#FF8A3D; --g2:#E35205; --g3:#FFB066; --glass:rgba(255,255,255,.90); --glass-b:rgba(255,255,255,.55);
        --grad: linear-gradient(135deg, #FFB066 0%, #FF8A3D 45%, #E35205 100%); }

/* แถบเมนูบน: กระจกฝ้า + ปุ่มเมนูทรงแคปซูล */
[data-testid="stHeader"] { background: rgba(255,255,255,.72) !important; backdrop-filter: blur(16px) saturate(1.4);
  -webkit-backdrop-filter: blur(16px) saturate(1.4); box-shadow: 0 1px 0 rgba(255,255,255,.6), 0 6px 24px rgba(15,23,42,.08) !important; }
[data-testid="stHeader"] a, .stNavigation a { border-radius: 999px !important; padding: 4px 12px !important; }
[data-testid="stHeader"] a[aria-current="page"], [data-testid="stHeader"] a[aria-selected="true"] {
  background: linear-gradient(135deg, #FFE6D3, #FFD2B0) !important; color: #B53F00 !important; font-weight: 700 !important;
  box-shadow: inset 0 0 0 1px rgba(227,82,5,.18); }
[data-testid="stHeader"] a:hover { background: rgba(255,138,61,.10) !important; }

/* กรอบเนื้อหา: กระจกขาว ขอบสว่าง */
.block-container { background: var(--glass) !important; border: 1px solid var(--glass-b);
  box-shadow: 0 20px 60px rgba(15,23,42,.22), inset 0 1px 0 rgba(255,255,255,.7) !important; border-radius: 28px !important; }
[data-testid="stBottom"] > div { background: var(--glass) !important; backdrop-filter: blur(22px) saturate(1.5);
  -webkit-backdrop-filter: blur(22px) saturate(1.5); border: 1px solid var(--glass-b); border-top: none; border-radius: 0 0 28px 28px !important; }

/* ชื่อแอปไล่สี */
.brand b { background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent !important; }

/* ปุ่ม: หลัก = ไล่สีส้ม, รอง = กระจกขาว ทรงมน */
.stButton > button, .stFormSubmitButton > button, [data-testid="stPopover"] button {
  border-radius: 14px !important; border: 1px solid rgba(23,32,43,.10) !important; background: rgba(255,255,255,.85) !important; }
.stButton > button[kind^="primary"], .stFormSubmitButton > button[kind^="primary"] {
  background: var(--grad) !important; border: none !important; color: #fff !important; font-weight: 600;
  box-shadow: 0 6px 18px rgba(227,82,5,.28) !important; }
.stButton > button[kind^="primary"]:hover, .stFormSubmitButton > button[kind^="primary"]:hover {
  box-shadow: 0 10px 24px rgba(227,82,5,.36) !important; filter: brightness(1.04); }
.stButton > button:not([kind="primary"]):hover { border-color: rgba(227,82,5,.35) !important; color: #B53F00 !important; }

/* ช่องกรอก ตัวเลือก แท็บ */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border-radius: 14px !important; }
[data-baseweb="tab-list"] { gap: 6px; background: rgba(23,32,43,.05); padding: 4px; border-radius: 999px; width: fit-content; }
[data-baseweb="tab"] { border-radius: 999px !important; padding: 6px 16px !important; }
[data-baseweb="tab"][aria-selected="true"] { background: #fff !important; box-shadow: 0 2px 8px rgba(15,23,42,.10); }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none !important; }
[data-testid="stExpander"] details { border-radius: 16px !important; border: 1px solid rgba(23,32,43,.08) !important;
  background: rgba(255,255,255,.7); }

/* การ์ดต่าง ๆ: ขาวไล่ส้มอ่อน มนขึ้น */
.panel, .metric, .day, .score, .vcard {
  border-radius: 18px !important; border: 1px solid rgba(23,32,43,.07) !important;
  background: linear-gradient(180deg, #FFFFFF 0%, #FFFBF7 100%) !important; box-shadow: 0 2px 10px rgba(15,23,42,.04); }
.metric .v, .day .n { letter-spacing: -.01em; }
.chip { box-shadow: 0 2px 6px rgba(0,0,0,.10); }
.tag { background: rgba(255,255,255,.8); border-color: rgba(23,32,43,.08); }
.advice { border-left: none !important; border-radius: 16px !important; position: relative;
  background: linear-gradient(135deg, #FFF3EA, #FFFAF5) !important; box-shadow: inset 0 0 0 1px rgba(227,82,5,.12); }
.advice::before { content: ""; position: absolute; left: 0; top: 12px; bottom: 12px; width: 4px; border-radius: 4px; background: var(--grad); }
.section-title { display: flex; align-items: center; gap: 8px; }
.section-title::before { content: ""; width: 6px; height: 18px; border-radius: 4px; background: var(--grad); }

/* ช่องพิมพ์แชต: แคปซูลกระจก ขอบไล่สีส้ม ปุ่มส่งวงกลมไล่สี */
[data-testid="stChatInput"] { border: 1.5px solid transparent !important; border-radius: 28px !important;
  background: linear-gradient(#ffffff, #ffffff) padding-box, linear-gradient(135deg, #FFC79A, #FF8A3D 50%, #E35205) border-box !important;
  box-shadow: 0 10px 30px rgba(227,82,5,.14), 0 2px 6px rgba(15,23,42,.06) !important; }
[data-testid="stChatInput"]:focus-within { box-shadow: 0 12px 36px rgba(227,82,5,.24), 0 0 0 4px rgba(255,138,61,.12) !important; }
[data-testid="stChatInputSubmitButton"] { background: var(--grad) !important; color: #fff !important; border-radius: 50% !important;
  box-shadow: 0 4px 12px rgba(227,82,5,.35); }
[data-testid="stChatInputSubmitButton"]:disabled { background: #F1F3F6 !important; color: #A7AFBA !important; box-shadow: none; }
[data-testid="stChatMessage"] { border-radius: 18px; }

/* แถบด้านข้าง: เมนูกระจกเข้มแบบแผนที่อากาศ */
[data-testid="stSidebar"] { background: rgba(20,28,44,.78) !important; backdrop-filter: blur(18px) saturate(1.3);
  -webkit-backdrop-filter: blur(18px) saturate(1.3); border-right: 1px solid rgba(255,255,255,.08); }
[data-testid="stSidebar"] * { color: #EEF2F7 !important; }
[data-testid="stSidebar"] .stButton > button { background: rgba(255,255,255,.08) !important; border: 1px solid rgba(255,255,255,.10) !important;
  border-radius: 999px !important; }
[data-testid="stSidebar"] .stButton > button:hover { background: rgba(255,255,255,.16) !important; }
[data-testid="stSidebar"] [data-baseweb="select"] > div { border-radius: 999px !important; }
[data-testid="stSidebar"] [data-baseweb="select"] > div { background: #FFFFFF !important; }
[data-testid="stSidebar"] [data-baseweb="select"] *, [data-testid="stSidebar"] [data-baseweb="select"] input {
  color: #17202B !important; -webkit-text-fill-color: #17202B !important; opacity: 1 !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] input, [data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"],
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] ~ div * {
  color: #17202B !important; -webkit-text-fill-color: #17202B !important; opacity: 1 !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] svg { color: #5B6675 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.10) !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] small { color: #A9B3C2 !important; }
[data-testid="stSidebarUserContent"] p strong { letter-spacing: .02em; color: #FFB066 !important; }

@media (max-width: 640px) { .block-container { border-radius: 0 !important; } }
</style>""", unsafe_allow_html=True)


def brand_header(subtitle: str):
    st.markdown(f'<div class="brand"><b>{C.APP_NAME}</b><span>{esc(subtitle)}</span></div>', unsafe_allow_html=True)


# ====================================================================== ชิ้นส่วนหน้าจอ
def chip(text, color):
    return f'<span class="chip" style="background:{color}">{esc(text)}</span>'


def tag(text, kind=None, color=GREY):
    return f'<span class="tag">{icon(kind, color, 15) if kind else ""}{esc(text)}</span>'


def dot(color):
    return f'<span class="dot" style="background:{color}"></span>'


def metric(kind, label, value, sub="", color=GREY) -> str:
    return (f'<div class="metric"><div class="k">{icon(kind, color, 16)}{esc(label)}</div>'
            f'<div class="v">{value}</div><div class="s">{sub}</div></div>')


def metrics(items) -> str:
    return '<div class="metrics">' + "".join(items) + "</div>"


def aqi_ruler(value: float) -> str:
    lv = C.pm25_level(value)
    i = lv["index"]
    lows, highs = [0, 15, 25, 37.5, 75], [15, 25, 37.5, 75, 150]
    frac = min(max((value - lows[i]) / (highs[i] - lows[i]), 0.02), 0.98)
    pos = (i + frac) / 5 * 100
    bars = "".join(f'<i style="background:{c}"></i>' for _, _, c, *_ in C.AQI_LEVELS)
    labels = "".join(f'<span class="{"on" if k == i else ""}">{t}</span>' for k, t in enumerate(C.LEVEL_SHORT))
    return (f'<div class="ruler"><div class="bar">{bars}</div><div class="track">'
            f'<span class="pin" style="left:{pos:.1f}%"></span></div><div class="labels">{labels}</div></div>')


def best_window(fc: pd.DataFrame, hours: int = 2, start_h: int = 6, end_h: int = 21):
    f = fc.set_index("time")
    score = f["pm25"] / C.STANDARD_PM25 + f["precipitation_probability"].fillna(0) / 50 \
        + (f["temperature_2m"] - C.HEAT_OK).clip(lower=0) / 3
    roll = score.rolling(hours).mean().shift(-(hours - 1)).dropna()
    roll = roll[[t.hour >= start_h and t.hour + hours <= end_h for t in roll.index]]
    if roll.empty:
        return None
    t = roll.idxmin()
    return t, t + pd.Timedelta(hours=hours)


def hourly_strip(fc24: pd.DataFrame, best=None) -> str:
    """รายชั่วโมงแบบแอปพยากรณ์อากาศ: เวลา / ค่าฝุ่น (สีตามระดับ) / ฝน / อุณหภูมิ  เลื่อนซ้ายขวาได้"""
    cols, prev_day, open_grp = [], None, False
    today = C.now_local().date()
    n_best = int(((fc24["time"] >= best[0]) & (fc24["time"] <= best[1])).sum()) if best is not None else 0
    for r in fc24.itertuples():
        rp = 0 if pd.isna(r.precipitation_probability) else float(r.precipitation_probability)
        temp = getattr(r, "temperature_2m", float("nan"))
        is_best = best is not None and best[0] <= r.time <= best[1]   # รวมจุดเวลาปลายช่วง: 20:00–22:00 = 20, 21, 22
        day = r.time.date()
        sep, t_label = "", (f'<b style="color:#C2560C">{r.time:%H:%M}</b>' if is_best else f"{r.time:%H:%M}")
        if prev_day is not None and day != prev_day:
            sep = '<div class="hsep"></div>'
            t_label = f'<b>{"พรุ่งนี้" if day == today + pd.Timedelta(days=1) else day_name(r.time, short=True)}</b>'
        prev_day = day
        rain = (f'<div class="hr" style="opacity:{0.45 + 0.55 * min(rp, 100) / 100:.2f}">'
                f'{icon("rain", RAIN_BLUE, 11)}{rp:.0f}%</div>') if rp >= 20 else '<div class="hr hr0">–</div>'
        t_txt = f"{temp:.0f}°" if pd.notna(temp) else ""
        tip = f"{r.time:%H:%M} น. ฝุ่น {r.pm25:.0f} ({r.level}) ฝน {rp:.0f}% {t_txt}"
        if open_grp and not is_best:
            cols.append("</div>")
            open_grp = False
        cols.append(sep)
        if is_best and not open_grp:
            cols.append(f'<div class="hgrp{" hleft" if len(cols) <= 1 else ""}" style="flex:{n_best} 0 {37 * n_best + 6}px" '
                        f'data-l="แนะนำ {best[0]:%H:%M}–{best[1]:%H:%M}">')
            open_grp = True
        cols.append(f'<div class="hcol" title="{esc(tip)}">'
                    f'<div class="ht">{t_label}</div>'
                    f'<div class="hp" style="background:{r.color}">{r.pm25:.0f}</div>'
                    f'{rain}<div class="hc">{t_txt}</div></div>')
    if open_grp:
        cols.append("</div>")
    css = """<style>
.hgrp .hcol{border:0}
.hgrp{display:flex;gap:1px;border:2px solid #E8742A;border-radius:14px;background:rgba(232,116,42,.07);position:relative}
.hgrp::before{content:attr(data-l);position:absolute;top:-11px;left:50%;transform:translateX(-50%);white-space:nowrap;
 font-size:.66rem;font-weight:700;color:#fff;background:#E8742A;border-radius:99px;padding:1px 8px;z-index:1}
.hgrp.hleft::before{left:0;transform:none}
.hwrap{display:flex;gap:1px;overflow-x:auto;padding:14px 2px 8px;scroll-snap-type:x proximity;
 -webkit-overflow-scrolling:touch;scrollbar-width:thin}
.hcol{flex:1 0 37px;display:flex;flex-direction:column;align-items:center;gap:5px;padding:8px 0;border-radius:14px;
 scroll-snap-align:start;position:relative;border:2px solid transparent}
.ht{font-size:.72rem;color:#6b7280}
.hp{min-width:31px;height:31px;border-radius:99px;color:#fff;font-weight:700;font-size:.88rem;
 display:flex;align-items:center;justify-content:center;padding:0 6px}
.hr{display:flex;gap:2px;align-items:center;font-size:.74rem;color:#2563eb;font-weight:600;height:16px}
.hr0{color:#c3c7cf;font-weight:400}
.hc{font-size:.8rem;color:#374151;font-weight:600}
.hsep{flex:0 0 1px;border-left:1px dashed #cbd0d8;margin:6px 1px}
.ht b{color:#374151;font-weight:700}
.hkey{display:flex;flex-wrap:wrap;gap:14px;font-size:.78rem;color:#6b7280;margin-top:2px}
.hkey b{display:inline-block;width:10px;height:10px;border-radius:99px;margin-right:4px;vertical-align:-1px}
</style>"""
    levels = [(lv["level"], lv["color"]) for lv in (C.pm25_level(v) for v in (10, 20, 30, 50, 100))]
    key = ('<div class="hkey"><span>ค่าในแต่ละช่อง = พยากรณ์ ณ เวลานั้น</span><span>วงกลม = ค่าฝุ่น PM2.5</span>'
           + "".join(f'<span><b style="background:{c}"></b>{esc(n)}</span>' for n, c in levels)
           + f'<span>{icon("rain", RAIN_BLUE, 12)} = โอกาสฝน (แสดงเมื่อ 20% ขึ้นไป)</span><span>ล่างสุด = อุณหภูมิ</span></div>')
    return css + f'<div class="hwrap">{"".join(cols)}</div>' + key


def reason_rows(items) -> str:
    out = []
    for f in items:
        color = STATUS_COLOR.get(f["status"], "#999")
        out.append(f'<div class="reason"><div class="t">{dot(color)}{esc(f["factor"])}</div>'
                   f'<div><b>{esc(f["level"])}</b> ({f["value"]:g} {esc(f["unit"])})'
                   f'<div class="m">{esc(f["meaning"])}</div></div></div>')
    return f'<div class="panel">{"".join(out)}</div>'


_KIND_ICON = {"dust": ("dust", None), "rain": ("rain", RAIN_BLUE), "heat": ("heat", GREY)}


def verdict_card(r: dict, name: str) -> str:
    """การ์ดผลประเมิน: กิจกรรม เวลา คำตัดสิน เหตุผลหลัก และตัวเลข 3 ปัจจัย"""
    end = r["start"] + pd.Timedelta(hours=r["hours"])
    facts = []
    for x in r["reasons"]:
        kind, col = _KIND_ICON[x["key"]]
        col = x["color"] if x["key"] == "dust" else col
        facts.append(f'<span>{icon(kind, col, 17)}{esc(x["value"])} <span class="note" style="margin:0">'
                     f'({esc(x["level"])})</span></span>')
    return f"""<div class="vcard"><div class="top" style="border-left-color:{r['color']}">
<div class="what">{esc(name)} · {day_name(r['start'])} {r['start']:%H:%M}–{end:%H:%M} น. · {C.KMITL_NAME}</div>
<div class="big" style="color:{r['color']}">{esc(r['title'])}</div>
<div class="why">{esc(r['because'])}</div>
<div class="note" style="margin-top:6px">ความแม่นของพยากรณ์ช่วงนี้: {esc(r['confidence'])}</div></div>
<div class="facts3">{''.join(facts)}</div></div>"""


def reason_table(r: dict) -> str:
    rows = []
    for x in r["reasons"]:
        kind, col = _KIND_ICON[x["key"]]
        col = x["color"] if x["key"] == "dust" else col
        rows.append(f'<div class="reason"><div class="t">{icon(kind, col, 17)}{esc(x["topic"])}</div>'
                    f'<div>{dot(STATUS_COLOR[x["status"]])}<b>{esc(x["level"])}</b> · {esc(x["value"])}'
                    f'<div class="m">{esc(x["meaning"])}</div></div></div>')
    return f'<div class="panel">{"".join(rows)}</div>'


def plotly_base(fig, height=320, title=None):
    fig.update_layout(height=height, template="plotly_white", font=PLOT_FONT,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.6)",
                      margin=dict(l=8, r=8, t=40 if title else 10, b=8),
                      title=dict(text=title, font=dict(size=15)) if title else None,
                      legend=dict(orientation="h", y=1.12, x=0), hoverlabel=dict(font_family="Anuphan"))
    return fig


def aqi_bands(fig, y_top):
    lo = 0
    for limit, _, color, *_ in C.AQI_LEVELS:
        hi = min(limit, y_top)
        fig.add_hrect(y0=lo, y1=hi, fillcolor=color, opacity=0.07, line_width=0, layer="below")
        lo = hi
        if lo >= y_top:
            break
    fig.add_hline(y=C.STANDARD_PM25, line_dash="dot", line_color="#D64545", line_width=1,
                  annotation_text="ค่ามาตรฐาน 37.5", annotation_position="top left",
                  annotation_font=dict(size=11, color="#D64545"))


def campus_map(cur: dict | None, height: int = 300):
    """แผนที่ขอบเขตที่ระบบครอบคลุม: ทั้ง สจล. เป็นพื้นที่เดียว + จุดเซนเซอร์ที่ใช้คำนวณค่าตอนนี้"""
    lat = [p[0] for p in C.CAMPUS_OUTLINE] + [C.CAMPUS_OUTLINE[0][0]]
    lon = [p[1] for p in C.CAMPUS_OUTLINE] + [C.CAMPUS_OUTLINE[0][1]]
    color = C.pm25_level(cur["pm25"])["color"] if cur else ORANGE
    fig = go.Figure()
    fig.add_trace(go.Scattermap(lat=lat, lon=lon, mode="lines", fill="toself", fillcolor=_rgba(color, .28),
                                line=dict(color=color, width=2), name="พื้นที่ที่ระบบครอบคลุม (ค่าเดียวทั้งวิทยาเขต)",
                                hoverinfo="skip"))
    if cur and cur.get("poles"):
        ps = cur["poles"]
        fig.add_trace(go.Scattermap(
            lat=[p["lat"] for p in ps], lon=[p["lon"] for p in ps], mode="markers",
            marker=dict(size=10, color="#4A5563"), name="จุดเซนเซอร์ (ชี้เพื่อดูค่าแต่ละจุด)",
            customdata=[[C.POLE_AREAS.get(p["name"], p["name"]), p["pm25"], C.pm25_level(p["pm25"])["level"], p["time"].strftime("%H:%M")] for p in ps],
            hovertemplate="%{customdata[0]}<br>ฝุ่น %{customdata[1]:.0f} (%{customdata[2]})<br>เวลา %{customdata[3]} น.<extra></extra>"))
    if cur:
        fig.add_trace(go.Scattermap(lat=[C.KMITL_LAT], lon=[C.KMITL_LON], mode="text",
                                    text=[f"{cur['pm25']:.0f}"], textfont=dict(size=22, color="#17202B"),
                                    hoverinfo="skip", showlegend=False))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), font=PLOT_FONT,
                      map=dict(style=os.getenv("MAP_STYLE", "carto-positron"), center=dict(lat=13.7283, lon=100.7780), zoom=13.75),
                      legend=dict(orientation="h", y=-0.02, x=0, bgcolor="rgba(255,255,255,.85)", font=dict(size=12)))
    return fig


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def source_line(cur: dict) -> str:
    t = cur["measured_at"][-5:] if cur.get("measured_at") else "-"
    s = f"{cur['source_text']} เวลา {t} น."
    if not cur["is_fresh"]:
        s += f" (ข้อมูลเก่า {cur['age_hours']:.0f} ชม.)"
    return s


def pole_table(cur: dict) -> str:
    """ค่าฝุ่นตอนนี้ของแต่ละจุดเซนเซอร์ (ค่าวัดจริง ไม่ใช่พยากรณ์)"""
    rows = []
    for p in sorted(cur["poles"], key=lambda x: -x["pm25"]):
        lv = C.pm25_level(p["pm25"])
        diff = p["pm25"] - cur["pm25"]
        rel = "เท่าค่ากลาง" if abs(diff) < 1 else f"{'สูง' if diff > 0 else 'ต่ำ'}กว่าค่ากลาง {abs(diff):.0f}"
        area = C.POLE_AREAS.get(p["name"], p["name"])
        rows.append(f'<div class="reason" style="grid-template-columns:1fr auto;align-items:center">'
                    f'<div><b>{esc(area)}</b><div class="note" style="margin:0">{esc(p["name"])} · {rel}</div></div>'
                    f'<div style="white-space:nowrap">{icon("dust", lv["color"], 15)} <b style="font-size:1.15rem">{p["pm25"]:.0f}</b> '
                    f'{chip(lv["level"], lv["color"])}</div></div>')
    return f'<div class="panel" style="padding:6px 16px">{"".join(rows)}</div>'
