"""หน้า: ถาม AI — ถามเป็นภาษาพูด AI ดึงตัวเลขจาก tools เท่านั้น บันทึกประวัติเมื่อเข้าสู่ระบบ"""

import json

import streamlit as st

import store
import ui

ui.brand_header("ถามเรื่องฝุ่น อากาศ และกิจกรรมใน สจล.")
api_key, model = ui.gemini()
if not api_key:
    st.info("ยังไม่ได้ตั้งค่า Gemini API key\n\n1. ขอ key ฟรีที่ https://aistudio.google.com/apikey\n"
            "2. ใส่ `GEMINI_API_KEY=...` ในไฟล์ `.env`\n3. ปิดแล้วเปิด `streamlit run app.py` ใหม่")
    st.stop()
res, err = ui.forecast()
if not res:
    st.info(err)
    st.stop()

from agent import AirAgent, clean_answer  # noqa: E402

u = ui.user()
owner = u["id"] if u else None
if owner and "conv_id" not in st.session_state:
    convs0 = store.list_conversations(owner, 1)
    st.session_state.conv_id = convs0[0]["conv_id"] if convs0 else store.new_conv_id()
conv = st.session_state.get("conv_id") if owner else None
if (st.session_state.get("chat_key") != (owner, conv, model)) or "agent" not in st.session_state:
    st.session_state.messages = [dict(m, content=clean_answer(m["content"]) if m["role"] == "assistant" else m["content"],
                                       options=[], trace=[]) for m in store.list_messages(owner, conv)] if owner else []
    st.session_state.agent = AirAgent(api_key, model, history=st.session_state.messages)
    st.session_state.chat_key = (owner, conv, model)


def open_conv(cid):
    st.session_state.conv_id = cid
    st.session_state.pop("agent", None)


# ---------------------------------------------------------------- ประวัติการถาม (เฉพาะผู้ที่เข้าสู่ระบบ)
if owner:
    convs = store.list_conversations(owner)
    side, main = st.columns([1, 2.7], gap="large")
    with side:
        st.markdown('<div class="section-title" style="margin-top:0">ประวัติการถาม</div>', unsafe_allow_html=True)
        st.button("+ เริ่มบทสนทนาใหม่", on_click=open_conv, args=(store.new_conv_id(),), type="primary", **ui.FULL)
        if not convs:
            st.caption("ยังไม่มีประวัติ คำถามที่ถามจะถูกเก็บไว้ที่นี่")
        for c in convs:
            title = (c["title"] or "บทสนทนา").strip().replace("\n", " ")
            short = title[:30] + ("…" if len(title) > 30 else "")
            when = f'{ui.day_name(c["last_at"], short=True)} {c["last_at"][11:16]} น.'
            if c["conv_id"] == conv:
                st.markdown(f'<div style="border-left:4px solid {ui.ORANGE};background:#FFF4EC;border-radius:0 8px 8px 0;'
                            f'padding:7px 10px;margin:4px 0 8px"><b>{ui.esc(short)}</b>'
                            f'<div class="note" style="margin:0">{when} · กำลังเปิดอยู่</div></div>', unsafe_allow_html=True)
            else:
                st.button(short, key=f"cv_{c['conv_id']}", on_click=open_conv, args=(c["conv_id"],),
                          help=f"{title} ({when})", **ui.FULL)
        if any(c["conv_id"] == conv for c in convs) and st.button("ลบบทสนทนานี้", key="del_conv"):
            store.delete_conversation(owner, conv)
            open_conv(store.new_conv_id())
            st.rerun()
else:
    main = st.container()

QUICK = ["พรุ่งนี้ห้าโมงเย็นเตะบอลได้ไหม", "ถ้าฝนตก วิ่งในร่มที่ไหนใน สจล. ได้บ้าง", "สามวันนี้ช่วงไหนเหมาะวิ่งที่สุด",
         "เย็นนี้ไปเดินตลาดหอในได้ไหม", "พรุ่งนี้ต้องใส่หน้ากากไหม", "ทำไมช่วงนี้ฝุ่นถึงเป็นแบบนี้"]
TOOL_TH = {
    "get_current_air_quality": "ฝุ่นตอนนี้", "get_current_weather": "อากาศตอนนี้",
    "get_pm25_forecast": "พยากรณ์ฝุ่น", "get_weather_forecast": "พยากรณ์ฝนและอากาศ",
    "find_best_outdoor_times": "หาช่วงเวลาที่เหมาะ", "evaluate_activity_plan": "เกณฑ์ประเมินกิจกรรม",
    "get_dust_statistics": "สถิติย้อนหลัง", "read_knowledge": "ฐานความรู้",
}

def render_trace(trace):
    if not trace:
        return
    names = ", ".join(dict.fromkeys(TOOL_TH.get(t["tool"], t["tool"]) for t in trace))
    with st.expander(f"ข้อมูลที่ AI ใช้ตอบ: {names}"):
        for t in trace:
            args = ", ".join(f"{k}={v!r}" for k, v in t["args"].items())
            st.markdown(f"**{TOOL_TH.get(t['tool'], t['tool'])}** `{t['tool']}({args})`")
            st.code(json.dumps(t["result"], ensure_ascii=False, indent=1)[:2500], language="json")


msgs = st.session_state.messages
with main:
    if not msgs:
        st.markdown("<p>ถามเป็นภาษาพูดได้เลย AI จะดึงข้อมูลฝุ่น พยากรณ์ และอากาศล่าสุดมาตอบ "
                    "แล้วเสนอทางเลือกให้คุณตัดสินใจเอง</p>", unsafe_allow_html=True)
        qcols = st.columns(3)
        for k, q in enumerate(QUICK):
            if qcols[k % 3].button(q, key=f"q_{k}", **ui.FULL):
                st.session_state.pending = q
    if not u:
        st.caption("ยังไม่ได้เข้าสู่ระบบ ประวัติแชตจะหายเมื่อปิดหน้า (เข้าสู่ระบบที่เมนู บัญชี เพื่อเก็บประวัติ)")


    for i, m in enumerate(msgs):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                render_trace(m.get("trace"))
                if m.get("decision"):
                    st.success(f"คุณเลือก: {m['decision']}")
                elif m.get("options") and i == len(msgs) - 1:
                    st.markdown("**คุณจะเลือกทางไหน**")
                    for j, (col, opt) in enumerate(zip(st.columns(len(m["options"])), m["options"])):
                        if col.button(opt, key=f"opt_{i}_{j}", **ui.FULL):
                            m["decision"] = opt
                            st.session_state.pending = f"ฉันเลือก: {opt} ช่วยบอกสิ่งที่ควรเตรียมสั้น ๆ"
                            st.rerun()


prompt = st.chat_input("พิมพ์คำถาม เช่น เย็นนี้วิ่งรอบสนามได้ไหม")
prompt = prompt or st.session_state.pop("pending", None)
if prompt:
    msgs.append({"role": "user", "content": prompt})
    with main:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"), st.spinner("กำลังดึงข้อมูลล่าสุดและวิเคราะห์..."):
            try:
                out = st.session_state.agent.ask(prompt, sensitive=ui.is_sensitive())
            except Exception as e:  # AI ล่ม/โควตาหมด: ตอบกลับให้รู้ ไม่เงียบหาย
                out = {"answer": f"ตอนนี้ AI ตอบไม่ได้ ({type(e).__name__}) ลองถามใหม่อีกครั้งในอีกสักครู่",
                       "options": [], "trace": [], "error": True}
    if not (out.get("answer") or "").strip():
        out["answer"] = "ตอนนี้ AI ตอบไม่ได้ ลองถามใหม่อีกครั้งในอีกสักครู่"
        out["error"] = True
    msgs.append({"role": "assistant", "content": out["answer"], "options": out.get("options") or [],
                 "trace": out.get("trace")})
    if owner and not out.get("error"):
        store.add_message(owner, "user", prompt, conv)
        store.add_message(owner, "assistant", out["answer"], conv)
    st.rerun()

if msgs and not owner and st.button("เริ่มบทสนทนาใหม่"):
    st.session_state.pop("agent", None)
    st.rerun()
