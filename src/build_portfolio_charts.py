"""README용 차트와 EW·VW 차이 분해 표를 만든다.

선행: python src/short_pressure_analysis.py  (input/processed_data/analysis_panel_*.csv 생성)
실행: python src/build_portfolio_charts.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "input" / "processed_data"
TABLES = ROOT / "output" / "tables"
CHARTS = ROOT / "output" / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

EW, VW, BENCH, ACCENT = "#2F6DA3", "#982A2F", "#8C8C8C", "#1F9A6E"
INK, MUTED = "#222222", "#666666"
for font_file in Path.home().glob("Library/Fonts/Pretendard-*.otf"):
    fm.fontManager.addfont(str(font_file))
plt.rcParams.update({
    "font.family": ["Pretendard", "AppleGothic"], "axes.unicode_minus": False,
    "axes.edgecolor": "#BBBBBB", "axes.titleweight": "bold", "axes.titlesize": 12,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": "#E6E6E6",
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "savefig.dpi": 160, "savefig.bbox": "tight", "figure.facecolor": "white",
})

BAN_RANGES = [("2011-08", "2011-11"), ("2020-03", "2021-04"), ("2023-11", "2025-03")]


def ann_t(x):
    x = pd.Series(x).dropna()
    return x.mean() * 12, x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), len(x)


# 1. 월별 D10·유니버스 수익률 재계산 (제출 결과와 동일한지 확인)
monthly = {}
for key, label in [("lending_balance", "대차거래잔고수량"), ("short_balance", "차입공매도잔고수량")]:
    panel = pd.read_csv(PANEL_DIR / f"analysis_panel_{key}.csv")
    rows = []
    for period, g in panel.groupby("period"):
        d = g[g["in_d10"]]
        w, dw = g["market_cap_mil_krw"], d["market_cap_mil_krw"]
        rows.append({
            "period": pd.Period(period, freq="M"),
            "d10_ew": d["next_return"].mean(), "d10_vw": (dw * d["next_return"]).sum() / dw.sum(),
            "univ_ew": g["next_return"].mean(), "univ_vw": (w * g["next_return"]).sum() / w.sum(),
            "d10_cap_share_of_universe": dw.sum() / w.sum(),
            "n_reported": int(g["reported_balance"].sum()),
        })
    m = pd.DataFrame(rows).set_index("period")
    m["U_EW"] = m["d10_ew"] - m["univ_ew"]
    m["U_VW"] = m["d10_vw"] - m["univ_vw"]
    monthly[label] = m

lend = monthly["대차거래잔고수량"]
check = pd.read_csv(TABLES / "proxy_test_summary.csv").set_index("proxy")
for label, m in monthly.items():
    ew, t_ew, _ = ann_t(m["U_EW"])
    vw, t_vw, _ = ann_t(m["U_VW"])
    assert abs(ew - check.loc[label, "ann_mean_ew"]) < 1e-9 and abs(vw - check.loc[label, "ann_mean_vw"]) < 1e-9

# 2. U_VW - U_EW 분해: (D10 VW - D10 EW) - (유니버스 VW - 유니버스 EW)
decomp = pd.DataFrame([
    ("U_EW (제출 결과)", *ann_t(lend["U_EW"])),
    ("U_VW (제출 결과)", *ann_t(lend["U_VW"])),
    ("U_VW - U_EW", *ann_t(lend["U_VW"] - lend["U_EW"])),
    ("  ① D10 내부: VW - EW", *ann_t(lend["d10_vw"] - lend["d10_ew"])),
    ("  ② 유니버스: VW - EW (빼는 항)", *ann_t(lend["univ_vw"] - lend["univ_ew"])),
    ("D10 VW 절대수익", *ann_t(lend["d10_vw"])),
    ("KOSPI200 유니버스 VW 절대수익", *ann_t(lend["univ_vw"])),
], columns=["항목", "연환산", "t", "개월수"])
decomp.to_csv(TABLES / "ew_vw_gap_decomposition.csv", index=False, encoding="utf-8-sig")
print(decomp.round(4).to_string())
print("D10 평균 시총 비중:", lend["d10_cap_share_of_universe"].mean())

# 3. 종목별 U_VW 기여 (D10 내 시총비중 × (다음달 수익률 - 유니버스 VW))
panel = pd.read_csv(PANEL_DIR / "analysis_panel_lending_balance.csv")
contrib = []
for period, g in panel.groupby("period"):
    d = g[g["in_d10"]]
    u = (g["market_cap_mil_krw"] * g["next_return"]).sum() / g["market_cap_mil_krw"].sum()
    w = d["market_cap_mil_krw"] / d["market_cap_mil_krw"].sum()
    contrib.append(pd.DataFrame({"name": d["name"], "weight": w, "contrib": w * (d["next_return"] - u)}))
contrib = pd.concat(contrib).groupby("name").agg(
    contrib=("contrib", "sum"), months_in_d10=("contrib", "size"), avg_weight=("weight", "mean"))
contrib["ann_contrib_pctp"] = contrib["contrib"] / len(lend) * 12 * 100
contrib = contrib.sort_values("ann_contrib_pctp")
contrib.to_csv(TABLES / "u_vw_contribution_by_stock.csv", encoding="utf-8-sig")

# 4. 대표 차트
fig = plt.figure(figsize=(15, 8.4))
gs = fig.add_gridspec(2, 2, height_ratios=[1.35, 1], width_ratios=[1.25, 1], hspace=0.45, wspace=0.22)

ax = fig.add_subplot(gs[0, :])
full_idx = pd.period_range("2010-01", "2026-05", freq="M")
cum = lend[["U_EW", "U_VW"]].reindex(full_idx).fillna(0).cumsum()
x = full_idx.to_timestamp()
for s, e in BAN_RANGES:
    ax.axvspan(pd.Period(s, "M").to_timestamp(), (pd.Period(e, "M") + 1).to_timestamp(), color="#EDEDED", linewidth=0)
ax.text(pd.Timestamp("2024-07-15"), -140, "공매도\n전면금지\n(제외)", fontsize=9, color=MUTED, ha="center")
ew_a, ew_t, _ = ann_t(lend["U_EW"])
vw_a, vw_t, _ = ann_t(lend["U_VW"])
ax.plot(x, cum["U_EW"] * 100, color=EW, linewidth=2, label=f"동일가중 U_EW  연 {ew_a*100:+.1f}%, t={ew_t:.2f} (비유의)")
ax.plot(x, cum["U_VW"] * 100, color=VW, linewidth=2, label=f"시총가중 U_VW  연 {vw_a*100:+.1f}%, t={vw_t:.2f} (유의)")
ax.axhline(0, color="#999999", linewidth=0.8)
ax.set_ylabel("누적 합계 (%p)")
ax.set_title("A. 대차잔고 상위 10%(D10)의 다음 달 수익률 − KOSPI200 유니버스 평균, 누적 (2010-01 ~ 2026-05, 159개월)", loc="left")
ax.legend(frameon=False, loc="lower left")

ax2 = fig.add_subplot(gs[1, 0])
items = [("U_VW − U_EW", decomp.iloc[2]), ("① D10 안에서\n대형주 가중 효과", decomp.iloc[3]),
         ("② 유니버스 VW−EW\n(차감되는 벤치마크 차이)", decomp.iloc[4])]
vals = [items[0][1]["연환산"] * 100, items[1][1]["연환산"] * 100, -items[2][1]["연환산"] * 100]
colors = [VW, BENCH, ACCENT]
yy = np.arange(3)[::-1]
ax2.barh(yy, vals, color=colors, height=0.55)
for yi, v, (lab, row) in zip(yy, vals, items):
    ax2.text(v + (-0.3 if v < 0 else 0.3), yi, f"{v:+.1f}%p  (t={row['t'] * (-1 if lab.startswith('②') else 1):.2f})",
             va="center", ha="right" if v < 0 else "left", fontsize=10, color=INK)
ax2.set_yticks(yy)
ax2.set_yticklabels([i[0] for i in items], fontsize=10)
ax2.axvline(0, color="#999999", linewidth=0.8)
ax2.set_xlim(-16, 4)
ax2.set_xlabel("연환산 %p   (U_VW − U_EW = ① − ②)")
ax2.set_title("B. 왜 VW에서만 유의했나 — 차이의 약 2/3는 벤치마크 쪽", loc="left")
ax2.grid(axis="y", visible=False)

ax3 = fig.add_subplot(gs[1, 1])
for label, color in [("대차거래잔고수량", VW), ("차입공매도잔고수량", EW)]:
    m = monthly[label]["n_reported"].reindex(full_idx)
    ax3.plot(x, m, color=color, linewidth=1.8, label=f"{label} (월평균 {m.mean():.0f}종목)")
ax3.set_ylim(0, 215)
ax3.set_ylabel("잔고가 보고된 KOSPI200 종목 수")
ax3.set_title("C. 두 프록시의 커버리지 — 실제 공매도잔고는 공시 기준 이상만 잡힘", loc="left")
ax3.legend(frameon=False, loc="center left", fontsize=9)

fig.suptitle("KOSPI200 공매도 압력 가설 검정: 대차잔고 D10은 다음 달 부진했나", x=0.01, ha="left", fontsize=15, fontweight="bold")
fig.text(0.01, 0.0, "공매도 전면금지 구간은 신호월 또는 수익률 측정월이 걸리면 제외(회색). 압력비율 = 잔고수량 / (시가총액 ÷ 원종가) × 100. "
         "D10은 월별 압력비율 상위 10%(약 20종목).", fontsize=9, color=MUTED)
fig.savefig(CHARTS / "hero_ew_vw_decomposition.png")
plt.close(fig)

# 5. 종목별 기여 차트
top = pd.concat([contrib.head(10), contrib.tail(5)])
fig, ax = plt.subplots(figsize=(10, 6.2))
yy = np.arange(len(top))[::-1]
ax.barh(yy, top["ann_contrib_pctp"], color=[VW if v < 0 else EW for v in top["ann_contrib_pctp"]], height=0.6)
ax.set_yticks(yy)
ax.set_yticklabels([f"{n}  ({int(m)}개월, 평균 {w*100:.0f}%)" for n, m, w in
                    zip(top.index, top["months_in_d10"], top["avg_weight"])], fontsize=9.5)
ax.axvline(0, color="#999999", linewidth=0.8)
ax.set_xlabel("U_VW 연환산 기여 (%p)")
ax.set_title("U_VW −12.2%p를 만든 종목 — D10 안에서 비중이 큰 POSCO홀딩스·LG전자·셀트리온 등", loc="left")
ax.grid(axis="y", visible=False)
fig.savefig(CHARTS / "u_vw_contribution_by_stock.png")
plt.close(fig)

# 6. 월별 D10 최대 비중 (VW 집중도 점검)
fig, ax = plt.subplots(figsize=(11, 3.8))
mw = pd.read_csv(TABLES / "d10_max_weight_check.csv")
for label, color in [("대차거래잔고수량", VW), ("차입공매도잔고수량", EW)]:
    s = mw[mw["proxy"] == label].set_index("period")["d10_max_weight"]
    s.index = pd.PeriodIndex(s.index, freq="M").to_timestamp()
    ax.plot(s.index, s * 100, color=color, linewidth=1.5, label=label)
ax.axhline(50, color="#999999", linewidth=0.8, linestyle="--")
ax.text(pd.Timestamp("2010-03-01"), 52, "50%: 사실상 한 종목 베팅", fontsize=9, color=MUTED)
ax.set_ylabel("D10 단일종목 최대 비중 (%)")
ax.set_title("VW 집중도 점검 — 대차잔고 D10은 최대 42.6%, 50%를 넘은 달 없음", loc="left")
ax.legend(frameon=False, fontsize=9, loc="upper right")
fig.savefig(CHARTS / "d10_max_weight.png")
plt.close(fig)
print(contrib.head(6).round(3))

# 7. 기간 강건성: 판정이 특정 구간에 의존하는지
windows = [("전체 2010-01~2026-05", "2010-01", "2026-05"), ("2026년 제외", "2010-01", "2025-12"),
           ("마지막 금지 해제 이전 (~2025-03)", "2010-01", "2025-03"),
           ("2010~2015", "2010-01", "2015-12"), ("2016~2020", "2016-01", "2020-12"), ("2021~2026", "2021-01", "2026-05")]
rob = []
for name, s, e in windows:
    sub = lend.loc[pd.Period(s, "M"):pd.Period(e, "M")]
    ew_a, ew_t, n = ann_t(sub["U_EW"])
    vw_a, vw_t, _ = ann_t(sub["U_VW"])
    verdict = {(True, True): "A", (True, False): "B", (False, True): "A+", (False, False): "신호 없음"}[(ew_t < -2, vw_t < -2)]
    rob.append({"구간": name, "개월수": n, "EW 연환산": ew_a, "t_EW": ew_t, "VW 연환산": vw_a, "t_VW": vw_t, "판정": verdict})
rob = pd.DataFrame(rob)
rob.to_csv(TABLES / "subperiod_robustness.csv", index=False, encoding="utf-8-sig")
print(rob.round(3).to_string())
