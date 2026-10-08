"""การ์ดแหล่งข้อมูลของแต่ละบริษัท: บอกว่าแต่ละแหล่งใช้อะไร (ชื่อแอป ชื่อหุ้น) แทนการโชว์ id
โหมดละเอียดเปิด/ปิดแหล่งรายบริษัทได้ และแก้ค่าได้จากปุ่ม "แก้ไข" ของแต่ละการ์ด"""
from urllib.parse import urlparse

import streamlit as st

from core import collect, db, profile
from core.sources import app_reviews
from ui.common import friendly_errors
from ui.labels import FINANCIALS_KEY, FINANCIALS_LABEL

ALL_SOURCES = {**{k: label for k, (_, label) in collect.SOURCES.items()}, FINANCIALS_KEY: FINANCIALS_LABEL}


def source_status(row):
    """{key: (ใช้ได้ไหม, ข้อความบอกว่าใช้อะไร)}"""
    names = [row["name"]] + [a for a in row["aliases"] if a != row["name"]]
    symbol = row.get("set_symbol")
    if symbol:
        set_status = (True, f"หุ้น {symbol}")
    elif symbol is None:
        set_status = (True, "ระบบจะหาชื่อหุ้นให้ตอนวิเคราะห์")
    else:
        set_status = (False, "ไม่อยู่ในตลาดหลักทรัพย์ฯ")
    apps = [f"{row.get('appstore_name') or row['appstore_id']} (App Store)" if row.get("appstore_id") else "",
            f"{row.get('play_name') or row['play_app_id']} (Google Play)" if row.get("play_app_id") else ""]
    apps = [a for a in apps if a]
    site = row.get("website")
    return {
        "google_news": (True, f"ค้นด้วยชื่อ “{row['name']}”"),
        "thai_rss": (True, "จับข่าวจากชื่อ " + ", ".join(names)),
        "set_news": set_status,
        FINANCIALS_KEY: set_status,
        "app_reviews": (bool(apps), " · ".join(apps) if apps else "ยังไม่ได้ตั้งค่าแอป"),
        "website": (bool(site), urlparse(site).netloc if site else "ยังไม่ได้ใส่ URL"),
    }


def enabled_sources(row, global_sources):
    """แหล่งที่จะใช้กับบริษัทนี้จริง = ที่เลือกในแถบซ้าย − ที่ปิดไว้เฉพาะบริษัทนี้"""
    return [k for k in global_sources if k not in row.get("disabled_sources", [])]


def _toggle(name, key, widget_key):
    row = db.get_companies([name])[0]
    disabled = set(row["disabled_sources"])
    (disabled.discard if st.session_state[widget_key] else disabled.add)(key)
    db.set_disabled_sources(name, disabled)


def _autofill(names):
    profiles = profile.suggest_profiles(names)
    notes = []
    for row in db.get_companies(names):
        found = app_reviews.search_apps(row["name"])
        p = profiles.get(row["name"], {})
        new_store, new_play = row["appstore_id"] or found.get("appstore_id"), row["play_app_id"] or found.get("play_app_id")
        db.update_company_sources(
            row["name"], row["aliases"] or p.get("aliases", []), new_play, new_store, row["website"],
            row["set_symbol"] or "",
            appstore_name=row.get("appstore_name") or (found.get("appstore_name") if new_store == found.get("appstore_id") else None),
            play_name=row.get("play_name") or (found.get("play_name") if new_play == found.get("play_app_id") else None))
        if row["set_symbol"] is None and p:  # ยังไม่เคยหาชื่อหุ้น ('' = หาแล้วไม่อยู่ในตลาด)
            db.set_company_profile(row["name"], p.get("set_symbol", ""))
        notes.append(row["name"])
    return notes


def _edit_form(row, version):
    with st.form(f"edit_{row['name']}_{version}", border=False):
        aliases = st.text_input("ชื่อที่ใช้ค้นในข่าว (คั่นด้วย ,)", ", ".join(row["aliases"]),
                                help="ชื่อไทย/อังกฤษ/ชื่อย่อที่สื่อใช้ ใช้จับข่าวจากสำนักข่าวไทย")
        symbol = st.text_input("ชื่อหุ้น SET", row["set_symbol"] or "", help="เว้นว่าง = ไม่อยู่ในตลาด")
        store = st.text_input("App Store id", row["appstore_id"] or "", help="ตัวเลขใน URL apps.apple.com/.../id<ตัวเลข>")
        play = st.text_input("Google Play id", row["play_app_id"] or "", help="ค่า id= ใน URL ของ Google Play")
        site = st.text_input("URL หน้าข่าว/โปรโมชัน", row["website"] or "")
        if st.form_submit_button("บันทึก", type="primary", icon=":material/save:"):
            store, play = store.strip(), play.strip()
            db.update_company_sources(
                row["name"], [a.strip() for a in aliases.split(",") if a.strip()], play, store, site.strip(),
                symbol.strip(),
                appstore_name=row.get("appstore_name") if store == (row["appstore_id"] or "") else None,
                play_name=row.get("play_name") if play == (row["play_app_id"] or "") else None)
            db.set_company_profile(row["name"], symbol)  # เว้นว่าง = ไม่อยู่ในตลาด (ระบบจะไม่หาให้อีก)
            st.toast(f"บันทึกแหล่งข้อมูลของ {row['name']} แล้ว")
            st.rerun()


def render(names, self_name, global_sources, advanced):
    if not names:
        return
    for n in names:  # การ์ดต้องมีแถวใน DB (สร้างแบบว่าง ๆ ไม่กระทบอย่างอื่น)
        if not db.company_ids([n]):
            db.update_company_sources(n)
    rows = db.get_companies(names)
    missing_apps = sum(1 for r in rows if not r["appstore_id"] and not r["play_app_id"])
    title = "แหล่งข้อมูลของแต่ละบริษัท" + (f" · {missing_apps} บริษัทยังไม่ได้ตั้งค่าแอป" if missing_apps else "")
    with st.expander(title, icon=":material/tune:"):
        c1, c2 = st.columns([1.4, 3])
        if c1.button("หาชื่อเรียก ชื่อหุ้น และแอปอัตโนมัติ", icon=":material/auto_fix_high:",
                     help="ใช้ LLM 1 ครั้ง + ค้น App Store/Google Play เติมเฉพาะช่องที่ยังว่าง"):
            with friendly_errors(), st.spinner("กำลังค้นหา..."):
                _autofill(names)
                st.session_state.panel_v = st.session_state.get("panel_v", 0) + 1
                st.rerun()
        c2.caption("ตรวจชื่อแอปและชื่อหุ้นในการ์ดก่อนวิเคราะห์ ถ้าไม่ใช่ของบริษัทนั้นกด “แก้ไข” "
                   + ("· ติ๊กออกเพื่อไม่ใช้แหล่งนั้นกับบริษัทนี้" if advanced else ""))

        version = st.session_state.get("panel_v", 0)
        for start in range(0, len(rows), 3):
            for col, row in zip(st.columns(3), rows[start:start + 3]):
                with col.container(border=True):
                    st.markdown(f"**{row['name']}**" + ("  :blue-badge[บริษัทเรา]" if row["name"] == self_name else ""))
                    status = source_status(row)
                    for key in global_sources:
                        ok, text = status[key]
                        label = f"{ALL_SOURCES[key]} :gray[· {text}]"
                        on = ok and key not in row["disabled_sources"]
                        if advanced:
                            wkey = f"cs_{row['name']}_{key}_{version}"
                            st.checkbox(label, value=on, disabled=not ok, key=wkey,
                                        on_change=_toggle, args=(row["name"], key, wkey))
                        else:
                            icon = ":green[:material/check_circle:]" if on else ":gray[:material/remove_circle_outline:]"
                            st.markdown(f"{icon} {label}")
                    with st.popover("แก้ไข", icon=":material/edit:", width="stretch"):
                        _edit_form(row, version)
