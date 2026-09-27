from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
RAW_XLSX = ROOT / "input" / "raw_data" / "3주차 데이터 원본.xlsx"
PROCESSED_DIR = ROOT / "input" / "processed_data"
OUTPUT_DIR = ROOT / "output" / "tables"

SHEET_RAW_CLOSE = "종가"
SHEET_ADJ_CLOSE = "수정주가"
SHEET_MCAP = "시가총액"
SHEET_UNIVERSE = "코스피200구성여부"
SHEET_LENDING = "대차거래잔고수량"
SHEET_SHORT_BALANCE = "차입공매도잔고수량"


@dataclass(frozen=True)
class ProxyConfig:
    key: str
    sheet_name: str
    label: str
    start_period: pd.Period
    fill_missing_balance_as_zero: bool


PROXIES = [
    ProxyConfig(
        key="short_balance",
        sheet_name=SHEET_SHORT_BALANCE,
        label="차입공매도잔고수량",
        start_period=pd.Period("2016-06", freq="M"),
        fill_missing_balance_as_zero=True,
    ),
    ProxyConfig(
        key="lending_balance",
        sheet_name=SHEET_LENDING,
        label="대차거래잔고수량",
        start_period=pd.Period("2010-01", freq="M"),
        fill_missing_balance_as_zero=True,
    ),
]


BAN_RANGES = [
    (pd.Period("2011-08", freq="M"), pd.Period("2011-11", freq="M")),
    (pd.Period("2020-03", freq="M"), pd.Period("2021-04", freq="M")),
    (pd.Period("2023-11", freq="M"), pd.Period("2025-03", freq="M")),
]


def read_wide_sheet(
    workbook,
    sheet_name: str,
    *,
    monthly_last_observation: bool = False,
) -> tuple[pd.DataFrame, pd.Series]:
    """Read a DataGuide-style wide sheet into a PeriodIndex x code DataFrame."""
    ws = workbook[sheet_name]
    codes = [cell.value for cell in ws[9][1:]]
    names = [cell.value for cell in ws[10][1:]]
    names_by_code = pd.Series(names, index=codes, name="name")

    if monthly_last_observation:
        rows_by_period: dict[pd.Period, tuple] = {}
        dates_by_period: dict[pd.Period, datetime] = {}
        for row in ws.iter_rows(min_row=15, values_only=True):
            date_value = row[0]
            if not isinstance(date_value, datetime):
                continue
            period = pd.Period(date_value, freq="M")
            if period not in dates_by_period or date_value >= dates_by_period[period]:
                dates_by_period[period] = date_value
                rows_by_period[period] = row[1 : 1 + len(codes)]

        periods = sorted(rows_by_period)
        data = [rows_by_period[p] for p in periods]
        df = pd.DataFrame(data, index=pd.PeriodIndex(periods, freq="M"), columns=codes)
    else:
        periods = []
        data = []
        for row in ws.iter_rows(min_row=15, values_only=True):
            date_value = row[0]
            if not isinstance(date_value, datetime):
                continue
            periods.append(pd.Period(date_value, freq="M"))
            data.append(row[1 : 1 + len(codes)])
        df = pd.DataFrame(data, index=pd.PeriodIndex(periods, freq="M"), columns=codes)

    return df, names_by_code


def numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(pd.to_numeric, errors="coerce")


def is_ban_month(period: pd.Period) -> bool:
    return any(start <= period <= end for start, end in BAN_RANGES)


def judgement_from_t(t_ew: float, t_vw: float) -> str:
    ew_sig = pd.notna(t_ew) and t_ew < -2
    vw_sig = pd.notna(t_vw) and t_vw < -2
    if ew_sig and vw_sig:
        return "A - VW에서도 유의"
    if ew_sig and not vw_sig:
        return "B - EW만 유의, VW 소멸"
    if not ew_sig and vw_sig:
        return "A+ - VW 중심 유의"
    return "신호 없음 / 결론유보"


def summarize_underperformance(values: pd.Series) -> tuple[float, float, int]:
    clean = values.dropna()
    n = len(clean)
    if n < 2:
        return np.nan, np.nan, n
    mean_monthly = clean.mean()
    std_monthly = clean.std(ddof=1)
    if std_monthly == 0 or pd.isna(std_monthly):
        t_stat = np.nan
    else:
        t_stat = mean_monthly / (std_monthly / math.sqrt(n))
    return mean_monthly * 12, t_stat, n


def make_simple_svg_line_chart(
    output_path: Path,
    data: pd.DataFrame,
    title: str,
    y_label: str,
) -> None:
    width, height = 980, 560
    left, right, top, bottom = 86, 30, 54, 82
    plot_w = width - left - right
    plot_h = height - top - bottom

    clean = data.dropna(how="all")
    if clean.empty:
        output_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
        return

    y_min = float(np.nanmin(clean.to_numpy()))
    y_max = float(np.nanmax(clean.to_numpy()))
    if y_min == y_max:
        y_min -= 0.01
        y_max += 0.01
    pad = (y_max - y_min) * 0.08
    y_min -= pad
    y_max += pad

    periods = list(clean.index.astype(str))
    n = len(periods)

    def x_pos(i: int) -> float:
        return left + (plot_w * i / max(n - 1, 1))

    def y_pos(value: float) -> float:
        return top + plot_h - ((value - y_min) / (y_max - y_min) * plot_h)

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]
    svg: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
        "<rect width='100%' height='100%' fill='white'/>",
        f"<text x='{left}' y='30' font-size='20' font-family='Arial, sans-serif' font-weight='700'>{title}</text>",
        f"<text x='20' y='{top + plot_h / 2}' font-size='12' font-family='Arial, sans-serif' transform='rotate(-90 20,{top + plot_h / 2})'>{y_label}</text>",
        f"<line x1='{left}' y1='{top}' x2='{left}' y2='{top + plot_h}' stroke='#333'/>",
        f"<line x1='{left}' y1='{top + plot_h}' x2='{left + plot_w}' y2='{top + plot_h}' stroke='#333'/>",
    ]

    for tick in range(6):
        value = y_min + (y_max - y_min) * tick / 5
        y = y_pos(value)
        svg.append(f"<line x1='{left}' y1='{y:.1f}' x2='{left + plot_w}' y2='{y:.1f}' stroke='#e6e6e6'/>")
        svg.append(
            f"<text x='{left - 10}' y='{y + 4:.1f}' text-anchor='end' font-size='11' "
            f"font-family='Arial, sans-serif'>{value:.1%}</text>"
        )

    for idx in np.linspace(0, n - 1, num=min(8, n), dtype=int):
        x = x_pos(int(idx))
        svg.append(f"<line x1='{x:.1f}' y1='{top + plot_h}' x2='{x:.1f}' y2='{top + plot_h + 5}' stroke='#333'/>")
        svg.append(
            f"<text x='{x:.1f}' y='{top + plot_h + 22}' text-anchor='middle' font-size='10' "
            f"font-family='Arial, sans-serif'>{periods[int(idx)]}</text>"
        )

    legend_x = left
    legend_y = height - 30
    for col_idx, column in enumerate(clean.columns):
        series = clean[column].dropna()
        if series.empty:
            continue
        color = colors[col_idx % len(colors)]
        points = []
        for period, value in series.items():
            i = periods.index(str(period))
            points.append(f"{x_pos(i):.1f},{y_pos(float(value)):.1f}")
        svg.append(f"<polyline points='{' '.join(points)}' fill='none' stroke='{color}' stroke-width='2.2'/>")
        lx = legend_x + (col_idx % 3) * 270
        ly = legend_y + (col_idx // 3) * 18
        svg.append(f"<line x1='{lx}' y1='{ly}' x2='{lx + 24}' y2='{ly}' stroke='{color}' stroke-width='2.5'/>")
        svg.append(
            f"<text x='{lx + 32}' y='{ly + 4}' font-size='11' font-family='Arial, sans-serif'>{column}</text>"
        )

    svg.append("</svg>")
    output_path.write_text("\n".join(svg), encoding="utf-8")


def make_matplotlib_line_chart(
    output_path: Path,
    data: pd.DataFrame,
    title: str,
    y_label: str,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    clean = data.dropna(how="all")
    if clean.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 6.5))
    x = np.arange(len(clean.index))
    for column in clean.columns:
        ax.plot(x, clean[column], linewidth=2, label=column)

    tick_count = min(10, len(clean.index))
    tick_positions = np.linspace(0, len(clean.index) - 1, tick_count, dtype=int)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([str(clean.index[i]) for i in tick_positions], rotation=45, ha="right")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.axhline(0, color="#555555", linewidth=1)
    ax.grid(True, axis="y", color="#dddddd", linewidth=0.8)
    ax.set_title(title)
    ax.set_ylabel(y_label)
    ax.legend(loc="best", frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def evaluate_proxy(
    *,
    config: ProxyConfig,
    balance: pd.DataFrame,
    names_by_code: pd.Series,
    raw_close: pd.DataFrame,
    adj_close: pd.DataFrame,
    market_cap_mil_krw: pd.DataFrame,
    universe: pd.DataFrame,
    shares_clean: pd.DataFrame,
    next_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    balance_numeric = numeric_frame(balance).reindex_like(raw_close)
    original_reported = balance_numeric.notna()

    if config.fill_missing_balance_as_zero:
        balance_for_pressure = balance_numeric.fillna(0.0)
        balance_for_pressure.loc[balance_for_pressure.index < config.start_period, :] = np.nan
    else:
        balance_for_pressure = balance_numeric.copy()

    pressure = balance_for_pressure / shares_clean * 100.0
    pressure.to_csv(PROCESSED_DIR / f"pressure_ratio_{config.key}.csv", encoding="utf-8-sig")

    monthly_rows = []
    d10_rows = []
    panel_rows = []
    skipped_rows = []

    for period in raw_close.index[:-1]:
        next_period = period + 1
        if period < config.start_period:
            skipped_rows.append(
                {"proxy": config.label, "period": str(period), "reason": "before_proxy_start"}
            )
            continue
        if is_ban_month(period) or is_ban_month(next_period):
            skipped_rows.append({"proxy": config.label, "period": str(period), "reason": "short_sale_ban"})
            continue

        period_universe = universe.loc[period].astype(str).str.upper().eq("Y")
        valid = (
            period_universe
            & pressure.loc[period].notna()
            & next_returns.loc[period].notna()
            & market_cap_mil_krw.loc[period].notna()
            & market_cap_mil_krw.loc[period].gt(0)
        )
        n_universe = int(valid.sum())
        if n_universe < 50:
            skipped_rows.append({"proxy": config.label, "period": str(period), "reason": "too_few_valid_names"})
            continue

        month_df = pd.DataFrame(
            {
                "code": raw_close.columns[valid].tolist(),
                "name": names_by_code.reindex(raw_close.columns[valid]).to_numpy(),
                "pressure_ratio": pressure.loc[period, valid].to_numpy(dtype=float),
                "balance_qty": balance_for_pressure.loc[period, valid].to_numpy(dtype=float),
                "reported_balance": original_reported.loc[period, valid].to_numpy(dtype=bool),
                "shares_outstanding": shares_clean.loc[period, valid].to_numpy(dtype=float),
                "raw_close": raw_close.loc[period, valid].to_numpy(dtype=float),
                "adj_close": adj_close.loc[period, valid].to_numpy(dtype=float),
                "market_cap_mil_krw": market_cap_mil_krw.loc[period, valid].to_numpy(dtype=float),
                "next_return": next_returns.loc[period, valid].to_numpy(dtype=float),
            }
        )
        month_df = month_df.sort_values(
            ["pressure_ratio", "market_cap_mil_krw", "code"],
            ascending=[False, False, True],
            kind="mergesort",
        ).reset_index(drop=True)

        d10_count = max(1, int(math.ceil(n_universe * 0.10)))
        month_df["rank_pressure"] = np.arange(1, len(month_df) + 1)
        month_df["in_d10"] = month_df["rank_pressure"] <= d10_count

        d10 = month_df.loc[month_df["in_d10"]].copy()
        full = month_df
        ew_under = d10["next_return"].mean() - full["next_return"].mean()
        vw_under = np.average(d10["next_return"], weights=d10["market_cap_mil_krw"]) - np.average(
            full["next_return"], weights=full["market_cap_mil_krw"]
        )
        d10_max_weight = d10["market_cap_mil_krw"].max() / d10["market_cap_mil_krw"].sum()

        monthly_rows.append(
            {
                "proxy": config.label,
                "period": str(period),
                "next_period": str(next_period),
                "n_universe": n_universe,
                "n_d10": d10_count,
                "n_reported_balance": int(month_df["reported_balance"].sum()),
                "n_nonzero_balance": int((month_df["balance_qty"] > 0).sum()),
                "d10_avg_pressure_ratio": d10["pressure_ratio"].mean(),
                "d10_min_pressure_ratio": d10["pressure_ratio"].min(),
                "universe_avg_pressure_ratio": full["pressure_ratio"].mean(),
                "u_ew": ew_under,
                "u_vw": vw_under,
                "d10_max_weight": d10_max_weight,
                "d10_max_weight_name": d10.sort_values("market_cap_mil_krw", ascending=False).iloc[0]["name"],
                "d10_max_weight_code": d10.sort_values("market_cap_mil_krw", ascending=False).iloc[0]["code"],
            }
        )

        d10_to_save = d10.copy()
        d10_to_save.insert(0, "proxy", config.label)
        d10_to_save.insert(1, "period", str(period))
        d10_rows.append(d10_to_save)

        panel_to_save = month_df.copy()
        panel_to_save.insert(0, "proxy", config.label)
        panel_to_save.insert(1, "period", str(period))
        panel_rows.append(panel_to_save)

    monthly = pd.DataFrame(monthly_rows)
    d10_all = pd.concat(d10_rows, ignore_index=True) if d10_rows else pd.DataFrame()
    panel_all = pd.concat(panel_rows, ignore_index=True) if panel_rows else pd.DataFrame()
    skipped = pd.DataFrame(skipped_rows)
    return monthly, d10_all, panel_all, skipped


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    workbook = load_workbook(RAW_XLSX, read_only=True, data_only=True)

    raw_close_raw, names_by_code = read_wide_sheet(workbook, SHEET_RAW_CLOSE)
    adj_close_raw, _ = read_wide_sheet(workbook, SHEET_ADJ_CLOSE)
    market_cap_raw, _ = read_wide_sheet(workbook, SHEET_MCAP)
    universe_raw, _ = read_wide_sheet(workbook, SHEET_UNIVERSE)
    lending_raw, _ = read_wide_sheet(workbook, SHEET_LENDING)
    short_balance_raw, _ = read_wide_sheet(workbook, SHEET_SHORT_BALANCE, monthly_last_observation=True)

    raw_close = numeric_frame(raw_close_raw)
    adj_close = numeric_frame(adj_close_raw).reindex_like(raw_close)
    market_cap_mil_krw = numeric_frame(market_cap_raw).reindex_like(raw_close)
    universe = universe_raw.reindex_like(raw_close)
    lending = numeric_frame(lending_raw).reindex_like(raw_close)
    short_balance = numeric_frame(short_balance_raw).reindex_like(raw_close)

    shares = market_cap_mil_krw * 1_000_000.0 / raw_close
    share_change = shares / shares.shift(1)
    split_artifact = (share_change > 3.0) | (share_change < (1 / 3.0))
    shares_clean = shares.mask(split_artifact)

    next_returns = adj_close.shift(-1) / adj_close - 1.0

    universe_mask = universe.astype(str).apply(lambda col: col.str.upper().eq("Y"))
    universe_count = universe_mask.sum(axis=1).rename("kospi200_count").to_frame()
    universe_count["split_artifact_count"] = split_artifact.sum(axis=1)
    universe_count.to_csv(PROCESSED_DIR / "universe_quality_by_month.csv", encoding="utf-8-sig")
    next_returns.to_csv(PROCESSED_DIR / "next_month_returns.csv", encoding="utf-8-sig")

    all_monthly = []
    all_d10 = []
    all_panel = []
    all_skipped = []
    balance_by_key = {
        "short_balance": short_balance,
        "lending_balance": lending,
    }

    for config in PROXIES:
        monthly, d10, panel, skipped = evaluate_proxy(
            config=config,
            balance=balance_by_key[config.key],
            names_by_code=names_by_code,
            raw_close=raw_close,
            adj_close=adj_close,
            market_cap_mil_krw=market_cap_mil_krw,
            universe=universe,
            shares_clean=shares_clean,
            next_returns=next_returns,
        )
        all_monthly.append(monthly)
        all_d10.append(d10)
        all_panel.append(panel)
        all_skipped.append(skipped)
        panel.to_csv(PROCESSED_DIR / f"analysis_panel_{config.key}.csv", index=False, encoding="utf-8-sig")

    monthly_under = pd.concat(all_monthly, ignore_index=True)
    d10_all = pd.concat(all_d10, ignore_index=True)
    skipped_all = pd.concat(all_skipped, ignore_index=True)

    monthly_under.to_csv(OUTPUT_DIR / "monthly_underperformance.csv", index=False, encoding="utf-8-sig")
    d10_all.to_csv(OUTPUT_DIR / "d10_constituents.csv", index=False, encoding="utf-8-sig")
    skipped_all.to_csv(OUTPUT_DIR / "skipped_months.csv", index=False, encoding="utf-8-sig")
    monthly_under[
        [
            "proxy",
            "period",
            "d10_max_weight",
            "d10_max_weight_name",
            "d10_max_weight_code",
            "n_universe",
            "n_reported_balance",
            "n_nonzero_balance",
        ]
    ].to_csv(OUTPUT_DIR / "d10_max_weight_check.csv", index=False, encoding="utf-8-sig")

    summary_rows = []
    for proxy, group in monthly_under.groupby("proxy", sort=False):
        ann_ew, t_ew, n_ew = summarize_underperformance(group["u_ew"])
        ann_vw, t_vw, n_vw = summarize_underperformance(group["u_vw"])
        summary_rows.append(
            {
                "proxy": proxy,
                "first_period": group["period"].min(),
                "last_period": group["period"].max(),
                "n_months": int(min(n_ew, n_vw)),
                "ann_mean_ew": ann_ew,
                "t_ew": t_ew,
                "ann_mean_vw": ann_vw,
                "t_vw": t_vw,
                "judgement": judgement_from_t(t_ew, t_vw),
                "avg_universe_count": group["n_universe"].mean(),
                "avg_reported_balance_count": group["n_reported_balance"].mean(),
                "avg_nonzero_balance_count": group["n_nonzero_balance"].mean(),
                "months_d10_max_weight_over_50pct": int((group["d10_max_weight"] > 0.5).sum()),
                "max_d10_max_weight": group["d10_max_weight"].max(),
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUTPUT_DIR / "proxy_test_summary.csv", index=False, encoding="utf-8-sig")

    chart_label_map = {
        "차입공매도잔고수량": "Short balance",
        "대차거래잔고수량": "Lending balance",
    }

    cumulative = monthly_under.pivot(index="period", columns="proxy", values="u_ew").sort_index()
    cumulative = (1.0 + cumulative.fillna(0.0)).cumprod() - 1.0
    cumulative.columns = [f"{chart_label_map.get(col, col)} EW" for col in cumulative.columns]

    cumulative_vw = monthly_under.pivot(index="period", columns="proxy", values="u_vw").sort_index()
    cumulative_vw = (1.0 + cumulative_vw.fillna(0.0)).cumprod() - 1.0
    cumulative_vw.columns = [f"{chart_label_map.get(col, col)} VW" for col in cumulative_vw.columns]

    chart_data = pd.concat([cumulative, cumulative_vw], axis=1)
    make_simple_svg_line_chart(
        OUTPUT_DIR / "cumulative_underperformance.svg",
        chart_data,
        "Cumulative high-pressure D10 underperformance",
        "Cumulative spread return",
    )
    make_matplotlib_line_chart(
        OUTPUT_DIR / "cumulative_underperformance.png",
        chart_data,
        "Cumulative high-pressure D10 underperformance",
        "Cumulative spread return",
    )

    main_row = summary.loc[summary["proxy"].eq("대차거래잔고수량")].iloc[0]
    short_row = summary.loc[summary["proxy"].eq("차입공매도잔고수량")].iloc[0]
    judgement_text = f"""# 최종 판정문 초안

## 주 프록시

본 분석은 `대차거래잔고수량`을 주 프록시로 사용했다. 대차잔고는 실제 순공매도 포지션만을 뜻하지는 않고 헤지·차익거래·결제 목적 대차도 포함하므로 공매도 압력의 광의 프록시라는 한계가 있다. 그러나 KOSPI200 전체 종목에 대해 장기간 관측되어 매월 20종목 D10을 안정적으로 구성할 수 있다는 장점이 있다.

`차입공매도잔고수량`은 실제 공매도 포지션에 더 가까운 협의 프록시지만, 본 데이터에서는 2016-06 이후에야 관측되고 KOSPI200 내 월평균 보고 종목 수가 {short_row['avg_reported_balance_count']:.1f}개에 그친다. 공시 임계값 때문에 작은 포지션이 누락되는 검열 문제가 커서, 주 검정보다는 보조 프록시로 사용했다.

## 금지기간 처리

공매도 전면금지 구간은 신호가 정상적으로 작동하기 어렵기 때문에 제외했다. 보수적으로 신호월 또는 다음 달 수익률 측정월이 금지기간에 걸리는 관측치를 제거했다. 제외 구간은 2011-08~2011-11, 2020-03~2021-04, 2023-11~2025-03이다.

## 검정 결과

주 프록시인 `대차거래잔고수량` 기준 분석기간은 {main_row['first_period']}~{main_row['last_period']}이고, 유효 관측월은 {int(main_row['n_months'])}개월이다. 고압력 십분위 D10의 다음 달 언더퍼폼은 EW 연환산 {main_row['ann_mean_ew']:.2%}, t_EW = {main_row['t_ew']:.2f}, VW 연환산 {main_row['ann_mean_vw']:.2%}, t_VW = {main_row['t_vw']:.2f}로 계산되었다. 판정표 기준 결론은 `{main_row['judgement']}`이다.

VW 집중도 점검에서는 D10 단일종목 최대 비중이 50%를 넘은 달이 {int(main_row['months_d10_max_weight_over_50pct'])}개월이고, 최대값도 {main_row['max_d10_max_weight']:.2%}였다. 따라서 VW 결과가 특정 한 종목에 의해 거의 전부 결정되었다고 보기는 어렵다.

보조 프록시인 `차입공매도잔고수량` 기준으로는 분석기간 {short_row['first_period']}~{short_row['last_period']}, 유효 관측월 {int(short_row['n_months'])}개월이며, EW 연환산 {short_row['ann_mean_ew']:.2%}, t_EW = {short_row['t_ew']:.2f}, VW 연환산 {short_row['ann_mean_vw']:.2%}, t_VW = {short_row['t_vw']:.2f}이다. 보조 프록시의 판정은 `{short_row['judgement']}`이지만, 이는 공시 잔고의 낮은 커버리지와 검열 문제를 함께 고려해 해석해야 한다.

## 해석

한국 KOSPI200에서는 `대차거래잔고수량` 기준 고압력 종목의 부진이 EW에서는 유의하지 않았지만 VW에서는 유의했다. 이는 APR의 “EW만 유의하고 VW에서는 소멸한다”는 전형적 B 패턴과는 다르며, 오히려 대형주 가중 결과에서 신호가 살아남는 드문 A+ 형태에 가깝다. 따라서 본 표본과 프록시에서는 가설 A가 조건부로 더 타당하다고 판단한다. 다만 주 프록시가 실제 공매도 잔고가 아니라 대차잔고라는 점, 보조 프록시에서는 커버리지 부족으로 명확한 신호가 약하다는 점을 한계로 제시한다.
"""
    (OUTPUT_DIR / "final_judgement_draft.md").write_text(judgement_text, encoding="utf-8")

    print("Created:")
    for path in [
        PROCESSED_DIR / "universe_quality_by_month.csv",
        PROCESSED_DIR / "next_month_returns.csv",
        PROCESSED_DIR / "pressure_ratio_short_balance.csv",
        PROCESSED_DIR / "pressure_ratio_lending_balance.csv",
        PROCESSED_DIR / "analysis_panel_short_balance.csv",
        PROCESSED_DIR / "analysis_panel_lending_balance.csv",
        OUTPUT_DIR / "monthly_underperformance.csv",
        OUTPUT_DIR / "proxy_test_summary.csv",
        OUTPUT_DIR / "d10_constituents.csv",
        OUTPUT_DIR / "d10_max_weight_check.csv",
        OUTPUT_DIR / "cumulative_underperformance.svg",
        OUTPUT_DIR / "cumulative_underperformance.png",
        OUTPUT_DIR / "final_judgement_draft.md",
    ]:
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
