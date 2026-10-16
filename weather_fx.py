"""เอฟเฟกต์พื้นหลังทั้งหน้าตามสภาพอากาศจริง (CSS ล้วน ไม่กินเครื่อง)"""

import random

FX_NAMES = {
    "sunny": "แดดจัด", "partly": "มีเมฆบางส่วน", "cloudy": "ฟ้าครึ้ม",
    "rain": "ฝนตก", "storm": "ฝนหนัก ฟ้าคะนอง", "night": "กลางคืน",
}

_BG = {
    "sunny":  "linear-gradient(180deg,#7CC4FF 0%,#BFE3FF 45%,#FFF1D6 100%)",
    "partly": "linear-gradient(180deg,#8CB8E0 0%,#C9DDF0 55%,#F3F6FA 100%)",
    "cloudy": "linear-gradient(180deg,#9AA7B6 0%,#C3CCD6 60%,#E3E7EC 100%)",
    "rain":   "linear-gradient(180deg,#5E6E82 0%,#8A97A8 55%,#B9C2CD 100%)",
    "storm":  "linear-gradient(180deg,#2F3846 0%,#4C5868 55%,#7A8594 100%)",
    "night":  "linear-gradient(180deg,#0B1533 0%,#1B2A5A 60%,#2D3F78 100%)",
}


def pick_fx(hour: int, rain_mm: float, cloud: float) -> str:
    if rain_mm >= 5:
        return "storm"
    if rain_mm >= 0.2:
        return "rain"
    if hour >= 18 or hour < 6:
        return "night"
    if cloud >= 80:
        return "cloudy"
    if cloud >= 30:
        return "partly"
    return "sunny"


def _drops(n, heavy):
    rnd = random.Random(7)
    out = []
    for _ in range(n):
        left, delay = rnd.uniform(0, 100), rnd.uniform(0, 2)
        dur = rnd.uniform(0.45, 0.75) if heavy else rnd.uniform(0.7, 1.2)
        out.append(f'<i class="drop" style="left:{left:.1f}vw;animation-delay:-{delay:.2f}s;animation-duration:{dur:.2f}s"></i>')
    return "".join(out)


def _stars(n):
    rnd = random.Random(3)
    return "".join(
        f'<i class="star" style="left:{rnd.uniform(0,100):.1f}vw;top:{rnd.uniform(0,70):.1f}vh;'
        f'animation-delay:-{rnd.uniform(0,3):.1f}s;width:{rnd.choice([2,2,3])}px;height:{rnd.choice([2,2,3])}px"></i>'
        for _ in range(n))


def _clouds(n, dark=False):
    rnd = random.Random(5)
    color = "rgba(120,130,145,.55)" if dark else "rgba(255,255,255,.85)"
    return "".join(
        f'<i class="cloud" style="top:{rnd.uniform(4,55):.0f}vh;width:{rnd.uniform(220,420):.0f}px;'
        f'height:{rnd.uniform(70,120):.0f}px;background:{color};'
        f'animation-duration:{rnd.uniform(60,110):.0f}s;animation-delay:-{rnd.uniform(0,90):.0f}s"></i>'
        for _ in range(n))


def background_html(kind: str, haze: float = 0.0) -> str:
    """kind = sunny/partly/cloudy/rain/storm/night, haze = 0..1 ความหนาของหมอกควันฝุ่น"""
    layers = ""
    if kind == "sunny":
        layers = '<i class="sun"></i>' + _clouds(2)
    elif kind == "partly":
        layers = '<i class="sun dim"></i>' + _clouds(6)
    elif kind == "cloudy":
        layers = _clouds(9, dark=True)
    elif kind == "rain":
        layers = _clouds(6, dark=True) + _drops(90, False)
    elif kind == "storm":
        layers = _clouds(7, dark=True) + _drops(160, True) + '<i class="flash"></i>'
    elif kind == "night":
        layers = '<i class="moon"></i>' + _stars(70)
    if haze > 0:
        layers += f'<i class="haze" style="opacity:{min(haze, 1):.2f}"></i>'

    return f"""
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], section.main {{ background: transparent !important; }}
[data-testid="stHeader"] {{ background: rgba(255,255,255,.94) !important; box-shadow: 0 1px 0 rgba(0,0,0,.06); }}
.block-container {{ position: relative; background: rgba(255,255,255,.97);
  border-radius: 26px; margin-top: 18px; padding: 1.4rem 2rem 2rem !important;
  box-shadow: 0 10px 40px rgba(15,23,42,.22); }}
#wx {{ position: fixed; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; background: {_BG[kind]}; }}
#wx i {{ position: absolute; display: block; }}
.drop {{ top: -12vh; width: 2px; height: 70px; border-radius: 2px;
  background: linear-gradient(transparent, rgba(255,255,255,.85)); animation: fall linear infinite; }}
@keyframes fall {{ to {{ transform: translate(-6vw, 115vh); }} }}
.cloud {{ left: -30vw; border-radius: 999px; filter: blur(14px); animation: drift linear infinite; }}
@keyframes drift {{ to {{ transform: translateX(160vw); }} }}
.sun {{ right: 6vw; top: 6vh; width: 150px; height: 150px; border-radius: 50%;
  background: radial-gradient(circle, #FFF6B0 0%, #FFD23F 45%, rgba(255,190,40,0) 72%);
  box-shadow: 0 0 120px 60px rgba(255,214,90,.55); animation: glow 4s ease-in-out infinite alternate; }}
.sun.dim {{ opacity: .7; }}
@keyframes glow {{ to {{ transform: scale(1.08); box-shadow: 0 0 160px 90px rgba(255,214,90,.65); }} }}
.moon {{ right: 8vw; top: 8vh; width: 90px; height: 90px; border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, #FFFDF0, #E9E4C9 60%, #CFC8A6);
  box-shadow: 0 0 60px 20px rgba(255,250,220,.35); }}
.star {{ border-radius: 50%; background: #fff; animation: twinkle 3s ease-in-out infinite; }}
@keyframes twinkle {{ 50% {{ opacity: .15; }} }}
.flash {{ inset: 0; background: #fff; opacity: 0; animation: flash 7s infinite; }}
@keyframes flash {{ 0%, 88%, 92%, 100% {{ opacity: 0; }} 89% {{ opacity: .55; }} 91% {{ opacity: .25; }} }}
.haze {{ inset: -10%; background:
  radial-gradient(ellipse at 20% 40%, rgba(196,140,90,.75), transparent 60%),
  radial-gradient(ellipse at 80% 60%, rgba(150,130,115,.7), transparent 60%),
  linear-gradient(180deg, rgba(190,160,130,.45), rgba(150,135,120,.55));
  animation: smog 18s ease-in-out infinite alternate; }}
@keyframes smog {{ to {{ transform: translate(4%, -3%) scale(1.05); }} }}
@media (prefers-reduced-motion: reduce) {{ #wx i {{ animation: none !important; }} }}
@media (max-width: 640px) {{ .block-container {{ border-radius: 0; margin-top: 0; padding: 1rem !important; }} }}
</style>
<div id="wx">{layers}</div>
"""


def haze_from_pm25(pm25: float) -> float:
    """ฝุ่นยิ่งสูง หมอกควันยิ่งหนา: เริ่มเห็นที่ระดับเหลือง เต็มที่ราว 100 µg/m³"""
    if pm25 is None or pm25 <= 25:
        return 0.0
    return min((pm25 - 25) / 75, 1.0) * 0.85
