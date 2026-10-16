"""Tools ที่ให้ Gemini เรียกใช้ (function calling)
กฎ: ตัวเลขทุกตัวมาจาก tools เหล่านี้เท่านั้น LLM ห้ามคำนวณ/เดาเอง
ทุก tool คืน dict ที่อ่านง่าย มีทั้งค่า ระดับ และความหมาย
"""


import functools
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config as C
import forecast as F
from data_sources import fetch_current_pm

TOOL_LOG = []   # บันทึกว่า AI เรียก tool อะไร ได้ผลอะไร (แสดงในหน้าเว็บ)

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def _clean(o):
    """แปลงค่าให้เป็น JSON ได้ (Gemini ต้องการ)"""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else round(float(o), 1)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp, date)):
        return str(o)
    return o


def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = _clean(fn(*args, **kwargs))
        except (F.ModelNotTrained, ValueError) as e:
            result = {"error": str(e)}
        except Exception as e:
            result = {"error": f"ดึงข้อมูลไม่สำเร็จ: {e}"}
        TOOL_LOG.append({"tool": fn.__name__, "args": kwargs or dict(zip(fn.__code__.co_varnames, args)),
                         "result": result})
        return result
    return wrapper


def _parse_date(s: str) -> date:
    today = C.now_local().date()
    s = (s or "").strip().lower()
    words = {"today": 0, "วันนี้": 0, "tomorrow": 1, "พรุ่งนี้": 1, "มะรืน": 2, "มะรืนนี้": 2}
    if s in words:
        return today + timedelta(days=words[s])
    return pd.to_datetime(s).date()


def _day_label(d: date) -> str:
    diff = (d - C.now_local().date()).days
    rel = {0: "วันนี้", 1: "พรุ่งนี้", 2: "มะรืนนี้"}.get(diff, f"อีก {diff} วัน")
    return f"{rel} ({THAI_DAYS[d.weekday()]} {d:%d/%m/%Y})"


def _slice_day(fc: pd.DataFrame, d: date) -> pd.DataFrame:
    day = fc[fc["date"] == d]
    if day.empty:
        last = fc["date"].max()
        raise ValueError(f"พยากรณ์ได้ถึงวันที่ {last} เท่านั้น (ไม่เกิน 7 วันข้างหน้า และไม่ย้อนหลัง)")
    return day


# ======================================================================== tools
@logged
def get_current_air_quality() -> dict:
    """ค่าฝุ่น PM2.5 ตอนนี้ใน สจล. ลาดกระบัง จากเซนเซอร์ Smart Pole ภายในวิทยาเขต
    (ถ้าใช้ไม่ได้จะใช้สถานีของกรมควบคุมมลพิษที่ใกล้ที่สุด) พร้อมระดับสีและคำแนะนำ
    ใช้เมื่อผู้ใช้ถามว่า 'ตอนนี้ฝุ่นเป็นยังไง'"""
    s = fetch_current_pm()
    lv = C.pm25_level(s["pm25"])
    return {"location": C.KMITL_NAME, "pm25": s["pm25"], "unit": C.PM_UNIT,
            "level": lv["level"], "advice": lv["advice"], "source": s["source_text"],
            "measured_at": s["measured_at"],
            "note": None if s["is_fresh"] else f'ข้อมูลอาจไม่เป็นปัจจุบัน (วัดเมื่อ {s["age_hours"]} ชม.ก่อน)'}


@logged
def get_current_weather() -> dict:
    """สภาพอากาศตอนนี้: ฝนตกไหม เมฆ อุณหภูมิ ความชื้น ลม (วัดจริงที่สนามบินสุวรรณภูมิ ถ้าไม่มีใช้แบบจำลอง Open-Meteo)
    ใช้ค่า raining และ weather_text ตอบว่าตอนนี้ฝนตกหรือไม่ และบอกที่มาจาก source"""
    return F.current_weather()


@logged
def get_pm25_forecast(date: str, hour: int = -1) -> dict:
    """พยากรณ์ฝุ่น PM2.5 บริเวณ KMITL จากโมเดล machine learning ของระบบ ล่วงหน้าได้ไม่เกิน 7 วัน

    Args:
        date: วันที่ต้องการ รูปแบบ YYYY-MM-DD หรือคำว่า today / tomorrow
        hour: ชั่วโมง 0-23 ที่ต้องการ ถ้า -1 จะสรุปทั้งวัน (ค่าเฉลี่ย ค่าสูงสุด และช่วงเวลาที่ฝุ่นสูง/ต่ำ)
    """
    res = F.get_forecast()
    d = _parse_date(date)
    day = _slice_day(res["hourly"], d)
    if hour is None or hour < 0:
        lv = C.pm25_level(day["pm25"].mean())
        peak, low = day.loc[day["pm25"].idxmax()], day.loc[day["pm25"].idxmin()]
        every3 = day[day["time"].dt.hour % 3 == 0]
        return {"day": _day_label(d), "pm25_daily_mean": day["pm25"].mean(), "pm25_max": peak["pm25"],
                "level_daily": lv["level"], "advice": lv["advice"],
                "highest_at": f'{peak["time"]:%H:00}', "lowest_at": f'{low["time"]:%H:00}',
                "by_3_hours": [{"time": f'{r.time:%H:00}', "pm25": r.pm25, "level": r.level} for r in every3.itertuples()],
                "why": F.explain_row(peak)[:3],
                "confidence": C.confidence_label(int(day["horizon"].min()))["label"],
                "source": "โมเดล ML ของระบบ (ช่วงแรกเริ่มจากค่าจริงตอนนี้)"}
    hour = int(hour)
    row = day[day["time"].dt.hour == hour]
    if row.empty:
        raise ValueError(f"ไม่มีข้อมูลพยากรณ์ช่วง {hour:02d}:00 ของ{_day_label(d)} (อาจเป็นเวลาที่ผ่านไปแล้ว)")
    r = row.iloc[0]
    lv = C.pm25_level(r["pm25"])
    return {"time": f'{_day_label(d)} {hour:02d}:00', "pm25": r["pm25"], "level": lv["level"],
            "advice": lv["advice"], "why": F.explain_row(r)[:3],
            "confidence": C.confidence_label(int(r["horizon"]))["label"],
            "note": "เกณฑ์ระดับสีอ้างอิงค่าเฉลี่ย 24 ชม. ค่ารายชั่วโมงใช้ประกอบเท่านั้น",
            "source": "โมเดล ML ของระบบ"}


@logged
def get_weather_forecast(date: str, hour: int = -1) -> dict:
    """พยากรณ์อากาศบริเวณ KMITL (ฝน โอกาสฝนตก อุณหภูมิ ลม UV) ล่วงหน้าไม่เกิน 7 วัน จาก Open-Meteo

    Args:
        date: วันที่ YYYY-MM-DD หรือ today / tomorrow
        hour: ชั่วโมง 0-23 ถ้า -1 จะสรุปทั้งวันพร้อมรายชั่วโมงทุก 3 ชั่วโมง
    """
    res = F.get_forecast()
    d = _parse_date(date)
    day = _slice_day(res["hourly"], d)

    def one(r):
        hl = C.heat_level(r.temperature_2m)
        return {"time": f"{r.time:%H:00}", "rain_chance_percent": r.precipitation_probability,
                "rain_mm": r.precipitation, "temperature_c": r.temperature_2m,
                "heat_level": hl["level"],
                "wind_kmh": r.wind_speed_10m, "uv_index": r.uv_index}

    if hour is None or hour < 0:
        rainy = day[day["precipitation_probability"] >= 50]
        return {"day": _day_label(d), "rain_chance_max_percent": day["precipitation_probability"].max(),
                "rain_total_mm": day["precipitation"].sum(),
                "likely_rain_hours": [f"{t:%H:00}" for t in rainy["time"]],
                "temp_max_c": day["temperature_2m"].max(), "temp_min_c": day["temperature_2m"].min(),
                "heat_level_peak": C.heat_level(day["temperature_2m"].max())["level"],
                "by_3_hours": [one(r) for r in day[day["time"].dt.hour % 3 == 0].itertuples()],
                "source": "Open-Meteo"}
    row = day[day["time"].dt.hour == int(hour)]
    if row.empty:
        raise ValueError(f"ไม่มีข้อมูลช่วง {int(hour):02d}:00 ของ{_day_label(d)}")
    out = one(next(row.itertuples()))
    out.update({"day": _day_label(d), "source": "Open-Meteo"})
    return out


@logged
def find_best_outdoor_times(days: int = 3, earliest_hour: int = 6, latest_hour: int = 21,
                            duration_hours: int = 2) -> dict:
    """หาช่วงเวลาที่เหมาะกับกิจกรรมกลางแจ้งที่สุด 3 ช่วง (เช่น เตะบอล วิ่ง จัดงาน) โดยดูฝุ่น ฝน และความร้อนรวมกัน

    Args:
        days: ค้นหาภายในกี่วันข้างหน้า (1-7)
        earliest_hour: เริ่มได้เร็วสุดกี่โมง (0-23)
        latest_hour: ต้องเสร็จไม่เกินกี่โมง (1-24)
        duration_hours: กิจกรรมใช้เวลากี่ชั่วโมง
    """
    import planner
    picks = planner.better_times(max(1, int(duration_hours)), int(max(1, min(days, 7))),
                                 int(earliest_hour), int(latest_hour))
    if not picks:
        raise ValueError("ไม่พบช่วงเวลาที่ตรงเงื่อนไข")
    return {"best_windows": [{"when": f'{_day_label(p["start"].date())} {p["start"]:%H:%M}–{p["end"]:%H:%M} น.',
                              "pm25_avg": p["pm25"], "pm25_level": C.pm25_level(p["pm25"])["level"],
                              "rain_chance_max_percent": p["rain"], "temp_max_c": p["temp"]} for p in picks],
            "criteria": "ฝุ่นต่ำ โอกาสฝนต่ำ และไม่ร้อนเกินไป",
            "source": "พยากรณ์ฝุ่นจากโมเดลของระบบ และพยากรณ์อากาศจาก Open-Meteo"}


@logged
def evaluate_activity_plan(date: str, start_hour: int, duration_hours: int = 2,
                           intensity: str = "moderate", sensitive: bool = False) -> dict:
    """ประเมินว่าแผนกิจกรรมกลางแจ้งเหมาะหรือไม่ ด้วยเกณฑ์ของระบบ (ฝุ่น ฝน ความร้อน ตลอดช่วงเวลา)
    ต้องใช้คำตัดสิน (verdict) ตามที่ tool คืนมาเท่านั้น

    Args:
        date: วันที่ YYYY-MM-DD หรือ today / tomorrow
        start_hour: เริ่มกี่โมง (0-23)
        duration_hours: ใช้เวลากี่ชั่วโมง
        intensity: 'heavy' (หอบ เหงื่อออกมาก เช่น วิ่ง กีฬา ซ้อมเชียร์), 'moderate' (เดิน จัดบูธ),
                   'light' (ยืนหรือนั่งเป็นส่วนใหญ่ เช่น ถ่ายรูป กินข้าว)
        sensitive: มีคนแพ้ฝุ่นหรือเป็นหอบหืดร่วมกิจกรรมหรือไม่
    """
    import planner
    start = pd.Timestamp(_parse_date(date)) + pd.Timedelta(hours=int(start_hour))
    r = planner.evaluate(start, max(1, int(duration_hours)), intensity, bool(sensitive))
    return {"plan": f'{_day_label(start.date())} {start:%H:%M} น. นาน {r["hours"]} ชม.',
            "verdict": r["title"], "because": r["because"],
            "reasons": [{k: x[k] for k in ("topic", "value", "level", "meaning")} for x in r["reasons"]],
            "prepare": r["checklist"], "options_if_not_good": r["options"],
            "forecast_reliability": r["confidence"]}


@logged
def get_dust_statistics() -> dict:
    """ข้อค้นพบทางสถิติจากข้อมูลย้อนหลังของ KMITL (คำนวณด้วย Python) และความแม่นของโมเดล
    ใช้เมื่อผู้ใช้ถามว่า ทำไมฝุ่นสูง / ฝนช่วยไหม / ช่วงไหนฝุ่นเยอะ / โมเดลแม่นแค่ไหน"""
    st = F.load_stats() or {}
    _, meta = F.load_model()
    best = next(m for m in meta["metrics"] if m["model"] == meta["model_name"])
    return {"findings": st.get("summary", []), "data_range": st.get("data_range"),
            "worst_hour": st.get("worst_hour"), "best_hour": st.get("best_hour"),
            "model": meta["model_name"], "model_mae_ugm3": best["MAE"],
            "beats_baseline": meta["beats_baseline"],
            "top_factors": [f["name_th"] for f in meta["feature_importance"][:5]]}


KNOWLEDGE_TOPICS = {
    "aqi": "01_aqi_levels.md", "health": "02_health_advice.md",
    "outdoor": "03_outdoor_activity.md", "system": "04_about_system.md",
    "places": "05_campus_places.md",
}


@logged
def read_knowledge(topic: str) -> dict:
    """อ่านฐานความรู้ของระบบ ใช้ทุกครั้งก่อนให้คำแนะนำด้านสุขภาพหรือกิจกรรม

    Args:
        topic: หัวข้อ 'aqi' (เกณฑ์ระดับสี PM2.5), 'health' (คำแนะนำสุขภาพ กลุ่มเสี่ยง หน้ากาก),
               'outdoor' (กีฬา/วิ่ง/จัดงาน + ฝน + ความร้อน), 'system' (ที่มาของข้อมูลและข้อจำกัดของระบบ),
               'places' (สถานที่ใน สจล. สนามกีฬา โรงยิม อาคาร โซนหอใน หอนอก ระยะทาง รถ EV)
    """
    fname = KNOWLEDGE_TOPICS.get((topic or "").strip().lower())
    if not fname:
        raise ValueError(f"ไม่มีหัวข้อนี้ เลือกได้: {list(KNOWLEDGE_TOPICS)}")
    return {"topic": topic, "content": (C.KNOWLEDGE_DIR / fname).read_text(encoding="utf-8")}


ALL_TOOLS = [get_current_air_quality, get_current_weather, get_pm25_forecast, get_weather_forecast,
             find_best_outdoor_times, evaluate_activity_plan, get_dust_statistics, read_knowledge]

if __name__ == "__main__":   # ทดสอบ tools โดยไม่ผ่าน LLM: python tools.py
    for fn, kw in [(get_current_air_quality, {}), (get_current_weather, {}),
                   (get_pm25_forecast, {"date": "tomorrow"}), (get_pm25_forecast, {"date": "tomorrow", "hour": 17}),
                   (get_weather_forecast, {"date": "tomorrow"}), (find_best_outdoor_times, {}),
                   (get_dust_statistics, {})]:
        print(f"\n===== {fn.__name__}({kw})")
        print(json.dumps(fn(**kw), ensure_ascii=False, indent=1)[:1200])
