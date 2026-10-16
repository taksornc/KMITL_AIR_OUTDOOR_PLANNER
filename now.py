"""หน้า: ตอนนี้ — ตอบคำถามเดียว 'ตอนนี้ออกไปข้างนอกได้ไหม'"""

import pandas as pd
import streamlit as st

import config as C
import store
import ui

sensitive = ui.is_sensitive()
cur, cur_err = ui.current()
res, fc_err = ui.forecast()
w, _ = ui.weather()
fc = res["hourly"] if res else None

ui.brand_header(f"ฝุ่นและอากาศตอนนี้ใน {C.KMITL_NAME}")

if cur:
    pm, source = cur["pm25"], ui.source_line(cur)
elif fc is not None:
    pm, source = float(fc["pm25"].iloc[0]), "เซนเซอร์และสถานีไม่ตอบกลับ ค่านี้มาจากโมเดลพยากรณ์ของระบบ"
else:
    st.error("ดึงข้อมูลฝุ่นไม่ได้ ลองกด 'ดึงข้อมูลล่าสุด' ในแถบด้านข้าง (กดลูกศรมุมซ้ายบน)")
    st.stop()
lv = C.pm25_level(pm)

# ข้อควรระวังจากปัจจัยอื่น (หัวข้อหลักพูดถึงฝุ่น จึงต้องบอกเรื่องฝนและความร้อนด้วยถ้ามีผล)
caveats = []
if w and w["temperature_c"] >= 37:
    caveats.append((ui.icon("heat", "#D64545", 17), f'ร้อนจัด {w["temperature_c"]:.0f}°C เลี่ยงแดดจัด'))
elif w and w["temperature_c"] >= 34:
    caveats.append((ui.icon("heat", "#B4532A", 17), f'อากาศร้อน {w["temperature_c"]:.0f}°C ดื่มน้ำบ่อย ๆ'))
if fc is not None:
    _n3 = fc[fc["horizon"] <= 3]
    rp3 = float(_n3["precipitation_probability"].fillna(0).max())
    if rp3 >= 50:
        _pk = _n3.loc[_n3["precipitation_probability"].fillna(0).idxmax(), "time"]
        caveats.append((ui.icon("rain", ui.RAIN_BLUE, 17), f"มีโอกาสฝนตก {rp3:.0f}% ช่วง {_pk:%H:%M} น. พกร่ม"))
# ฝนตอนนี้: ใช้ค่าเดียวกันทั้งหน้า (current_weather) วัดจริงจากสนามบิน ถ้าไม่มีจึงเป็นค่าแบบจำลอง
raining = bool(w and w["raining"])
if raining:
    caveats.append((ui.icon("rain", ui.RAIN_BLUE, 17),
                    f'สถานีตรวจอากาศใกล้ สจล. รายงาน{w["weather_text"] or "ฝนตก"} ฝนอาจกำลังมาหรือตกที่ สจล. พกร่มไว้' if w["observed"]
                    else "แบบจำลองคาดว่าตอนนี้อาจมีฝน พกร่มไว้"))
# หัวข้อหลักต้องไม่ขัดกับคำเตือนด้านล่าง: ถ้าฝุ่นไม่หนักแต่มีฝนหรือร้อน ให้หัวข้อพูดถึงด้วย
rainy = raining or any("ฝน" in t for _, t in caveats)
hot = any("ร้อน" in t for _, t in caveats)
headline = lv["headline"]
if lv["index"] <= 2 and (rainy or hot):
    extra = "อาจมีฝน" if rainy else ""
    if hot:
        extra = (extra + "และอากาศร้อน") if extra else "อากาศร้อน"
    headline = f"ฝุ่น{lv['level']} ออกไปข้างนอกได้ แต่{extra}"
caveat_html = "".join(f'<div style="display:flex;gap:8px;align-items:center;margin:2px 0 6px;font-size:1.05rem">'
                      f'{i}<span>{ui.esc(t)}</span></div>' for i, t in caveats)

# ---------------------------------------------------------------- อากาศตอนนี้ (แถบเดียวใต้ค่าฝุ่น)
wt = f'{w["time"][-5:]} น.' if w else ""
cells = []
if w:
    night = w["hour"] >= 18 or w["hour"] < 6
    cl, txt = w["cloud_percent"], w.get("weather_text") or ""
    if w["raining"] and ("หนัก" in txt or "คะนอง" in txt):
        sky, emo = txt, "⛈️"
    elif w["raining"]:
        sky, emo = (f'{txt or "ฝนตก"}บริเวณใกล้เคียง') if w["observed"] else "อาจมีฝน", "🌧️"
    elif txt:
        sky, emo = txt, "🌦️" if "ฝน" in txt else "🌫️"
    elif cl >= 80:
        sky, emo = "เมฆมาก ฟ้าครึ้ม", "☁️"
    elif cl >= 30:
        sky, emo = ("มีเมฆบางส่วน", "☁️" if night else "⛅")
    else:
        sky, emo = ("ฟ้าโปร่ง", "🌙") if night else ("แดดจัด ฟ้าใส", "☀️")
    uv = w.get("uv_index")
    sub = (f"เมฆ {cl:.0f}%" + (f" · UV {uv:.0f}" if uv is not None and not night and uv >= 3 else "")
           + (f" · สถานีตรวจอากาศใกล้ สจล. {w['sky_time']} น." if w["observed"] else " · แบบจำลอง")
           + ' · <a href="https://weather.tmd.go.th/" target="_blank">ดูเรดาร์ฝนสด</a>')
    cells.append(("sky", None, "ท้องฟ้าตอนนี้", f'<span style="font-size:1.25rem">{emo}</span> {sky}', sub))
if fc is not None:
    rp3 = fc[fc["horizon"] <= 3]
    rp = float(rp3["precipitation_probability"].fillna(0).max())
    pk = rp3.loc[rp3["precipitation_probability"].fillna(0).idxmax(), "time"]
    cells.append(("rain", ui.RAIN_BLUE, "โอกาสฝน", f"{rp:.0f}%",
                  ("ไม่น่าตก" if rp < 30 else "อาจตก พกร่ม" if rp < 60 else "น่าจะตก")
                  + (f" · {pk:%H:%M} น." if rp >= 30 else "")))
if w:
    cells.append(("heat", "#E8742A", "อุณหภูมิ", f'{w["temperature_c"]:.0f}°', C.heat_level(w["temperature_c"])["level"]))
    cells.append(("wind", ui.GREY, "ลม", f'{w["wind_kmh"]:.0f}<small> กม./ชม.</small>',
                  C.interpret_factor("wind", w["wind_kmh"])["level"]))
    cells.append(("humid", ui.GREY, "ความชื้น", f'{w["humidity_percent"]}%',
                  C.interpret_factor("humidity", w["humidity_percent"])["level"]))
wx_html = ""
if cells:
    wx_html = ('<div class="wxrow">' + "".join(
        f'<div class="wxc{" wsky" if k == "sky" else ""}"><div class="wk">{ui.icon(k, col, 15) if col else ""}{lab}</div><div class="wv">{val}</div>'
        f'<div class="ws">{sub}</div></div>' for k, col, lab, val, sub in cells) + '</div>'
        f'<div class="wxsrc">อากาศตอนนี้: {ui.esc(w["source"]) if w else "-"} · โอกาสฝนเป็นพยากรณ์ Open-Meteo 3 ชม. ข้างหน้า</div>')
st.markdown("""<style>
.wxrow{display:grid;grid-template-columns:repeat(4,1fr);margin-top:14px;border:1px solid var(--line,#e6e8ec);
 border-radius:16px;background:rgba(255,255,255,.75);overflow:hidden}
.wxc{padding:10px 12px;border-left:1px solid var(--line,#e6e8ec)}
.wxc:first-child{border-left:none}
.wk{display:flex;gap:5px;align-items:center;font-size:.8rem;color:#6b7280}
.wv{font-size:1.5rem;font-weight:700;line-height:1.25;margin-top:2px}
.wv small{font-size:.75rem;font-weight:500;color:#6b7280}
.ws{font-size:.8rem;color:#6b7280}
.wsky{grid-column:1 / -1;display:flex;align-items:center;gap:10px;flex-wrap:wrap;border-left:none;
 border-bottom:1px solid var(--line,#e6e8ec);background:rgba(255,255,255,.6)}
.wsky .wk{font-size:.8rem}.wsky .wv{font-size:1.05rem;margin:0}.wsky .ws{margin-left:auto}
.wxc:nth-child(2){border-left:none}
.wxsrc{font-size:.74rem;color:#8a8f98;margin-top:6px}
@media (max-width:640px){.wxrow{grid-template-columns:repeat(2,1fr)}
 .wxc:nth-child(4){border-left:none}.wxc:nth-child(n+4){border-top:1px solid var(--line,#e6e8ec)}}
</style>""", unsafe_allow_html=True)

left, right = st.columns([1.35, 1], gap="large")
with left:
    st.markdown(f"""
<div class="verdict">{ui.esc(headline)}</div>{caveat_html}
<div class="reading" style="margin-top:10px">{ui.icon('dust', lv['color'], 30)}<span class="num" style="color:{lv['color']}">{pm:.0f}</span>
<span class="unit">{C.PM_UNIT} (ฝุ่น PM2.5)</span> {ui.chip(lv['level'], lv['color'])}</div>
{ui.aqi_ruler(pm)}
<p class="note">{ui.esc(source)}</p>{wx_html}""", unsafe_allow_html=True)
with right:
    st.plotly_chart(ui.campus_map(cur, 250), config={"displayModeBar": False, "scrollZoom": False}, **ui.FULL)
    if cur and cur.get("poles"):
        vals = [p["pm25"] for p in cur["poles"]]
        st.markdown(f'<p class="note" style="margin-top:-6px">ค่าตอนนี้แต่ละจุดอยู่ระหว่าง {min(vals):.0f}–{max(vals):.0f} '
                    f'ระบบใช้ค่ากลาง {cur["pm25"]:.0f} เป็นตัวแทนทั้งวิทยาเขต (ชี้ที่จุดบนแผนที่เพื่อดูค่า)</p>',
                    unsafe_allow_html=True)
        with st.expander(f"ดูค่าฝุ่นตอนนี้ทั้ง {len(vals)} จุด"):
            st.markdown(ui.pole_table(cur), unsafe_allow_html=True)
            st.markdown(f'<p class="note"><b>แหล่งข้อมูล:</b> เซนเซอร์ฝุ่นบนเสาอัจฉริยะ {C.SMARTPOLE_CREDIT} '
                        f'<a href="{C.SMARTPOLE_BASE}" target="_blank">geo.scira.kmitl.ac.th</a> '
                        'ระบบดึงค่าใหม่ทุก 15 นาที</p>'
                        f'<p class="note"><b>ทำไมใช้ค่ากลาง (median) {cur["pm25"]:.0f}:</b> เรียงค่าทั้ง {len(vals)} จุดจากน้อยไปมาก '
                        'แล้วเลือกค่าที่อยู่ตรงกลาง ถ้ามีเซนเซอร์บางตัวอ่านค่าผิดปกติ เช่น ฝุ่นจากรถหรือการก่อสร้างข้างเสา '
                        'หรือเซนเซอร์เสีย ค่ากลางจะแทบไม่เปลี่ยน ต่างจากค่าเฉลี่ยที่ถูกค่าผิดปกติตัวเดียวดึงขึ้นหรือลงได้ '
                        'ค่ากลางจึงเป็นตัวแทนทั้งวิทยาเขตได้ดีกว่า</p>'
                        '<p class="note">พยากรณ์และการประเมินกิจกรรมใช้ค่ากลางนี้ค่าเดียวทั้งวิทยาเขต '
                        'ตารางนี้มีไว้ดูความต่างระหว่างจุด</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="note" style="margin-top:-6px">ทั้งวิทยาเขตใช้ค่าเดียวกัน</p>', unsafe_allow_html=True)


with st.expander("ข้อมูลแต่ละค่ามาจากไหน"):
    st.markdown(f'<p class="note">'
                f'• ฝุ่น PM2.5: {ui.esc(cur["source_text"]) if cur else "โมเดลพยากรณ์ของระบบ (เซนเซอร์และสถานีไม่ตอบกลับ)"}'
                f'{" วัดเมื่อ " + pd.Timestamp(cur["measured_at"]).strftime("%H:%M") + " น." if cur and cur.get("measured_at") else ""} '
                f'(ดึงใหม่ทุก 15 นาที ถ้าเซนเซอร์ใน สจล. ไม่ตอบ ระบบใช้สถานี Air4Thai ของกรมควบคุมมลพิษแทน)<br>'
                f'• ท้องฟ้า ฝนตอนนี้ อุณหภูมิ ลม ความชื้น: {ui.esc(w["source"]) if w else "-"} '
                f'(สถานีตรวจอากาศใกล้ สจล. คือสนามบินสุวรรณภูมิ VTBS ห่าง ~5 กม. รายงานทุก 30 นาที ถ้าดึงไม่ได้ใช้แบบจำลอง Open-Meteo แทน)<br>'
                f'• โอกาสฝน: พยากรณ์รายชั่วโมงของ Open-Meteo ใช้ค่าสูงสุดใน 3 ชม. ข้างหน้า<br>'
                f'• คำอธิบายระดับ เช่น สบาย ชื้นมาก ไม่น่าตก: เกณฑ์ของระบบ ดูได้ที่หน้า "ความแม่นและแหล่งข้อมูล"<br>'
                f'อัปเดตหน้านี้ล่าสุด {C.now_local():%d/%m/%Y %H:%M} น.</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- 24 ชั่วโมงข้างหน้า
best = None
if fc is not None:
    import planner
    fc24 = fc[fc["horizon"] <= 24]
    st.markdown('<div class="section-title">24 ชั่วโมงข้างหน้า</div>', unsafe_allow_html=True)

    # ให้ผู้ใช้เลือกช่วงที่สะดวกเอง ระบบหาช่วง 2 ชม. ที่ดีที่สุดในช่วงนั้น
    PERIODS = [("เช้า", 6, 11), ("กลางวัน", 11, 16), ("เย็น", 16, 20), ("ค่ำ", 20, 24)]
    now_t = C.now_local()
    end_t = fc24["time"].max() + pd.Timedelta(hours=1)
    picks = {}
    # สร้างช่วงจริงที่ยังมาไม่ถึงภายใน 24 ชม. แล้วเรียงตามเวลา (เช่น ตอนบ่าย: เย็นวันนี้ -> ค่ำวันนี้ -> เช้าพรุ่งนี้ -> กลางวันพรุ่งนี้)
    for d in (0, 1):
        day = (now_t + pd.Timedelta(days=d)).normalize()
        for name, a, b in PERIODS:
            p0, p1 = day + pd.Timedelta(hours=a), day + pd.Timedelta(hours=b)
            if p1 <= now_t + pd.Timedelta(hours=1) or p0 >= end_t:
                continue
            sub = fc24[(fc24["time"] >= max(p0, now_t.floor("h"))) & (fc24["time"] < p1)]
            win = ui.best_window(sub, 2, 0, 24) if len(sub) >= 2 else None
            if not win:
                continue
            try:
                ev = planner.evaluate(win[0], 2, "moderate", sensitive)
            except Exception:
                continue
            label = f'{name}{"วันนี้" if d == 0 else "พรุ่งนี้"}'
            picks[label] = (win, ev)
    picks = dict(sorted(picks.items(), key=lambda kv: kv[1][0][0])[:4])
    if picks:
        order = {"good": 0, "caution": 1, "bad": 2}
        default = min(picks, key=lambda k: (order[picks[k][1]["verdict"]], picks[k][0][0]))
        st.markdown('<p style="margin-bottom:4px">สะดวกออกไปช่วงไหน กดเลือกได้เลย '
                    'ระบบหาช่วง 2 ชม. ที่ดีที่สุดในช่วงนั้นให้ (เรียงจากใกล้ไปไกล)</p>', unsafe_allow_html=True)
        sel = st.segmented_control("ช่วงเวลา", list(picks), default=default, key="now_period",
                                   label_visibility="collapsed") if hasattr(st, "segmented_control") else default
        sel = sel or default
        cards = st.columns(len(picks))
        for col, (name, (win, ev)) in zip(cards, picks.items()):
            on = name == sel
            col.markdown(f'<div class="panel" style="padding:10px 12px;border-top:4px solid {ev["color"]};margin:0;'
                         f'{"outline:2px solid #E8742A;background:rgba(232,116,42,.06);" if on else ""}">'
                         f'<div style="font-weight:700">{name}</div>'
                         f'<div style="font-size:1.05rem">{win[0]:%H:%M}–{win[1]:%H:%M} น.</div>'
                         f'<div style="color:{ev["color"]};font-weight:700">{ui.esc(ev["title"])}</div></div>',
                         unsafe_allow_html=True)
        sel = sel or default
        best, ev = picks[sel]
        why = "" if ev["verdict"] == "good" else f' ({ui.esc(ev["because"])})'
        st.markdown(f'<p style="margin-top:10px">ช่วง{sel}ที่ดีที่สุดคือ <b>'
                    f'{best[0]:%H:%M}–{best[1]:%H:%M} น.</b> ผล: <b style="color:{ev["color"]}">{ui.esc(ev["title"])}</b>{why}</p>',
                    unsafe_allow_html=True)
    st.markdown(ui.hourly_strip(fc24, best), unsafe_allow_html=True)
elif fc_err:
    st.info(fc_err)

# ---------------------------------------------------------------- คำแนะนำ
parts = [lv["advice"]]
if w and w["temperature_c"] >= 37:
    parts.append("อากาศร้อนจัด เลี่ยงการอยู่กลางแดดนาน ๆ")
elif w and w["temperature_c"] >= 34:
    parts.append("อากาศค่อนข้างร้อน ดื่มน้ำบ่อย ๆ")
if raining:
    parts.append("ตอนนี้มีฝน พกร่มด้วย" if w["observed"] else "แบบจำลองคาดว่าอาจมีฝน พกร่มไว้ก็ดี")
elif fc is not None:
    _n = fc[fc["horizon"] <= 6]
    _r = float(_n["precipitation_probability"].fillna(0).max())
    if _r >= 30:
        _t = _n.loc[_n["precipitation_probability"].fillna(0).idxmax(), "time"]
        parts.append(f"แต่มีโอกาสฝน {_r:.0f}% ช่วง {_t:%H:%M} น. ถ้าจะออกไปช่วงนั้นพกร่มด้วย")
if sensitive and lv["index"] >= 2:
    parts.append("คนที่แพ้ฝุ่นหรือเป็นหอบหืดควรใส่หน้ากากเมื่ออยู่ข้างนอก")
st.markdown('<div class="section-title">คำแนะนำ</div>', unsafe_allow_html=True)
st.markdown(f'<div class="advice"><div class="who">สำหรับ{"คนที่แพ้ฝุ่นหรือเป็นหอบหืด" if sensitive else "คนทั่วไป"}</div>'
            f'{ui.esc(" ".join(parts))}</div>', unsafe_allow_html=True)

api_key, model = ui.gemini()
if api_key and res:
    hour_key = f"{C.now_local():%Y%m%d%H}"
    key = f"brief2_{hour_key}_{sensitive}"
    if key in st.session_state:
        st.markdown(f'<div class="advice"><div class="who">AI สรุปให้</div>{ui.esc(st.session_state[key])}</div>',
                    unsafe_allow_html=True)
    elif st.button("ให้ AI สรุปเพิ่มเติม"):
        from agent import quick_brief
        try:
            with st.spinner("AI กำลังอ่านข้อมูลล่าสุด..."):
                st.session_state[key] = quick_brief(api_key, model, sensitive, hour_key)
            st.rerun()
        except RuntimeError as e:
            st.warning(f"{e} (คำแนะนำด้านบนยังใช้ได้ตามปกติ)")

# ---------------------------------------------------------------- กิจกรรมวันนี้ของฉัน
u = ui.user()
if u:
    today = [a for a in store.list_activities(u["id"]) if a["start_ts"].date() == C.now_local().date()]
    if today:
        lines = "".join(f'<div style="margin-top:4px">{ui.icon("clock", ui.GREY, 15)} {a["start_ts"]:%H:%M} น. '
                        f'{ui.esc(a["title"])} <span class="note">({ui.until_text(a["start_ts"], a["end_ts"])})</span></div>'
                        for a in today)
        st.markdown(f'<div class="panel" style="margin-top:6px"><b>วันนี้คุณมี {len(today)} กิจกรรม</b>{lines}</div>',
                    unsafe_allow_html=True)

st.write("")
b1, b2, _ = st.columns([1.2, 1, 1.8])
if b1.button("วางแผนกิจกรรม", type="primary", **ui.FULL):
    st.switch_page("views/plan.py")
if b2.button("ถาม AI", **ui.FULL):
    st.switch_page("views/chat.py")
