"""ประเมินแผนกิจกรรมกลางแจ้งจาก ฝุ่น + ฝน + ความร้อน
คำตัดสินมาจากเกณฑ์ที่เขียนไว้ชัดเจนในไฟล์นี้ (ตรวจสอบได้ ถามซ้ำได้ผลเดิม) — AI ไม่ได้เป็นผู้ตัดสิน
มีตัวแปลงประโยคภาษาไทยแบบใช้กฎ (parse_text) ไว้ใช้เมื่อ AI ไม่พร้อม และใช้เป็นเกณฑ์เทียบตอนประเมิน AI
"""

from __future__ import annotations

import re

import pandas as pd

import config as C
import forecast as F
from data_sources import ttl_cache

# ---------------------------------------------------------------- ระดับการออกแรง (ระบบ/AI ประเมินจากชื่อกิจกรรม)
INTENSITY = {
    "heavy": "ออกแรงมาก",
    "moderate": "ออกแรงปานกลาง",
    "light": "ออกแรงน้อย",
}
_LEGACY = {"exercise": "heavy", "sport": "heavy", "event": "moderate", "errand": "light"}

VERDICT = {
    "good": ("เหมาะ", "#1E9E5A"),
    "caution": ("พอได้ ถ้าเตรียมตัว", "#C99A06"),
    "bad": ("ไม่แนะนำ", "#D64545"),
}
_RANK = {"good": 0, "caution": 1, "bad": 2}
_PHRASE = {
    "dust": {"caution": "ฝุ่นปานกลาง", "bad": "ฝุ่นสูง"},
    "rain": {"caution": "อาจมีฝน", "bad": "มีโอกาสฝนตกสูง"},
    "heat": {"caution": "อากาศร้อน", "bad": "ร้อนจัด"},
}


def norm_intensity(x: str | None) -> str:
    x = (x or "moderate").strip().lower()
    return _LEGACY.get(x, x if x in INTENSITY else "moderate")


def _window(fc: pd.DataFrame, start: pd.Timestamp, hours: int) -> pd.DataFrame:
    end = start + pd.Timedelta(hours=hours)
    return fc[(fc["time"] >= start) & (fc["time"] < end)]


@ttl_cache(seconds=600)
def evaluate(start: pd.Timestamp, hours: int, intensity: str = "moderate", sensitive: bool = False) -> dict:
    """ประเมินแผน 1 ช่วงเวลา คืน verdict (good/caution/bad), เหตุผลรายปัจจัย, สิ่งที่ต้องเตรียม"""
    intensity = norm_intensity(intensity)
    fc = F.get_forecast()["hourly"]
    start = pd.Timestamp(start)
    seg = _window(fc, start, hours)
    if seg.empty:
        raise ValueError("ช่วงเวลานี้อยู่นอกช่วงพยากรณ์ (วางแผนล่วงหน้าได้ไม่เกิน 7 วัน และต้องยังไม่ผ่านไป)")

    # ---- ฝุ่น: ยิ่งออกแรงมาก หายใจแรง รับฝุ่นมาก เกณฑ์จึงเข้มขึ้น / กลุ่มเสี่ยงใช้เกณฑ์เข้มสุดเสมอ
    pm = float(seg["pm25"].max())
    lv = C.pm25_level(pm)
    i = lv["index"]                                   # 0 ดีมาก 1 ดี 2 ปานกลาง 3 เริ่มมีผล 4 มีผล
    if intensity == "heavy" or sensitive:
        dust = "good" if i <= 1 else "caution" if i == 2 else "bad"
    elif intensity == "moderate":
        dust = "good" if i <= 1 else "caution" if i <= 3 else "bad"
    else:
        dust = "good" if i <= 2 else "caution" if i == 3 else "bad"

    # ---- ฝน: ใช้โอกาสฝนสูงสุดในช่วงกิจกรรม
    rain = float(seg["precipitation_probability"].fillna(0).max())
    rain_s = "good" if rain < 30 else "caution" if rain < 60 else "bad"

    # ---- ความร้อน: ใช้อุณหภูมิอากาศสูงสุดในช่วงกิจกรรม
    temp = float(seg["temperature_2m"].max())
    heat_s = "good" if temp < C.HEAT_OK else "caution" if temp < (
        C.HEAT_CAUTION_HEAVY if intensity == "heavy" else C.HEAT_CAUTION) else "bad"

    reasons = [
        {"key": "dust", "topic": "ฝุ่น PM2.5", "status": dust, "value": f"สูงสุด {pm:.0f} {C.PM_UNIT}",
         "level": lv["level"], "color": lv["color"],
         "meaning": "อยู่ในเกณฑ์ดี" if dust == "good" else
         ("ใส่หน้ากากและพักเป็นระยะ" if dust == "caution" else "ฝุ่นสูงเกินไปสำหรับกิจกรรมนี้")},
        {"key": "rain", "topic": "ฝน", "status": rain_s, "value": f"โอกาสฝนสูงสุด {rain:.0f}%",
         "level": "ไม่น่าตก" if rain < 30 else "อาจตก" if rain < 60 else "มีโอกาสตกสูง", "color": None,
         "meaning": "ไม่ต้องกังวลเรื่องฝน" if rain < 30 else "เตรียมร่มหรือที่หลบฝน" if rain < 60
         else "ควรมีแผนสำรองในร่ม"},
        {"key": "heat", "topic": "ความร้อน", "status": heat_s, "value": f"อุณหภูมิสูงสุด {temp:.0f}°C",
         "level": C.heat_level(temp)["level"], "color": None,
         "meaning": "อากาศกำลังสบาย" if heat_s == "good" else "ดื่มน้ำบ่อย ๆ และพักในที่ร่ม"
         if heat_s == "caution" else "เสี่ยงเพลียแดด ควรเลื่อนไปช่วงที่เย็นกว่า"},
    ]
    overall = max((r["status"] for r in reasons), key=_RANK.get)
    title, color = VERDICT[overall]
    why = [_PHRASE[r["key"]][r["status"]] for r in reasons if r["status"] == overall and overall != "good"]
    because = " และ".join(why) if why else "ฝุ่น ฝน และความร้อนอยู่ในเกณฑ์ดีตลอดช่วงเวลา"

    checklist = []
    if dust != "good":
        checklist.append("หน้ากาก N95 หรือ KN95")
    if rain >= 30:
        checklist.append("ร่มหรือเสื้อกันฝน")
    if rain >= 60:
        checklist.append("แผนสำรองในร่ม")
    if temp >= C.HEAT_OK:
        checklist.append("น้ำดื่มอย่างน้อย 1 ลิตร และพักในที่ร่มทุก 30 นาที" if intensity == "heavy"
                         else "น้ำดื่ม และหาที่ร่มไว้พัก")
    if sensitive:
        checklist.append("ยาประจำตัวของคนที่แพ้ฝุ่นหรือเป็นหอบหืด")
    if int(seg["horizon"].min()) > 3:
        checklist.append("เปิดดูพยากรณ์อีกครั้งก่อนออก 1 ชม.")

    options = []
    if overall != "good":
        options.append("เลื่อนไปช่วงเวลาที่ดีกว่า")
        if overall == "bad":
            places = ", ".join(n for n, _ in C.INDOOR_PLACES[:2])
            options.append(f"ย้ายเข้าในร่ม เช่น {places}" if places else "ย้ายเข้าอาคารหรือโรงยิมในร่ม ถ้ากิจกรรมทำได้")
        if intensity == "heavy":
            options.append("ลดเวลาหรือลดความหนักของกิจกรรม")

    conf = C.confidence_label(int(seg["horizon"].min()))
    return {"verdict": overall, "title": title, "because": because, "color": color,
            "reasons": reasons, "checklist": checklist, "options": options,
            "confidence": conf["label"], "start": start, "hours": hours,
            "intensity": intensity, "sensitive": bool(sensitive)}



# ======================================================================== กิจกรรมในร่ม: ดูเฉพาะตอนเดินทางไป-กลับ
@ttl_cache(seconds=600)
def travel_check(start: pd.Timestamp, hours: int, sensitive: bool = False) -> dict:
    """กิจกรรมในร่มไม่ได้รับผลจากฝุ่น ฝน แดดโดยตรง แต่ช่วงเดินทางไป (ชั่วโมงเริ่ม) และกลับ (ชั่วโมงจบ) ยังอยู่ข้างนอก
    คืนรูปแบบเดียวกับ evaluate() เพื่อใช้ร่วมกับหน้าเว็บ ตาราง และอีเมลได้"""
    fc = F.get_forecast()["hourly"]
    start = pd.Timestamp(start)
    end = start + pd.Timedelta(hours=hours)
    legs = fc[fc["time"].isin([start, end - pd.Timedelta(hours=1), end])]
    if legs.empty:
        raise ValueError("ช่วงเวลานี้อยู่นอกช่วงพยากรณ์ (วางแผนล่วงหน้าได้ไม่เกิน 7 วัน และต้องยังไม่ผ่านไป)")
    pm = float(legs["pm25"].max())
    lv = C.pm25_level(pm)
    rain = float(legs["precipitation_probability"].fillna(0).max())
    temp = float(legs["temperature_2m"].max())
    mask = lv["index"] >= 3 or (sensitive and lv["index"] >= 2)
    checklist = []
    if mask:
        checklist.append("หน้ากาก N95 หรือ KN95 ใส่ระหว่างเดินทาง")
    if rain >= 30:
        checklist.append("ร่มหรือเสื้อกันฝน สำหรับช่วงเดินไป-กลับ")
    if temp >= C.HEAT_CAUTION:
        checklist.append("น้ำดื่ม และเดินในที่ร่มระหว่างทาง")
    if sensitive and lv["index"] >= 1:
        checklist.append("ยาประจำตัวของคนที่แพ้ฝุ่นหรือเป็นหอบหืด")
    notes = []
    if mask:
        notes.append(f"ฝุ่นช่วงเดินทาง{lv['level']}")
    if rain >= 30:
        notes.append(f"อาจมีฝนตอนเดินทาง ({rain:.0f}%)")
    verdict = "caution" if notes else "good"
    because = ("กิจกรรมทำในร่มได้ตามปกติ แต่" + " และ".join(notes)) if notes else \
        "กิจกรรมทำในร่มได้ตามปกติ และช่วงเดินทางไป-กลับอากาศดี"
    reasons = [
        {"key": "dust", "topic": "ฝุ่นช่วงเดินทาง", "status": "caution" if mask else "good",
         "value": f"สูงสุด {pm:.0f} {C.PM_UNIT}", "level": lv["level"], "color": lv["color"],
         "meaning": "ใส่หน้ากากระหว่างเดินทาง" if mask else "ไม่ต้องใส่หน้ากาก"},
        {"key": "rain", "topic": "ฝนช่วงเดินทาง", "status": "caution" if rain >= 30 else "good",
         "value": f"โอกาสฝนสูงสุด {rain:.0f}%", "level": "ไม่น่าตก" if rain < 30 else "อาจตก" if rain < 60 else "มีโอกาสตกสูง",
         "color": None, "meaning": "พกร่ม" if rain >= 30 else "ไม่ต้องพกร่ม"},
        {"key": "heat", "topic": "อุณหภูมิช่วงเดินทาง", "status": "good", "value": f"สูงสุด {temp:.0f}°C",
         "level": C.heat_level(temp)["level"], "color": None, "meaning": "ทำกิจกรรมในร่ม ไม่ได้อยู่กลางแดด"},
    ]
    title = "ทำได้ตามปกติ" if verdict == "good" else "ทำได้ เตรียมตัวตอนเดินทาง"
    return {"verdict": verdict, "title": title, "because": because,
            "color": VERDICT["good"][1] if verdict == "good" else "#2F80ED",
            "reasons": reasons, "checklist": checklist, "options": [], "indoor": True,
            "confidence": C.confidence_label(int(legs["horizon"].min()))["label"], "start": start, "hours": hours,
            "intensity": "light", "sensitive": bool(sensitive)}


def assess(start, hours, intensity="moderate", sensitive=False, indoor=False) -> dict:
    """จุดเดียวที่ทุกหน้าใช้: กลางแจ้ง -> evaluate, ในร่ม -> travel_check"""
    return travel_check(start, hours, sensitive) if indoor else evaluate(start, hours, intensity, sensitive)


# ======================================================================== สถานที่ใน สจล. ที่เข้ากับกิจกรรม
# (คำในชื่อกิจกรรม, สถานที่กลางแจ้งที่ใช้ได้, สถานที่ในร่มที่ใช้แทนได้)  ใช้เฉพาะสถานที่ที่ยืนยันจากเว็บ สจล. แล้ว
PLACE_RULES = [
    (("วิ่ง", "จ๊อก", "เดินออกกำลัง"), "ลู่วิ่งยางสังเคราะห์ สนามกีฬากลาง", "ลู่วิ่งในฟิตเนส KM Wellness & Sport Center"),
    (("บาส",), None, "โรงยิม 1 ฝั่งวิศวฯ (สนามบาสในร่ม 1 สนาม)"),
    (("วอลเลย์",), None, "โรงยิม 1 ฝั่งวิศวฯ (สนามวอลเลย์บอลในร่ม 2 สนาม)"),
    (("แบด",), None, "โรงยิม 2 ระหว่างสนามกีฬากลางกับหอใน (แบดมินตัน 9 คอร์ต)"),
    (("ปิงปอง",), None, "โรงยิม 2 ระหว่างสนามกีฬากลางกับหอใน (โต๊ะปิงปอง 4 โต๊ะ)"),
    (("ฟุตบอล", "เตะบอล", "ฟุตซอล"), "สนามกีฬากลาง",
     "ฟิตเนส KM Wellness & Sport Center หรือเปลี่ยนไปเล่นบาส/วอลเลย์ที่โรงยิม 1 ฝั่งวิศวฯ"),
    (("ตลาด", "ช้อป"), "ตลาดใจกล้า (ตึกพระเทพ) ตลาดหอใน (อ.–พฤ.) หรือตลาดวิศวะการ์เด้น (ทุกวัน)",
     "ร้านอิ่มเอม (ในร่ม) หรือเลื่อนไปวันที่อากาศดี"),
    (("กินข้าว", "กินอาหาร", "หาอะไรกิน"), "ร้านอาหารซอยเกกีงาม 4 หรือตลาดวิศวะการ์เด้น", "ร้านอิ่มเอม (ในร่ม)"),
    (("ตะกร้อ",), "สนามตะกร้อ สนามกีฬากลาง", None),
    (("เทนนิส",), "สนามเทนนิส 4 คอร์ต", None),
    (("ว่ายน้ำ",), "สระว่ายน้ำเฉลิมพระเกียรติ สมเด็จพระเทพฯ (เปิด 9:00–19:30)", None),
    (("ฟิตเนส", "ยกเวท", "เวท", "โยคะ", "แอโรบิก"), None, "KM Wellness & Sport Center (เปิด 9:00–20:00)"),
    (("อ่านหนังสือ", "ติว", "ทำงานกลุ่ม", "ทำการบ้าน", "ประชุม"), None,
     "Co-working space ตึก HM ชั้น 3–7 (6:00–22:00) หรือหอสมุด KLLC"),
    (("เดินเล่น", "ปิกนิก", "นั่งเล่น"), "สวนรัชกาลที่ 4 และสวนพักผ่อนของสถาบัน", "หอสมุด KLLC หรือตึก HM"),
]


def suggest_place(activity: str, verdict: str, indoor: bool = False) -> str | None:
    """แนะนำสถานที่ใน สจล. เฉพาะเมื่อมีประโยชน์: เหมาะ -> ที่ทำกลางแจ้งได้ / ไม่เหมาะ -> ที่ในร่มที่ใช้แทน
    ถ้าไม่มีสถานที่ที่ยืนยันแล้วสำหรับกิจกรรมนี้ คืน None (ไม่เดา)"""
    a = (activity or "").lower()
    for words, outdoor, indoor_place in PLACE_RULES:
        if any(w in a for w in words):
            if indoor:
                return f"ทำได้ที่ {indoor_place}" if indoor_place else None
            if verdict == "good":
                return f"ที่ทำได้ใน สจล.: {outdoor}" if outdoor else None
            if indoor_place:
                return f"ย้ายเข้าในร่มได้ที่ {indoor_place}"
            return "กิจกรรมนี้ไม่มีสนามในร่มใน สจล. แนะนำเลื่อนเวลาแทน"
    return None


def _score(fc: pd.DataFrame) -> pd.Series:
    """คะแนนความไม่เหมาะ (ยิ่งต่ำยิ่งดี) รวมฝุ่น ฝน ความร้อน"""
    return fc["pm25"] / C.STANDARD_PM25 + fc["precipitation_probability"].fillna(0) / 50 \
        + (fc["temperature_2m"] - C.HEAT_OK).clip(lower=0) / 3


@ttl_cache(seconds=600)
def better_times(hours: int, days: int = 3, earliest: int = 6, latest: int = 21, exclude=None,
                 prefer_hour: int | None = None, max_shift: int | None = None) -> list[dict]:
    """ช่วงเวลาที่ดีที่สุด 3 ช่วง (วันละไม่เกิน 1 ช่วง) เรียงตามเวลา
    prefer_hour: ให้น้ำหนักกับเวลาที่ใกล้เวลาเดิมของผู้ใช้ (นัดเย็น ก็เสนอเวลาเย็น)
    max_shift: เสนอเฉพาะเวลาที่ห่างจากเวลาเดิมไม่เกินกี่ชั่วโมง (คนนัดเตะบอลเย็น ไม่อยากถูกเสนอให้ไปตอนเช้า)"""
    fc = F.get_forecast()["hourly"].set_index("time")
    end = C.now_local().normalize() + pd.Timedelta(days=days + 1)
    fc = fc[fc.index < end]
    roll = _score(fc).rolling(hours).mean().shift(-(hours - 1)).dropna()
    roll = roll[roll.index > C.now_local()]
    if prefer_hour is not None:
        roll = roll + pd.Series([abs(t.hour - prefer_hour) * 0.04 for t in roll.index], index=roll.index)
    picks, used = [], set()
    for t, _ in roll.sort_values().items():
        if t.hour < earliest or t.hour + hours > latest:
            continue
        if prefer_hour is not None and max_shift is not None and abs(t.hour - prefer_hour) > max_shift:
            continue
        if t.date() in used or (exclude is not None and t == pd.Timestamp(exclude)):
            continue
        used.add(t.date())
        seg = fc.loc[t: t + pd.Timedelta(hours=hours - 1)]
        picks.append({"start": t, "end": t + pd.Timedelta(hours=hours), "pm25": float(seg["pm25"].max()),
                      "rain": float(seg["precipitation_probability"].fillna(0).max()),
                      "temp": float(seg["temperature_2m"].max())})
        if len(picks) == 3:
            break
    return sorted(picks, key=lambda x: x["start"])


@ttl_cache(seconds=600)
def best_on_same_day(start: pd.Timestamp, hours: int, intensity: str, sensitive: bool,
                     earliest: int = 6, latest: int = 21):
    """ช่วงเวลาในวันเดียวกันที่ผลประเมินดีกว่าแผนเดิม (ใช้กับปุ่ม 'เลื่อนเป็น ...') ไม่มีคืน None"""
    start = pd.Timestamp(start)
    try:
        base = evaluate(start, hours, intensity, sensitive)
    except ValueError:
        return None
    if base["verdict"] == "good":
        return None
    now = C.now_local().floor("h")
    best = None
    lo, hi = max(earliest, start.hour - 4), min(latest - hours, start.hour + 4)   # เลื่อนไม่เกิน 4 ชม.
    for h in range(lo, hi + 1):
        t = start.normalize() + pd.Timedelta(hours=h)
        if t == start or t <= now:
            continue
        try:
            r = evaluate(t, hours, intensity, sensitive)
        except ValueError:
            continue
        if _RANK[r["verdict"]] < _RANK[base["verdict"]]:
            if best is None or _RANK[r["verdict"]] < _RANK[best["verdict"]] or \
                    (_RANK[r["verdict"]] == _RANK[best["verdict"]] and abs(h - start.hour) < abs(best["start"].hour - start.hour)):
                best = r
    return best


# ======================================================================== แปลงประโยคภาษาไทยด้วยกฎ (สำรอง)
_TH_DIGIT = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_NUM_WORDS = [("สิบเอ็ด", 11), ("สิบสอง", 12), ("สิบ", 10), ("หนึ่ง", 1), ("นึง", 1), ("สอง", 2), ("สาม", 3),
              ("สี่", 4), ("ห้า", 5), ("หก", 6), ("เจ็ด", 7), ("แปด", 8), ("เก้า", 9)]
_NUM_RE = r"(\d{1,2}|สิบเอ็ด|สิบสอง|สิบ|หนึ่ง|นึง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)"
_WEEKDAYS = [("จันทร์", 0), ("อังคาร", 1), ("พุธ", 2), ("พฤหัส", 3), ("ศุกร์", 4), ("เสาร์", 5), ("อาทิตย์", 6)]

# (คำค้น, ชื่อที่แสดง, ระดับการออกแรง, ชั่วโมงโดยปกติ) — เรียงคำยาวก่อน
ACTIVITY_WORDS = [
    ("ฟุตซอล", "เตะฟุตซอล", "heavy", 2), ("ฟุตบอล", "เตะฟุตบอล", "heavy", 2), ("บอล", "เตะบอล", "heavy", 2),
    ("บาส", "เล่นบาส", "heavy", 2), ("วอลเลย์", "เล่นวอลเลย์บอล", "heavy", 2), ("แบด", "ตีแบด", "heavy", 2),
    ("เทนนิส", "เล่นเทนนิส", "heavy", 2), ("ตะกร้อ", "เล่นตะกร้อ", "heavy", 2), ("วิ่ง", "วิ่ง", "heavy", 1),
    ("เชียร์", "ซ้อมเชียร์", "heavy", 3), ("เต้น", "ซ้อมเต้น", "heavy", 2), ("ออกกำลัง", "ออกกำลังกาย", "heavy", 1),
    ("กีฬาสี", "งานกีฬาสี", "heavy", 4), ("กีฬา", "เล่นกีฬา", "heavy", 2), ("ซ้อม", "ซ้อม", "heavy", 2),
    ("รับปริญญา", "ถ่ายรูปรับปริญญา", "light", 3), ("ถ่ายรูป", "ถ่ายรูป", "light", 2),
    ("บูธ", "ออกบูธ", "moderate", 4), ("ตลาดนัด", "ตลาดนัด", "moderate", 3), ("ตลาด", "เดินตลาด", "moderate", 2),
    ("รับน้อง", "รับน้อง", "moderate", 4), ("จัดงาน", "จัดงาน", "moderate", 4), ("งาน", "จัดงาน", "moderate", 3),
    ("ปั่น", "ปั่นจักรยาน", "moderate", 1), ("จักรยาน", "ปั่นจักรยาน", "moderate", 1),
    ("เดินเล่น", "เดินเล่น", "moderate", 1), ("เดิน", "เดิน", "moderate", 1), ("ปิกนิก", "ปิกนิก", "light", 2),
    ("กินข้าว", "กินข้าว", "light", 1), ("อ่านหนังสือ", "อ่านหนังสือ", "light", 2),
    ("รอรถ", "รอรถ", "light", 1), ("นั่ง", "นั่งเล่น", "light", 1), ("พิธี", "งานพิธี", "light", 2),
]
INDOOR_WORDS = ["ในร่ม", "โรงยิม", "ยิม", "ฟิตเนส", "ในห้อง", "ห้องเรียน", "หอประชุม", "ในอาคาร", "ในตึก", "ห้าง",
                "ห้องสมุด", "หอสมุด", "kllc", "KLLC", "co-working", "โคเวิร์ก", "แล็บ", "ห้องแล็บ", "ประชุม", "ติวหนังสือ", "อ่านหนังสือ"]
SENSITIVE_WORDS = ["แพ้ฝุ่น", "หอบหืด", "ภูมิแพ้", "หอบ", "เด็กเล็ก", "ผู้สูงอายุ", "คนแก่"]


def _num(w: str) -> int:
    if w.isdigit():
        return int(w)
    for word, n in _NUM_WORDS:
        if w == word:
            return n
    return int(w)


def _times(t: str) -> list[tuple[int, int, int]]:
    """หาเวลาทุกจุดในข้อความ คืน [(ตำแหน่ง, ชั่วโมง, นาที)]"""
    found = []
    for m in re.finditer(r"(\d{1,2})[:.](\d{2})", t):
        found.append((m.start(), int(m.group(1)), int(m.group(2))))
    pats = [
        (r"บ่าย\s*" + _NUM_RE + r"?\s*(?:โมง)?", lambda n: 12 + (n or 1)),
        (_NUM_RE + r"\s*โมง\s*เย็น", lambda n: n + 12 if n < 12 else n),
        (_NUM_RE + r"\s*โมง\s*เช้า", lambda n: n),
        (r"ตี\s*" + _NUM_RE, lambda n: n),
        (_NUM_RE + r"\s*ทุ่ม|ทุ่ม\s*(นึง|หนึ่ง)", lambda n: 18 + (n or 1)),
        (r"เที่ยงคืน", lambda n: 0),
        (r"เที่ยง", lambda n: 12),
        (_NUM_RE + r"\s*โมง", lambda n: n if 7 <= n <= 12 else (n + 12 if n <= 6 else n)),
    ]
    taken = [(p, p + 5) for p, _, _ in found]
    for pat, fn in pats:
        for m in re.finditer(pat, t):
            if any(a <= m.start() < b for a, b in taken):
                continue
            g = next((x for x in m.groups() if x), None) if m.groups() else None
            n = _num(g) if g else None
            if pat.startswith(_NUM_RE) and n is None:
                continue
            h = fn(n)
            if "เช้า" in t[m.end():m.end() + 6] and h >= 12 and pat.endswith("โมง"):
                h -= 12
            found.append((m.start(), h % 24, 0))
            taken.append((m.start(), m.end()))
    return sorted(found)


def parse_text(text: str) -> dict:
    """แปลงประโยค เช่น 'พรุ่งนี้ห้าโมงเย็นเตะบอล 2 ชม.' เป็นข้อมูลแผน (ใช้กฎ ไม่ใช้ AI)
    คืน {activity_name, date, start_hour, duration_hours, intensity, is_outdoor, sensitive, missing}"""
    raw = (text or "").strip()
    t = raw.translate(_TH_DIGIT).replace("ชั่วโมง", "ชม").replace("ชม.", "ชม")
    today = C.now_local().date()

    # ---- กิจกรรม
    name, intensity, dur_default = None, "moderate", 2
    for kw, disp, inten, d in ACTIVITY_WORDS:
        if kw in t:
            name, intensity, dur_default = disp, inten, d
            break

    # ---- วัน
    date = None
    if re.search(r"มะรืน", t):
        date = today + pd.Timedelta(days=2)
    elif "พรุ่งนี้" in t:
        date = today + pd.Timedelta(days=1)
    elif re.search(r"วันนี้|คืนนี้|เย็นนี้|เช้านี้|บ่ายนี้|ตอนนี้|เดี๋ยวนี้", t):
        date = today
    else:
        for word, wd in _WEEKDAYS:
            m = re.search(word + r"(\s*หน้า)?", t)
            if m:
                ahead = (wd - today.weekday()) % 7
                if m.group(1):
                    ahead += 7
                date = today + pd.Timedelta(days=ahead)
                break
        m = re.search(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", t)
        if date is None and m:
            try:
                date = pd.Timestamp(year=today.year, month=int(m.group(2)), day=int(m.group(1))).date()
            except ValueError:
                pass

    # ---- เวลาเริ่ม + ระยะเวลา
    times = _times(t)
    start_hour = times[0][1] if times else None
    if start_hour is None:
        for word, h in [("เช้า", 7), ("สาย", 10), ("บ่าย", 14), ("เย็น", 17), ("ค่ำ", 19), ("กลางคืน", 20)]:
            if word in t:
                start_hour = h
                break
    duration = None
    m = re.search(_NUM_RE + r"\s*ชม", t)
    if m:
        duration = _num(m.group(1))
    elif "ครึ่งชม" in t:
        duration = 1
    elif "ทั้งวัน" in t:
        duration, start_hour = 9, start_hour if start_hour is not None else 9
    elif len(times) >= 2 and times[1][1] > times[0][1]:
        duration = times[1][1] - times[0][1]
    if date is None and start_hour is not None:
        date = today if start_hour > C.now_local().hour else today + pd.Timedelta(days=1)
    elif date == today and start_hour is not None and start_hour <= C.now_local().hour \
            and any(w in t for w, _ in _WEEKDAYS) and "นี้" not in t:
        date = today + pd.Timedelta(days=7)            # "วันเสาร์" แต่เวลาวันนี้ผ่านไปแล้ว = เสาร์หน้า

    is_outdoor = not any(w in t for w in INDOOR_WORDS) or "กลางแจ้ง" in t
    sensitive = any(w in t for w in SENSITIVE_WORDS)
    missing = [k for k, v in (("date", date), ("start_hour", start_hour)) if v is None]
    return {"activity_name": name or (raw[:40] if raw else "กิจกรรม"),
            "date": date.isoformat() if date is not None else None,
            "start_hour": start_hour, "duration_hours": int(min(max(duration or dur_default, 1), 12)),
            "intensity": intensity, "is_outdoor": is_outdoor, "sensitive": sensitive, "missing": missing,
            "parser": "rule"}


# ======================================================================== อีเมลเตือนก่อนเริ่ม 1 ชม.
def smtp_ready() -> bool:
    import os
    return bool(os.getenv("SMTP_USER")) and bool(os.getenv("SMTP_APP_PASSWORD"))


def email_ready() -> bool:
    return C.env_flag("EMAIL_REMINDER", False) and smtp_ready()


def send_reset_code(to: str, code: str):
    body = f"""<div style="font-family:Tahoma,sans-serif;max-width:480px;color:#222">
<h2 style="margin:0 0 8px">ตั้งรหัสผ่านใหม่</h2>
<p>รหัสยืนยันของคุณคือ</p>
<p style="font-size:32px;letter-spacing:8px;font-weight:bold;color:#E8742A;margin:8px 0">{code}</p>
<p>ใช้ได้ภายใน 15 นาที ถ้าคุณไม่ได้ขอตั้งรหัสผ่านใหม่ ไม่ต้องทำอะไร รหัสผ่านเดิมยังใช้ได้ตามปกติ</p>
<p style="color:#888;font-size:12px">{C.APP_NAME}</p></div>"""
    send_email(to, f"[{C.APP_NAME}] รหัสยืนยันสำหรับตั้งรหัสผ่านใหม่", body)


def _report_html(a: dict) -> tuple[str, str]:
    """สร้างหัวเรื่องและเนื้อหาอีเมล: ผลประเมินล่าสุด + สถานการณ์ตอนนี้"""
    import html
    from data_sources import fetch_current_pm
    esc = html.escape
    ev = assess(a["start_ts"], a["hours"], a["intensity"], a["sensitive"], a.get("setting") == "indoor")
    now_lines = []
    try:
        cur = fetch_current_pm()
        if cur:
            lv = C.pm25_level(cur["pm25"])
            now_lines.append(f"ฝุ่น PM2.5 ตอนนี้ {cur['pm25']:.0f} {C.PM_UNIT} ({lv['level']}) จาก {cur.get('source_short', '')}")
    except Exception:
        pass
    try:
        w = F.current_weather()
        now_lines.append(f"อุณหภูมิ {w['temperature_c']:.0f}°C ความชื้น {w['humidity_percent']}% ลม {w['wind_kmh']:.0f} กม./ชม."
                         + (" ตอนนี้ฝนกำลังตก" if w["raining"] else "") + f" ({w['source_short']})")
    except Exception:
        pass
    changed = bool(a.get("verdict_at_save")) and a["verdict_at_save"] not in (ev["title"], ev["verdict"])
    reasons = "".join(f"<tr><td style='padding:4px 10px 4px 0'><b>{esc(r['topic'])}</b></td>"
                      f"<td style='padding:4px 10px 4px 0'>{esc(r['value'])}</td><td>{esc(r['meaning'])}</td></tr>"
                      for r in ev["reasons"])
    saved, done = list(a.get("prepare") or []), set(a.get("checked") or [])
    items = saved + [x for x in ev["checklist"] if x not in saved]          # รายการของผู้ใช้ (รวมที่เพิ่มเอง) + ที่ระบบแนะนำใหม่
    prep = "".join(f"<li>{'✅ ' if x in done else '⬜ '}{esc(x)}"
                   + (" <span style='color:#B4532A;font-size:12px'>(ระบบแนะนำเพิ่มตามพยากรณ์ล่าสุด)</span>" if x not in saved else "")
                   + "</li>" for x in items) or "<li>ไม่มีอะไรพิเศษ</li>"
    end = a["end_ts"]
    subject = f"[{C.APP_NAME}] อีก 1 ชม. {a['title']} {a['start_ts']:%H:%M} น. : {ev['title']}"
    body = f"""<div style="font-family:Tahoma,sans-serif;max-width:560px;color:#222">
<h2 style="margin:0 0 4px">{esc(a['title'])}</h2>
<p style="margin:0;color:#666">{a['start_ts']:%d/%m/%Y %H:%M}–{end:%H:%M} น. ที่ {esc(C.KMITL_NAME)}</p>
<div style="margin:14px 0;padding:12px 14px;border-radius:12px;background:{ev['color']}18;border-left:5px solid {ev['color']}">
<b style="color:{ev['color']};font-size:18px">{esc(ev['title'])}</b><br>{esc(ev['because'])}</div>
{"<p style='color:#B4532A'><b>ผลเปลี่ยนจากตอนที่บันทึกไว้</b> ลองเปิดเว็บดูช่วงเวลาอื่นที่ดีกว่า</p>" if changed else ""}
<h3 style="margin:14px 0 4px">สถานการณ์ตอนนี้</h3><p style="margin:0">{"<br>".join(esc(x) for x in now_lines) or "ดึงข้อมูลตอนนี้ไม่ได้"}</p>
<h3 style="margin:14px 0 4px">ช่วงกิจกรรม (พยากรณ์)</h3><table style="border-collapse:collapse">{reasons}</table>
<h3 style="margin:14px 0 4px">ของที่ควรเตรียม</h3><ul style="margin:0;list-style:none;padding-left:4px">{prep}</ul>
{f"<p style='margin:10px 0 0'><b>บันทึกของคุณ:</b> {esc(a['note'])}</p>" if a.get('note') else ""}
<p style="color:#888;font-size:12px;margin-top:18px">ส่งอัตโนมัติจาก {esc(C.APP_NAME)} ปิดการแจ้งเตือนได้ที่หน้า บัญชีของฉัน
ใช้ประกอบการตัดสินใจเท่านั้น</p></div>"""
    return subject, body


def send_email(to: str, subject: str, html_body: str):
    """ส่งผ่าน Gmail: ลองพอร์ต 587 (STARTTLS) ก่อน ถ้าไม่ได้ค่อยลอง 465 (SSL)
    บางเครือข่าย (เช่น Wi-Fi มหาลัย หรือโปรแกรมแอนตี้ไวรัส) ปิดพอร์ตใดพอร์ตหนึ่งไว้"""
    import os, smtplib, ssl
    from email.mime.text import MIMEText
    user = (os.getenv("SMTP_USER") or "").strip()
    pw = (os.getenv("SMTP_APP_PASSWORD") or "").replace(" ", "").strip()
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, f"{C.APP_NAME} <{user}>", to
    ctx = ssl.create_default_context()
    errors = []
    for port in (587, 465):
        try:
            if port == 587:
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
                    s.ehlo(); s.starttls(context=ctx); s.ehlo()
                    s.login(user, pw); s.send_message(msg)
            else:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20, context=ctx) as s:
                    s.login(user, pw); s.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError:
            raise RuntimeError("Gmail ไม่รับรหัส ตรวจ SMTP_USER และ App Password 16 ตัว (ต้องไม่ใช่รหัส Gmail ปกติ)")
        except Exception as e:
            errors.append(f"พอร์ต {port}: {e}")
    raise RuntimeError("เชื่อมต่อ Gmail ไม่ได้ อาจถูกเครือข่ายหรือแอนตี้ไวรัสบล็อก ลองใช้ Wi-Fi อื่นหรือฮอตสปอตมือถือ ("
                       + " | ".join(errors) + ")")


def send_reminder(a: dict, to: str | None = None):
    subject, body = _report_html(a)
    send_email(to or a["email"], subject, body)


def check_reminders() -> int:
    """ส่งอีเมลให้กิจกรรมที่จะเริ่มภายใน 1 ชม. คืนจำนวนที่ส่ง"""
    import store
    sent = 0
    for a in store.due_reminders(60):
        try:
            send_reminder(a)
            store.mark_reminded(a["id"])
            sent += 1
        except Exception as e:
            print("reminder failed:", a["id"], e)
    return sent


# ======================================================================== สรุปตอนเช้า: ส่งเฉพาะวันที่อากาศไม่ดี
DAILY_HOUR = 6          # ส่งหลัง 06:30 น. (ปรับได้ด้วย DAILY_ALERT_HOUR ใน .env)
DAILY_FROM, DAILY_TO = 6, 21   # ดูเฉพาะช่วงที่คนออกไปข้างนอก


def _runs(mask: pd.Series, times: pd.Series) -> list[tuple]:
    """ช่วงเวลาต่อเนื่องที่ mask เป็นจริง -> [(เริ่ม, จบ)]"""
    out, start, prev = [], None, None
    for t, m in zip(times, mask):
        if m and start is None:
            start = t
        if not m and start is not None:
            out.append((start, prev + pd.Timedelta(hours=1)))
            start = None
        prev = t
    if start is not None:
        out.append((start, prev + pd.Timedelta(hours=1)))
    return out


def daily_alerts(day=None, sensitive: bool = False) -> list[dict]:
    """หาเรื่องที่ควรรู้ของวันนี้ (ฝน ฝุ่น ร้อน) คืนรายการว่างถ้าอากาศดีทั้งวัน"""
    fc = F.get_forecast()["hourly"]
    day = pd.Timestamp(day or C.now_local()).normalize()
    d = fc[(fc["time"] >= day + pd.Timedelta(hours=DAILY_FROM)) & (fc["time"] < day + pd.Timedelta(hours=DAILY_TO))]
    d = d[d["time"] >= C.now_local().floor("h")]
    if d.empty:
        return []
    alerts = []
    rain = d["precipitation_probability"].fillna(0)
    for a, b in _runs(rain >= 50, d["time"]):
        seg = rain[(d["time"] >= a) & (d["time"] < b)]
        alerts.append({"kind": "rain", "icon": "🌧️", "title": f"มีโอกาสฝนตก {seg.max():.0f}%",
                       "when": f"{a:%H:%M}–{b:%H:%M} น.", "tip": "พกร่ม ถ้ามีกิจกรรมกลางแจ้งช่วงนี้ควรมีแผนสำรองในร่ม"})
    lim = 2 if sensitive else 3            # ระดับ "ปานกลาง" สำหรับกลุ่มเสี่ยง / "เริ่มมีผล" สำหรับคนทั่วไป
    idx = d["pm25"].apply(lambda v: C.pm25_level(v)["index"])
    for a, b in _runs(idx >= lim, d["time"]):
        seg = d[(d["time"] >= a) & (d["time"] < b)]["pm25"]
        lv = C.pm25_level(seg.max())
        alerts.append({"kind": "dust", "icon": "😷", "title": f"ฝุ่น PM2.5 สูงสุด {seg.max():.0f} {C.PM_UNIT} ({lv['level']})",
                       "when": f"{a:%H:%M}–{b:%H:%M} น.", "tip": "ใส่หน้ากาก N95 เมื่ออยู่ข้างนอก เลี่ยงออกกำลังกายกลางแจ้ง"})
    for a, b in _runs(d["temperature_2m"] >= C.HEAT_CAUTION_HEAVY, d["time"]):
        seg = d[(d["time"] >= a) & (d["time"] < b)]["temperature_2m"]
        alerts.append({"kind": "heat", "icon": "🌡️", "title": f"อากาศร้อน สูงสุด {seg.max():.0f}°C",
                       "when": f"{a:%H:%M}–{b:%H:%M} น.", "tip": "ดื่มน้ำบ่อย ๆ เลี่ยงแดดจัด"})
    return alerts


def daily_email(u: dict, force: bool = False) -> tuple[str, str] | None:
    """อีเมลสรุปเช้า คืน None ถ้าอากาศดีทั้งวันและไม่มีกิจกรรมที่ได้รับผล (ไม่ส่ง) / force=True ใช้ตอนทดสอบ"""
    import html
    import store
    esc = html.escape
    today = C.now_local().normalize()
    alerts = daily_alerts(today, bool(u.get("sensitive")))
    acts = [a for a in store.list_activities(u["id"]) if a["start_ts"].normalize() == today]
    act_rows = []
    for a in acts:
        try:
            ev = assess(a["start_ts"], a["hours"], a["intensity"], a["sensitive"], a.get("setting") == "indoor")
        except ValueError:
            continue
        act_rows.append(f"<li><b>{a['start_ts']:%H:%M} น. {esc(a['title'])}</b> — "
                        f"<span style='color:{ev['color']}'><b>{esc(ev['title'])}</b></span> {esc(ev['because'])}</li>")
    if not alerts and not force:
        return None
    if alerts:
        head = "วันนี้มีเรื่องที่ควรระวัง"
        items = "".join(f"<div style='margin:8px 0;padding:10px 12px;border-radius:10px;background:#FFF5EC'>"
                        f"<b>{x['icon']} {esc(x['title'])}</b> <span style='color:#666'>ช่วง {x['when']}</span>"
                        f"<br><span style='font-size:14px'>{esc(x['tip'])}</span></div>" for x in alerts)
    else:
        head = "วันนี้อากาศดี ไม่มีเรื่องต้องระวัง"
        items = "<p>ไม่มีฝนตกหนัก ฝุ่นอยู่ในเกณฑ์ดี และไม่ร้อนจัด ทำกิจกรรมกลางแจ้งได้ตามปกติ</p>"
    kinds = {"rain": "ฝน", "dust": "ฝุ่น", "heat": "ร้อน"}
    tag = " ".join(sorted({kinds[x["kind"]] for x in alerts}))
    subject = f"[{C.APP_NAME}] สรุปอากาศวันนี้ {today:%d/%m}" + (f" : ระวัง{tag}" if tag else " : อากาศดี")
    body = f"""<div style="font-family:Tahoma,sans-serif;max-width:560px;color:#222">
<h2 style="margin:0 0 4px">{head}</h2><p style="margin:0;color:#666">{today:%d/%m/%Y} · {esc(C.KMITL_NAME)} (ช่วง 06:00–21:00 น.)</p>
{items}
{"<h3 style='margin:16px 0 4px'>กิจกรรมของคุณวันนี้</h3><ul style='margin:0;padding-left:18px'>" + "".join(act_rows) + "</ul>" if act_rows else ""}
<p style="color:#888;font-size:12px;margin-top:18px">ส่งเฉพาะวันที่อากาศไม่ดี ถ้าไม่ได้รับอีเมล แปลว่าวันนั้นอากาศดี
· ปิดได้ที่หน้า บัญชีของฉัน · {esc(C.APP_NAME)}</p></div>"""
    return subject, body


def check_daily() -> int:
    """เรียกจากตัวเช็กเบื้องหลังทุก 5 นาที: หลัง 06:30 ส่งสรุปให้ผู้ใช้ที่เปิดรับ วันละครั้ง"""
    import os
    import store
    now = C.now_local()
    hour = int(os.getenv("DAILY_ALERT_HOUR", DAILY_HOUR))
    if not (now.hour > hour or (now.hour == hour and now.minute >= 30)) or now.hour >= 12:
        return 0
    sent = 0
    for u in store.daily_due(now.strftime("%Y-%m-%d")):
        try:
            mail = daily_email(u)
            if mail:
                send_email(u["email"], *mail)
                sent += 1
            store.mark_daily(u["id"], now.strftime("%Y-%m-%d"))   # วันที่อากาศดีก็บันทึกว่าเช็กแล้ว จะได้ไม่เช็กซ้ำ
        except Exception as e:
            print("daily alert failed:", u["id"], e)
    return sent
