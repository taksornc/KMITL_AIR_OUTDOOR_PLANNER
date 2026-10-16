"""หน้า: วางแผนกิจกรรม — พิมพ์ประโยคเดียว -> AI เข้าใจแผน -> เกณฑ์ของระบบตัดสิน -> AI อธิบาย -> บันทึกลงตาราง"""

import json

import pandas as pd
import streamlit as st

import config as C
import planner as P
import store
import ui

ui.brand_header("วางแผนกิจกรรม")
res, err = ui.forecast()
if not res:
    st.info(err)
    st.stop()
fc = res["hourly"]
dates = sorted(fc["date"].unique())
api_key, model = ui.gemini()
now = C.now_local()

st.markdown("<p>พิมพ์ว่าจะทำอะไร เมื่อไร ระบบจะดูฝุ่น ฝน และความร้อนตลอดช่วงเวลานั้น แล้วบอกว่าเหมาะไหม "
            "ต้องเตรียมอะไร และมีเวลาไหนดีกว่า</p>", unsafe_allow_html=True)

EXAMPLES = ["พรุ่งนี้ห้าโมงเย็นเตะบอลกับเพื่อน", "วิ่งรอบสนามเช้าวันเสาร์", "ถ่ายรูปรับปริญญาบ่ายสามวันพุธ"]


def run_parse(text: str):
    text = text.strip()
    if not text:
        return
    plan, note = None, None
    if api_key:
        from agent import parse_plan
        try:
            with st.spinner("AI กำลังอ่านแผนของคุณ..."):
                plan = parse_plan(api_key, model, text, f"{now:%Y%m%d%H}")
        except RuntimeError as e:
            note = f"{e} ระบบใช้ตัวแปลงสำรองแทน ตรวจสอบสิ่งที่ระบบเข้าใจด้านล่างอีกครั้ง"
    if plan is None:
        plan = P.parse_text(text)
    plan["sensitive"] = bool(plan.get("sensitive")) or ui.is_sensitive()
    plan["text"] = text
    st.session_state.plan = plan
    st.session_state.plan_note = note
    st.session_state.pop("saved_msg", None)


with st.form("ask"):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    text = c1.text_input("จะทำอะไร เมื่อไร", value=st.session_state.get("plan", {}).get("text", ""),
                         placeholder="เช่น พรุ่งนี้ห้าโมงเย็นเตะบอลกับเพื่อน 2 ชม.")
    go_btn = c2.form_submit_button("ตรวจสอบ", type="primary", **ui.FULL)
if go_btn:
    run_parse(text)

if "plan" not in st.session_state:
    st.markdown('<p class="note">ลองตัวอย่าง</p>', unsafe_allow_html=True)
    cols = st.columns(len(EXAMPLES))
    for col, ex in zip(cols, EXAMPLES):
        if col.button(ex, **ui.FULL):
            run_parse(ex)
            st.rerun()
    st.markdown(f'<p class="note">ประเมินกิจกรรมใน สจล. ล่วงหน้าได้ไม่เกิน 7 วัน ถ้าทำในร่ม ระบบดูให้เฉพาะช่วงเดินทางไป-กลับ '
                f'ทั้งวิทยาเขตใช้พยากรณ์ชุดเดียวกัน</p>', unsafe_allow_html=True)
    st.stop()

plan = st.session_state.plan
if st.session_state.get("plan_note"):
    st.warning(st.session_state.plan_note)

# ---------------------------------------------------------------- สิ่งที่ระบบเข้าใจ (แก้ได้)
start = None
if plan["date"] and plan["start_hour"] is not None:
    start = pd.Timestamp(plan["date"]) + pd.Timedelta(hours=int(plan["start_hour"]))
end = start + pd.Timedelta(hours=plan["duration_hours"]) if start is not None else None
tags = [ui.tag(plan["activity_name"])]
tags.append(ui.tag(f'{ui.day_name(start)} {start:%H:%M}–{end:%H:%M} น.' if start is not None else "ยังไม่ระบุวันเวลา",
                   "clock"))
if plan["is_outdoor"]:
    tags.append(ui.tag(P.INTENSITY[plan["intensity"]]))
if plan["sensitive"]:
    tags.append(ui.tag("มีคนแพ้ฝุ่นร่วมด้วย"))
st.markdown(f'<div class="note" style="margin:2px 0 4px">ระบบเข้าใจว่า</div>{"".join(tags)}', unsafe_allow_html=True)

WHERE = {"outdoor": "กลางแจ้ง", "indoor": "ในร่ม (ดูแค่ช่วงเดินทาง)"}
where_now = "outdoor" if plan["is_outdoor"] else "indoor"
if hasattr(st, "segmented_control"):
    where = st.segmented_control("ทำกิจกรรมที่ไหน", list(WHERE), default=where_now, format_func=WHERE.get,
                                 key=f"where_{plan.get('text', '')}_{where_now}")
else:
    where = st.radio("ทำกิจกรรมที่ไหน", list(WHERE), index=list(WHERE).index(where_now), format_func=WHERE.get,
                     horizontal=True)
if where and where != where_now:
    plan["is_outdoor"] = where == "outdoor"
    st.session_state.pop("saved_msg", None)
    st.rerun()
indoor = not plan["is_outdoor"]

with st.expander("แก้ไขรายละเอียด", expanded=start is None):
    with st.form("edit"):
        name = st.text_input("ชื่อกิจกรรม", value=plan["activity_name"])
        e1, e2, e3 = st.columns(3)
        d0 = pd.Timestamp(plan["date"]).date() if plan["date"] else (dates[1] if len(dates) > 1 else dates[0])
        day = e1.selectbox("วัน", dates, index=dates.index(d0) if d0 in dates else 0, format_func=ui.day_name)
        hour = e2.selectbox("เริ่ม", list(range(0, 24)),
                            index=list(range(0, 24)).index(plan["start_hour"]) if plan["start_hour"] in range(0, 24) else 12,
                            format_func=lambda h: f"{h:02d}:00 น.")
        hrs = e3.selectbox("นาน", list(range(1, 13)), index=plan["duration_hours"] - 1, format_func=lambda h: f"{h} ชม.")
        inten = st.radio("ลักษณะกิจกรรม", list(P.INTENSITY), index=list(P.INTENSITY).index(plan["intensity"]),
                         horizontal=True, format_func=lambda k: {
                             "heavy": "ออกแรงมาก (วิ่ง กีฬา ซ้อมเชียร์)", "moderate": "ปานกลาง (เดิน จัดบูธ)",
                             "light": "ออกแรงน้อย (ถ่ายรูป นั่ง รอรถ)"}[k])
        sens = st.checkbox("มีคนแพ้ฝุ่นหรือเป็นหอบหืดร่วมด้วย", value=plan["sensitive"])
        if st.form_submit_button("ใช้ข้อมูลนี้", type="primary"):
            plan.update({"activity_name": name.strip() or plan["activity_name"], "date": str(day), "start_hour": hour,
                         "duration_hours": hrs, "intensity": inten, "sensitive": sens})
            st.session_state.pop("saved_msg", None)
            st.rerun()

if start is None:
    st.markdown("<p>ยังไม่รู้ว่าจะทำวันไหน กี่โมง เลือกด่วนได้เลย หรือกรอกในช่องแก้ไขด้านบน</p>", unsafe_allow_html=True)
    quick = []
    if now.hour < 16:
        quick.append(("วันนี้เย็น 17:00", now.date(), 17))
    tmr = (now + pd.Timedelta(days=1)).date()
    quick += [("พรุ่งนี้เช้า 06:00", tmr, 6), ("พรุ่งนี้เย็น 17:00", tmr, 17)]
    for col, (label, d, h) in zip(st.columns(len(quick)), quick):
        if col.button(label, **ui.FULL):
            plan.update({"date": str(d), "start_hour": h})
            st.rerun()
    st.stop()


try:
    r = P.assess(start, plan["duration_hours"], plan["intensity"], plan["sensitive"], indoor)
except ValueError as e:
    st.warning(f"{e} ลองเลือกวันเวลาใหม่ในช่องแก้ไขรายละเอียด")
    st.stop()
alts = []
place = P.suggest_place(plan["activity_name"], r["verdict"], indoor)
if r["verdict"] != "good" and not indoor:
    rank = {"good": 0, "caution": 1, "bad": 2}
    # เสนอเฉพาะเวลาใกล้เวลาเดิม (±2 ชม. ก่อน ถ้าไม่มีค่อยขยายเป็น ±4 ชม.) ไม่เสนอให้ไปตอนเช้ามืดถ้านัดไว้ตอนเย็น
    for shift in (2, 4):
        for a in P.better_times(plan["duration_hours"], days=7, exclude=start, prefer_hour=start.hour, max_shift=shift):
            ev = P.evaluate(a["start"], plan["duration_hours"], plan["intensity"], plan["sensitive"])
            if rank[ev["verdict"]] < rank[r["verdict"]]:
                alts.append({**a, "eval": ev})
        if alts:
            break
    no_alt_note = not alts

# ---------------------------------------------------------------- ผลประเมิน
st.markdown(ui.verdict_card(r, plan["activity_name"]), unsafe_allow_html=True)

left, right = st.columns([1.45, 1], gap="large")
with left:
    st.markdown(f'<div class="section-title" style="margin-top:18px">{"ช่วงเดินทางไป-กลับ" if indoor else "เหตุผล"}</div>',
                unsafe_allow_html=True)
    st.markdown(ui.reason_table(r), unsafe_allow_html=True)
with right:
    st.markdown('<div class="section-title" style="margin-top:18px">สิ่งที่ควรเตรียม</div>', unsafe_allow_html=True)
    prep_ph = st.empty()


def show_prep(items):
    prep_ph.markdown('<div class="panel">' + ("".join(f"<div style='margin:3px 0'>☐ {ui.esc(i)}</div>" for i in items)
                                              or "ไม่ต้องเตรียมอะไรเป็นพิเศษ") + "</div>", unsafe_allow_html=True)


with right:
    show_prep(r["checklist"])
    if r["options"]:
        st.markdown('<div class="note">ทางเลือก: ' + " · ".join(ui.esc(o) for o in r["options"]) + "</div>",
                    unsafe_allow_html=True)
    if place:
        st.markdown(f'<div class="panel" style="margin-top:10px;padding:10px 14px">{ui.icon("pin", ui.ORANGE, 16)} '
                    f'{ui.esc(place)}</div>', unsafe_allow_html=True)

advice_ph = st.empty()

# ---------------------------------------------------------------- บันทึกลงตาราง
u = ui.user()
if st.session_state.get("saved_msg"):
    st.success(st.session_state.saved_msg)
b1, b2, _ = st.columns([1.3, 1, 1.7])
if u:
    do_save = b1.button("เพิ่มลงตารางของฉัน", type="primary", **ui.FULL)
    if b2.button("ดูตารางของฉัน", **ui.FULL):
        st.switch_page("views/schedule.py")
else:
    do_save = False
    with b1.popover("เพิ่มลงตารางของฉัน", **ui.FULL):
        ui.login_box("เข้าสู่ระบบเพื่อบันทึกกิจกรรม", "plan")

# ---------------------------------------------------------------- เวลาที่ดีกว่า
if not indoor and r["verdict"] != "good" and not alts:
    st.markdown('<div class="section-title">เวลาที่ดีกว่า</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="panel">ช่วงใกล้เวลาเดิม ({start:%H:%M} น. ±4 ชม.) ใน 7 วันข้างหน้า ยังไม่มีช่วงไหนดีกว่านี้ '
                'ลองดูหน้า "พยากรณ์ 7 วัน" หรือเตรียมตัวตามรายการด้านบน</div>', unsafe_allow_html=True)
if alts:
    st.markdown('<div class="section-title">เวลาที่ดีกว่า (ช่วงเวลาใกล้เคียงกับที่คุณนัดไว้)</div>', unsafe_allow_html=True)
    for k, (col, a) in enumerate(zip(st.columns(len(alts)), alts)):
        lv = C.pm25_level(a["pm25"])
        col.markdown(f"""<div class="panel" style="border-top:5px solid {a['eval']['color']}">
<div class="note" style="margin:0">{ui.day_name(a['start'])}</div>
<div style="font-size:1.3rem;font-weight:700">{a['start']:%H:%M}–{a['end']:%H:%M} น.</div>
<div style="color:{a['eval']['color']};font-weight:700">{a['eval']['title']}</div>
<div style="margin-top:6px;font-size:.92rem">{ui.icon('dust', lv['color'], 15)} ฝุ่น {a['pm25']:.0f} ({lv['level']})<br>
{ui.icon('rain', ui.RAIN_BLUE, 15)} โอกาสฝน {a['rain']:.0f}%<br>{ui.icon('heat', ui.GREY, 15)} อุณหภูมิสูงสุด {a['temp']:.0f}°C</div></div>""",
                     unsafe_allow_html=True)
        if col.button("ใช้เวลานี้แทน", key=f"use_{k}", **ui.FULL):
            plan.update({"date": str(a["start"].date()), "start_hour": a["start"].hour})
            st.session_state.pop("saved_msg", None)
            st.rerun()

st.markdown('<p class="note" style="margin-top:18px">คำตัดสินมาจากเกณฑ์ของระบบ (ดูได้ในหน้า "ความแม่นและแหล่งข้อมูล") '
            'ยิ่งออกแรงมากหรือมีคนแพ้ฝุ่น เกณฑ์ฝุ่นยิ่งเข้มขึ้น AI ช่วยอ่านประโยคและอธิบายผล แต่ไม่ได้เปลี่ยนคำตัดสิน</p>',
            unsafe_allow_html=True)

# ---------------------------------------------------------------- AI อธิบาย (ทำท้ายสุด หน้าจึงขึ้นก่อนไม่ต้องรอ AI)
ai = None
if api_key:
    payload = json.dumps({
        "activity": plan["activity_name"], "intensity": P.INTENSITY[plan["intensity"]],
        "when": f"{ui.day_name(start)} {start:%H:%M}-{end:%H:%M}", "verdict": r["title"], "because": r["because"],
        "reasons": [{k: x[k] for k in ("topic", "value", "level", "meaning")} for x in r["reasons"]],
        "prepare": r["checklist"], "has_sensitive_people": plan["sensitive"],
        "where": "ในร่ม" if indoor else "กลางแจ้ง", "place": place,
        "forecast_reliability": r["confidence"],
        "better_times": [{"when": f"{ui.day_name(a['start'])} {a['start']:%H:%M}-{a['end']:%H:%M}",
                          "pm25_max": round(a["pm25"]), "rain_chance_max": round(a["rain"]),
                          "temp_max": round(a["temp"])} for a in alts]}, ensure_ascii=False)
    from agent import explain_plan
    try:
        advice_ph.markdown('<div class="advice" style="margin-top:16px;opacity:.7"><div class="who">AI อธิบายเพิ่ม</div>'
                           'กำลังอ่านผลประเมิน…</div>', unsafe_allow_html=True)
        ai = explain_plan(api_key, model, payload)
    except RuntimeError as e:
        advice_ph.caption(f"AI อธิบายไม่ได้ตอนนี้: {e}")

prep = r["checklist"] + [x for x in (ai["extra_prepare"] if ai else []) if x not in r["checklist"]]
if ai:
    show_prep(prep)
    if ai["advice"]:
        advice_ph.markdown(f'<div class="advice" style="margin-top:16px"><div class="who">AI อธิบายเพิ่ม</div>'
                           f'{ui.esc(ai["advice"])}</div>', unsafe_allow_html=True)
    else:
        advice_ph.empty()
if do_save:
    aid = store.add_activity(u["id"], plan["activity_name"], start, plan["duration_hours"], plan["intensity"],
                             plan["sensitive"], r["title"], prep, (ai or {}).get("one_liner") or None,
                             "indoor" if indoor else "outdoor")
    when = f'{ui.day_name(start, True)} {start:%H:%M} น.'
    st.session_state.saved_msg = (f'เพิ่ม "{plan["activity_name"]}" {when} ลงตารางแล้ว' if aid
                                  else f'"{plan["activity_name"]}" {when} อยู่ในตารางแล้ว')
    st.rerun()
