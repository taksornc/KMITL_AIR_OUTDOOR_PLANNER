"""หน้า: บัญชีของฉัน — เข้าสู่ระบบ / สมัคร / ตั้งค่า / ลบข้อมูล (PDPA)"""

import streamlit as st

import store
import ui

u = ui.user()
if not u:
    ui.brand_header("เข้าสู่ระบบ")
    st.markdown("<p>ดูฝุ่น พยากรณ์ และประเมินกิจกรรมได้โดยไม่ต้องเข้าสู่ระบบ "
                "เข้าสู่ระบบเมื่ออยากบันทึกกิจกรรมลงตาราง และเก็บประวัติการถาม AI</p>", unsafe_allow_html=True)
    ui.login_box("เข้าสู่ระบบด้วยอีเมล สจล.", "account")
    st.stop()

ui.brand_header("บัญชีของฉัน")
n = store.counts(u["id"])
st.markdown(f"""<div class="panel"><b>{ui.esc(u['email'])}</b>
<div class="note" style="margin-top:4px">สมัครเมื่อ {u['created_at'][:10]} · กิจกรรมในตาราง {n['activities']} รายการ ·
ข้อความแชต {n['messages']} ข้อความ</div></div>""", unsafe_allow_html=True)

st.markdown('<div class="section-title">ตั้งค่า</div>', unsafe_allow_html=True)
v = st.toggle("ฉันแพ้ฝุ่นหรือเป็นหอบหืด", value=u["sensitive"],
              help="ใช้เกณฑ์ฝุ่นแบบเข้มที่สุดทุกครั้งที่ประเมินกิจกรรม และ AI จะแนะนำแบบกลุ่มเสี่ยง")
ui.set_sensitive(v)

import planner
rem = st.toggle("ส่งอีเมลเตือนก่อนกิจกรรมเริ่ม 1 ชม.", value=store.get_email_remind(u["id"]),
                help="อีเมลจะบอกผลประเมินล่าสุด ฝุ่นและอากาศตอนนั้น และของที่ควรเตรียม ส่งไปที่อีเมล สจล. ของคุณ")
if rem != store.get_email_remind(u["id"]):
    store.set_email_remind(u["id"], rem)
daily = st.toggle("ส่งสรุปอากาศตอนเช้า เฉพาะวันที่ฝนตก ฝุ่นสูง หรือร้อนจัด", value=store.get_daily_alert(u["id"]),
                  help="ส่งราว 06:30 น. วันละครั้ง ถ้าวันนั้นอากาศดีจะไม่ส่ง จะได้ไม่รกกล่องอีเมล")
if daily != store.get_daily_alert(u["id"]):
    store.set_daily_alert(u["id"], daily)
if not planner.email_ready():
    st.caption("ผู้ดูแลระบบยังไม่ได้ตั้งค่าการส่งอีเมล (SMTP_USER, SMTP_APP_PASSWORD, EMAIL_REMINDER ใน .env)")
else:
    acts = store.list_activities(u["id"])
    if st.button("ส่งอีเมลทดสอบด้วยกิจกรรมถัดไป", disabled=not acts):
        try:
            with st.spinner("กำลังส่ง..."):
                planner.send_reminder(acts[0], to=u["email"])
            st.success(f"ส่งแล้วไปที่ {u['email']} (ถ้าไม่เห็น ลองดูในโฟลเดอร์ Spam)")
        except Exception as e:
            st.error(f"ส่งไม่สำเร็จ: {e}")
    if not acts:
        st.caption("บันทึกกิจกรรมในตารางก่อน แล้วจึงกดส่งอีเมลทดสอบได้")
    if st.button("ส่งสรุปอากาศวันนี้ (ทดสอบ)"):
        try:
            with st.spinner("กำลังส่ง..."):
                planner.send_email(u["email"], *planner.daily_email({**u, "sensitive": ui.is_sensitive()}, force=True))
            st.success(f"ส่งแล้วไปที่ {u['email']} (ตอนทดสอบส่งเสมอ ของจริงส่งเฉพาะวันที่อากาศไม่ดี)")
        except Exception as e:
            st.error(f"ส่งไม่สำเร็จ: {e}")

st.markdown('<div class="section-title">ข้อมูลที่ระบบเก็บ</div>', unsafe_allow_html=True)
st.markdown("""<div class="panel">
<div class="reason"><div class="t">อีเมล</div><div class="m">ใช้เข้าสู่ระบบเท่านั้น</div></div>
<div class="reason"><div class="t">รหัสผ่าน</div><div class="m">เก็บแบบแฮช (PBKDF2) ระบบไม่รู้รหัสผ่านจริง</div></div>
<div class="reason"><div class="t">แพ้ฝุ่นหรือไม่</div><div class="m">เก็บแค่ ใช่ / ไม่ใช่ ไม่เก็บรายละเอียดสุขภาพอื่น</div></div>
<div class="reason"><div class="t">ตารางกิจกรรม</div><div class="m">ชื่อกิจกรรม เวลา และสิ่งที่ติ๊กเตรียมแล้ว</div></div>
<div class="reason"><div class="t">ประวัติแชต</div><div class="m">คำถามและคำตอบ เพื่อให้กลับมาดูต่อได้</div></div>
</div>""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
if c1.button("ลบประวัติแชตทั้งหมด", **ui.FULL):
    store.clear_messages(u["id"])
    st.session_state.pop("agent", None)
    st.session_state.pop("messages", None)
    st.session_state.pop("conv_id", None)
    st.success("ลบประวัติแชตแล้ว")
if c2.button("ออกจากระบบ", **ui.FULL):
    for k in ("user", "agent", "messages", "conv_id", "chat_key"):
        st.session_state.pop(k, None)
    st.rerun()
with c3.popover("ลบบัญชีและข้อมูลทั้งหมด", **ui.FULL):
    st.markdown("ลบบัญชี ตารางกิจกรรม และประวัติแชตทั้งหมด กู้คืนไม่ได้")
    if st.button("ยืนยันลบบัญชี", type="primary"):
        store.delete_user(u["id"])
        for k in ("user", "agent", "messages", "conv_id", "chat_key"):
            st.session_state.pop(k, None)
        st.rerun()
