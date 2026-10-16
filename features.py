"""สร้างตัวแปรต้น (ใช้ร่วมกันทั้งตอนเทรนและตอนใช้งานจริง เพื่อให้ตรงกันเสมอ)

แนวคิด: ยืนอยู่ ณ เวลา origin (ตอนนี้) แล้วทายฝุ่น ณ เวลา target (อีก h ชั่วโมง, h = 1..168)
  - ตัวแปร o_* : รู้ ณ origin  -> ฝุ่น/มลพิษล่าสุด (ไม่ใช้มลพิษของอนาคต = ป้องกัน data leakage)
  - ตัวแปร t_* : สภาพอากาศ ณ target -> ตอนเทรนใช้ค่าจริง, ตอนใช้งานใช้ค่าพยากรณ์ของ Open-Meteo
  - horizon    : ทายล่วงหน้ากี่ชั่วโมง
"""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd

ORIGIN_FEATURES = [
    "o_pm_now", "o_pm_mean24", "o_pm_max24", "o_pm_mean72", "o_pm_trend24",
    "o_pm10_mean24", "o_co_mean24", "o_no2_mean24", "o_o3_mean24",
]
TARGET_FEATURES = [
    "t_temp", "t_rh", "t_dew", "t_pressure", "t_cloud", "t_rad",
    "t_wind", "t_gust", "t_wind_sin", "t_wind_cos", "t_wind_mean6", "t_calm12",
    "t_blh", "t_rain24",
    "t_hour", "t_dow", "t_weekend", "t_holiday", "t_doy_sin", "t_doy_cos",
]
ALL_FEATURES = ORIGIN_FEATURES + TARGET_FEATURES + ["horizon"]

_SRC = {  # ชื่อคอลัมน์ใน API -> ชื่อสั้น
    "t_temp": "temperature_2m", "t_rh": "relative_humidity_2m", "t_dew": "dew_point_2m",
    "t_pressure": "surface_pressure", "t_cloud": "cloud_cover", "t_rad": "shortwave_radiation",
    "t_wind": "wind_speed_10m", "t_gust": "wind_gusts_10m", "t_blh": "boundary_layer_height",
}


def _col(h: pd.DataFrame, name: str) -> pd.Series:
    return h[name] if name in h.columns else pd.Series(np.nan, index=h.index)


@functools.lru_cache(maxsize=None)
def _th_holidays(year: int) -> frozenset:
    try:
        import holidays
        return frozenset(holidays.Thailand(years=year).keys())
    except Exception:
        return frozenset()


def origin_frame(h: pd.DataFrame) -> pd.DataFrame:
    pm = _col(h, "pm2_5")
    o = pd.DataFrame(index=h.index)
    o["o_pm_now"] = pm
    o["o_pm_mean24"] = pm.rolling(24, min_periods=12).mean()
    o["o_pm_max24"] = pm.rolling(24, min_periods=12).max()
    o["o_pm_mean72"] = pm.rolling(72, min_periods=36).mean()
    o["o_pm_trend24"] = o["o_pm_mean24"] - o["o_pm_mean24"].shift(24)
    for short, src in [("pm10", "pm10"), ("co", "carbon_monoxide"), ("no2", "nitrogen_dioxide"), ("o3", "ozone")]:
        o[f"o_{short}_mean24"] = _col(h, src).rolling(24, min_periods=12).mean()
    return o


def target_frame(h: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame(index=h.index)
    for k, src in _SRC.items():
        t[k] = _col(h, src)
    rad = np.deg2rad(_col(h, "wind_direction_10m"))
    t["t_wind_sin"], t["t_wind_cos"] = np.sin(rad), np.cos(rad)
    wind = _col(h, "wind_speed_10m")
    t["t_wind_mean6"] = wind.rolling(6, min_periods=3).mean()
    t["t_calm12"] = (wind < 5).astype(float).where(wind.notna()).rolling(12, min_periods=6).sum()
    t["t_rain24"] = _col(h, "precipitation").rolling(24, min_periods=12).sum()
    idx = h.index
    t["t_hour"] = idx.hour
    t["t_dow"] = idx.dayofweek
    t["t_weekend"] = (idx.dayofweek >= 5).astype(int)
    t["t_holiday"] = [int(d in _th_holidays(d.year)) for d in idx.date]
    t["t_doy_sin"] = np.sin(2 * np.pi * idx.dayofyear / 365.25)
    t["t_doy_cos"] = np.cos(2 * np.pi * idx.dayofyear / 365.25)
    return t


def training_rows(h: pd.DataFrame, horizons: list[int], step: int = 6) -> pd.DataFrame:
    """สร้างตารางเทรน: 1 แถว = (origin, horizon) -> y = PM2.5 ณ origin + horizon"""
    o, t, y = origin_frame(h), target_frame(h), _col(h, "pm2_5")
    origins = h.index[72::step]
    parts = []
    for hz in horizons:
        tgt = origins + pd.Timedelta(hours=hz)
        ok = tgt.isin(h.index)
        oi, ti = origins[ok], tgt[ok]
        df = pd.concat([o.loc[oi].reset_index(drop=True), t.loc[ti].reset_index(drop=True)], axis=1)
        df["horizon"] = hz
        df["origin_time"], df["target_time"] = oi, ti
        df["y"] = y.loc[ti].to_numpy()
        parts.append(df)
    out = pd.concat(parts, ignore_index=True)
    return out.dropna(subset=["y", "o_pm_now", "o_pm_mean24"])


def inference_rows(h: pd.DataFrame, origin, max_horizon: int) -> pd.DataFrame:
    """แถวสำหรับทายทุกชั่วโมงตั้งแต่ origin+1 ถึง origin+max_horizon"""
    o, t = origin_frame(h), target_frame(h)
    targets = h.index[(h.index > origin) & (h.index <= origin + pd.Timedelta(hours=max_horizon))]
    df = t.loc[targets].reset_index(drop=True)
    for c in ORIGIN_FEATURES:
        df[c] = o.at[origin, c]
    df["horizon"] = ((targets - origin) / pd.Timedelta(hours=1)).astype(int)
    df["target_time"] = targets
    return df
