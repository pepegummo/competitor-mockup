"""แท็บเจาะลึก: งบการเงินจาก SET (รวมตัวชี้วัดธนาคาร)"""
import pandas as pd
import streamlit as st

from ui import charts, insights
from ui.common import fmt_time
from ui.labels import GLOSSARY


BANK_COLUMNS = ("nii_mb", "nii_yoy_pct", "fee_income_mb", "fee_income_yoy_pct", "nim_approx_pct",
                "cost_to_income_pct", "credit_cost_pct", "ldr_pct", "loans_mb", "deposits_mb")


def section_banks(banks, self_name):
    st.markdown("##### Bank Metrics")
    st.caption("คิดจากงบย่อที่ยื่น SET · ตัวเลขต่อปีแปลงจากงบสะสม (เช่น 6 เดือน × 2) · "
               "ไม่มี NPL เพราะงบย่อของ SET ไม่มีข้อมูลนี้")
    st.altair_chart(charts.bank_ratio_chart(banks, self_name), width="stretch")
    st.dataframe(
        banks, width="stretch",
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "nii_mb": st.column_config.NumberColumn("รายได้ดอกเบี้ยสุทธิ (ลบ.)", format="localized"),
            "nii_yoy_pct": st.column_config.NumberColumn("ดอกเบี้ยสุทธิโต (%)", format="%+.1f"),
            "fee_income_mb": st.column_config.NumberColumn("ค่าธรรมเนียมสุทธิ (ลบ.)", format="localized"),
            "fee_income_yoy_pct": st.column_config.NumberColumn("ค่าธรรมเนียมโต (%)", format="%+.1f"),
            "nim_approx_pct": st.column_config.NumberColumn("NIM โดยประมาณ (%)", format="%.2f",
                                                            help=GLOSSARY["NIM โดยประมาณ"]),
            "cost_to_income_pct": st.column_config.NumberColumn("Cost to income (%)", format="%.1f",
                                                                help=GLOSSARY["Cost to income"]),
            "credit_cost_pct": st.column_config.NumberColumn("Credit cost (%)", format="%.2f",
                                                             help=GLOSSARY["Credit cost"]),
            "ldr_pct": st.column_config.NumberColumn("สินเชื่อ/เงินฝาก (%)", format="%.1f",
                                                     help=GLOSSARY["สินเชื่อ/เงินฝาก (LDR)"]),
            "loans_mb": st.column_config.NumberColumn("สินเชื่อสุทธิ (ลบ.)", format="localized"),
            "deposits_mb": st.column_config.NumberColumn("เงินฝาก (ลบ.)", format="localized"),
        },
    )


def section_finance(res, v):
    fin, raw, self_name = v["fin"], v["fin_raw"], v["self_name"]
    missing = [c for c in v["companies"] if c not in fin.index]
    fetched = max(f["fetched_at"] for f in raw.values())
    as_of = max(f["market"].get("as_of") or "" for f in raw.values())
    st.caption(f"งบรวมที่บริษัทยื่นต่อตลาดหลักทรัพย์ฯ (ดึงเมื่อ {fmt_time(fetched)}) · ราคาหุ้น ณ {as_of} · "
               "ตัวเงินหน่วยล้านบาท · ตัวกรองช่วงเวลา/หมวดไม่มีผลกับงบ"
               + (f" · ไม่มีงบ: {', '.join(missing)}" if missing else ""))
    insights.show(st, insights.finance(fin))
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### Annual Revenue & Net Profit")
        chart = charts.finance_history_chart(raw, self_name)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
    with right:
        st.markdown("##### Latest Financials Comparison (%)")
        st.altair_chart(charts.finance_ratio_chart(fin, self_name), width="stretch")
        st.caption("รายได้/กำไรโต = เทียบช่วงเดียวกันปีก่อน (ถ้าปีก่อนขาดทุนจะไม่แสดง) · ROE มาจากงบทั้งปีล่าสุด")
    order = charts.company_order(list(fin.index), self_name)
    bank_cols = [c for c in BANK_COLUMNS if c in fin.columns]
    st.dataframe(
        fin.loc[order].drop(columns=bank_cols), width="stretch",
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "symbol": st.column_config.TextColumn("ชื่อหุ้น"),
            "sector": st.column_config.TextColumn("หมวดธุรกิจ (SET)"),
            "period": st.column_config.TextColumn("งบรอบ", help="6M = ครึ่งปีแรก, 9M = 9 เดือน"),
            "revenue_mb": st.column_config.NumberColumn("รายได้รวม (ลบ.)", format="localized",
                                                        help="ธนาคารใช้รายได้จากการดำเนินงาน "
                                                             "(ดอกเบี้ยสุทธิ + ค่าธรรมเนียมสุทธิ + อื่น ๆ)"),
            "revenue_yoy_pct": st.column_config.NumberColumn("รายได้โต (%)", format="%+.1f",
                                                             help="เทียบช่วงเดียวกันของปีก่อน"),
            "net_profit_mb": st.column_config.NumberColumn("กำไรสุทธิ (ลบ.)", format="localized"),
            "net_profit_yoy_pct": st.column_config.NumberColumn("กำไรโต (%)", format="%+.1f"),
            "net_margin_pct": st.column_config.NumberColumn("อัตรากำไรสุทธิ (%)", format="%.1f",
                                                            help=GLOSSARY["อัตรากำไรสุทธิ"]),
            "ebitda_margin_pct": st.column_config.NumberColumn("อัตรา EBITDA (%)", format="%.1f",
                                                               help=GLOSSARY["EBITDA"]),
            "fy": st.column_config.NumberColumn("ปีงบ (ROE, D/E)", format="%d"),
            "roe_pct": st.column_config.NumberColumn("ROE (%)", format="%.1f", help=GLOSSARY["ROE"]),
            "de_ratio": st.column_config.NumberColumn("D/E (เท่า)", format="%.2f", help=GLOSSARY["D/E"]),
            "market_cap_mb": st.column_config.NumberColumn("มูลค่าตลาด (ลบ.)", format="localized"),
            "pe": st.column_config.NumberColumn("P/E (เท่า)", format="%.1f", help=GLOSSARY["P/E"]),
            "dividend_yield_pct": st.column_config.NumberColumn("ปันผล (%)", format="%.2f"),
        },
    )
    banks = fin.loc[order, bank_cols].dropna(how="all") if bank_cols else pd.DataFrame()
    if not banks.empty:
        section_banks(banks, self_name)
    links =[f"[{f['symbol']} {f['latest']['period']}]({f['latest']['filed_url']})"
             for f in raw.values() if f["latest"].get("filed_url")]
    if links:
        st.caption("งบฉบับเต็ม (zip): " + " · ".join(links))
