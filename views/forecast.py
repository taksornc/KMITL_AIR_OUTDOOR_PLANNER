"""หน้า: พยากรณ์ 7 วัน"""

import plotly.graph_objects as go
import streamlit as st

import config as C
import forecast as F
import ui

ui.brand_header("พยากรณ์ฝุ่นและอากาศ 7 วันข้างหน้า ทั้งวิทยาเขต")
res, err = ui.forecast()
if not res:
    st.info(err)
    st.stop()

fc = res["hourly"]
daily = F.daily_summary(fc)

# ---------------------------------------------------------------- ภาพรวม 7 วัน
st.markdown('<div class="section-title">ภาพรวมรายวัน</div>', unsafe_allow_html=True)
cards = []
for r in daily.itertuples():
    conf = C.confidence_label(int(r.min_horizon))
    cards.append(f'<div class="day"><div class="d">{ui.day_name(r.date)}</div>'
                 f'<div class="n" style="color:{r.color}">{r.pm25_mean:.0f}</div>'
                 f'<div class="l">{ui.dot(r.color)}{r.level}</div>'
                 f'<div class="r">{ui.icon("rain", ui.RAIN_BLUE, 13)}ฝน {r.rain_prob_max:.0f}%</div>'
                 f'<div class="r">{ui.icon("heat", ui.GREY, 13)}{r.temp_min:.0f}–{r.temp_max:.0f}°C</div>'
                 f'<div class="r">{conf["label"]}</div></div>')
st.markdown(f'<div class="days">{"".join(cards)}</div>', unsafe_allow_html=True)
st.markdown(f'<p class="note">ตัวเลขใหญ่คือฝุ่นเฉลี่ยทั้งวัน ({C.PM_UNIT}) · ฝน = โอกาสฝนสูงสุดของวัน · '
            f'ตัวเลข °C = อุณหภูมิต่ำสุด–สูงสุดของวัน · ยิ่งพยากรณ์ไกล ความแม่นยิ่งลดลง</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------- เลือกวัน
st.markdown('<div class="section-title">ดูรายชั่วโมง</div>', unsafe_allow_html=True)
days = list(daily["date"])
default = 1 if len(days) > 1 else 0
pick = st.radio("เลือกวัน", days, index=default, horizontal=True, format_func=ui.day_name,
                label_visibility="collapsed")
day = fc[fc["date"] == pick]
d = daily[daily["date"] == pick].iloc[0]
best = ui.best_window(day)

summary = (f"{ui.day_name(pick)} {ui.icon('dust', d.color, 16)} ฝุ่นเฉลี่ย <b>{d.pm25_mean:.0f} {C.PM_UNIT}</b> ({d.level}) "
           f"สูงสุดช่วง {int(d.peak_hour):02d}:00 น. · {ui.icon('rain', ui.RAIN_BLUE, 16)} โอกาสฝนสูงสุด <b>{d.rain_prob_max:.0f}%</b>")
if best:
    summary += f" ช่วงที่เหมาะออกไปข้างนอกที่สุดคือ <b>{best[0]:%H:%M}–{best[1]:%H:%M} น.</b>"
st.markdown(f"<p>{summary}</p>", unsafe_allow_html=True)

y_top = max(60, day["pm25"].max() * 1.2)
fig = go.Figure()
ui.aqi_bands(fig, y_top)
fig.add_bar(x=day["time"], y=day["pm25"], marker_color=day["color"], name="ฝุ่น PM2.5 (แท่ง สีตามระดับ) แกนซ้าย",
            customdata=day[["level", "precipitation_probability", "temperature_2m"]],
            hovertemplate="%{x|%H:%M} น.<br>ฝุ่น %{y:.0f} " + C.PM_UNIT +
                          " (%{customdata[0]})<br>โอกาสฝน %{customdata[1]:.0f}%<br>อุณหภูมิ %{customdata[2]:.0f}°C<extra></extra>")
fig.add_scatter(x=day["time"], y=day["precipitation_probability"], yaxis="y2", mode="lines+markers",
                line=dict(color=ui.RAIN_BLUE, width=2, dash="dot"), marker=dict(size=4), name="โอกาสฝน (%) แกนขวา",
                hoverinfo="skip")
if best:
    fig.add_vrect(x0=best[0], x1=best[1], fillcolor="#17202B", opacity=0.06, line_width=0,
                  annotation_text="ช่วงที่เหมาะที่สุด", annotation_position="top left", annotation_font_size=11)
ui.plotly_base(fig, 360)
fig.update_layout(bargap=0.15, yaxis=dict(title=f"ฝุ่น ({C.PM_UNIT})", range=[0, y_top]),
                  yaxis2=dict(title="โอกาสฝน (%)", overlaying="y", side="right", range=[0, 100], dtick=25, showgrid=False),
                  xaxis=dict(tickformat="%H:%M"))
st.plotly_chart(fig, config={"displayModeBar": False}, **ui.FULL)
st.markdown('<p class="note" style="margin-top:-8px">พยากรณ์ช่วงแรกเริ่มจากค่าจริงตอนนี้ แล้วค่อย ๆ ใช้ค่าจากโมเดล</p>',
            unsafe_allow_html=True)

# ---------------------------------------------------------------- เจาะรายชั่วโมง
hours = day["time"].dt.hour.tolist()
h = st.select_slider("เลือกเวลาเพื่อดูว่าทำไมฝุ่นถึงเป็นแบบนี้", options=hours,
                     value=17 if 17 in hours else hours[len(hours) // 2], format_func=lambda x: f"{x:02d}:00 น.")
r = day[day["time"].dt.hour == h].iloc[0]
lv, hl, conf = C.pm25_level(r["pm25"]), C.heat_level(r["temperature_2m"]), C.confidence_label(int(r["horizon"]))

left, right = st.columns([1, 1.5], gap="large")
with left:
    st.markdown(f"""<div class="panel"><div class="note" style="margin:0">{ui.day_name(pick)} เวลา {h:02d}:00 น.</div>
<div class="reading" style="margin-top:6px"><span class="num" style="color:{lv['color']};font-size:2.6rem">{r['pm25']:.0f}</span>
<span class="unit">{C.PM_UNIT}</span> {ui.chip(lv['level'], lv['color'])}</div>
{'<p style="margin:10px 0 4px;color:#1F5FAF">โอกาสฝนสูง ถ้าจะออกไปช่วงนี้ควรพกร่ม</p>' if r['precipitation_probability'] >= 50 else '<div style="height:8px"></div>'}
<div style="margin-top:4px;line-height:1.9">{ui.icon('rain', ui.RAIN_BLUE, 15)} โอกาสฝน {r['precipitation_probability']:.0f}%<br>
{ui.icon('heat', ui.GREY, 15)} อุณหภูมิ {r['temperature_2m']:.0f}°C ({hl['level']})<br>
{ui.icon('wind', ui.GREY, 15)} ลม {r['wind_speed_10m']:.0f} กม./ชม.</div>
<p class="note" style="margin:6px 0 0">ความแม่นของพยากรณ์ช่วงนี้: {conf['label']}</p></div>""",
                unsafe_allow_html=True)
with right:
    st.markdown("**ปัจจัยที่มีผลต่อฝุ่นในช่วงเวลานี้**")
    st.markdown(ui.reason_rows(F.explain_row(r)), unsafe_allow_html=True)
