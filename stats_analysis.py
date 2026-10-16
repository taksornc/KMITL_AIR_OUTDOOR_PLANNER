"""วิเคราะห์ทางสถิติ (คำนวณด้วย Python/SciPy ทั้งหมด ไม่ให้ LLM คำนวณเอง)
ผลบันทึกที่ artifacts/stats.json -> ใช้แสดงในหน้า "สถิติ" และให้ LLM อ่านผ่าน tool
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

import config as C


def _daily(h: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame({
        "pm25": h["pm2_5"].resample("D").mean(),
        "wind": h["wind_speed_10m"].resample("D").mean(),
        "rh": h["relative_humidity_2m"].resample("D").mean(),
        "rain": h["precipitation"].resample("D").sum(min_count=12),
    })
    if "boundary_layer_height" in h.columns:
        d["blh"] = h["boundary_layer_height"].resample("D").mean()
    d["is_weekend"] = d.index.dayofweek >= 5
    d["is_dust_season"] = d.index.month.isin([12, 1, 2, 3])
    return d.dropna(subset=["pm25"])


def _spearman(d, x, label_th, unit_desc):
    s = d[[x, "pm25"]].dropna()
    rho, p = stats.spearmanr(s[x], s["pm25"])
    direction = "สูงขึ้น" if rho > 0 else "ต่ำลง"
    strength = "สูง" if abs(rho) >= 0.5 else "ปานกลาง" if abs(rho) >= 0.3 else "ต่ำ"
    sig = p < 0.05
    finding = (f"เมื่อ{label_th}{unit_desc} ฝุ่นมีแนวโน้ม{direction} "
               f"(ความสัมพันธ์ระดับ{strength}, ρ = {rho:.2f})") if sig else \
              f"ไม่พบความสัมพันธ์ที่มีนัยสำคัญระหว่าง{label_th}กับฝุ่น (ρ = {rho:.2f})"
    return {"test": "Spearman correlation", "variable": label_th, "n": int(len(s)),
            "rho": round(float(rho), 3), "p_value": float(p), "significant": bool(sig), "finding": finding}


def _mannwhitney(d, mask, name_a, name_b, topic):
    a, b = d.loc[mask, "pm25"].dropna(), d.loc[~mask, "pm25"].dropna()
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    rbc = 1 - 2 * u / (len(a) * len(b))                 # rank-biserial correlation (effect size)
    rbc = -rbc                                           # ให้ค่าบวก = กลุ่ม a สูงกว่า b
    diff = (a.median() - b.median()) / b.median() * 100 if b.median() else np.nan
    sig = p < 0.05
    more_less = "สูงกว่า" if diff > 0 else "ต่ำกว่า"
    finding = (f"{name_a} ฝุ่น{more_less}{name_b} {abs(diff):.0f}% "
               f"(มัธยฐาน {a.median():.1f} เทียบ {b.median():.1f} มคก./ลบ.ม.)") if sig else \
              f"ฝุ่นของ{name_a}และ{name_b}ไม่ต่างกันอย่างมีนัยสำคัญ"
    size = "ใหญ่" if abs(rbc) >= 0.5 else "ปานกลาง" if abs(rbc) >= 0.3 else "เล็ก"
    return {"test": "Mann-Whitney U", "topic": topic, "group_a": name_a, "group_b": name_b,
            "n_a": int(len(a)), "n_b": int(len(b)),
            "median_a": round(float(a.median()), 1), "median_b": round(float(b.median()), 1),
            "diff_percent": round(float(diff), 1), "p_value": float(p),
            "effect_size_r": round(float(rbc), 3), "effect_size_label": size,
            "significant": bool(sig), "finding": finding}


def run(h: pd.DataFrame) -> dict:
    d = _daily(h)
    tests = [
        _mannwhitney(d, d["rain"] > 1, "วันที่ฝนตก", "วันที่ไม่มีฝน", "ฝน"),
        _mannwhitney(d, d["is_dust_season"], "ฤดูฝุ่น (ธ.ค.–มี.ค.)", "ช่วงอื่นของปี", "ฤดูกาล"),
        _mannwhitney(d, d["is_weekend"], "วันเสาร์-อาทิตย์", "วันทำงาน", "วันหยุด"),
        _spearman(d, "wind", "ลม", "แรงขึ้น"),
        _spearman(d, "rh", "ความชื้น", "สูงขึ้น"),
    ]
    if "blh" in d.columns:
        tests.append(_spearman(d, "blh", "ความสูงของชั้นอากาศที่ฝุ่นลอยได้", "สูงขึ้น (อากาศระบายดีขึ้น)"))

    monthly = d.groupby(d.index.month)["pm25"].agg(["mean", "max"]).round(1)
    exceed = d.assign(ex=d["pm25"] > C.STANDARD_PM25).groupby(d.index.month)["ex"].sum()
    hourly = h["pm2_5"].groupby(h.index.hour).mean().round(1)
    worst_hour, best_hour = int(hourly.idxmax()), int(hourly.idxmin())

    out = {
        "data_range": [str(d.index.min().date()), str(d.index.max().date())],
        "n_days": int(len(d)),
        "tests": tests,
        "monthly": {int(m): {"mean": float(r["mean"]), "max": float(r["max"]), "days_over_standard": int(exceed[m])}
                    for m, r in monthly.iterrows()},
        "hourly_profile": {int(k): float(v) for k, v in hourly.items()},
        "worst_hour": worst_hour, "best_hour": best_hour,
        "summary": [t["finding"] for t in tests] + [
            f"โดยเฉลี่ยฝุ่นสูงสุดช่วง {worst_hour:02d}:00 น. และต่ำสุดช่วง {best_hour:02d}:00 น.",
            f"เดือนที่ฝุ่นเฉลี่ยสูงสุดคือเดือน {int(monthly['mean'].idxmax())}",
        ],
    }
    C.STATS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    hist = pd.read_csv(C.HISTORY_FILE, parse_dates=["datetime"]).set_index("datetime")
    res = run(hist)
    print("\n".join("• " + s for s in res["summary"]))
