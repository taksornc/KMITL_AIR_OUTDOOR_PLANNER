# KMITL Outdoor Planner

พยากรณ์ฝุ่นและสภาพอากาศ เพื่อวางแผนกิจกรรมกลางแจ้งใน สจล. ลาดกระบัง
**ML** (พยากรณ์ฝุ่นรายชั่วโมง 7 วัน) + **สถิติ** + **LLM** (Gemini + tools + knowledge) + **ฐานข้อมูล SQLite** + **Streamlit**

## เริ่มใช้งาน (VS Code, Python 3.10 ขึ้นไป)

```bash
# 1) สร้าง virtual env ด้วย Python 3.12 แล้วติดตั้ง (ทำครั้งเดียว)
py -3.12 -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2) คัดลอก .env.example เป็น .env แล้วใส่ GEMINI_API_KEY (ขอฟรีที่ https://aistudio.google.com/apikey)

# 3) ดึงข้อมูลย้อนหลัง + สถิติ + เทรนโมเดล (ครั้งแรก 1-3 นาที)
python train.py

# 4) เปิดเว็บ
streamlit run app.py

# 5) (ก่อนนำเสนอ) ประเมิน AI 4 ด้าน แล้วดูผลในหน้า "ผลประเมิน AI"
python evaluate_llm.py
```

ครั้งต่อไปแค่ `.venv\Scripts\activate` แล้ว `streamlit run app.py`

## โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `app.py` | จุดเริ่มของเว็บ: เมนู แถบตั้งค่า พื้นหลังตามอากาศ |
| `views/now.py` | ตอนนี้: ฝุ่นตอนนี้ แผนที่ขอบเขต สจล. 24 ชม. ข้างหน้า คำแนะนำ |
| `views/plan.py` | วางแผนกิจกรรม: พิมพ์ประโยคเดียว → ผลประเมิน + ของที่ต้องเตรียม + เวลาที่ดีกว่า |
| `views/schedule.py` | ตารางของฉัน: การ์ดกิจกรรม ประเมินซ้ำทุกครั้ง ติ๊กของที่เตรียม เลื่อนเวลา |
| `views/forecast.py` | พยากรณ์ 7 วัน |
| `views/chat.py` | ถาม AI (บันทึกประวัติเมื่อเข้าสู่ระบบ) |
| `views/insights.py` | สถิติย้อนหลัง: เลือกช่วงเวลา/มุมมอง/ตัวแปรเอง + ผลทดสอบสถิติ |
| `views/trust.py` | ความแม่นของโมเดล แหล่งข้อมูล เกณฑ์ตัดสิน ข้อจำกัด |
| `views/llm_eval.py` | ผลประเมิน AI 4 ด้าน |
| `views/guide.py` / `views/account.py` | วิธีใช้ / บัญชีและลบข้อมูล (PDPA) |
| `planner.py` | เกณฑ์ตัดสินกิจกรรม + ตัวแปลงประโยคแบบกฎ (สำรองเมื่อ AI ไม่พร้อม) |
| `agent.py` | Gemini: แปลงประโยคเป็นแผน, อธิบายผล, แชตพร้อม tools |
| `tools.py` | 8 tools ที่ Gemini เรียกได้ |
| `store.py` | ฐานข้อมูล SQLite (`data/app.db`) ผู้ใช้ กิจกรรม แชต |
| `evaluate_llm.py` | ชุดทดสอบและตัวประเมิน AI |
| `data_sources.py` | Smart Pole สจล., Air4Thai, Open-Meteo |
| `features.py` `train.py` `forecast.py` `stats_analysis.py` | ML และสถิติ |
| `ui.py` `weather_fx.py` `config.py` | หน้าตา ไอคอน ค่าคงที่ |
| `knowledge/` | ฐานความรู้ให้ AI อ่าน |

## ตั้งค่าใน .env
- `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`
- `USE_SMARTPOLE=true` ใช้เซนเซอร์ใน สจล. เป็นค่าฝุ่นตอนนี้ (`false` = ใช้สถานีกรมควบคุมมลพิษ)

## แหล่งข้อมูลและเครดิต
โค้ดในโปรเจกต์นี้ใช้สัญญาอนุญาต MIT แต่ข้อมูลจากแหล่งต่อไปนี้เป็นของเจ้าของแต่ละแหล่ง
- ค่าฝุ่นปัจจุบัน: KMITL Smart Pole โดย SCiRA, สจล. (ใช้เพื่อการศึกษาในรายวิชา)
- ข้อมูลฝุ่นสำรอง: Air4Thai กรมควบคุมมลพิษ
- พยากรณ์อากาศและข้อมูลฝึกโมเดล: Open-Meteo (CC BY 4.0)
- แผนที่: © OpenStreetMap contributors, © CARTO
- ผู้ช่วย AI: Google Gemini API

โปรเจกต์รายวิชา สาขาสถิติประยุกต์และการวิเคราะห์ข้อมูล สจล. ไม่ใช่คำแนะนำทางการแพทย์

## Deploy (Streamlit Community Cloud)
1. รัน `python train.py` บนเครื่องก่อน อัปโหลดโฟลเดอร์ขึ้น GitHub รวม `artifacts/` และ `data/history_hourly.csv`
   **ห้ามอัป `.env` และ `data/app.db`**
2. share.streamlit.io → Create app → main file: `app.py`
3. Settings → Secrets ใส่ `GEMINI_API_KEY = "..."` และ `GEMINI_MODEL = "..."`
4. บน Streamlit Cloud ไฟล์ฐานข้อมูล SQLite จะหายเมื่อเซิร์ฟเวอร์รีสตาร์ต (ใช้เดโมได้) ถ้าใช้งานจริงให้ย้าย `store.py` ไป Azure SQL
