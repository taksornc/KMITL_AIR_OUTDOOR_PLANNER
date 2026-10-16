"""หน้า: ความน่าเชื่อถือของระบบ (ประเมินโมเดล + ข้อจำกัด)"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as C
import forecast as F
import ui

ui.brand_header("ระบบแม่นแค่ไหน ข้อมูลมาจากไหน และตัดสินอย่างไร")
try:
    _, meta = F.load_model()
except F.ModelNotTrained as e:
    st.info(str(e))
    st.stop()

best = next(m for m in meta["metrics"] if m["model"] == meta["model_name"])
base = min(m["MAE"] for m in meta["metrics"] if m["model"].startswith("Baseline"))
gain = (base - best["MAE"]) / base

st.markdown(f"""<p>โมเดลพยากรณ์ฝุ่น ({meta['model_name']}) ทายคลาดเคลื่อนเฉลี่ย <b>{best['MAE']:.1f} {C.PM_UNIT}</b>
ซึ่ง{'ดีกว่า' if gain > 0 else 'ยังไม่ดีกว่า'}วิธีพื้นฐานที่ไม่ใช้ machine learning <b>{abs(gain):.0%}</b>
(ทดสอบกับข้อมูลช่วง {meta['test_from']} เป็นต้นไป ซึ่งโมเดลไม่เคยเห็นตอนเทรน)</p>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- ตาราง
st.markdown('<div class="section-title">ความคลาดเคลื่อนแยกตามระยะที่ทายล่วงหน้า</div>', unsafe_allow_html=True)
mt = pd.DataFrame(meta["metrics"]).set_index("model")
mt.index = [i.replace("Baseline: ค่าเท่าตอนนี้", "วิธีพื้นฐาน: ทายว่าเท่ากับตอนนี้")
             .replace("Baseline: ค่าเฉลี่ย 24 ชม.", "วิธีพื้นฐาน: ทายเท่าค่าเฉลี่ย 24 ชม.") for i in mt.index]
mt.columns = [c.replace("MAE ", "MAE ").replace("RMSE", "RMSE") for c in mt.columns]
st.dataframe(mt.style.highlight_min(axis=0, color="#FDE7D9").format("{:.2f}"), **ui.FULL)
st.markdown(f'<p class="note">MAE คือค่าคลาดเคลื่อนเฉลี่ย หน่วย {C.PM_UNIT} ยิ่งต่ำยิ่งดี ช่องสีส้มคือค่าที่ดีที่สุดในแต่ละคอลัมน์ '
            'แบ่งข้อมูลทดสอบตามเวลา ไม่สุ่ม เพื่อจำลองการใช้งานจริง</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- กราฟ
g1, g2 = st.columns(2, gap="large")
with g1:
    bt = pd.DataFrame(meta["backtest_24h"])
    if not bt.empty:
        bt["time"] = pd.to_datetime(bt["time"])
        fig = go.Figure()
        fig.add_scatter(x=bt["time"], y=bt["actual"], name="ค่าจริง", line=dict(color="#9AA3AE", width=1.5))
        fig.add_scatter(x=bt["time"], y=bt["predicted"], name="โมเดลทายล่วงหน้า 24 ชม.",
                        line=dict(color=ui.ORANGE, width=1.5))
        ui.plotly_base(fig, 320, "ค่าที่ทายเทียบกับค่าจริง ช่วงทดสอบ")
        fig.update_layout(legend=dict(orientation="h", y=-0.15, x=0))
        st.plotly_chart(fig, config={"displayModeBar": False}, **ui.FULL)
with g2:
    # รวมตัวแปรที่เป็นเรื่องเดียวกัน (ทิศลม 2 ตัว, ฤดูกาล 2 ตัว) แล้วคิดเป็น % ของความสำคัญทั้งหมด
    WHY = {
        "ฝุ่น": "ฝุ่นตอนนี้และช่วงที่ผ่านมา ฝุ่นมักค้างต่อเนื่องหลายชั่วโมง",
        "ช่วงเวลาของวัน": "ฝุ่นมักสูงช่วงเช้ามืดและค่ำ ต่ำช่วงบ่าย",
        "ลม": "ลมแรงพัดฝุ่นออกไป ลมนิ่งฝุ่นสะสม",
        "ทิศลม": "ลมจากบางทิศพาฝุ่นจากแหล่งอื่นเข้ามา",
        "ฤดูกาล": "ฝุ่นสูงช่วงหน้าหนาวถึงหน้าร้อน ต่ำหน้าฝน",
        "ฝน": "ฝนชะล้างฝุ่นในอากาศ",
        "ชั้นอากาศผสม": "ถ้าชั้นอากาศต่ำ ฝุ่นถูกกดไว้ใกล้พื้น",
        "ความชื้น": "อากาศชื้นทำให้ฝุ่นจับตัวและค้างในอากาศ",
        "ความกดอากาศ": "ความกดอากาศสูงมักมากับอากาศนิ่ง ฝุ่นสะสม",
        "อุณหภูมิและแดด": "อุณหภูมิ แดด และเมฆ มีผลต่อการลอยตัวของอากาศ",
        "มลพิษอื่น": "PM10 ไอเสียรถ และควันจากการเผา",
        "วันหยุด": "วันหยุดรถน้อยลง",
        "ระยะที่ทาย": "ยิ่งทายไกล ยิ่งพึ่งค่าตอนนี้น้อยลง",
    }
    def group(f):
        if f.startswith("o_pm_"): return "ฝุ่น"
        if f.startswith("o_"): return "มลพิษอื่น"
        if f == "t_hour": return "ช่วงเวลาของวัน"
        if f in ("t_wind", "t_gust", "t_wind_mean6", "t_calm12"): return "ลม"
        if f in ("t_wind_sin", "t_wind_cos"): return "ทิศลม"
        if f in ("t_doy_sin", "t_doy_cos"): return "ฤดูกาล"
        if f == "t_rain24" or "rain" in f or "precip" in f: return "ฝน"
        if f == "t_blh": return "ชั้นอากาศผสม"
        if f in ("t_dow", "t_weekend", "t_holiday"): return "วันหยุด"
        if f == "horizon": return "ระยะที่ทาย"
        if f in ("t_rh", "t_dew"): return "ความชื้น"
        if f == "t_pressure": return "ความกดอากาศ"
        return "อุณหภูมิและแดด"
    fi = pd.DataFrame(meta["feature_importance"])
    fi["g"] = fi["feature"].map(group)
    gs = fi.groupby("g")["importance"].sum().sort_values(ascending=False)
    gs = (gs / gs.sum() * 100).head(7)
    rows = "".join(
        f'<div style="margin:9px 0"><div style="display:flex;justify-content:space-between;font-size:.92rem">'
        f'<b>{ui.esc(g)}</b><span style="color:{ui.ORANGE};font-weight:700">{v:.0f}%</span></div>'
        f'<div style="background:#f1f2f4;border-radius:99px;height:9px;margin:3px 0">'
        f'<div style="width:{v / gs.iloc[0] * 100:.0f}%;height:9px;border-radius:99px;background:{ui.ORANGE}"></div></div>'
        f'<div class="note" style="margin:0">{ui.esc(WHY.get(g, ""))}</div></div>' for g, v in gs.items())
    st.markdown(f'<div class="panel"><b>โมเดลดูอะไรบ้างตอนทายฝุ่น</b>'
                f'<div class="note" style="margin:2px 0 6px">% คือสัดส่วนที่แต่ละเรื่องช่วยให้โมเดลทายแม่น (จากปัจจัยหลัก 15 ตัว) '
                f'ยิ่งมาก ยิ่งสำคัญ (ถ้าตัดเรื่องนั้นออก โมเดลจะทายพลาดเพิ่มขึ้นมาก)</div>{rows}</div>',
                unsafe_allow_html=True)

# ---------------------------------------------------------------- แหล่งข้อมูล
st.markdown('<div class="section-title">ข้อมูลแต่ละส่วนมาจากไหน</div>', unsafe_allow_html=True)
cur, _ = ui.current()
res, _ = ui.forecast()
om_row = ""
if res is not None:
    try:
        om_t = res["origin"]
        om_v = float(res["recent"].at[om_t, "pm2_5"])
        diff = (f"ค่าที่วัดจริงจาก Smart Pole คือ <b>{cur['pm25']:.0f}</b> ต่างกัน {cur['pm25'] - om_v:+.0f} "
                "ระบบใช้ส่วนต่างนี้ปรับพยากรณ์ช่วงแรก") if cur else ""
        om_row = (f'<div class="reason"><div class="t">{ui.icon("dust", ui.GREY, 17)}เทียบแบบจำลองกับค่าจริง</div>'
                  f'<div>Open-Meteo ณ {om_t:%H:%M} น. = <b>{om_v:.0f}</b> {C.PM_UNIT}'
                  f'<div class="m">{diff} (ค่าจากแบบจำลองเป็นค่าเฉลี่ยของพื้นที่กว้าง จึงต่างจากค่าที่วัดในรั้ว สจล. ได้)</div></div></div>')
    except Exception:
        om_row = ""
m1, m2 = st.columns([1.15, 1], gap="large")
with m1:
    st.markdown(f"""<div class="panel">
<div class="reason"><div class="t">{ui.icon('dust', ui.ORANGE, 17)}ฝุ่นตอนนี้</div><div>ค่ากลางของเซนเซอร์ {C.SMARTPOLE_CREDIT} ใน สจล.
<div class="m">ถ้าเซนเซอร์ไม่พร้อม ใช้สถานีกรมควบคุมมลพิษ (Air4Thai) ที่ใกล้ที่สุดแทน</div></div></div>
<div class="reason"><div class="t">{ui.icon('dust', ui.ORANGE, 17)}พยากรณ์ฝุ่น 7 วัน</div><div><b>โมเดล ML ของระบบ</b>
<div class="m">เทรนจากข้อมูล PM2.5 และสภาพอากาศย้อนหลังประมาณ 3 ปีของแบบจำลอง Open-Meteo (CAMS)
ในช่องตารางที่ครอบคลุม สจล. ช่วงแรกของพยากรณ์ปรับให้เริ่มจากค่าจริงของ Smart Pole แล้วค่อย ๆ ใช้ค่าจากโมเดล</div></div></div>{om_row}
<div class="reason"><div class="t">{ui.icon('rain', ui.RAIN_BLUE, 17)}ฝน อุณหภูมิ ลม</div><div>Open-Meteo
<div class="m">ใช้พยากรณ์โดยตรง ไม่ได้ผ่านโมเดลของระบบ</div></div></div>
<div class="reason"><div class="t">{ui.icon('pin', ui.GREY, 17)}พื้นที่</div><div>ค่าเดียวทั้งวิทยาเขต
<div class="m">ไม่แยกรายจุดหรือรายตึก เพราะเซนเซอร์ใน สจล. มีข้อมูลย้อนหลังแค่ 24 ชม. ไม่พอเทรนพยากรณ์รายจุด</div></div></div>
</div>""", unsafe_allow_html=True)
with m2:
    st.plotly_chart(ui.campus_map(cur, 330), config={"displayModeBar": False, "scrollZoom": False}, **ui.FULL)
    st.markdown('<p class="note" style="margin-top:-6px">ขอบเขตวิทยาเขตโดยประมาณ</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- เกณฑ์ตัดสิน
st.markdown('<div class="section-title">เกณฑ์ที่ใช้ตัดสินกิจกรรม</div>', unsafe_allow_html=True)
st.markdown(f"""<p>ดูค่าที่แย่ที่สุดตลอดช่วงเวลากิจกรรม แต่ละปัจจัยได้ผล เหมาะ / พอได้ / ไม่แนะนำ
แล้วใช้ผลที่แย่ที่สุดเป็นคำตัดสิน ถามซ้ำได้ผลเดิมเสมอ AI ไม่ได้เป็นผู้ตัดสิน</p>
<div class="panel">
<div class="reason"><div class="t">{ui.icon('dust', ui.ORANGE, 17)}ฝุ่น</div><div>
ออกแรงมาก หรือมีคนแพ้ฝุ่น: ดีขึ้นไป = เหมาะ, ปานกลาง = พอได้, เริ่มมีผลขึ้นไป = ไม่แนะนำ<br>
ออกแรงปานกลาง: ปานกลางถึงเริ่มมีผล = พอได้, มีผลต่อสุขภาพ = ไม่แนะนำ<br>
ออกแรงน้อย: ปานกลางลงมา = เหมาะ, เริ่มมีผล = พอได้, มีผลต่อสุขภาพ = ไม่แนะนำ
<div class="m">ระดับสีตามเกณฑ์กรมควบคุมมลพิษ ยิ่งออกแรงยิ่งหายใจแรง รับฝุ่นมากขึ้น</div></div></div>
<div class="reason"><div class="t">{ui.icon('rain', ui.RAIN_BLUE, 17)}ฝน</div><div>โอกาสฝนต่ำกว่า 30% = เหมาะ, 30–59% = พอได้, 60% ขึ้นไป = ไม่แนะนำ</div></div>
<div class="reason"><div class="t">{ui.icon('heat', ui.GREY, 17)}ความร้อน</div><div>อุณหภูมิต่ำกว่า 33°C = เหมาะ,
ถึง 38°C (ออกแรงมาก) หรือ 41°C (อื่น ๆ) = พอได้, สูงกว่านั้น = ไม่แนะนำ
<div class="m">อิงหมวดดัชนีความร้อน (Heat Index)</div></div></div>
</div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- ข้อจำกัด
st.markdown('<div class="section-title">ข้อจำกัด</div>', unsafe_allow_html=True)
limits = [
    ("ใช้ได้เฉพาะ สจล.", "โมเดลเทรนจากข้อมูลที่พิกัด สจล. ลาดกระบัง และให้ค่าเดียวทั้งวิทยาเขต"),
    ("ข้อมูลเทรนเป็นค่าจากแบบจำลอง", "ฝุ่นย้อนหลังมาจากแบบจำลอง CAMS ผ่าน Open-Meteo ซึ่งเฉลี่ยพื้นที่กว้าง "
                                       "ระบบจึงให้พยากรณ์ช่วงแรกเริ่มจากค่าที่วัดได้จริง"),
    ("ความแม่นวัดกับข้อมูลแบบจำลอง", "ค่า MAE ด้านบนทดสอบกับข้อมูลย้อนหลังของ Open-Meteo ยังไม่ได้ทดสอบกับเซนเซอร์ใน สจล. "
                                      "เพราะเซนเซอร์เก็บย้อนหลังได้แค่ 24 ชม."),
    ("ยิ่งทายไกลยิ่งคลาดเคลื่อน", "1 วันค่อนข้างแม่น 2–3 วันแม่นปานกลาง 4–7 วันใช้ดูแนวโน้ม"),
    ("ฝนและอุณหภูมิไม่ได้มาจากโมเดลของเรา", "ใช้พยากรณ์ของ Open-Meteo โดยตรง"),
    ("เกณฑ์บางส่วนกลุ่มกำหนดเอง", "เช่น เส้นแบ่งโอกาสฝน 30% และ 60% ส่วนระดับสีฝุ่นใช้เกณฑ์ของกรมควบคุมมลพิษ"),
    ("ไม่ใช่คำแนะนำทางการแพทย์", "ถ้ามีอาการผิดปกติ เช่น หายใจลำบาก ควรพบแพทย์"),
]
st.markdown('<div class="panel">' + "".join(
    f'<div class="reason"><div class="t">{t}</div><div class="m" style="color:var(--ink)">{d}</div></div>'
    for t, d in limits) + "</div>", unsafe_allow_html=True)
st.markdown(f'<p class="note">เทรนเมื่อ {meta["trained_at"]} จากข้อมูล {meta["data_range"][0]} ถึง {meta["data_range"][1]} '
            f'จำนวน {meta["n_train_rows"]:,} แถว ตัวแปรต้น {len(meta["features"])} ตัว</p>', unsafe_allow_html=True)
