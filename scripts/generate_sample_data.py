"""공개용 합성 샘플 데이터 생성기. 원본 DataGuide Excel의 시트 구조를 CSV로 흉내 낸 가짜 값이다."""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "sample_data"
OUT.mkdir(exist_ok=True)
rng = np.random.default_rng(3)
months = pd.period_range("2024-01", periods=12, freq="M")
codes = [f"A{100000 + i:06d}" for i in range(1, 41)]
idx = months.to_timestamp(how="end").strftime("%Y-%m-%d")

raw_close = pd.DataFrame(30000 * np.cumprod(1 + rng.normal(0.01, 0.08, (12, 40)), axis=0), index=idx, columns=codes).round(0)
adj_close = raw_close.copy()
shares = rng.integers(10_000_000, 500_000_000, 40)
mcap_mil = (raw_close * shares / 1e6).round(2)
universe = pd.DataFrame(np.where(rng.random((12, 40)) > 0.1, "Y", "N"), index=idx, columns=codes)
lending = (pd.DataFrame(rng.uniform(0, 0.08, (12, 40)), index=idx, columns=codes) * shares).round(0)
short = lending.where(rng.random((12, 40)) > 0.8) * 0.3  # 공시 임계값 이상만 보고되는 구조 흉내

for df, name in [(raw_close, "종가"), (adj_close, "수정주가"), (mcap_mil, "시가총액_백만원"), (universe, "코스피200구성여부"),
                 (lending, "대차거래잔고수량"), (short.round(0), "차입공매도잔고수량")]:
    df.index.name = "Date"
    df.to_csv(OUT / f"{name}_sample.csv", encoding="utf-8-sig")
print(sorted(p.name for p in OUT.glob("*.csv")))
