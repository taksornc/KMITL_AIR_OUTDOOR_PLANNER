"""ดึงข้อมูลจาก API: Open-Meteo (อากาศ + มลพิษ) และ Air4Thai (ค่าฝุ่นจริงจากสถานี)"""

from __future__ import annotations

import functools
import time
from datetime import timedelta

import numpy as np
import pandas as pd
import requests
import urllib3

import config as C

HEADERS = {"User-Agent": "KMITL-Air-student-project/1.0"}


# ---------------------------------------------------------------- utilities
def ttl_cache(seconds: int):
    """cache ผลลัพธ์ตามเวลา (ใช้ได้ทั้งใน Streamlit และสคริปต์ธรรมดา)"""
    def deco(fn):
        store: dict = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            hit = store.get(key)
            if hit and time.time() - hit[0] < seconds:
                return hit[1]
            value = fn(*args, **kwargs)
            store[key] = (time.time(), value)
            return value

        wrapper.cache_clear = store.clear
        return wrapper
    return deco


def _get(url: str, params: dict | None = None, verify: bool = True, timeout: int = 60,
         retries: int = 3) -> requests.Response:
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout, verify=verify)
            if r.status_code == 400:      # 400 = พารามิเตอร์ผิด ไม่ต้อง retry
                return r
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"เรียก {url.split('/')[2]} ไม่สำเร็จ: {last}")


def _get_hourly(url: str, params: dict, variables: list[str]) -> pd.DataFrame:
    """ดึงตัวแปรรายชั่วโมง ถ้า API ไม่รองรับตัวแปรไหน จะตัดทิ้งแล้วลองใหม่อัตโนมัติ"""
    variables = list(variables)
    while variables:
        r = _get(url, {**params, "hourly": ",".join(variables)})
        if r.ok:
            df = pd.DataFrame(r.json()["hourly"]).rename(columns={"time": "datetime"})
            df["datetime"] = pd.to_datetime(df["datetime"])
            return df
        reason = r.text
        bad = [v for v in variables if v in reason]
        if not bad:
            raise RuntimeError(f"{url} -> {r.status_code}: {reason[:200]}")
        print(f"  ! API ไม่รองรับ {bad} -> ตัดทิ้ง")
        variables = [v for v in variables if v not in bad]
    raise RuntimeError("ไม่เหลือตัวแปรให้ดึง")


def _base_params() -> dict:
    return {"latitude": C.KMITL_LAT, "longitude": C.KMITL_LON, "timezone": C.TZ}


def _to_hourly_index(df: pd.DataFrame) -> pd.DataFrame:
    """ทำให้เป็นรายชั่วโมงต่อเนื่อง และเติมช่องว่างสั้น ๆ"""
    df = df.drop_duplicates("datetime").set_index("datetime").sort_index()
    df = df.asfreq("h")
    num = df.select_dtypes("number").columns
    df[num] = df[num].interpolate(limit=3, limit_area="inside")
    return df


# ---------------------------------------------------------------- ข้อมูลย้อนหลัง (ใช้เทรน)
def fetch_history(days: int = C.HISTORY_DAYS) -> pd.DataFrame:
    end = C.now_local().date() - timedelta(days=2)   # archive ช้ากว่าปัจจุบันเล็กน้อย
    start = end - timedelta(days=days)
    p = {**_base_params(), "start_date": start.isoformat(), "end_date": end.isoformat()}

    print(f"ดึงสภาพอากาศย้อนหลัง {start} → {end}")
    w = _get_hourly(C.OM_ARCHIVE_URL, p, C.WEATHER_VARS)
    print(f"  ✓ {len(w):,} ชั่วโมง")
    print("ดึงมลพิษย้อนหลัง")
    aq = _get_hourly(C.OM_AQ_URL, p, C.AQ_VARS)
    print(f"  ✓ {len(aq):,} ชั่วโมง (มีค่า PM2.5 {aq['pm2_5'].notna().sum():,})")

    h = _to_hourly_index(w.merge(aq, on="datetime", how="inner"))
    first_pm = h["pm2_5"].first_valid_index()
    h = h.loc[first_pm:]                             # ตัดช่วงต้นที่ยังไม่มีข้อมูลฝุ่น
    return h


# ---------------------------------------------------------------- ข้อมูลล่าสุด + พยากรณ์ (ใช้ตอนใช้งานจริง)
@ttl_cache(seconds=1800)
def fetch_recent_and_forecast() -> tuple[pd.DataFrame, bool]:
    """คืน (ข้อมูลรายชั่วโมง 3 วันที่ผ่านมา + พยากรณ์ 8 วัน, is_stale)
    ถ้า API ล่ม จะใช้ข้อมูลสำรองครั้งล่าสุดแทน (is_stale=True)"""
    try:
        p = {**_base_params(), "past_days": 3, "forecast_days": 8}
        w = _get_hourly(C.OM_FORECAST_URL, p, C.WEATHER_VARS + C.FORECAST_ONLY_VARS)
        aq = _get_hourly(C.OM_AQ_URL, {**_base_params(), "past_days": 4, "forecast_days": 1}, C.AQ_VARS)
        h = _to_hourly_index(w.merge(aq, on="datetime", how="left"))
        h.reset_index().to_csv(C.SNAPSHOT_FILE, index=False)
        return h, False
    except Exception as e:
        if C.SNAPSHOT_FILE.exists():
            print(f"! ใช้ข้อมูลสำรอง เพราะ API ล้ม: {e}")
            h = pd.read_csv(C.SNAPSHOT_FILE, parse_dates=["datetime"]).set_index("datetime")
            return h, True
        raise


# ---------------------------------------------------------------- Air4Thai (ค่าจริงจากสถานี)
@ttl_cache(seconds=900)
def fetch_air4thai_nearest() -> dict:
    """ค่าฝุ่นล่าสุดจากสถานี Air4Thai ที่ใกล้ KMITL ที่สุด"""
    # เว็บ Air4Thai ติดตั้งใบรับรอง SSL ไม่ครบ จึงปิดการตรวจเฉพาะแหล่งนี้ (ข้อมูลสาธารณะ อ่านอย่างเดียว)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    js = _get(C.AIR4THAI_URL, verify=False, timeout=30).json()
    rows = []
    for s in js.get("stations", []):
        last = s.get("AQILast") or {}
        pm = pd.to_numeric((last.get("PM25") or {}).get("value"), errors="coerce")
        try:
            lat, lon = float(s["lat"]), float(s["long"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"station": s.get("nameTH"), "area": s.get("areaTH"), "lat": lat, "lon": lon,
                     "pm25": pm, "date": last.get("date"), "time": last.get("time")})
    df = pd.DataFrame(rows)
    df = df[df["pm25"] >= 0]
    if df.empty:
        raise RuntimeError("Air4Thai ไม่มีข้อมูล PM2.5 ที่ใช้ได้")
    df["distance_km"] = np.hypot(df["lat"] - C.KMITL_LAT,
                                 (df["lon"] - C.KMITL_LON) * np.cos(np.deg2rad(C.KMITL_LAT))) * 111.32
    s = df.nsmallest(1, "distance_km").iloc[0]
    measured = pd.to_datetime(f"{s['date']} {s['time']}", errors="coerce")
    age_h = (C.now_local() - measured).total_seconds() / 3600 if pd.notna(measured) else None
    return {
        "station": s["station"], "area": s["area"], "pm25": float(s["pm25"]),
        "measured_at": measured.strftime("%Y-%m-%d %H:%M") if pd.notna(measured) else None,
        "age_hours": round(age_h, 1) if age_h is not None else None,
        "distance_km": round(float(s["distance_km"]), 1),
        "is_fresh": age_h is not None and age_h <= 3,
    }


# ---------------------------------------------------------------- Smart Pole ภายใน สจล. (ค่าจริงตอนนี้)
@ttl_cache(seconds=900)
def fetch_smartpole() -> dict:
    """ค่าฝุ่นล่าสุดจากเซนเซอร์ Smart Pole ใน สจล. (ดึงไม่เกินทุก 15 นาที เพื่อไม่รบกวนระบบต้นทาง)
    คืน {poles: [...], pm25 (มัธยฐาน), n, measured_at, age_hours, is_fresh}"""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    s = requests.Session()
    s.headers.update({**HEADERS, "Referer": C.SMARTPOLE_BASE + "/", "Accept": "application/json"})
    s.get(C.SMARTPOLE_BASE + "/", timeout=15, verify=False)          # หน้าเว็บสาธารณะจะออก session cookie ให้
    r = s.get(C.SMARTPOLE_BASE + "/api/poles", timeout=15, verify=False)
    r.raise_for_status()
    rows = []
    for p in r.json():
        pm = pd.to_numeric(p.get("pm25"), errors="coerce")
        t = pd.to_datetime(p.get("update_time"), errors="coerce", utc=True)
        if pd.isna(pm) or pm < 0 or pd.isna(t):
            continue
        rows.append({"name": p.get("name"), "lat": float(p["lat"]), "lon": float(p["lng"]), "pm25": float(pm),
                     "time": t.tz_convert(C.TZ).tz_localize(None)})
    if not rows:
        raise RuntimeError("Smart Pole ไม่มีค่าฝุ่นที่ใช้ได้")
    df = pd.DataFrame(rows)
    latest = df["time"].max()
    df = df[df["time"] >= latest - pd.Timedelta(hours=2)]               # ใช้เฉพาะเสาที่อัปเดตพร้อมกัน
    age_h = (C.now_local() - latest).total_seconds() / 3600
    return {"poles": df.to_dict("records"), "pm25": round(float(df["pm25"].median()), 1), "n": int(len(df)),
            "measured_at": latest.strftime("%Y-%m-%d %H:%M"), "age_hours": round(age_h, 1),
            "is_fresh": age_h <= 3}


def fetch_current_pm() -> dict:
    """ค่าฝุ่นตอนนี้ของ สจล. 1 ค่า เลือกแหล่งให้อัตโนมัติ
    1) Smart Pole ใน สจล. (ถ้าเปิดใช้และข้อมูลใหม่)  2) สถานี Air4Thai ที่ใกล้ที่สุด"""
    errors = []
    if C.env_flag("USE_SMARTPOLE", True):
        try:
            sp = fetch_smartpole()
            if sp["is_fresh"]:
                return {"pm25": sp["pm25"], "source": "smartpole", "measured_at": sp["measured_at"],
                        "is_fresh": True, "age_hours": sp["age_hours"], "poles": sp["poles"],
                        "source_text": f"ค่ากลางจากเซนเซอร์ {sp['n']} จุดใน สจล. ({C.SMARTPOLE_CREDIT})",
                        "source_short": f"เซนเซอร์ใน สจล. {sp['n']} จุด"}
            errors.append("Smart Pole ไม่อัปเดต")
        except Exception as e:
            errors.append(f"Smart Pole: {e}")
    s = fetch_air4thai_nearest()
    return {"pm25": s["pm25"], "source": "air4thai", "measured_at": s["measured_at"],
            "is_fresh": s["is_fresh"], "age_hours": s["age_hours"], "poles": [],
            "source_text": f"สถานี{s['station']} ของกรมควบคุมมลพิษ ห่าง สจล. {s['distance_km']} กม.",
            "source_short": f"สถานี{s['station']}", "fallback_reason": "; ".join(errors) or None}


# ---------------------------------------------------------------- อากาศที่วัดจริง: สถานีตรวจอากาศสนามบินสุวรรณภูมิ (METAR)
METAR_STATION = "VTBS"            # สุวรรณภูมิ ห่าง สจล. ราว 5 กม. รายงานทุก 30 นาที
_CLOUD_PCT = {"SKC": 0, "CLR": 0, "NSC": 0, "NCD": 0, "CAVOK": 0, "FEW": 20, "SCT": 45, "BKN": 75, "OVC": 100, "VV": 100}


def _metar_weather(wx: str) -> tuple[str | None, bool]:
    """แปลรหัสสภาพอากาศ METAR เป็นภาษาไทย คืน (คำอธิบาย, ฝนตกที่สถานีหรือไม่)"""
    wx = (wx or "").upper()
    if not wx:
        return None, False
    here = [t for t in wx.split() if not t.startswith("VC")]
    near = [t for t in wx.split() if t.startswith("VC")]
    h = " ".join(here)
    if "TS" in h and any(k in h for k in ("RA", "SH")):
        return ("ฝนฟ้าคะนองหนัก" if "+" in h else "ฝนฟ้าคะนอง"), True
    if any(k in h for k in ("RA", "SH", "DZ")):
        return ("ฝนหนัก" if "+" in h else "ฝนเล็กน้อย" if "-" in h else "ฝนตก"), True
    if "TS" in h:
        return "ฟ้าคะนอง", False
    if any(k in h for k in ("HZ", "FU")):
        return "ฟ้าหลัว มีหมอกควัน", False
    if any(k in h for k in ("BR", "FG")):
        return "มีหมอก", False
    if near:
        return ("มีพายุฝนฟ้าคะนองบริเวณใกล้เคียง" if any("TS" in t for t in near) else "มีฝนบริเวณใกล้เคียง"), False
    return None, False


@ttl_cache(seconds=900)
def fetch_metar() -> dict:
    """ค่าที่วัดจริงล่าสุดจากสนามบินสุวรรณภูมิ (aviationweather.gov ใช้ฟรี ไม่ต้องใช้ key)"""
    r = requests.get("https://aviationweather.gov/api/data/metar",
                     params={"ids": METAR_STATION, "format": "json", "hours": 3}, timeout=6)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError("สถานีไม่มีรายงานล่าสุด")
    m = max(rows, key=lambda x: x.get("obsTime") or 0)
    t = pd.Timestamp(m["obsTime"], unit="s", tz="UTC").tz_convert(C.TZ).tz_localize(None)
    temp, dew = m.get("temp"), m.get("dewp")
    rh = None
    if temp is not None and dew is not None:            # ความชื้นสัมพัทธ์จากจุดน้ำค้าง (สูตร Magnus)
        a, b = 17.625, 243.04
        rh = round(100 * np.exp(a * dew / (b + dew)) / np.exp(a * temp / (b + temp)))
    covers = [c.get("cover") for c in (m.get("clouds") or []) if c.get("cover")]
    cloud = max([_CLOUD_PCT.get(c, 0) for c in covers] or [_CLOUD_PCT.get(m.get("cover"), 0)])
    desc, raining = _metar_weather(m.get("wxString"))
    wspd = m.get("wspd")
    return {"time": t, "temperature_c": temp, "humidity_percent": rh,
            "wind_kmh": round(float(wspd) * 1.852, 1) if isinstance(wspd, (int, float)) else None,
            "cloud_percent": cloud, "raining": raining, "weather_text": desc,
            "age_hours": (C.now_local() - t) / pd.Timedelta(hours=1), "raw": m.get("rawOb", "")}
