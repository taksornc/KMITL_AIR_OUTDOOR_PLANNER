"""หน้า: ตารางของฉัน — การ์ดกิจกรรม ประเมินซ้ำตามพยากรณ์ล่าสุดทุกครั้งที่เปิด"""

import pandas as pd
import streamlit as st

import config as C
import planner as P
import store
import ui

ui.brand_header("ตารางของฉัน")
u = ui.user()
if not u:
    st.markdown("<p>ตารางของฉันเก็บกิจกรรมที่บันทึกจากหน้าวางแผน พร้อมบอกว่าพยากรณ์ล่าสุดยังโอเคไหม</p>",
                unsafe_allow_html=True)
    ui.login_box("เข้าสู่ระบบเพื่อดูตารางของคุณ", "schedule")
    st.stop()

items = store.list_activities(u["id"])
if st.session_state.get("photo_full"):
    st.info(st.session_state.pop("photo_full"))
res, err = ui.forecast()
now = C.now_local()


def edit_box(a, n_photos):
    """แก้ชื่อ / จดบันทึก / แนบรูป (ไม่เกิน 3 รูป)"""
    label = "แก้ไขชื่อ · บันทึก · รูป" + (f" ({n_photos} รูป)" if n_photos else "")
    with st.expander(label, expanded=st.session_state.get(f"open_e_{a['id']}", False)):
        with st.form(f"ed_{a['id']}", border=False):
            title = st.text_input("ชื่อกิจกรรม", value=a["title"], max_chars=60)
            note = st.text_area("บันทึกเพิ่มเติม", value=a.get("note") or "", max_chars=1000, height=80,
                                placeholder="เช่น ค่าข้าว 50 บาท, วิ่งได้ 5 กม., นัดเพื่อนที่หน้าตึก HM")
            files = st.file_uploader(f"แนบรูป (ไม่เกิน {store.MAX_PHOTOS} รูปต่อกิจกรรม)", type=["jpg", "jpeg", "png", "webp"],
                                     accept_multiple_files=True, key=f"up_{a['id']}")
            if st.form_submit_button("บันทึก", type="primary"):
                store.update_activity(a["id"], u["id"], title, note)
                full = False
                for f in files or []:
                    if f.size > 8 * 1024 * 1024:
                        st.warning(f"{f.name} ใหญ่เกิน 8 MB")
                        continue
                    try:
                        full = not store.add_photo(a["id"], u["id"], f.getvalue()) or full
                    except Exception:
                        st.warning(f"เปิดรูป {f.name} ไม่ได้")
                if full:
                    st.session_state["photo_full"] = f"แนบได้สูงสุด {store.MAX_PHOTOS} รูปต่อกิจกรรม"
                st.session_state[f"open_e_{a['id']}"] = True
                st.rerun()
        if n_photos:
            ph = store.list_photos(a["id"], u["id"])
            pcols = st.columns(store.MAX_PHOTOS)
            for col, p in zip(pcols, ph):
                col.image(p["data"], **ui.FULL)
                if col.button("ลบรูป", key=f"dp_{p['id']}", **ui.FULL):
                    store.delete_photo(p["id"], u["id"])
                    st.session_state[f"open_e_{a['id']}"] = True
                    st.rerun()

if not items:
    st.markdown('<div class="panel">ยังไม่มีกิจกรรมในตาราง ไปที่หน้าวางแผนกิจกรรม พิมพ์ว่าจะทำอะไร เมื่อไร '
                'แล้วกด "เพิ่มลงตารางของฉัน"</div>', unsafe_allow_html=True)
    st.write("")
    if st.button("วางแผนกิจกรรม", type="primary"):
        st.switch_page("views/plan.py")
else:
    # ---- ประเมินทุกกิจกรรมใหม่ด้วยพยากรณ์ล่าสุด
    for a in items:
        a["eval"], a["move"] = None, None
        if res:
            s0 = max(a["start_ts"], now.floor("h"))
            hrs = max(1, int((a["end_ts"] - s0) / pd.Timedelta(hours=1)))
            try:
                a["eval"] = P.assess(s0, hrs, a["intensity"], a["sensitive"] or ui.is_sensitive(), a["indoor"])
                if a["start_ts"] > now and not a["indoor"]:
                    a["move"] = P.best_on_same_day(a["start_ts"], a["hours"], a["intensity"],
                                                   a["sensitive"] or ui.is_sensitive())
            except ValueError:
                pass
        a["changed"] = bool(a["eval"]) and a["eval"]["title"] != a["verdict_at_save"]

    n_today = sum(a["start_ts"].date() == now.date() for a in items)
    n_tmr = sum(a["start_ts"].date() == (now + pd.Timedelta(days=1)).date() for a in items)
    n_chk = sum(a["changed"] or (a["eval"] and a["eval"]["verdict"] == "bad") for a in items)
    summary = [f"วันนี้ {n_today} กิจกรรม", f"พรุ่งนี้ {n_tmr} กิจกรรม", f"ทั้งหมด {len(items)} กิจกรรม"]
    if n_chk:
        summary.append(f'<b style="color:#B54708">{n_chk} กิจกรรมควรตรวจอีกครั้ง</b>')
    st.markdown("<p>" + " · ".join(summary) + "</p>", unsafe_allow_html=True)

    # ---- ไทม์ไลน์: เห็นทุกกิจกรรมตามวันและเวลาในภาพเดียว
    def timeline(acts):
        days = sorted({a["start_ts"].normalize() for a in acts})[:7]
        h0 = min([6] + [a["start_ts"].hour for a in acts])
        h1 = max([22] + [min(24, a["start_ts"].hour + a["hours"]) for a in acts])
        span = h1 - h0
        pct = lambda h: (h - h0) / span * 100
        ticks = "".join(f'<span style="left:{pct(h):.2f}%">{h:02d}</span>' for h in range(h0, h1 + 1, 3))
        grid = "".join(f'<i style="left:{pct(h):.2f}%"></i>' for h in range(h0, h1 + 1, 3))
        rows = []
        for d in days:
            blocks = []
            for a in [x for x in acts if x["start_ts"].normalize() == d]:
                ev = a["eval"]
                col = ev["color"] if ev else "#8A94A6"
                st_h = a["start_ts"].hour + a["start_ts"].minute / 60
                en_h = min(st_h + a["hours"], 24)
                w_ = max(pct(en_h) - pct(st_h), 11)
                left_ = min(pct(st_h), 100 - w_)
                small = w_ < 14
                blocks.append(
                    f'<div class="tl-b{" tl-s" if small else ""}" style="left:{left_:.2f}%;width:{w_:.2f}%;'
                    f'background:{col}" title="{ui.esc(a["title"])} {a["start_ts"]:%H:%M}–{a["end_ts"]:%H:%M} น. '
                    f'{ui.esc(ev["title"]) if ev else ""}"><b>{"🏠 " if a["indoor"] else ""}{ui.esc(a["title"])}</b>'
                    f'<small>{a["start_ts"]:%H:%M}–{a["end_ts"]:%H:%M}</small></div>')
            nowline = ""
            if d == now.normalize() and h0 <= now.hour + now.minute / 60 <= h1:
                nowline = f'<div class="tl-now" style="left:{pct(now.hour + now.minute / 60):.2f}%"></div>'
            rows.append(f'<div class="tl-r"><div class="tl-d">{ui.day_name(d, short=True)}</div>'
                        f'<div class="tl-t">{grid}{"".join(blocks)}{nowline}</div></div>')
        return f"""<style>
.tl{{border:1px solid var(--line,#e4e8ee);border-radius:16px;background:rgba(255,255,255,.8);padding:26px 14px 8px}}
.tl-r{{display:flex;align-items:center;gap:10px;margin:8px 0}}
.tl-d{{flex:0 0 92px;font-size:.84rem;font-weight:600;color:#374151}}
.tl-t{{position:relative;flex:1;height:54px;background:#f5f7fa;border-radius:10px}}
.tl-t i{{position:absolute;top:0;bottom:0;border-left:1px dashed #dde2e8}}
.tl-b{{position:absolute;top:4px;bottom:4px;border-radius:9px;color:#fff;padding:2px 8px;overflow:hidden;
 display:flex;flex-direction:column;justify-content:center;box-shadow:0 2px 6px rgba(15,23,42,.15);line-height:1.55}}
.tl-b b{{font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tl-b small{{font-size:.68rem;opacity:.9;white-space:nowrap}}
.tl-s{{padding:2px 6px}}.tl-s b{{font-size:.74rem}}.tl-s small{{font-size:.64rem}}
.tl-now{{position:absolute;top:-4px;bottom:-4px;width:2px;background:#E8742A;border-radius:2px}}
.tl-now::before{{content:"ตอนนี้";position:absolute;top:-20px;left:-14px;white-space:nowrap;font-size:.62rem;color:#E8742A;font-weight:700}}
.tl-x{{position:relative;height:16px;margin-left:102px}}
.tl-x span{{position:absolute;transform:translateX(-50%);font-size:.7rem;color:#8a8f98}}
.tl-k{{display:flex;gap:14px;flex-wrap:wrap;font-size:.75rem;color:#6b7280;margin-top:6px}}
.tl-k b{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}}
</style><div class="tl">{"".join(rows)}<div class="tl-x">{ticks}</div>
<div class="tl-k"><span><b style="background:#1E9E5A"></b>เหมาะ / ทำได้ตามปกติ</span>
<span><b style="background:#C99A06"></b>พอได้ ถ้าเตรียมตัว</span><span><b style="background:#D64545"></b>ไม่แนะนำ</span>
<span><b style="background:#2F80ED"></b>ในร่ม เตรียมตัวตอนเดินทาง</span><span>🏠 = ในร่ม</span></div></div>"""

    st.markdown('<div class="section-title" style="margin-top:6px">ไทม์ไลน์</div>', unsafe_allow_html=True)
    st.markdown(timeline(items), unsafe_allow_html=True)

    def _k(aid, p):
        import hashlib
        return f"c_{aid}_{hashlib.md5(p.encode()).hexdigest()[:8]}"

    def save_checks(aid, prep):
        done = [p for p in prep if st.session_state.get(_k(aid, p))]
        store.set_checked(aid, u["id"], done)
        st.session_state[f"open_p_{aid}"] = True

    def prep_box(a):
        """สิ่งที่ต้องเตรียม: ติ๊ก / ลบ / เพิ่มเอง"""
        prep, chk = a["prepare"], a["checked"]
        done = len([p for p in prep if p in chk])
        with st.expander(f"สิ่งที่ต้องเตรียม ({done}/{len(prep)})" if prep else "สิ่งที่ต้องเตรียม (ยังไม่มี กดเพื่อเพิ่ม)",
                         expanded=st.session_state.get(f"open_p_{a['id']}", False)):
            for p in prep:
                c1, c2 = st.columns([12, 1], vertical_alignment="center")
                c1.checkbox(p, value=p in chk, key=_k(a["id"], p), on_change=save_checks, args=(a["id"], prep))
                if c2.button("✕", key="x" + _k(a["id"], p), help="ลบรายการนี้",
                             type="tertiary" if ui._ST_VER >= (1, 40) else "secondary"):
                    store.set_prepare(a["id"], u["id"], [x for x in prep if x != p], chk)
                    st.session_state[f"open_p_{a['id']}"] = True
                    st.rerun()
            with st.form(f"addp_{a['id']}", border=False, clear_on_submit=True):
                f1, f2 = st.columns([5, 1], vertical_alignment="bottom")
                new = f1.text_input("เพิ่มรายการ", placeholder="เช่น พาวเวอร์แบงก์, เสื้อสำรอง", label_visibility="collapsed")
                if f2.form_submit_button("เพิ่ม", **ui.FULL) and new.strip() and new.strip() not in prep:
                    store.set_prepare(a["id"], u["id"], prep + [new.strip()], chk)
                    st.session_state[f"open_p_{a['id']}"] = True
                    st.rerun()

    group = None
    photos_n = store.photo_counts(u["id"])
    for a in items:
        g = ui.day_name(a["start_ts"])
        if g != group:
            group = g
            st.markdown(f'<div class="section-title">{g}</div>', unsafe_allow_html=True)
        ev = a["eval"]
        color = ev["color"] if ev else "#8A94A6"
        with st.container(border=True):
            st.markdown(f"""<div style="border-left:6px solid {color};padding-left:12px">
<div class="acard-head"><span class="when">{ui.icon('clock', ui.GREY, 16)} {a['start_ts']:%H:%M}–{a['end_ts']:%H:%M} น.</span>
<span class="cd">{ui.until_text(a['start_ts'], a['end_ts'])}</span></div>
<div class="acard-title">{ui.esc(a['title'])}{' <span class="tag" style="font-size:.75rem">ในร่ม</span>' if a['indoor'] else ''}</div>
{f'<div class="note" style="margin:2px 0 4px">📝 {ui.esc(a["note"])}</div>' if a.get('note') else ''}
<div style="color:{color};font-weight:700">{ui.esc(ev['title']) if ev else 'ยังประเมินไม่ได้'}
<span style="color:var(--ink);font-weight:400"> — {ui.esc(ev['because']) if ev else 'อยู่นอกช่วงพยากรณ์'}</span></div>
</div>""", unsafe_allow_html=True)
            if ev:
                facts = []
                for x in ev["reasons"]:
                    kind = {"dust": "dust", "rain": "rain", "heat": "heat"}[x["key"]]
                    col = x["color"] if x["key"] == "dust" else (ui.RAIN_BLUE if x["key"] == "rain" else ui.GREY)
                    facts.append(ui.tag(x["value"], kind, col))
                st.markdown("".join(facts), unsafe_allow_html=True)
            if a["changed"]:
                st.markdown(f'<div class="warnbar">พยากรณ์เปลี่ยนแล้ว ตอนบันทึกได้ "{ui.esc(a["verdict_at_save"])}" '
                            f'ตอนนี้เป็น "{ui.esc(ev["title"])}"</div>', unsafe_allow_html=True)
            if a["ai_note"]:
                st.markdown(f'<div class="note" style="margin:6px 0">คำแนะนำจาก AI: {ui.esc(a["ai_note"])}</div>',
                            unsafe_allow_html=True)
            prep_box(a)
            edit_box(a, photos_n.get(a["id"], 0))
            cols = st.columns([1.3, 1, 0.8, 1.6])
            mv = a["move"]
            if mv and cols[0].button(f"เลื่อนเป็น {mv['start']:%H:%M} น. ({mv['title']})", key=f"mv_{a['id']}", **ui.FULL):
                store.move_activity(a["id"], u["id"], mv["start"], mv["title"], mv["checklist"])
                st.rerun()
            if cols[1].button("ตรวจละเอียด", key=f"chk_{a['id']}", **ui.FULL):
                st.session_state.plan = {"activity_name": a["title"], "date": str(a["start_ts"].date()),
                                         "start_hour": a["start_ts"].hour, "duration_hours": a["hours"],
                                         "intensity": a["intensity"], "is_outdoor": not a["indoor"],
                                         "sensitive": a["sensitive"], "missing": [], "text": a["title"]}
                st.session_state.pop("saved_msg", None)
                st.switch_page("views/plan.py")
            if cols[2].button("ลบ", key=f"del_{a['id']}", **ui.FULL):
                store.delete_activity(a["id"], u["id"])
                st.rerun()

past = store.past_activities(u["id"])
if past:
    pn = store.photo_counts(u["id"])
    with st.expander(f"ที่ผ่านมา ({len(past)}) จดบันทึกหรือแนบรูปหลังทำกิจกรรมได้"):
        for a in past:
            st.markdown(f'<div style="margin:8px 0 2px"><b>{ui.esc(a["title"])}</b> '
                        f'<span class="note">{ui.day_name(a["start_ts"])} {a["start_ts"]:%H:%M} น. · '
                        f'ตอนบันทึก: {ui.esc(a["verdict_at_save"])}</span></div>'
                        + (f'<div class="note" style="margin:0">📝 {ui.esc(a["note"])}</div>' if a.get("note") else ""),
                        unsafe_allow_html=True)
            edit_box(a, pn.get(a["id"], 0))

st.markdown('<p class="note" style="margin-top:16px">ผลประเมินคำนวณใหม่จากพยากรณ์ล่าสุดทุกครั้งที่เปิดหน้านี้ '
            'ยิ่งใกล้วันจริง พยากรณ์ยิ่งแม่นขึ้น</p>', unsafe_allow_html=True)
