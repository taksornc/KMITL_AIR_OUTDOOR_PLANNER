"""KMITL Outdoor Planner — จุดเริ่มของเว็บ (เมนู ธีม ผู้ใช้ การตั้งค่า)
รัน: streamlit run app.py
"""

import streamlit as st
from dotenv import load_dotenv

import config as C
import store
import ui
import weather_fx as FX

load_dotenv()
st.set_page_config(page_title=C.APP_NAME, page_icon="☁️", layout="wide", initial_sidebar_state="collapsed")
ui.inject_css()
store.init()


@st.cache_resource
def _warm_up():
    """ดึงข้อมูลและพยากรณ์ล่วงหน้าตอนเซิร์ฟเวอร์เริ่ม ผู้ใช้คนแรกจะไม่ต้องรอ"""
    import threading

    def run():
        try:
            import forecast
            forecast.get_forecast()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
    return True


_warm_up()


@st.cache_resource
def _reminder_loop():
    """เช็กทุก 5 นาที แล้วส่งอีเมลเตือนกิจกรรมที่จะเริ่มภายใน 1 ชม. (ทำงานเฉพาะตอนเซิร์ฟเวอร์รันอยู่)"""
    import threading, time
    import planner

    def run():
        while True:
            try:
                if planner.email_ready():
                    planner.check_reminders()
                    planner.check_daily()
            except Exception as e:
                print("reminder loop:", e)
            time.sleep(300)
    threading.Thread(target=run, daemon=True).start()
    return True


_reminder_loop()

# ---------------------------------------------------------------- แถบด้านข้าง
with st.sidebar:
    u = ui.user()
    st.markdown(f"**{'เข้าสู่ระบบเป็น ' + u['email'] if u else 'ยังไม่ได้เข้าสู่ระบบ'}**")
    sens = st.toggle("ฉันแพ้ฝุ่นหรือเป็นหอบหืด", value=ui.is_sensitive(),
                     help="คำแนะนำทั้งเว็บและเกณฑ์ประเมินกิจกรรมจะเข้มขึ้น")
    ui.set_sensitive(sens)
    if st.button("ดึงข้อมูลล่าสุด", **ui.FULL):
        ui.refresh_all()
        st.rerun()
    st.divider()
    st.markdown("**สำหรับนำเสนอ**")
    fx_choice = st.selectbox("พื้นหลังตามสภาพอากาศ", ["auto"] + list(FX.FX_NAMES),
                             format_func=lambda k: "ตามอากาศจริง" if k == "auto" else FX.FX_NAMES[k])
    fx_haze = st.checkbox("จำลองวันที่ฝุ่นหนา", value=False)
    st.divider()
    st.caption(f"ฝุ่นตอนนี้: {C.SMARTPOLE_CREDIT} (สำรอง: Air4Thai กรมควบคุมมลพิษ)  \n"
               "พยากรณ์ฝุ่น: โมเดล machine learning ของระบบ  \n"
               "ฝน อุณหภูมิ ลม: Open-Meteo  \nผู้ช่วย AI: Google Gemini")

# ---------------------------------------------------------------- พื้นหลังตามอากาศจริง
cur, _ = ui.current()
w, _ = ui.weather()
_rain = (6.0 if "หนัก" in (w.get("weather_text") or "") or "คะนอง" in (w.get("weather_text") or "") else 1.0) \
    if w and w["raining"] else 0.0
auto_kind = FX.pick_fx(w["hour"], _rain, w["cloud_percent"]) if w else "partly"
q = st.query_params
kind = fx_choice if fx_choice != "auto" else (q.get("fx") if q.get("fx") in FX.FX_NAMES else auto_kind)
haze = 0.75 if (fx_haze or q.get("haze") == "1") else (FX.haze_from_pm25(cur["pm25"]) if cur else 0)
st.markdown(FX.background_html(kind, haze), unsafe_allow_html=True)
ui.theme_css()

# ---------------------------------------------------------------- เมนู
pages = {
    "": [
        st.Page("views/now.py", title="ตอนนี้", default=True),
        st.Page("views/plan.py", title="วางแผนกิจกรรม"),
        st.Page("views/schedule.py", title="ตารางของฉัน"),
        st.Page("views/forecast.py", title="พยากรณ์ 7 วัน"),
        st.Page("views/chat.py", title="ถาม AI"),
    ],
    "ข้อมูลและระบบ": [
        st.Page("views/insights.py", title="สถิติย้อนหลัง"),
        st.Page("views/trust.py", title="ความแม่นและแหล่งข้อมูล"),
        st.Page("views/llm_eval.py", title="ผลประเมิน AI"),
        st.Page("views/guide.py", title="วิธีใช้"),
    ],
    "บัญชี": [st.Page("views/account.py", title="บัญชีของฉัน" if ui.user() else "เข้าสู่ระบบ")],
}
try:
    nav = st.navigation(pages, position="top")
except TypeError:                      # Streamlit รุ่นเก่ายังไม่มีเมนูด้านบน
    nav = st.navigation(pages)
nav.run()

st.markdown(f'<p class="note" style="margin-top:40px">{C.APP_NAME} โครงงานรายวิชา สาขาสถิติประยุกต์ สจล. '
            'ใช้ประกอบการตัดสินใจเท่านั้น ไม่ใช่คำแนะนำทางการแพทย์</p>', unsafe_allow_html=True)
