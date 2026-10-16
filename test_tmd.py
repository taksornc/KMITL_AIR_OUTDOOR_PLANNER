import requests, math

KMITL = (13.7299, 100.7782)

def dist(a, b):
    R = 6371
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    return 2 * R * math.asin(math.sqrt(math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))

url = "https://data.tmd.go.th/api/Weather3Hours/V2/"
r = requests.get(url, params={"uid": "api", "ukey": "api12345", "format": "json"}, timeout=20)
print("HTTP", r.status_code)
data = r.json()
stations = data.get("Stations", {}).get("Station", [])
print("จำนวนสถานี:", len(stations))

rows = []
for s in stations:
    try:
        lat, lon = float(s["Latitude"]["Value"] if isinstance(s["Latitude"], dict) else s["Latitude"]), \
                   float(s["Longitude"]["Value"] if isinstance(s["Longitude"], dict) else s["Longitude"])
    except Exception:
        continue
    rows.append((dist(KMITL, (lat, lon)), s))

rows.sort(key=lambda x: x[0])
for d, s in rows[:6]:
    obs = s.get("Observation", {})
    print(f"\n{d:5.1f} กม. | {s.get('StationNameThai')} ({s.get('WmoStationNumber')})")
    print("  เวลา:", obs.get("DateTime"))
    print("  อุณหภูมิ:", obs.get("AirTemperature"), "| ความชื้น:", obs.get("RelativeHumidity"))
    print("  ฝน 3 ชม.:", obs.get("Rainfall"), "| ฝน 24 ชม.:", obs.get("Rainfall24Hr"))
    print("  ลม:", obs.get("WindSpeed"), "| ทัศนวิสัย:", obs.get("LandVisibility"))