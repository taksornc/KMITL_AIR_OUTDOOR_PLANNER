"""หน้า: สถิติย้อนหลัง — สำรวจข้อมูลเอง (เลือกช่วงเวลา/มุมมอง/ตัวแปร) + ผลทดสอบสถิติจากข้อมูลทั้งหมด"""

import functools

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as C
import data_sources as DS
import forecast as F
import ui

ui.brand_header("สถิติฝุ่นและอากาศย้อนหลังของ สจล.")

VARS = {  # ชื่อคอลัมน์: (ชื่อไทย, หน่วย, ไอคอน, สี, วิธีรวม)
    "pm2_5": ("ฝุ่น PM2.5", C.PM_UNIT, "dust", ui.ORANGE, "mean"),
    "precipitation": ("ฝน", "มม.", "rain", ui.RAIN_BLUE, "sum"),
    "temperature_2m": ("อุณหภูมิ", "°C", "heat", "#8C5A3C", "mean"),
    "relative_humidity_2m": ("ความชื้น", "%", "humid", "#3C8C8C", "mean"),
    "wind_speed_10m": ("ลม", "กม./ชม.", "wind", ui.GREY, "mean"),
}


@functools.lru_cache(maxsize=1)
def _history(mtime: float) -> pd.DataFrame:
    return pd.read_csv(C.HISTORY_FILE, parse_dates=["datetime"]).set_index("datetime")


def load_data() -> pd.DataFrame:
    if not C.HISTORY_FILE.exists():
        return pd.DataFrame()
    h = _history(C.HISTORY_FILE.stat().st_mtime)
    try:  # ต่อด้วยข้อมูล 3 วันล่าสุด ให้ดูถึงปัจจุบันได้
        recent, _ = DS.fetch_recent_and_forecast()
        recent = recent[recent.index <= C.now_local()]
        h = pd.concat([h, recent[~recent.index.isin(h.index)]]).sort_index()
    except Exception:
        pass
    return h[[c for c in VARS if c in h.columns]]


data = load_data()
if data.empty:
    st.info("ยังไม่มีข้อมูลย้อนหลัง ให้รันคำสั่ง python train.py ก่อน")
    st.stop()

first, last = data.index.min(), data.index.max()
st.markdown(f"<p>ข้อมูลรายชั่วโมงที่พิกัด สจล. ตั้งแต่ {first:%d/%m/%Y} ถึง {last:%d/%m/%Y %H:%M} น. "
            "เลือกช่วงเวลา มุมมอง และตัวแปรที่อยากดูได้เอง</p>", unsafe_allow_html=True)

# ---------------------------------------------------------------- ตัวเลือก
RANGES = {"1 วัน": 1, "7 วัน": 7, "1 เดือน": 30, "6 เดือน": 182, "1 ปี": 365, "ทั้งหมด": None, "กำหนดเอง": -1}
c1, c2 = st.columns([1.6, 1])
rng = c1.radio("ช่วงเวลา", list(RANGES), index=3, horizontal=True)
if RANGES[rng] == -1:
    dr = c2.date_input("เลือกวันที่", value=((last - pd.Timedelta(days=30)).date(), last.date()),
                       min_value=first.date(), max_value=last.date())
    a, b = (pd.Timestamp(dr[0]), pd.Timestamp(dr[1]) + pd.Timedelta(hours=23)) if len(dr) == 2 else (first, last)
elif RANGES[rng] is None:
    a, b = first, last
else:
    a, b = last - pd.Timedelta(days=RANGES[rng]), last
df = data.loc[a:b]
days = max((df.index.max() - df.index.min()).days + 1, 1) if not df.empty else 0
if df.empty:
    st.warning("ไม่มีข้อมูลในช่วงที่เลือก")
    st.stop()

views = ["ตามวันเวลา"]
if days >= 2:
    views.append("เฉลี่ยตามชั่วโมงของวัน")
if days >= 14:
    views.append("เฉลี่ยตามวันในสัปดาห์")
if days >= 120:
    views.append("เฉลี่ยตามเดือน")
d1, d2, d3, d4 = st.columns([1.2, 1, 1, 1])
view = d1.selectbox("มุมมอง", views)
var = d2.selectbox("ตัวแปร", list(VARS), format_func=lambda k: VARS[k][0])
cmp_opts = ["-"] + [k for k in VARS if k != var]
cmp = d3.selectbox("เทียบกับ", cmp_opts, format_func=lambda k: "ไม่เทียบ" if k == "-" else VARS[k][0])
res_opts = {"รายชั่วโมง": "h", "รายวัน": "D", "รายสัปดาห์": "W", "รายเดือน": "MS"}
allowed = [k for k, f in res_opts.items() if (f == "h" and days <= 31) or (f == "D" and 2 <= days <= 400)
           or (f == "W" and days >= 30) or (f == "MS" and days >= 120)] or ["รายชั่วโมง"]
default = "รายชั่วโมง" if days <= 7 else "รายวัน" if days <= 182 else "รายสัปดาห์"
resn = d4.selectbox("ความละเอียด", allowed, index=allowed.index(default) if default in allowed else 0,
                    disabled=view != "ตามวันเวลา")


def agg(s: pd.Series, how: str):
    if view == "ตามวันเวลา":
        if res_opts[resn] == "h":
            return s
        return s.resample(res_opts[resn]).sum(min_count=1) if how == "sum" else s.resample(res_opts[resn]).mean()
    key = {"เฉลี่ยตามชั่วโมงของวัน": s.index.hour, "เฉลี่ยตามวันในสัปดาห์": s.index.dayofweek,
           "เฉลี่ยตามเดือน": s.index.month}[view]
    if how == "sum" and view != "เฉลี่ยตามชั่วโมงของวัน":            # ฝนรวมต่อวัน แล้วเฉลี่ย
        daily = s.resample("D").sum(min_count=1)
        k2 = daily.index.dayofweek if view == "เฉลี่ยตามวันในสัปดาห์" else daily.index.month
        return daily.groupby(k2).mean()
    return s.groupby(key).mean()


def xlabels(idx):
    if view == "เฉลี่ยตามชั่วโมงของวัน":
        return [f"{h:02d}:00" for h in idx]
    if view == "เฉลี่ยตามวันในสัปดาห์":
        return [ui.DAYS_FULL[d] for d in idx]
    if view == "เฉลี่ยตามเดือน":
        return [ui.MONTHS[m] for m in idx]
    return idx


name, unit, ic, color, how = VARS[var]
y = agg(df[var], how).dropna()
fig = go.Figure()
x = xlabels(y.index)
if var == "pm2_5" and len(y) <= 400:
    fig.add_bar(x=x, y=y, marker_color=[C.pm25_level(v)["color"] for v in y], name=f"{name} ({unit})")
elif var == "precipitation":
    fig.add_bar(x=x, y=y, marker_color=ui.RAIN_BLUE, name=f"{name} ({unit})")
else:
    fig.add_scatter(x=x, y=y, mode="lines", line=dict(color=color, width=2), name=f"{name} ({unit})")
if cmp != "-":
    n2, u2, _, c2_, h2 = VARS[cmp]
    y2 = agg(df[cmp], h2).reindex(y.index)
    fig.add_scatter(x=x, y=y2, mode="lines", yaxis="y2", line=dict(color=c2_, width=2, dash="dot"), name=f"{n2} ({u2}) แกนขวา")
    fig.update_layout(yaxis2=dict(title=f"{n2} ({u2})", overlaying="y", side="right", showgrid=False))
if var == "pm2_5":
    fig.add_hline(y=C.STANDARD_PM25, line_dash="dot", line_color="#D64545", line_width=1,
                  annotation_text="ค่ามาตรฐานเฉลี่ย 24 ชม. 37.5", annotation_position="top left",
                  annotation_font=dict(size=11, color="#D64545"))
ui.plotly_base(fig, 380)
fig.update_layout(yaxis=dict(title=f"{name} ({unit})"), bargap=0.12, showlegend=cmp != "-")
st.plotly_chart(fig, config={"displayModeBar": False}, **ui.FULL)

# ---- สรุปตัวเลขของช่วงที่เลือก
s = df[var].dropna()
items = [ui.metric(ic, "ค่าเฉลี่ยทั้งช่วง", f"{s.mean():.1f}", unit, color),
         ui.metric(ic, "สูงสุด", f"{s.max():.1f}", f"{unit} · {s.idxmax():%d/%m/%y %H:%M} น.", color),
         ui.metric(ic, "ต่ำสุด", f"{s.min():.1f}", f"{unit} · {s.idxmin():%d/%m/%y %H:%M} น.", color)]
if var == "pm2_5":
    dm = s.resample("D").mean().dropna()
    items.append(ui.metric("dust", "วันที่เกินมาตรฐาน", f"{int((dm > C.STANDARD_PM25).sum())} วัน",
                           f"จาก {len(dm)} วัน (เฉลี่ยรายวันเกิน 37.5)", "#D64545"))
elif var == "precipitation":
    dm = s.resample("D").sum()
    items.append(ui.metric("rain", "ฝนรวม", f"{s.sum():.0f} มม.", f"ฝนตก {int((dm >= 1).sum())} จาก {len(dm)} วัน",
                           ui.RAIN_BLUE))
st.markdown(ui.metrics(items), unsafe_allow_html=True)
st.markdown('<p class="note" style="margin-top:14px">ฝุ่นย้อนหลังเป็นค่าจากแบบจำลองคุณภาพอากาศ (CAMS ผ่าน Open-Meteo) ที่พิกัด สจล. '
            'ใช้ดูรูปแบบและแนวโน้ม ค่าอาจต่ำกว่าที่เครื่องวัดจริงอ่านได้ในวันที่ฝุ่นหนัก</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- ผลทดสอบสถิติ (จากข้อมูลทั้งหมด ไม่เปลี่ยนตามช่วงที่เลือก)
stats = F.load_stats()
if stats:
    st.markdown('<div class="section-title">ข้อค้นพบหลักจากข้อมูลทั้งหมด</div>', unsafe_allow_html=True)
    a0, b0 = stats["data_range"]
    st.markdown(f"<p>ทดสอบจากข้อมูลรายวัน {stats['n_days']:,} วัน ({a0} ถึง {b0}) ด้วย Python (SciPy) "
                "ที่ระดับนัยสำคัญ 0.05 ผลส่วนนี้ใช้ข้อมูลทั้งหมดเสมอ ไม่เปลี่ยนตามช่วงที่เลือกด้านบน</p>",
                unsafe_allow_html=True)
    rows = []
    for t in stats["tests"]:
        p = "น้อยกว่า 0.001" if t["p_value"] < 0.001 else f"{t['p_value']:.3f}"
        if "rho" in t:
            detail = f"Spearman correlation, ρ = {t['rho']}, p = {p}, n = {t['n']} วัน"
        else:
            detail = (f"Mann-Whitney U, p = {p}, ขนาดอิทธิพล r = {t['effect_size_r']} ({t['effect_size_label']}), "
                      f"n = {t['n_a']} และ {t['n_b']} วัน")
        col = "#1E9E5A" if t["significant"] else "#9AA3AE"
        status = "มีนัยสำคัญ" if t["significant"] else "ไม่มีนัยสำคัญ"
        finding = t["finding"].replace("µg/m³", C.PM_UNIT).replace("ชั้นอากาศผสม", "ความสูงของชั้นอากาศที่ฝุ่นลอยได้")
        rows.append(f'<div class="finding">{ui.dot(col)}<b>{ui.esc(finding)}</b>'
                    f'<div class="meta">{status}: {detail}</div></div>')
    st.markdown(f'<div class="panel">{"".join(rows)}</div>', unsafe_allow_html=True)
