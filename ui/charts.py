"""กราฟ Altair ทั้งหมด (ข้อมูลเข้ามาเป็นตารางที่ analyze คิดไว้แล้ว)"""
import altair as alt
import pandas as pd

from ui.labels import BANK_TH, CATEGORY_TH, FINANCE_TH, SENTIMENT_COLORS, SENTIMENT_TH


def company_opacity(self_name):
    """ถ้ามีบริษัทเรา ให้แถบของเราเข้ม คู่แข่งจางลง"""
    if not self_name:
        return alt.value(1)
    return alt.condition(alt.datum.company == self_name, alt.value(1), alt.value(0.45))


def company_order(names, self_name):
    return ([self_name] if self_name in names else []) + [c for c in names if c != self_name]


def sentiment_chart(table_b, self_name=None):
    long = (table_b.rename(columns=SENTIMENT_TH).reset_index()
            .melt(id_vars="company", var_name="น้ำเสียง", value_name="สัดส่วน (%)"))
    long["ลำดับ"] = long["น้ำเสียง"].map({"บวก": 0, "กลาง": 1, "ลบ": 2})
    return (alt.Chart(long).mark_bar()
            .encode(
                x=alt.X("สัดส่วน (%):Q", stack="normalize", axis=alt.Axis(format="%", title=None)),
                y=alt.Y("company:N", title=None, sort=company_order(list(table_b.index), self_name)),
                color=alt.Color("น้ำเสียง:N",
                                scale=alt.Scale(domain=list(SENTIMENT_COLORS), range=list(SENTIMENT_COLORS.values())),
                                legend=alt.Legend(orient="bottom", title=None)),
                opacity=company_opacity(self_name),
                order="ลำดับ:Q",
                tooltip=["company", "น้ำเสียง", "สัดส่วน (%)"],
            )
            .properties(height=60 + 40 * len(table_b)))


def category_chart(df, self_name=None):
    """สัดส่วนหมวดของแต่ละบริษัท (% ของข่าวบริษัทนั้น) เทียบกันได้แม้จำนวนข่าวไม่เท่ากัน"""
    counts = df.groupby(["company", "หมวด"]).size().reset_index(name="จำนวนข่าว")
    counts["สัดส่วน (%)"] = (counts["จำนวนข่าว"] / counts.groupby("company")["จำนวนข่าว"].transform("sum") * 100).round(1)
    order = [v for v in CATEGORY_TH.values() if v in set(counts["หมวด"])]
    companies = company_order(sorted(counts["company"].unique()), self_name)
    return (alt.Chart(counts).mark_bar()
            .encode(
                x=alt.X("หมวด:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                xOffset=alt.XOffset("company:N", sort=companies),
                y=alt.Y("สัดส่วน (%):Q", title="% ของข่าวบริษัทนั้น"),
                color=alt.Color("company:N", title="บริษัท", sort=companies, legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(self_name),
                tooltip=["company", "หมวด", "จำนวนข่าว", "สัดส่วน (%)"],
            )
            .properties(height=340))


def gap_chart(gap, kind, self_name):
    data = gap[gap["type"] == kind].copy()
    labels = CATEGORY_TH if kind == "category" else SENTIMENT_TH
    data["รายการ"] = data["item"].map(labels)
    if kind == "category":
        # หมวด: มาก/น้อยกว่าไม่ได้แปลว่าดี/แย่ แค่บอกว่าเราเน้นต่างจากคู่แข่ง
        data["ผล"] = data["gap_pts"].map(lambda g: f"{self_name} เน้นมากกว่า" if g >= 0 else f"{self_name} เน้นน้อยกว่า")
        domain = [f"{self_name} เน้นมากกว่า", f"{self_name} เน้นน้อยกว่า"]
        colors = ["#2557a7", "#e08a2b"]
    else:
        # น้ำเสียง: ข่าวบวกมากกว่า = ดี, ข่าวลบมากกว่า = แย่
        good = data.apply(lambda r: r["gap_pts"] >= 0 if r["item"] != "negative" else r["gap_pts"] <= 0, axis=1)
        data["ผล"] = good.map({True: "ดีกว่าคู่แข่ง", False: "แย่กว่าคู่แข่ง"})
        domain, colors = ["ดีกว่าคู่แข่ง", "แย่กว่าคู่แข่ง"], ["#2e9e5b", "#d9534f"]
    return (alt.Chart(data).mark_bar()
            .encode(
                x=alt.X("gap_pts:Q", title="ส่วนต่างจากค่าเฉลี่ยคู่แข่ง (จุด)"),
                y=alt.Y("รายการ:N", title=None, sort=list(labels.values())),
                color=alt.Color("ผล:N", scale=alt.Scale(domain=domain, range=colors),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=[alt.Tooltip("รายการ:N"), alt.Tooltip("us_pct:Q", title="เรา (%)"),
                         alt.Tooltip("competitor_avg_pct:Q", title="คู่แข่งเฉลี่ย (%)"),
                         alt.Tooltip("gap_pts:Q", title="ส่วนต่าง (จุด)")],
            )
            .properties(height=40 + 32 * len(data)))


def stars_chart(reviews_df, self_name):
    stars = reviews_df.groupby(["company", "source_name"])["rating"].mean().round(2).reset_index()
    return (alt.Chart(stars).mark_bar().encode(
                x=alt.X("rating:Q", title="ดาวเฉลี่ย (เต็ม 5)", scale=alt.Scale(domain=[0, 5])),
                y=alt.Y("company:N", title=None, sort=company_order(sorted(stars["company"].unique()), self_name)),
                yOffset="source_name:N",
                color=alt.Color("source_name:N", title=None, legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(self_name),
                tooltip=["company", "source_name", "rating"],
            ).properties(height=60 + 50 * stars["company"].nunique()))


def finance_history_chart(raw, self_name):
    hist = pd.DataFrame([{**h, "company": name} for name, f in raw.items() for h in f["history"]
                         if h["period"] == "ทั้งปี"])
    if hist.empty:
        return None
    order = company_order(list(raw), self_name)
    long = hist.melt(id_vars=["company", "year"], value_vars=["revenue", "net_profit"],
                     var_name="ตัวเลข", value_name="ล้านบาท")
    long["ตัวเลข"] = long["ตัวเลข"].map({"revenue": "รายได้รวม", "net_profit": "กำไรสุทธิ"})
    return (alt.Chart(long).mark_bar().encode(
                x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
                xOffset=alt.XOffset("company:N", sort=order),
                y=alt.Y("ล้านบาท:Q", title="ล้านบาท"),
                color=alt.Color("company:N", title="บริษัท", sort=order, legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(self_name),
                row=alt.Row("ตัวเลข:N", title=None, sort=["รายได้รวม", "กำไรสุทธิ"]),
                tooltip=["company", "year", "ตัวเลข", alt.Tooltip("ล้านบาท:Q", format=",.0f")],
            ).properties(height=170).resolve_scale(y="independent"))


def finance_ratio_chart(fin, self_name):
    order = company_order(list(fin.index), self_name)
    ratios = (fin[list(FINANCE_TH)].rename(columns=FINANCE_TH).reset_index()
              .melt(id_vars="company", var_name="ตัวชี้วัด", value_name="%").dropna())
    return (alt.Chart(ratios).mark_bar().encode(
                x=alt.X("%:Q", title="%"),
                y=alt.Y("ตัวชี้วัด:N", title=None, sort=list(FINANCE_TH.values())),
                yOffset=alt.YOffset("company:N", sort=order),
                color=alt.Color("company:N", title="บริษัท", sort=order, legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(self_name),
                tooltip=["company", "ตัวชี้วัด", alt.Tooltip("%:Q", format=".1f")],
            ).properties(height=60 + 22 * len(ratios)))


def bank_ratio_chart(banks, self_name):
    order = company_order(list(banks.index), self_name)
    ratios = (banks[[c for c in BANK_TH if c in banks.columns]].rename(columns=BANK_TH).reset_index()
              .melt(id_vars="company", var_name="ตัวชี้วัด", value_name="%").dropna())
    return (alt.Chart(ratios).mark_bar().encode(
                x=alt.X("%:Q", title="%"),
                y=alt.Y("ตัวชี้วัด:N", title=None, sort=list(BANK_TH.values())),
                yOffset=alt.YOffset("company:N", sort=order),
                color=alt.Color("company:N", title="บริษัท", sort=order, legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(self_name),
                tooltip=["company", "ตัวชี้วัด", alt.Tooltip("%:Q", format=".2f")],
            ).properties(height=60 + 22 * len(ratios)))


def week_start(dates):
    """วันจันทร์ของสัปดาห์ (ตัด timezone ก่อน เพื่อไม่ให้ pandas เตือน)"""
    return dates.dt.tz_convert(None).dt.to_period("W").dt.start_time


def _weekly(df):
    d = df.dropna(subset=["published_dt"]).copy()
    d["สัปดาห์"] = week_start(d["published_dt"])
    return d


def _line(data, y, y_title, self_name, fmt=".0f"):
    order = company_order(sorted(data["company"].unique()), self_name)
    return (alt.Chart(data).mark_line(point=True).encode(
                x=alt.X("สัปดาห์:T", title=None, axis=alt.Axis(format="%d %b")),
                y=alt.Y(f"{y}:Q", title=y_title),
                color=alt.Color("company:N", title="บริษัท", sort=order, legend=alt.Legend(orient="bottom")),
                strokeWidth=(alt.condition(alt.datum.company == self_name, alt.value(3.5), alt.value(1.5))
                             if self_name else alt.value(2)),
                tooltip=["company", alt.Tooltip("สัปดาห์:T", format="%d %b %Y"), alt.Tooltip(f"{y}:Q", format=fmt)],
            ).properties(height=300))


def weekly_volume_chart(news, self_name):
    counts = _weekly(news).groupby(["company", "สัปดาห์"]).size().reset_index(name="ข่าว")
    return _line(counts, "ข่าว", "จำนวนข่าว", self_name)


def weekly_negative_chart(news, self_name, min_news=3):
    d = _weekly(news)
    g = d.groupby(["company", "สัปดาห์"])
    neg = pd.DataFrame({"n": g.size(), "ข่าวลบ (%)": g["sentiment"].apply(lambda s: (s == "negative").mean() * 100)})
    return _line(neg[neg["n"] >= min_news].reset_index(), "ข่าวลบ (%)", "% ข่าวลบ", self_name)


def weekly_stars_chart(reviews, self_name):
    stars = _weekly(reviews).groupby(["company", "สัปดาห์"])["rating"].mean().round(2).reset_index(name="ดาว")
    return _line(stars, "ดาว", "ดาวเฉลี่ย", self_name, ".2f")


def internal_chart(table, metric, self_name, unit=""):
    data = table[[metric]].dropna().reset_index().rename(columns={metric: "ค่า"})
    order = company_order(list(data["company"]), self_name)
    return (alt.Chart(data).mark_bar().encode(
                x=alt.X("ค่า:Q", title=f"{metric} ({unit})" if unit else metric),
                y=alt.Y("company:N", title=None, sort=order),
                color=alt.Color("company:N", sort=order, legend=None),
                opacity=company_opacity(self_name),
                tooltip=["company", alt.Tooltip("ค่า:Q", format=",.2f")],
            ).properties(height=60 + 40 * len(data)))


def sector_strip_chart(df, pct, ours, metric_th):
    """ทุกบริษัทในหมวดบนแกนเปอร์เซ็นไทล์ (ขวา = ดีกว่า) จุดเทาคือบริษัทอื่น จุดสีคือบริษัทที่เลือก
    df/pct index = ชื่อหุ้น · ours = {ชื่อหุ้น: ชื่อบริษัท}"""
    rows = [{"หุ้น": s, "ตัวชี้วัด": metric_th[m], "เปอร์เซ็นไทล์": pct.at[s, m], "ค่า": df.at[s, m],
             "บริษัท": ours.get(s, "")}
            for m in pct.columns for s in pct.index if pd.notna(pct.at[s, m])]
    data = pd.DataFrame(rows)
    order = [metric_th[m] for m in pct.columns]
    x = alt.X("เปอร์เซ็นไทล์:Q", scale=alt.Scale(domain=[0, 100]),
              title="ตำแหน่งในหมวด (ขวา = ดีกว่า · D/E และ P/E ต่ำอยู่ขวา)")
    y = alt.Y("ตัวชี้วัด:N", sort=order, title=None)
    tip = ["หุ้น", "ตัวชี้วัด", alt.Tooltip("ค่า:Q", format=",.2f"), alt.Tooltip("เปอร์เซ็นไทล์:Q", format=".0f")]
    others = (alt.Chart(data).transform_filter(alt.datum.บริษัท == "")
              .mark_circle(size=45, opacity=0.3, color="#8a94a6").encode(x=x, y=y, tooltip=tip))
    mine = alt.Chart(data).transform_filter(alt.datum.บริษัท != "")
    dots = mine.mark_circle(size=190, opacity=1, stroke="white", strokeWidth=1.5).encode(
        x=x, y=y, color=alt.Color("บริษัท:N", legend=alt.Legend(orient="bottom", title=None)), tooltip=tip)
    labels = mine.mark_text(dy=-13, fontSize=11, fontWeight="bold").encode(
        x=x, y=y, text="หุ้น:N", color=alt.Color("บริษัท:N", legend=None))
    return (others + dots + labels).properties(height=46 * len(order))


def price_news_chart(prices, ev):
    """เส้นราคาปิดรายวัน + จุดวันที่มีข่าว (สีตามน้ำเสียง) วันที่ขยับผิดปกติเป็นจุดใหญ่มีขอบ
    prices = Series ราคาปิด index = วันที่ · ev = แถวของ impact.events() ของหุ้นตัวนี้"""
    line_data = prices.rename("ราคาปิด").rename_axis("วันที่").reset_index()
    line = alt.Chart(line_data).mark_line(color="#8a94a6").encode(
        x=alt.X("วันที่:T", title=None, axis=alt.Axis(format="%d %b")),
        y=alt.Y("ราคาปิด:Q", title="ราคาปิด (บาท)", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("วันที่:T", format="%d %b %Y"), "ราคาปิด:Q"])
    if ev.empty:
        return line.properties(height=320)
    pts = ev.assign(
        วันที่=pd.to_datetime(ev["date"]), ราคาปิด=ev["close"], น้ำเสียง=ev["sentiment"].map(SENTIMENT_TH),
        หัวข้อ=ev["titles"].map(lambda t: " / ".join(t[:2])[:140]),
        ผิดปกติ=ev["big"].map({True: "ขยับผิดปกติ", False: "ปกติ"}))
    dots = alt.Chart(pts).mark_circle(stroke="#1b2330").encode(
        x="วันที่:T", y="ราคาปิด:Q",
        color=alt.Color("น้ำเสียง:N", scale=alt.Scale(domain=list(SENTIMENT_COLORS),
                                                       range=list(SENTIMENT_COLORS.values())),
                        legend=alt.Legend(orient="bottom", title="น้ำเสียงข่าว")),
        size=alt.condition(alt.datum.ผิดปกติ == "ขยับผิดปกติ", alt.value(220), alt.value(60)),
        strokeWidth=alt.condition(alt.datum.ผิดปกติ == "ขยับผิดปกติ", alt.value(2), alt.value(0)),
        tooltip=[alt.Tooltip("วันที่:T", format="%d %b %Y"), "หัวข้อ:N", "news:Q",
                 alt.Tooltip("r1_pct:Q", title="1 วัน (%)", format="+.2f"),
                 alt.Tooltip("r3_pct:Q", title="3 วัน (%)", format="+.2f"),
                 alt.Tooltip("z:Q", title="เท่าของปกติ"), "ผิดปกติ:N"])
    return (line + dots).properties(height=320)
