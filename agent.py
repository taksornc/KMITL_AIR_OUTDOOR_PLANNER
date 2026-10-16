"""ผู้ช่วย AI (Google Gemini) ของ KMITL Outdoor Planner
หน้าที่ของ AI มี 3 อย่าง และไม่มีอย่างไหนที่เป็นการ "ตัดสิน" ว่ากิจกรรมทำได้หรือไม่
  1. parse_plan   : แปลงประโยคที่ผู้ใช้พิมพ์ เป็นข้อมูลแผน (วัน เวลา ระยะเวลา ลักษณะกิจกรรม)
  2. explain_plan : อธิบายผลประเมินจากเกณฑ์ และแนะนำสิ่งที่ควรเตรียมเฉพาะกิจกรรม
  3. AirAgent     : ตอบคำถามทั่วไป โดยดึงตัวเลขจาก tools เท่านั้น (function calling)
"""

from __future__ import annotations

import json
import os
import re
import time

import pandas as pd

import config as C
import tools as T
from data_sources import ttl_cache

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
BUSY = ("503", "UNAVAILABLE", "500", "INTERNAL", "429", "RESOURCE_EXHAUSTED", "overloaded")


_AUTO_CACHE: list[str] | None = None
_SKIP = ("tts", "image", "embedding", "live", "audio", "native", "vision", "aqa", "learnlm", "robotics", "computer-use")


def _discover(client) -> list[str]:
    """ดึงรายชื่อโมเดล Gemini ที่ key นี้ใช้ได้ (เฉพาะรุ่นสร้างข้อความ) เรียงรุ่น flash ก่อน"""
    global _AUTO_CACHE
    if _AUTO_CACHE is not None or client is None:
        return _AUTO_CACHE or []
    names = []
    try:
        for m in client.models.list():
            name = (m.name or "").replace("models/", "")
            acts = getattr(m, "supported_actions", None) or []
            if not name.startswith("gemini") or any(k in name for k in _SKIP):
                continue
            if acts and "generateContent" not in acts:
                continue
            names.append(name)
    except Exception:
        pass
    # flash-lite และ flash โควตาฟรีเยอะกว่า pro จึงลองก่อน รุ่นใหม่ก่อนรุ่นเก่า
    rank = lambda n: (0 if "flash-lite" in n else 1 if "flash" in n else 2, "preview" in n or "exp" in n)
    _AUTO_CACHE = sorted(names, key=lambda n: (rank(n), n), reverse=False)
    _AUTO_CACHE = sorted(_AUTO_CACHE, key=lambda n: rank(n)[0] != 1)   # flash ปกติก่อน แล้วค่อย lite และ pro
    return _AUTO_CACHE


def _models(model: str, client=None) -> list[str]:
    """รุ่นหลัก -> รุ่นสำรองใน GEMINI_FALLBACK_MODELS -> ถ้ามีคำว่า auto ให้ลองทุกรุ่นที่ key ใช้ได้"""
    fb = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-flash-latest,auto").split(",") if m.strip()]
    out = [model]
    for m in fb:
        for x in (_discover(client) if m.lower() == "auto" else [m]):
            if x not in out:
                out.append(x)
    return out[:8]


def _quota(msg: str) -> bool:
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def thinking(model: str):
    """ลดเวลาคิดของโมเดล (ตอบเร็วขึ้นมาก) ปรับได้ด้วย GEMINI_THINKING = minimal | low | medium | high | off
    รุ่น 3.x ใช้ thinking_level, รุ่น 2.5 ใช้ thinking_budget"""
    from google.genai import types
    level = os.getenv("GEMINI_THINKING", "low").strip().lower()
    if level in ("", "default", "off"):
        return None
    m = model.lower()
    if "gemini-2.5" in m:
        budget = {"minimal": 0, "low": 512, "medium": 2048, "high": -1}.get(level, 512)
        if "pro" in m and budget == 0:
            budget = 128                       # 2.5 Pro ปิดการคิดไม่ได้
        return types.ThinkingConfig(thinking_budget=budget)
    if "gemini-3" in m or "latest" in m:
        return types.ThinkingConfig(thinking_level=level.upper())
    return None


def _no_thinking_support(msg: str) -> bool:
    return ("thinking" in msg.lower()) and ("400" in msg or "INVALID_ARGUMENT" in msg)


def error_text(msg: str, model: str = "") -> str:
    if "API key" in msg or "PERMISSION_DENIED" in msg or "401" in msg or "API_KEY" in msg:
        return "GEMINI_API_KEY ไม่ถูกต้อง ตรวจสอบไฟล์ .env"
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "ใช้งาน Gemini เกินโควตาชั่วคราว รอสักครู่แล้วลองใหม่"
    if any(k in msg for k in BUSY):
        return "Gemini มีผู้ใช้หนาแน่นชั่วคราว ลองใหม่ในไม่กี่วินาที"
    if "404" in msg or "not found" in msg.lower():
        return f"ไม่พบโมเดล {model} ลองเปลี่ยน GEMINI_MODEL ในไฟล์ .env"
    return f"เรียก Gemini ไม่สำเร็จ ({msg[:120]})"


def _generate(api_key: str, model: str, prompt: str, as_json: bool = False) -> str:
    """เรียก Gemini ครั้งเดียว มีลองใหม่เมื่อเซิร์ฟเวอร์ไม่ว่าง และสลับไปรุ่นสำรองเมื่อจำเป็น"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    last = ""
    for m in _models(model, client):
        think = thinking(m)
        for attempt in range(3):
            cfg = types.GenerateContentConfig(temperature=0 if as_json else 0.4, thinking_config=think,
                                              response_mime_type="application/json" if as_json else None)
            try:
                text = (client.models.generate_content(model=m, contents=prompt, config=cfg).text or "").strip()
                if text:
                    return text
            except Exception as e:
                last = str(e)
                if think is not None and _no_thinking_support(last):
                    think = None                  # รุ่นนี้ไม่รับค่าการคิด -> ส่งใหม่แบบปกติ
                    continue
                if "404" in last or "not found" in last.lower() or _quota(last):
                    break                         # รุ่นนี้ไม่มีหรือโควตาเต็ม -> ไปรุ่นถัดไปทันที
                if not any(k in last for k in BUSY):
                    raise RuntimeError(error_text(last, m))
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(error_text(last or "503", model))


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0) if m else text)


def indoor_text() -> str:
    if not C.INDOOR_PLACES:
        return ("ไม่มีรายชื่อสถานที่ในร่มที่ยืนยันแล้ว ให้แนะนำแบบกว้าง ๆ เช่น \"ย้ายไปอาคารหรือโรงยิมในร่มที่ใกล้ที่สุด\" "
                "ห้ามเดาชื่ออาคาร")
    return "สถานที่ในร่มใน สจล. ที่ใช้แนะนำได้: " + "; ".join(f"{n} ({u})" for n, u in C.INDOOR_PLACES)


def _now_line() -> str:
    now = C.now_local()
    return f"วัน{THAI_DAYS[now.weekday()]}ที่ {now:%Y-%m-%d} เวลา {now:%H:%M} น. (เวลาประเทศไทย)"


# ======================================================================== 1) แปลงประโยคเป็นแผน
PARSE_PROMPT = """แปลงข้อความของผู้ใช้เป็นข้อมูลแผนกิจกรรม ตอบเป็น JSON อย่างเดียว
ตอนนี้คือ {now}

ข้อความ: "{text}"

รูปแบบ JSON:
{{"activity_name": "ชื่อกิจกรรมสั้น ๆ ภาษาไทย เช่น เตะบอล, ถ่ายรูปรับปริญญา",
  "date": "YYYY-MM-DD หรือ null ถ้าไม่ได้บอกวันและเดาไม่ได้",
  "start_hour": ตัวเลข 0-23 หรือ null,
  "duration_hours": ตัวเลข 1-12,
  "intensity": "heavy | moderate | light",
  "is_outdoor": true หรือ false,
  "sensitive": true หรือ false}}

กติกา
- วันพูดแบบสัมพัทธ์ (วันนี้ พรุ่งนี้ มะรืน เสาร์นี้ เสาร์หน้า) ให้แปลงเป็นวันที่จริงจากวันนี้
- เวลาแบบไทย: ห้าโมงเย็น=17, บ่ายสาม=15, หนึ่งทุ่ม=19, ตีห้า=5, เที่ยง=12
- บอกแค่ช่วง (เช้า บ่าย เย็น ค่ำ) ให้ใช้ 7, 14, 17, 19 ตามลำดับ
- บอกเวลาแต่ไม่บอกวัน ให้ใช้วันที่ใกล้ที่สุดที่เวลานั้นยังมาไม่ถึง
- ไม่บอกระยะเวลา ให้เดาตามปกติของกิจกรรมนั้น (เตะบอล 2, วิ่ง 1, ออกบูธ 4, ถ่ายรูป 2)
- intensity: heavy = หอบ เหงื่อออกมาก (วิ่ง กีฬา ซ้อมเชียร์ เต้น), moderate = ขยับตลอดแต่ไม่หอบ
  (เดิน ปั่นจักรยานสบาย ๆ จัดบูธ ยกของ), light = ยืนหรือนั่งเป็นส่วนใหญ่ (ถ่ายรูป กินข้าว รอรถ ชมงาน)
- is_outdoor = false ถ้าระบุว่าทำในร่ม หรือเป็นกิจกรรมที่ปกติทำในอาคาร เช่น ในยิม ฟิตเนส ในห้อง ห้องสมุด
  อ่านหนังสือ เรียน สอบ ประชุม หอประชุม ในอาคาร (ฟุตซอล บาส แบด ให้ถือว่ากลางแจ้ง เว้นแต่บอกว่าในร่มหรือในยิม)
- sensitive = true ถ้ามีคนแพ้ฝุ่น หอบหืด ภูมิแพ้ เด็กเล็ก หรือผู้สูงอายุร่วมด้วย"""


def _clean_plan(d: dict, text: str) -> dict:
    out = {"activity_name": str(d.get("activity_name") or "").strip()[:40] or text[:40],
           "date": None, "start_hour": None, "duration_hours": 2, "intensity": "moderate",
           "is_outdoor": bool(d.get("is_outdoor", True)), "sensitive": bool(d.get("sensitive", False))}
    try:
        out["date"] = pd.Timestamp(d.get("date")).date().isoformat() if d.get("date") else None
    except Exception:
        pass
    try:
        h = int(d.get("start_hour")) if d.get("start_hour") is not None else None
        out["start_hour"] = h if h is not None and 0 <= h <= 23 else None
    except (TypeError, ValueError):
        pass
    try:
        out["duration_hours"] = int(min(max(int(round(float(d.get("duration_hours") or 2))), 1), 12))
    except (TypeError, ValueError):
        pass
    if str(d.get("intensity")) in ("heavy", "moderate", "light"):
        out["intensity"] = d["intensity"]
    out["missing"] = [k for k in ("date", "start_hour") if out[k] is None]
    return out


@ttl_cache(seconds=3600)
def parse_plan(api_key: str, model: str, text: str, day_key: str = "") -> dict:
    """ข้อความ -> แผน (ใช้ Gemini) ถ้าล้มเหลวจะ raise RuntimeError ให้หน้าเว็บสลับไปใช้ตัวแปลงแบบกฎ"""
    raw = _generate(api_key, model, PARSE_PROMPT.format(now=_now_line(), text=text.replace('"', "'")), as_json=True)
    try:
        plan = _clean_plan(_json(raw), text)
    except Exception:
        raise RuntimeError("AI ตอบกลับในรูปแบบที่อ่านไม่ได้")
    plan["parser"] = "ai"
    return plan


# ======================================================================== 2) อธิบายผลประเมิน
EXPLAIN_PROMPT = """คุณเป็นผู้ช่วยวางแผนกิจกรรมกลางแจ้งใน สจล. ด้านล่างคือผลประเมินที่ระบบคำนวณจากเกณฑ์แล้ว (JSON)

{plan}

ตอบเป็น JSON อย่างเดียว:
{{"advice": "คำแนะนำ 2-3 ประโยค ภาษาไทยเป็นกันเอง ไม่ใช้ emoji",
  "extra_prepare": ["สิ่งที่ควรเตรียมเฉพาะกิจกรรมนี้ ไม่ซ้ำกับรายการ prepare เดิม ไม่เกิน 3 ข้อ สั้น ๆ"],
  "one_liner": "สรุป 1 ประโยคสั้น สำหรับแสดงบนการ์ดในตาราง"}}

กติกา
- ห้ามเปลี่ยนคำตัดสิน (verdict) ห้ามสร้างตัวเลขใหม่ ใช้เฉพาะตัวเลขที่อยู่ใน JSON
- อธิบายว่าผลนี้หมายถึงอะไรกับกิจกรรมนี้โดยเฉพาะ (เช่น กีฬาหายใจแรงจึงรับฝุ่นมาก สนามลื่นเมื่อฝนตก)
- ถ้ามี better_times และผลไม่ใช่ "เหมาะ" ให้แนะนำช่วงที่ดีที่สุด 1 ช่วงพร้อมเหตุผลสั้น ๆ
  ห้ามเสนอวันเวลาอื่นที่ไม่อยู่ใน better_times ถ้า better_times ว่าง ให้แนะนำการเตรียมตัวแทน
- ถ้ามีคนกลุ่มเสี่ยง ให้คำแนะนำเฉพาะสำหรับเขา
- ถ้าผลไม่ใช่ "เหมาะ" ให้บอกแผนสำรองในร่มที่ใช้ได้จริงกับกิจกรรมนี้ 1 ประโยค
- {indoor}
- ถ้า where เป็น "ในร่ม" ระบบประเมินเฉพาะช่วงเดินทางไป-กลับ ให้แนะนำเรื่องการเดินทาง (หน้ากาก ร่ม) เท่านั้น
  ห้ามแนะนำให้เลื่อนเวลาหรือย้ายสถานที่
- ถ้ามี place ให้พูดถึงสถานที่นั้นได้ ห้ามเอ่ยชื่อสถานที่อื่นที่ไม่มีในข้อมูล
- พูดกับผู้ใช้โดยตรงเป็นคำแนะนำ ห้ามเขียนแบบข้อกำหนดระบบ เช่น "AI ควรจะ..." "ระบบควร..." และห้ามใช้หัวข้อหรือ bullet ใน advice"""


@ttl_cache(seconds=3600)
def explain_plan(api_key: str, model: str, plan_json: str) -> dict:
    raw = _generate(api_key, model, EXPLAIN_PROMPT.format(plan=plan_json, indoor=indoor_text()), as_json=True)
    try:
        d = _json(raw)
    except Exception:
        return {"advice": raw[:600], "extra_prepare": [], "one_liner": ""}
    extra = [str(x).strip() for x in (d.get("extra_prepare") or []) if str(x).strip()][:3]
    return {"advice": str(d.get("advice", "")).strip(), "extra_prepare": extra,
            "one_liner": str(d.get("one_liner", "")).strip()}


# ======================================================================== 3) แชตถามตอบ
def system_prompt() -> str:
    return f"""คุณคือผู้ช่วยของ "{C.APP_NAME}" ระบบพยากรณ์ฝุ่นและสภาพอากาศเพื่อวางแผนกิจกรรมกลางแจ้งใน{C.KMITL_NAME}
ผู้ใช้คือนักศึกษาและบุคลากร สจล. ตอบเป็นภาษาไทย เป็นกันเอง กระชับ อ่านง่ายบนมือถือ

ตอนนี้คือ {_now_line()}
เมื่อผู้ใช้พูดว่า "วันนี้/พรุ่งนี้/เสาร์นี้" ให้แปลงเป็นวันที่ YYYY-MM-DD เองก่อนเรียก tool

กฎสำคัญ
1. ตัวเลขทุกตัว (ฝุ่น อุณหภูมิ ฝน ลม สถิติ) ต้องมาจาก tool เท่านั้น ห้ามเดา ห้ามคำนวณเอง
   ห้ามบวก ลบ หาค่าเฉลี่ย หรือคิดเปอร์เซ็นต์ใหม่ ห้ามประมาณช่วงตัวเลขขึ้นเอง ถ้า tool ไม่มีตัวเลขที่ต้องการ ให้บอกเป็นคำ
2. ก่อนให้คำแนะนำด้านสุขภาพหรือกิจกรรม ให้เรียก read_knowledge หัวข้อที่เกี่ยวข้อง และแนะนำตามนั้น
3. คำถามว่ากิจกรรมกลางแจ้งทำได้ไหม ถ้าผู้ใช้บอกวันเวลา ให้ใช้ evaluate_activity_plan และยึดคำตัดสินจาก tool
   (ห้ามตัดสินเองหรือเปลี่ยนคำตัดสิน) ถ้าถามหาช่วงเวลาที่ดีที่สุด ให้ใช้ find_best_outdoor_times
4. บอกที่มาของตัวเลขสั้น ๆ เช่น (เซนเซอร์ใน สจล.) / (โมเดลพยากรณ์ของระบบ) / (Open-Meteo)
5. ระบบพยากรณ์เป็นค่าเดียวทั้งวิทยาเขต ไม่แยกรายจุดหรือรายตึก ล่วงหน้าได้ไม่เกิน 7 วัน
6. ถ้าผู้ใช้เป็นกลุ่มเสี่ยง ให้คำแนะนำที่เข้มขึ้นตามฐานความรู้
7. กิจกรรมในร่มไม่ได้รับผลจากฝนและแดดโดยตรง ตอบสั้น ๆ ว่าทำได้ตามปกติ
8. แผนสำรองในร่ม: {indoor_text()}
   คำถามเรื่องสถานที่ใน สจล. (สนาม โรงยิม ตึก หอพัก ระยะทาง รถ EV) ให้เรียก read_knowledge หัวข้อ places
   และตอบเฉพาะสถานที่ที่อยู่ในไฟล์ ถ้าไม่มีข้อมูลให้บอกตรง ๆ ห้ามเดาชื่อหรือตำแหน่ง
9. พูดกับผู้ใช้โดยตรง ห้ามเขียนแบบข้อกำหนดระบบ เช่น "AI ควรจะ..." หรือ "ระบบควร..."
10. นอกพื้นที่ สจล. หรือนอกเรื่องฝุ่น อากาศ และกิจกรรม ให้บอกขอบเขตของระบบอย่างสุภาพ
11. ไม่วินิจฉัยโรค ถ้ามีอาการผิดปกติให้แนะนำพบแพทย์
12. ถ้า tool คืน error ให้บอกตรง ๆ ว่าข้อมูลส่วนนั้นไม่พร้อม ห้ามแต่งตัวเลขแทน

วิธีเขียนคำตอบ (เป็นคำสั่งสำหรับคุณ ห้ามพิมพ์ข้อความส่วนนี้หรือพูดถึงกฎเหล่านี้ในคำตอบ)
- ไม่ใช้ emoji หน่วยฝุ่นเขียนว่า มคก./ลบ.ม. เวลาเขียนแบบ 17:00 น.
- ความร้อนใช้อุณหภูมิอากาศเท่านั้น ห้ามพูดถึง "อุณหภูมิที่รู้สึก" หรือ feels like
- เริ่มด้วยคำตอบตรงคำถาม 1 ประโยค ตามด้วยรายละเอียด 2-4 บรรทัด
- ท้ายสุดให้ทางเลือกสั้น ๆ 2-3 ข้อ (ข้อละไม่เกิน 40 ตัวอักษร เป็นสิ่งที่ผู้ใช้ทำได้) ใส่ในแท็กแบบนี้:
<options>
- เลื่อนไปช่วงเย็น
- ย้ายไปเล่นในร่ม
</options>
"""


_LEAK = re.compile(r"(ฟอร์แมต|รูปแบบคำตอบ|วิธีเขียนคำตอบ|โครงสร้างคำตอบ|ตามกฎ|และกฎ|กฎของระบบ|system prompt)", re.I)


def clean_answer(text: str) -> str:
    """ตัดข้อความที่ AI เผลอคัดลอกคำสั่งระบบออกมา เช่น 'เขียนตอบตามฟอร์แมตและกฎ: 1. ตัวเลขมาจาก tool ...'"""
    out, skip = [], False
    for line in (text or "").splitlines():
        t = line.strip()
        if _LEAK.search(t) and len(t) < 80:
            skip = True                      # หัวข้อที่รั่ว -> ข้ามบรรทัดนี้และรายการข้อย่อยที่ตามมา
            continue
        if skip and (re.match(r"^(\d+[.)]|[-•*])\s", t) or not t):
            continue
        skip = False
        if re.search(r"\btool\b", t, re.I) and re.search(r"ตัวเลข|ที่มา|เท่านั้น", t):
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _good_option(o: str) -> bool:
    return bool(o) and len(o) <= 60 and not re.search(r"[<>]|:$|คำตอบ|ฟอร์แมต|ทางเลือกที่ \d", o)


def split_options(text):
    """แยกส่วน <options> ออกจากคำตอบ -> (คำตอบ, [ทางเลือก])"""
    m = re.search(r"<options>(.*?)(?:</options>|$)", text or "", flags=re.S)
    if not m:
        return (text or "").strip(), []
    opts = [re.sub(r"^\s*[-•*\d.)]+\s*", "", line).strip() for line in m.group(1).splitlines()]
    rest = (text[:m.start()] + text[m.end():]).replace("</options>", "")
    return rest.strip(), [o for o in opts if _good_option(o)][:3]


class AirAgent:
    def __init__(self, api_key: str, model: str, history: list[dict] | None = None):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.config = self._config(model)
        hist = [types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])])
                for m in (history or [])[-12:] if m.get("content")]
        self.chat = self.client.chats.create(model=model, config=self.config, history=hist)

    def _config(self, model: str, think=True):
        return self.types.GenerateContentConfig(
            system_instruction=system_prompt(), tools=T.ALL_TOOLS, temperature=0.3,
            thinking_config=thinking(model) if think else None,
            automatic_function_calling=self.types.AutomaticFunctionCallingConfig(maximum_remote_calls=10))

    def _send(self, message: str) -> str:
        last = ""
        for i, model in enumerate(_models(self.model, self.client)):
            if i > 0:
                try:
                    history = self.chat.get_history()
                except Exception:
                    history = []
                self.config = self._config(model)
                self.chat = self.client.chats.create(model=model, config=self.config, history=history)
            for attempt in range(3):
                try:
                    return self.chat.send_message(message).text or ""
                except Exception as e:
                    last = str(e)
                    if self.config.thinking_config is not None and _no_thinking_support(last):
                        history = self.chat.get_history()
                        self.config = self._config(model, think=False)
                        self.chat = self.client.chats.create(model=model, config=self.config, history=history)
                        continue
                    if "404" in last or "not found" in last.lower() or _quota(last):
                        break
                    if not any(k in last for k in BUSY):
                        raise RuntimeError(error_text(last, model))
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(error_text(last, self.model))

    def ask(self, question: str, sensitive: bool = False) -> dict:
        """ส่งคำถาม -> {answer, options, trace, error}"""
        T.TOOL_LOG.clear()
        ctx = ("\n[สถานะผู้ใช้: เป็นกลุ่มเสี่ยง (แพ้ฝุ่น/หอบหืด)]" if sensitive
               else "\n[สถานะผู้ใช้: คนทั่วไป ไม่ใช่กลุ่มเสี่ยง]")
        try:
            text = self._send(question + ctx)
        except RuntimeError as e:
            return {"answer": str(e), "options": [], "trace": list(T.TOOL_LOG), "error": True}
        answer, options = split_options(text)
        answer = clean_answer(answer)
        return {"answer": answer or "ขออภัย ระบบยังสรุปคำตอบไม่ได้ ลองถามใหม่อีกครั้ง",
                "options": options, "trace": list(T.TOOL_LOG), "error": False}


@ttl_cache(seconds=3600)
def quick_brief(api_key: str, model: str, sensitive: bool, hour_key: str) -> str:
    """คำแนะนำสั้นสำหรับหน้าแรก (cache 1 ชม. ทุกคนใช้ผลเดียวกัน ลดการเรียก Gemini ซ้ำ)"""
    q = ("สรุปสภาพอากาศใน สจล. ตอนนี้และช่วงที่เหลือของวันนี้ให้ครบ 3 เรื่อง: ฝุ่น ฝน (โอกาสฝนและช่วงเวลาที่น่าจะตก "
         "จาก get_weather_forecast ของวันนี้) และความร้อน แล้วแนะนำการออกไปข้างนอก เช่น ควรพกร่มไหม ช่วงไหนเลี่ยง "
         "ตอบไม่เกิน 4 ประโยค ไม่ต้องมีทางเลือก")
    out = AirAgent(api_key, model).ask(q, sensitive=sensitive)
    if out["error"]:
        raise RuntimeError(out["answer"])
    return out["answer"]
