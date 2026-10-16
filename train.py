"""เทรนโมเดลพยากรณ์ PM2.5 รายชั่วโมงล่วงหน้า 1–168 ชม. (7 วัน) ที่พิกัด KMITL

รัน:  python train.py            (ใช้ข้อมูลย้อนหลังที่ดึงไว้แล้ว ถ้ามี)
      python train.py --refresh  (ดึงข้อมูลย้อนหลังใหม่)

ได้: artifacts/model.joblib, artifacts/model_meta.json, artifacts/stats.json
"""

from __future__ import annotations

import argparse
import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error

import config as C
import stats_analysis
from data_sources import fetch_history
from features import ALL_FEATURES, training_rows

HORIZONS = [1, 2, 3, 6, 9, 12, 18, 24, 30, 36, 48, 60, 72, 96, 120, 144, 168]
BUCKETS = [(1, 24, "1–24 ชม. (พรุ่งนี้)"), (25, 72, "25–72 ชม. (2–3 วัน)"), (73, 168, "73–168 ชม. (4–7 วัน)")]

FEATURE_TH = {  # ชื่อไทยสำหรับแสดงผล
    "o_pm_now": "ฝุ่นตอนนี้", "o_pm_mean24": "ฝุ่นเฉลี่ย 24 ชม.ที่ผ่านมา", "o_pm_max24": "ฝุ่นสูงสุด 24 ชม.ที่ผ่านมา",
    "o_pm_mean72": "ฝุ่นเฉลี่ย 3 วันที่ผ่านมา", "o_pm_trend24": "แนวโน้มฝุ่นจากเมื่อวาน",
    "o_pm10_mean24": "PM10 ล่าสุด", "o_co_mean24": "คาร์บอนมอนอกไซด์ล่าสุด (รถ/การเผา)",
    "o_no2_mean24": "NO₂ ล่าสุด (ไอเสียรถ)", "o_o3_mean24": "โอโซนล่าสุด",
    "t_temp": "อุณหภูมิ", "t_rh": "ความชื้น", "t_dew": "จุดน้ำค้าง", "t_pressure": "ความกดอากาศ",
    "t_cloud": "เมฆ", "t_rad": "แสงแดด", "t_wind": "ความเร็วลม", "t_gust": "ลมกระโชก",
    "t_wind_sin": "ทิศลม (เหนือ-ใต้)", "t_wind_cos": "ทิศลม (ออก-ตก)", "t_wind_mean6": "ลมเฉลี่ย 6 ชม.",
    "t_calm12": "ชั่วโมงที่ลมนิ่ง", "t_blh": "ชั้นอากาศผสม (การระบายอากาศ)", "t_rain24": "ฝน 24 ชม.",
    "t_hour": "ช่วงเวลาของวัน", "t_dow": "วันในสัปดาห์", "t_weekend": "วันหยุดสุดสัปดาห์",
    "t_holiday": "วันหยุดราชการ", "t_doy_sin": "ฤดูกาล", "t_doy_cos": "ฤดูกาล", "horizon": "ระยะที่ทายล่วงหน้า",
}


def load_history(refresh: bool) -> pd.DataFrame:
    if C.HISTORY_FILE.exists() and not refresh:
        print(f"ใช้ข้อมูลย้อนหลังที่มีอยู่: {C.HISTORY_FILE.name}  (ดึงใหม่: python train.py --refresh)")
        return pd.read_csv(C.HISTORY_FILE, parse_dates=["datetime"]).set_index("datetime")
    h = fetch_history()
    h.reset_index().to_csv(C.HISTORY_FILE, index=False)
    return h


def evaluate(name, y, p, horizon) -> dict:
    out = {"model": name, "MAE": mean_absolute_error(y, p), "RMSE": float(np.sqrt(mean_squared_error(y, p)))}
    for lo, hi, label in BUCKETS:
        m = (horizon >= lo) & (horizon <= hi)
        if m.any():
            out[f"MAE {label}"] = mean_absolute_error(y[m], p[m])
    return {k: (round(float(v), 2) if isinstance(v, (float, np.floating)) else v) for k, v in out.items()}


def make_models() -> dict:
    return {
        "Random Forest": RandomForestRegressor(n_estimators=150, max_depth=16, min_samples_leaf=10,
                                               max_features=0.5, n_jobs=-1, random_state=42),
        "Gradient Boosting": HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05,
                                                           max_leaf_nodes=31, l2_regularization=1.0,
                                                           random_state=42),
    }


def main(refresh: bool = False):
    t0 = time.time()
    h = load_history(refresh)
    print(f"ข้อมูลรายชั่วโมง: {len(h):,} ชม. ({h.index.min().date()} → {h.index.max().date()})")

    # ---------------- สถิติ
    print("\n[1/4] วิเคราะห์สถิติ")
    st = stats_analysis.run(h)
    for s in st["summary"]:
        print("  •", s)

    # ---------------- ตารางเทรน
    print("\n[2/4] สร้างตารางเทรน")
    df = training_rows(h, HORIZONS, step=6)
    feats = [f for f in ALL_FEATURES if df[f].notna().mean() > 0.5]   # ตัดตัวแปรที่ข้อมูลว่างเกินครึ่ง
    medians = df[feats].median()
    df[feats] = df[feats].fillna(medians)
    print(f"  {len(df):,} แถว | ตัวแปรต้น {len(feats)} ตัว")

    # แบ่งตามเวลา: 80% แรกเทรน / 20% หลังทดสอบ (target ของชุดเทรนต้องจบก่อนชุดทดสอบเริ่ม = ไม่รั่ว)
    cutoff = df["origin_time"].quantile(0.8)
    train = df[df["target_time"] < cutoff]
    test = df[df["origin_time"] >= cutoff]
    print(f"  เทรน: {len(train):,} แถว (ถึง {cutoff:%Y-%m-%d}) | ทดสอบ: {len(test):,} แถว")

    # ---------------- เทรน + วัดผล
    print("\n[3/4] เทรนและวัดผลเทียบ baseline")
    y, hz = test["y"].to_numpy(), test["horizon"].to_numpy()
    results = [
        evaluate("Baseline: ค่าเท่าตอนนี้", y, test["o_pm_now"].to_numpy(), hz),
        evaluate("Baseline: ค่าเฉลี่ย 24 ชม.", y, test["o_pm_mean24"].to_numpy(), hz),
    ]
    fitted = {}
    for name, model in make_models().items():
        model.fit(train[feats], train["y"])
        fitted[name] = model
        results.append(evaluate(name, y, model.predict(test[feats]), hz))
    table = pd.DataFrame(results)
    print(table.to_string(index=False))

    best_name = min(fitted, key=lambda n: table.loc[table["model"] == n, "MAE"].iloc[0])
    best_base = table[table["model"].str.startswith("Baseline")]["MAE"].min()
    best_mae = table.loc[table["model"] == best_name, "MAE"].iloc[0]
    print(f"\n  โมเดลที่ดีที่สุด: {best_name} (MAE {best_mae}) | baseline ที่ดีที่สุด MAE {best_base} "
          f"-> {'ชนะ' if best_mae < best_base else 'ยังไม่ชนะ'} baseline {abs(best_base - best_mae) / best_base:.0%}")

    sample = test.sample(min(3000, len(test)), random_state=0)
    pi = permutation_importance(fitted[best_name], sample[feats], sample["y"], n_repeats=3,
                                random_state=0, scoring="neg_mean_absolute_error")
    imp = pd.Series(pi.importances_mean, index=feats).clip(lower=0).sort_values(ascending=False)

    # กราฟทายเทียบจริง (ทาย 24 ชม.ล่วงหน้า ในช่วงทดสอบ)
    t24 = test[test["horizon"] == 24].sort_values("target_time")
    backtest = pd.DataFrame({"time": t24["target_time"].dt.strftime("%Y-%m-%d %H:%M"),
                             "actual": t24["y"].round(1),
                             "predicted": fitted[best_name].predict(t24[feats]).round(1)})

    # ---------------- เทรนใหม่ด้วยข้อมูลทั้งหมด แล้วบันทึก
    print("\n[4/4] เทรนโมเดลสุดท้ายด้วยข้อมูลทั้งหมด แล้วบันทึก")
    final = make_models()[best_name].fit(df[feats], df["y"])
    joblib.dump(final, C.MODEL_FILE, compress=3)
    meta = {
        "model_name": best_name, "features": feats, "medians": medians[feats].round(4).to_dict(),
        "trained_at": C.now_local().strftime("%Y-%m-%d %H:%M"),
        "data_range": [str(h.index.min().date()), str(h.index.max().date())],
        "n_train_rows": int(len(df)), "horizons": HORIZONS, "test_from": str(cutoff.date()),
        "metrics": results, "beats_baseline": bool(best_mae < best_base),
        "feature_importance": [{"feature": f, "name_th": FEATURE_TH.get(f, f), "importance": round(float(v), 4)}
                               for f, v in imp.head(15).items()],
        "backtest_24h": backtest.to_dict(orient="records"),
    }
    C.META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    size_mb = C.MODEL_FILE.stat().st_size / 1e6
    print(f"  ✓ {C.MODEL_FILE.name} ({size_mb:.1f} MB) | {C.META_FILE.name} | {C.STATS_FILE.name}")
    print(f"\nเสร็จใน {time.time() - t0:.0f} วินาที -> ต่อไป: streamlit run app.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ดึงข้อมูลย้อนหลังใหม่")
    main(ap.parse_args().refresh)
