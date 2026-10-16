"""ค่าคงที่ทั้งหมดของโปรเจกต์ KMITL Outdoor Planner (แก้ที่ไฟล์นี้ที่เดียว)"""

import os
from pathlib import Path

APP_NAME = "KMITL Outdoor Planner"
APP_TAGLINE = "พยากรณ์ฝุ่นและสภาพอากาศ เพื่อวางแผนกิจกรรมกลางแจ้งใน สจล."

# ---------------------------------------------------------------- พื้นที่
KMITL_NAME = "สจล. ลาดกระบัง"
KMITL_LAT, KMITL_LON = 13.7299, 100.7782
TZ = "Asia/Bangkok"


def now_local():
    """เวลาปัจจุบันของไทย (แบบไม่มี timezone) — ใช้แทน datetime.now() เพราะ server บน cloud เป็น UTC"""
    import pandas as pd
    return pd.Timestamp.now(tz=TZ).tz_localize(None)


# ---------------------------------------------------------------- โฟลเดอร์
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ARTIFACT_DIR = ROOT / "artifacts"
KNOWLEDGE_DIR = ROOT / "knowledge"
for _d in (DATA_DIR, ARTIFACT_DIR):
    _d.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "history_hourly.csv"
SNAPSHOT_FILE = DATA_DIR / "last_recent.csv"      # ข้อมูลสำรองกรณี API ล่มตอนเดโม
MODEL_FILE = ARTIFACT_DIR / "model.joblib"
META_FILE = ARTIFACT_DIR / "model_meta.json"
STATS_FILE = ARTIFACT_DIR / "stats.json"
LLM_EVAL_FILE = ARTIFACT_DIR / "llm_eval.json"
DB_FILE = DATA_DIR / "app.db"


def env_flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v.strip().lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------- ข้อมูล
HISTORY_DAYS = 1095            # ย้อนหลัง ~3 ปี (ถ้า API มีไม่ถึง จะได้เท่าที่มี)
MAX_HORIZON_H = 168            # พยากรณ์ล่วงหน้าสูงสุด 7 วัน

WEATHER_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation", "surface_pressure", "cloud_cover",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "shortwave_radiation", "boundary_layer_height",
]
FORECAST_ONLY_VARS = ["precipitation_probability", "uv_index"]   # ใช้แสดงผล/ตอบคำถาม ไม่ใช่ input โมเดล
AQ_VARS = ["pm2_5", "pm10", "carbon_monoxide", "nitrogen_dioxide", "ozone"]

# เซนเซอร์ Smart Pole ภายใน สจล. (SCiRA) — ใช้เป็น "ค่าฝุ่นตอนนี้" ปิดได้ด้วย USE_SMARTPOLE=false ใน .env
SMARTPOLE_BASE = "https://geo.scira.kmitl.ac.th:8444"
SMARTPOLE_CREDIT = "KMITL Smart Pole (SCiRA)"
# ชื่อย่านของแต่ละเสา (ตามที่เว็บ Smart Pole ของ สจล. ใช้)
POLE_AREAS = {
    "SP-1": "ย่านสำนักงานอธิการบดี/คณะวิทยาศาสตร์/คณะเทคโนโลยีสารสนเทศ",
    "SP-2": "ย่านหอพัก นศ.",
    "SP-3": "ย่านสนามกีฬากลาง",
    "SP-4": "ย่านคณะบริหารธุรกิจ/คณะครุศาสตร์",
    "SP-5": "ย่านชุมชนริมทางรถไฟสถานีหัวตะเข้",
    "SP-6": "ย่านสถานีรถไฟหัวตะเข้/โรงเรียนพรตฯ",
    "SP-7": "ย่านคณะเกษตรฯ และหอประชุมใหญ่",
    "SP-8": "ย่านคณะสถาปัตยฯ และคณะวิศวกรรมศาสตร์",
    "SP-9": "ย่านหอพักเอกชนเกกีงาม",
}
# สถานที่ในร่มใน สจล. ที่ AI ใช้แนะนำเป็นแผนสำรอง — ใส่เฉพาะที่ตรวจสอบแล้วว่ามีจริงและใช้ได้
# รูปแบบ: ("ชื่อสถานที่", "เหมาะกับกิจกรรมอะไร")  ถ้าว่างไว้ AI จะแนะนำแบบกว้าง ๆ โดยไม่ระบุชื่อ
INDOOR_PLACES = [   # ยืนยันจากเว็บ kmitl.ac.th และคณะวิศวฯ (ดูรายละเอียดใน knowledge/05_campus_places.md)
    ("โรงยิม 1 (ฝั่งวิศวฯ)", "บาสเกตบอล วอลเลย์บอล"),
    ("โรงยิม 2 (ระหว่างสนามกีฬากลางกับหอใน)", "แบดมินตัน ปิงปอง"),
    ("ฟิตเนส KM Wellness & Sport Center", "วิ่งบนลู่ ฟิตเนส โยคะ แอโรบิก (9:00–20:00 เริ่ม 30 บาท)"),
    ("Co-working space ตึก HM ชั้น 3–7", "อ่านหนังสือ ทำงานกลุ่ม (6:00–22:00)"),
    ("หอสมุด KLLC", "อ่านหนังสือ ห้องสัมมนา"),
    ("ร้านอิ่มเอม", "กินข้าวในร่ม"),
]
# ขอบเขตวิทยาเขตโดยประมาณ (ใช้วาดแผนที่เท่านั้น) [lat, lon]
CAMPUS_OUTLINE = [
    (13.7322, 100.7690), (13.7330, 100.7760), (13.7322, 100.7860), (13.7290, 100.7880),
    (13.7248, 100.7862), (13.7238, 100.7790), (13.7246, 100.7700), (13.7290, 100.7680),
]
AIR4THAI_URL = "http://air4thai.pcd.go.th/services/getNewAQI_JSON.php"
OM_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OM_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OM_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# ---------------------------------------------------------------- เกณฑ์ PM2.5 (µg/m³ เฉลี่ย 24 ชม.)
# เกณฑ์ AQI ของกรมควบคุมมลพิษ (มีผล 1 มิ.ย. 2566) — ตรวจทานกับ air4thai.pcd.go.th ก่อนใช้จริง
STANDARD_PM25 = 37.5
AQI_LEVELS = [
    # (ไม่เกิน, ชื่อระดับ, สี, emoji, คำแนะนำสั้น, ประโยคสรุปสำหรับหน้าแรก)
    (15.0, "ดีมาก", "#2F80ED", "🔵", "เหมาะกับกิจกรรมกลางแจ้งทุกประเภท",
     "อากาศดีมาก ออกไปทำกิจกรรมข้างนอกได้เต็มที่"),
    (25.0, "ดี", "#27AE60", "🟢", "ทำกิจกรรมกลางแจ้งได้ตามปกติ",
     "อากาศดี ใช้ชีวิตข้างนอกได้ตามปกติ"),
    (37.5, "ปานกลาง", "#E2B007", "🟡", "คนทั่วไปทำกิจกรรมได้ ถ้าแพ้ฝุ่นควรลดเวลาอยู่ข้างนอก",
     "ฝุ่นปานกลาง ออกไปข้างนอกได้ ถ้าแพ้ฝุ่นควรพกหน้ากาก"),
    (75.0, "เริ่มมีผลต่อสุขภาพ", "#EB6F1C", "🟠", "ควรใส่หน้ากากและเลี่ยงออกกำลังกายกลางแจ้ง",
     "ฝุ่นเริ่มมีผลต่อสุขภาพ ใส่หน้ากากและเลี่ยงออกกำลังกายข้างนอก"),
    (float("inf"), "มีผลต่อสุขภาพ", "#D64545", "🔴", "ควรงดกิจกรรมกลางแจ้งและอยู่ในอาคาร",
     "ฝุ่นอยู่ในระดับอันตราย ควรอยู่ในอาคารและใส่หน้ากาก N95 เมื่อออกไปข้างนอก"),
]
LEVEL_SHORT = ["ดีมาก", "ดี", "ปานกลาง", "เริ่มมีผล", "มีผล"]
PM_UNIT = "มคก./ลบ.ม."


def pm25_level(value: float) -> dict:
    """แปลงค่า PM2.5 เป็นระดับสี + คำแนะนำ"""
    for i, (limit, name, color, emoji, advice, headline) in enumerate(AQI_LEVELS):
        if value <= limit:
            return {"level": name, "color": color, "emoji": emoji, "advice": advice,
                    "headline": headline, "index": i}
    return {"level": "-", "color": "#999", "emoji": "", "advice": "", "headline": "", "index": 0}


# ---------------------------------------------------------------- เกณฑ์แปลความหมายปัจจัย
# เกณฑ์เบื้องต้นที่กลุ่มกำหนด (ไม่ใช่มาตรฐานทางการ) — ระบุในรายงาน
FACTOR_RULES = {
    "wind": ("ลม", "กม./ชม.", [
        (5, "bad", "แทบไม่มีลม", "ฝุ่นไม่ถูกพัดออกไป จึงค้างอยู่ในพื้นที่"),
        (12, "mid", "ลมอ่อน", "พัดฝุ่นออกได้บ้าง"),
        (1e9, "good", "ลมดี", "ช่วยพัดฝุ่นออกจากพื้นที่")]),
    "blh": ("การระบายอากาศ", "ม.", [
        (500, "bad", "อากาศปิด", "อากาศด้านบนกดฝุ่นไว้ใกล้พื้น ฝุ่นจึงสะสม"),
        (1000, "mid", "ระบายได้บ้าง", "ฝุ่นลอยขึ้นและกระจายออกได้บางส่วน"),
        (1e9, "good", "ระบายดี", "ฝุ่นลอยขึ้นที่สูงและเจือจางได้ดี")]),
    "rain24": ("ฝนใน 24 ชม.ก่อนหน้า", "มม.", [
        (1, "bad", "ไม่มีฝน", "ไม่มีฝนช่วยชะล้างฝุ่น"),
        (10, "mid", "ฝนเล็กน้อย", "ชะล้างฝุ่นได้บ้าง"),
        (1e9, "good", "ฝนตก", "ชะล้างฝุ่นได้ดี")]),
    "humidity": ("ความชื้น", "%", [
        (60, "good", "ปกติ", "ไม่ค่อยมีผลต่อฝุ่น"),
        (80, "mid", "ค่อนข้างชื้น", "ฝุ่นลอยค้างในอากาศนานขึ้น"),
        (101, "bad", "ชื้นมาก", "ฝุ่นจับตัวกับไอน้ำและลอยค้างนาน")]),
    "trend": ("ฝุ่นเทียบกับเมื่อวาน", "มคก./ลบ.ม.", [
        (-3, "good", "ลดลง", "ฝุ่นน้อยลงกว่าเมื่อวาน"),
        (3, "mid", "พอ ๆ กับเมื่อวาน", "ฝุ่นใกล้เคียงกับเมื่อวาน"),
        (1e9, "bad", "เพิ่มขึ้น", "ฝุ่นสะสมมากขึ้นกว่าเมื่อวาน")]),
}
STATUS_ICON = {"good": "🟢", "mid": "🟡", "bad": "🔴"}


def interpret_factor(kind: str, value: float) -> dict:
    label, unit, rules = FACTOR_RULES[kind]
    for limit, status, level, meaning in rules:
        if value < limit:
            return {"factor": label, "value": round(float(value), 1), "unit": unit,
                    "status": status, "icon": STATUS_ICON[status], "level": level, "meaning": meaning}
    raise ValueError(kind)


# ---------------------------------------------------------------- ความร้อน (ใช้อุณหภูมิอากาศจริง)
# เกณฑ์เบื้องต้นที่กลุ่มกำหนดสำหรับอากาศกรุงเทพฯ (ไม่ใช่มาตรฐานทางการ)
HEAT_LEVELS = [
    (30, "สบาย", ""),
    (33, "อุ่น", ""),
    (36, "ร้อน", ""),
    (39, "ร้อนจัด", ""),
    (float("inf"), "ร้อนมาก", ""),
]
HEAT_OK, HEAT_CAUTION_HEAVY, HEAT_CAUTION = 33, 36, 38   # เกณฑ์ประเมินกิจกรรม (°C)


def heat_level(temp_c: float) -> dict:
    for limit, name, emoji in HEAT_LEVELS:
        if temp_c < limit:
            return {"level": name, "emoji": emoji}
    return {"level": "-", "emoji": "⚪"}


def confidence_label(horizon_h: int) -> dict:
    if horizon_h <= 24:
        return {"label": "ค่อนข้างแม่น", "emoji": "🟢", "level": 0}
    if horizon_h <= 72:
        return {"label": "แม่นปานกลาง", "emoji": "🟡", "level": 1}
    return {"label": "ดูแนวโน้ม", "emoji": "🟠", "level": 2}
