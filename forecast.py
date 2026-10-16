"""เครื่องยนต์พยากรณ์: โหลดโมเดล -> ดึงข้อมูลล่าสุด -> ทาย PM2.5 รายชั่วโมง 7 วัน -> สรุป/อธิบายผล"""

from __future__ import annotations

import functools
import json

import joblib
import time

import numpy as np
import pandas as pd

import config as C
from data_sources import fetch_current_pm, fetch_recent_and_forecast, ttl_cache
from features import inference_rows, origin_frame, target_frame

SHOW_COLS = ["temperature_2m", "apparent_temperature", "relative_humidity_2m", "precipitation",
             "precipitation_probability", "wind_speed_10m", "uv_index", "boundary_layer_height"]


class ModelNotTrained(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def load_model():
    if not C.MODEL_FILE.exists() or not C.META_FILE.exists():
        raise ModelNotTrained("ยังไม่มีโมเดล กรุณารัน: python train.py")
    return joblib.load(C.MODEL_FILE), json.loads(C.META_FILE.read_text(encoding="utf-8"))


def load_stats() -> dict | None:
    return json.loads(C.STATS_FILE.read_text(encoding="utf-8")) if C.STATS_FILE.exists() else None


@ttl_cache(seconds=1800)
def get_forecast() -> dict:
    """คืน dict: hourly (DataFrame พยากรณ์รายชั่วโมง), origin, is_stale, bias, station"""
    model, meta = load_model()
    h, stale = fetch_recent_and_forecast()
    now = C.now_local().floor("h")

    pm_known = h.loc[h.index <= now, "pm2_5"].dropna()
    if pm_known.empty:
        raise RuntimeError("ไม่มีข้อมูลฝุ่นล่าสุดสำหรับเริ่มพยากรณ์")
    origin = pm_known.index[-1]

    rows = inference_rows(h, origin, C.MAX_HORIZON_H)
    rows = rows[rows["target_time"] > now].reset_index(drop=True)
    feats, med = meta["features"], pd.Series(meta["medians"])
    pred = model.predict(rows[feats].fillna(med))

    # ให้พยากรณ์เริ่มจากค่าจริงตอนนี้ (Smart Pole หรือสถานี) แล้วค่อย ๆ กลับไปใช้ค่าจากโมเดล
    # ส่วนต่างจะเหลือราว 1 ใน 3 ภายใน 24 ชม. และแทบหมดไปภายใน 3 วัน
    current, offset = None, 0.0
    try:
        current = fetch_current_pm()
        if current["is_fresh"]:
            offset = current["pm25"] - float(h.at[origin, "pm2_5"])
    except Exception:
        pass
    adj = np.clip(pred + offset * np.exp(-rows["horizon"].to_numpy() / 24), 0, None)

    out = pd.DataFrame({"time": rows["target_time"], "horizon": rows["horizon"],
                        "pm25": adj.round(1), "pm25_model": pred.round(1)})
    tf = target_frame(h)
    for c in SHOW_COLS:
        out[c] = h[c].reindex(out["time"]).to_numpy() if c in h.columns else np.nan
    out["wind_mean6"] = tf["t_wind_mean6"].reindex(out["time"]).to_numpy()
    out["rain24"] = tf["t_rain24"].reindex(out["time"]).to_numpy()
    out["trend24"] = float(origin_frame(h).at[origin, "o_pm_trend24"])
    lv = out["pm25"].apply(C.pm25_level)
    out["level"], out["color"], out["emoji"] = lv.str["level"], lv.str["color"], lv.str["emoji"]
    out["date"] = out["time"].dt.date
    return {"hourly": out, "origin": origin, "is_stale": stale, "bias_offset": round(offset, 1),
            "current": current, "recent": h}


_METAR_FAIL = 0.0


def current_weather() -> dict:
    """อากาศตอนนี้: ใช้ค่าที่วัดจริงจากสนามบินสุวรรณภูมิเป็นหลัก (ถ้าอายุไม่เกิน 2 ชม.)
    ถ้าดึงไม่ได้ ใช้ค่าจากแบบจำลอง Open-Meteo ของชั่วโมงนี้แทน — ทุกหน้า AI และอีเมลใช้ผลจากฟังก์ชันนี้ที่เดียว"""
    h, stale = fetch_recent_and_forecast()
    now = C.now_local().floor("h")
    row = h.loc[h.index <= now].iloc[-1]
    model_rain = float(row["precipitation"]) if pd.notna(row["precipitation"]) else 0.0
    w = {
        "time": row.name.strftime("%Y-%m-%d %H:%M"),
        "temperature_c": round(row["temperature_2m"], 1),
        "humidity_percent": round(row["relative_humidity_2m"]),
        "wind_kmh": round(row["wind_speed_10m"], 1),
        "rain_mm_last_hour": round(model_rain, 1),
        "cloud_percent": round(row["cloud_cover"]) if pd.notna(row.get("cloud_cover", np.nan)) else 0,
        "hour": int(C.now_local().hour),
        "uv_index": round(row.get("uv_index", np.nan), 1) if pd.notna(row.get("uv_index", np.nan)) else None,
        "observed": False, "raining": model_rain >= 0.2, "weather_text": None,
        "source": f"แบบจำลอง Open-Meteo ชั่วโมง {row.name:%H:%M} น.", "source_short": "Open-Meteo",
        "is_stale": stale,
    }
    global _METAR_FAIL
    if C.env_flag("USE_METAR", True) and time.time() - _METAR_FAIL > 600:
        try:
            from data_sources import fetch_metar
            m = fetch_metar()
            if m["age_hours"] <= 2:
                # อุณหภูมิ ความชื้น ลม ยังใช้ Open-Meteo ที่พิกัด สจล. / ใช้สนามบินเฉพาะยืนยันว่าฝนตกจริงไหมและสภาพท้องฟ้า
                w.update({"cloud_percent": m["cloud_percent"], "raining": m["raining"], "observed": True,
                          "weather_text": m["weather_text"], "rain_mm_last_hour": w["rain_mm_last_hour"] if m["raining"] else 0.0,
                          "sky_time": m["time"].strftime("%H:%M"),
                          "source": f"อุณหภูมิ ลม ความชื้น: Open-Meteo พิกัด สจล. ชั่วโมง {row.name:%H:%M} น. · "
                                    f"ฝนและท้องฟ้า: วัดจริงที่สถานีตรวจอากาศใกล้ สจล. {m['time']:%H:%M} น.",
                          "source_short": "สถานีตรวจอากาศใกล้ สจล."})
        except Exception:
            _METAR_FAIL = time.time()        # ดึงไม่ได้ เว้น 10 นาทีค่อยลองใหม่ หน้าเว็บจะได้ไม่ช้า
    hl = C.heat_level(w["temperature_c"])
    w["heat_level"] = hl["level"]
    w["factors"] = [C.interpret_factor("wind", w["wind_kmh"]), C.interpret_factor("humidity", w["humidity_percent"])]
    return w


def explain_row(r: pd.Series) -> list[dict]:
    """แปลปัจจัยของชั่วโมงที่ทาย ให้เป็นภาษาคน (เรียงปัจจัยที่ทำให้ฝุ่นสูงขึ้นก่อน)"""
    items = []
    for kind, val in [("wind", r["wind_mean6"]), ("blh", r["boundary_layer_height"]),
                      ("rain24", r["rain24"]), ("humidity", r["relative_humidity_2m"]), ("trend", r["trend24"])]:
        if pd.notna(val):
            it = C.interpret_factor(kind, val)
            if kind == "wind":
                it["factor"] = "ลมช่วง 6 ชม.ก่อนหน้า"
            items.append(it)
    order = {"bad": 0, "mid": 1, "good": 2}
    return sorted(items, key=lambda x: order[x["status"]])


def daily_summary(fc: pd.DataFrame) -> pd.DataFrame:
    g = fc.groupby("date")
    d = pd.DataFrame({
        "pm25_mean": g["pm25"].mean().round(1), "pm25_max": g["pm25"].max().round(1),
        "peak_hour": fc.loc[g["pm25"].idxmax(), "time"].dt.hour.to_numpy(),
        "rain_prob_max": g["precipitation_probability"].max(), "rain_mm": g["precipitation"].sum().round(1),
        "temp_max": g["temperature_2m"].max().round(1), "temp_min": g["temperature_2m"].min().round(1),
        "hours": g.size(), "min_horizon": g["horizon"].min(),
    }).reset_index()
    lv = d["pm25_mean"].apply(C.pm25_level)
    d["level"], d["color"], d["emoji"] = lv.str["level"], lv.str["color"], lv.str["emoji"]
    return d
