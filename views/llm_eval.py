"""หน้า: ผลประเมิน AI (LLM Evaluation 4 ด้าน)"""

import json

import pandas as pd
import streamlit as st

import config as C
import ui

ui.brand_header("AI ในระบบนี้ทำงานได้ดีแค่ไหน")
st.markdown("<p>ประเมินจากชุดคำถามทดสอบที่กำหนดไว้ล่วงหน้า (ไฟล์ <code>evaluate_llm.py</code>) "
            "ตรวจอัตโนมัติด้วยโค้ดเป็นหลัก ส่วนด้านความปลอดภัยใช้ AI อีกตัวเป็นกรรมการตามเกณฑ์ที่เขียนไว้</p>",
            unsafe_allow_html=True)

ASPECTS = [
    ("understanding", "1. ความเข้าใจคำขอ", "แปลงประโยคแผนเป็น วัน เวลา ระยะเวลา ลักษณะ และในร่ม/กลางแจ้ง ได้ถูกครบทุกช่อง"),
    ("grounded", "2. ความถูกต้องตามข้อมูลจริง", "ตัวเลขในคำตอบมีอยู่ในข้อมูลที่ดึงจากระบบจริง ไม่แต่งเอง (Groundedness)"),
    ("tools", "3. การเลือกใช้เครื่องมือ", "เรียกเครื่องมือที่ถูกต้องกับคำถาม เช่น ถามแผนกิจกรรมต้องใช้เกณฑ์ประเมินของระบบ"),
    ("safety", "4. ความปลอดภัยและขอบเขต", "ไม่ตอบนอกขอบเขต ไม่วินิจฉัยโรค ดูแลกลุ่มเสี่ยง ไม่ยอมแต่งตัวเลขตามที่ถูกสั่ง"),
]

data = json.loads(C.LLM_EVAL_FILE.read_text(encoding="utf-8")) if C.LLM_EVAL_FILE.exists() else None

if not data:
    st.info("ยังไม่มีผลประเมิน รันคำสั่งนี้ใน Terminal (ต้องตั้งค่า GEMINI_API_KEY แล้ว) จากนั้นรีเฟรชหน้านี้\n\n"
            "`python evaluate_llm.py`  (หรือ `python evaluate_llm.py --quick` เพื่อประหยัดโควตา)")
    st.markdown('<div class="panel">' + "".join(
        f'<div class="reason"><div class="t">{t}</div><div class="m" style="color:var(--ink)">{d}</div></div>'
        for _, t, d in ASPECTS) + "</div>", unsafe_allow_html=True)
    st.stop()

asp = data["aspects"]
cols = st.columns(4)
for col, (k, t, d) in zip(cols, ASPECTS):
    sc = asp[k]["score"]
    color = "#1E9E5A" if sc >= 0.85 else "#C99A06" if sc >= 0.6 else "#D64545"
    col.markdown(f'<div class="score"><div class="n" style="color:{color}">{sc:.0%}</div><div class="t">{t}</div>'
                 f'<div class="d">{d}</div><div class="d">ทดสอบ {asp[k]["n"]} ข้อ</div></div>', unsafe_allow_html=True)
st.markdown(f'<p class="note">ประเมินเมื่อ {data["run_at"]} · โมเดล {data["model"]}'
            f'{" · โหมดย่อ" if data.get("quick") else ""}</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- รายละเอียด
u = asp["understanding"]
st.markdown('<div class="section-title">1. ความเข้าใจคำขอ เทียบกับตัวแปลงแบบกฎ</div>', unsafe_allow_html=True)
st.markdown(f"<p>AI แปลงถูกครบทุกช่อง <b>{u['score']:.0%}</b> ของประโยค (ถูกรายช่อง {u['ai_field_acc']:.0%}) "
            f"เทียบกับตัวแปลงแบบกฎที่กลุ่มเขียนเอง <b>{u['rule_score']:.0%}</b> (รายช่อง {u['rule_field_acc']:.0%}) "
            "ระบบจึงใช้ AI เป็นหลัก และใช้ตัวแปลงแบบกฎเป็นตัวสำรองเมื่อ AI ไม่พร้อม</p>", unsafe_allow_html=True)
with st.expander("ดูรายข้อ"):
    st.dataframe(pd.DataFrame([{"ประโยค": r["text"], "AI": "ถูก" if r["ai_ok"] else "ผิด",
                                "แบบกฎ": "ถูก" if r["rule_ok"] else "ผิด",
                                "ช่องที่ AI ผิด": ", ".join(k for k, v in r["ai_fields"].items() if not v) or "-"}
                               for r in u["cases"]]), hide_index=True, **ui.FULL)

g = asp["grounded"]
st.markdown('<div class="section-title">2. ความถูกต้องตามข้อมูลจริง</div>', unsafe_allow_html=True)
st.markdown(f"<p>ตรวจตัวเลข {g['numbers_checked']} ตัวจากคำตอบ {g['n']} ข้อ พบว่า <b>{g['score']:.0%}</b> "
            "ตรงกับข้อมูลที่ AI ดึงจากเครื่องมือของระบบ</p>", unsafe_allow_html=True)
with st.expander("ดูรายข้อ"):
    for r in g["cases"]:
        bad = ", ".join(f"{n:g}" for n in r["ungrounded"]) or "ไม่มี"
        st.markdown(f"**{r['question']}** — อ้างอิงได้ {r['grounded_ratio']:.0%} (ตัวเลขที่หาที่มาไม่เจอ: {bad})")
        st.caption(r["answer"][:500])

t = asp["tools"]
st.markdown('<div class="section-title">3. การเลือกใช้เครื่องมือ</div>', unsafe_allow_html=True)
st.dataframe(pd.DataFrame([{"คำถาม": r["question"], "ควรเรียก": ", ".join(r["expected_tools"]),
                            "เรียกจริง": ", ".join(dict.fromkeys(r["tools_called"])) or "-",
                            "ผล": "ผ่าน" if r["tool_ok"] else "ไม่ผ่าน"} for r in t["cases"]]),
             hide_index=True, **ui.FULL)

s = asp["safety"]
st.markdown('<div class="section-title">4. ความปลอดภัยและขอบเขต</div>', unsafe_allow_html=True)
for r in s["cases"]:
    with st.expander(f"{'ผ่าน' if r['pass'] else 'ไม่ผ่าน'} · {r['question']}"):
        st.markdown(f"**เกณฑ์:** {r['criteria']}  \n**กรรมการ:** {r['reason']}")
        st.caption(r["answer"][:600])

st.markdown('<p class="note">ข้อจำกัด: ชุดทดสอบมีขนาดเล็กและกลุ่มเขียนเอง คำตอบของ AI อาจต่างกันเล็กน้อยในแต่ละครั้ง '
            'ตัวตรวจตัวเลขยกเว้นเวลา วันที่ และตัวเลขที่มาจากคำถาม</p>', unsafe_allow_html=True)
