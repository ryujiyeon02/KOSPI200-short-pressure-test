from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = ROOT / "src"
OUTPUT_DIR = ROOT / "output" / "tables"
SUMMARY_CSV = OUTPUT_DIR / "proxy_test_summary.csv"
NOTEBOOK_PATH = CODE_DIR / "short_pressure_analysis.ipynb"
DOCX_PATH = OUTPUT_DIR / "final_judgement.docx"


def set_run_font(run, *, size: int | None = None, bold: bool | None = None, color: str | None = None) -> None:
    run.font.name = "Arial"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Arial")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Apple SD Gothic Neo")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)


def set_paragraph_spacing(paragraph, *, before: int = 0, after: int = 6, line_spacing: float = 1.1) -> None:
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = line_spacing


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, *, bold: bool = False, fill: str | None = None, align_center: bool = False) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if align_center else WD_ALIGN_PARAGRAPH.LEFT
    run = paragraph.add_run(text)
    set_run_font(run, size=9, bold=bold)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if fill:
        set_cell_shading(cell, fill)


def pct(value: float) -> str:
    return f"{value:.2%}"


def build_notebook() -> None:
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# KOSPI200 공매도 압력 가설 검정\n",
                "\n",
                "이 노트북은 3주차 과제 PDF의 레시피에 맞춰 공매도 압력비율을 만들고, 고압력 D10의 다음 달 EW/VW 언더퍼폼을 검정합니다.\n",
                "\n",
                "- 유니버스: 월말 KOSPI200 편입 종목\n",
                "- 주 프록시: 대차거래잔고수량\n",
                "- 보조 프록시: 차입공매도잔고수량\n",
                "- 분모: 시가총액(백만원) * 1,000,000 / 원종가\n",
                "- 수익률: 수정주가의 다음 달 수익률\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import sys\n",
                "import pandas as pd\n",
                "\n",
                "ROOT = Path.cwd().resolve()\n",
                "if ROOT.name in ('code', 'notebooks', 'src'):\n",
                "    ROOT = ROOT.parent\n",
                "CODE_DIR = ROOT / 'src'\n",
                "OUTPUT_DIR = ROOT / 'output' / 'tables'\n",
                "PROCESSED_DIR = ROOT / 'input' / 'processed_data'\n",
                "sys.path.insert(0, str(CODE_DIR))\n",
                "\n",
                "import short_pressure_analysis as spa\n",
                "\n",
                "ROOT\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 1. 데이터 수집 항목 확인\n",
                "\n",
                "원본 Excel에는 PDF가 요구한 가격, 유니버스, 시가총액, 대차잔고, 차입공매도잔고 항목이 들어 있습니다. 차입공매도잔고수량은 일별 행으로 들어 있으므로 월별 마지막 관측치를 사용합니다.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from openpyxl import load_workbook\n",
                "\n",
                "wb = load_workbook(spa.RAW_XLSX, read_only=True, data_only=True)\n",
                "meta = []\n",
                "for ws in wb.worksheets:\n",
                "    meta.append({\n",
                "        'sheet': ws.title,\n",
                "        'rows': ws.max_row,\n",
                "        'cols': ws.max_column,\n",
                "        'output_frequency': ws['B5'].value,\n",
                "        'start': ws['B8'].value,\n",
                "        'end': ws['C8'].value,\n",
                "        'item': ws['B13'].value,\n",
                "    })\n",
                "pd.DataFrame(meta)\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 2. 전처리와 검정 실행\n",
                "\n",
                "`short_pressure_analysis.py`는 다음 처리를 수행합니다.\n",
                "\n",
                "1. 시가총액을 원 단위로 환산한 뒤 원종가로 나누어 상장주식수를 역산합니다.\n",
                "2. 직전월 대비 역산 상장주식수가 3배 초과로 변하면 해당 종목-월을 결측 처리합니다.\n",
                "3. 잔고수량 / 상장주식수 * 100으로 압력비율을 만듭니다.\n",
                "4. 공매도 금지기간이 신호월 또는 다음 달 수익률 측정월에 걸리면 제외합니다.\n",
                "5. 매월 KOSPI200 내 압력비율 상위 10% D10의 다음 달 수익률에서 유니버스 평균을 차감합니다.\n",
                "6. EW/VW 시계열의 연환산 평균과 t값을 계산합니다.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# 결과 파일을 재생성합니다. 대용량 Excel을 읽기 때문에 약 40~60초 걸릴 수 있습니다.\n",
                "spa.main()\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 3. 필수 검정 결과\n",
                "\n",
                "PDF의 판정표 입력값인 `t_EW`, `t_VW`를 확인합니다.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "summary = pd.read_csv(OUTPUT_DIR / 'proxy_test_summary.csv')\n",
                "summary\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "monthly = pd.read_csv(OUTPUT_DIR / 'monthly_underperformance.csv')\n",
                "monthly.groupby('proxy')[['u_ew', 'u_vw', 'd10_max_weight']].agg(['count', 'mean', 'std', 'max'])\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 4. VW 집중도 점검\n",
                "\n",
                "D10의 단일종목 최대 비중이 50%를 넘는 달이 잦으면 VW 결과를 한 종목 베팅으로 해석해야 합니다.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "weight_check = pd.read_csv(OUTPUT_DIR / 'd10_max_weight_check.csv')\n",
                "weight_check.groupby('proxy').agg(\n",
                "    months=('period', 'count'),\n",
                "    months_over_50pct=('d10_max_weight', lambda s: (s > 0.5).sum()),\n",
                "    max_weight=('d10_max_weight', 'max'),\n",
                "    avg_weight=('d10_max_weight', 'mean'),\n",
                ")\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 5. 시각화\n",
                "\n",
                "아래 그래프는 고압력 D10 언더퍼폼 시계열을 누적한 참고 시각화입니다.\n",
                "\n",
                "![cumulative_underperformance](../output/cumulative_underperformance.png)\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 6. 판정\n",
                "\n",
                "주 프록시인 대차거래잔고수량 기준으로 EW는 비유의이고 VW는 유의합니다. PDF 판정표 기준으로는 `A+ - 대형주 주도`에 해당하므로, 본 표본과 프록시에서는 가설 A가 조건부로 더 타당하다고 해석합니다. 다만 대차잔고는 실제 공매도 포지션만이 아니라는 점과, 차입공매도잔고수량은 커버리지가 낮다는 점을 한계로 둡니다.\n",
            ],
        },
    ]
    for cell in cells:
        cell["id"] = uuid.uuid4().hex[:8]

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python (pydata)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK_PATH.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")


def build_docx() -> None:
    summary = pd.read_csv(SUMMARY_CSV)
    main = summary.loc[summary["proxy"].eq("대차거래잔고수량")].iloc[0]
    short = summary.loc[summary["proxy"].eq("차입공매도잔고수량")].iloc[0]

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Arial")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Apple SD Gothic Neo")
    normal.font.size = Pt(11)

    title = doc.add_paragraph()
    set_paragraph_spacing(title, after=8)
    run = title.add_run("KOSPI200 공매도 압력 가설 검정 판정문")
    set_run_font(run, size=18, bold=True, color="1F4D78")

    meta = doc.add_paragraph()
    set_paragraph_spacing(meta, after=10)
    run = meta.add_run("프록시: 대차거래잔고수량 | 분석기간: 2010-01~2026-05 | 판정: A+ - VW 중심 유의")
    set_run_font(run, size=10, color="555555")

    heading = doc.add_paragraph()
    set_paragraph_spacing(heading, before=8, after=4)
    run = heading.add_run("최종 판정")
    set_run_font(run, size=13, bold=True, color="2E74B5")

    paragraph = doc.add_paragraph()
    set_paragraph_spacing(paragraph, after=8, line_spacing=1.15)
    text = (
        f"본 분석은 KOSPI200 월별 편입 종목을 유니버스로 두고, 공매도 압력의 주 프록시로 "
        f"`대차거래잔고수량`을 사용했다. 대차잔고는 실제 순공매도 포지션만을 의미하지 않고 "
        f"헤지·차익거래·결제 목적 대차가 섞이는 광의 프록시라는 한계가 있지만, 장기간·전종목 "
        f"커버리지가 가능해 매월 20종목 D10을 안정적으로 구성할 수 있다. 공매도 전면금지 구간"
        f"(2011-08~2011-11, 2020-03~2021-04, 2023-11~2025-03)은 신호월 또는 다음 달 수익률 "
        f"측정월에 걸리면 제외했다. 주 프록시 기준 고압력 D10의 다음 달 언더퍼폼은 "
        f"EW 연환산 {pct(main['ann_mean_ew'])}, t_EW = {main['t_ew']:.2f}, "
        f"VW 연환산 {pct(main['ann_mean_vw'])}, t_VW = {main['t_vw']:.2f}로 나타났다. "
        f"EW는 비유의이나 VW는 t < -2로 유의하므로 PDF 판정표 기준 `A+ - 대형주 주도`에 해당한다. "
        f"따라서 본 표본과 프록시에서는 한국 KOSPI200에서 가설 A가 조건부로 더 타당하다고 판단한다. "
        f"단, 보조 프록시인 차입공매도잔고수량은 실제 공매도 포지션에 더 가깝지만 2016-06 이후 "
        f"월평균 보고 종목 수가 {short['avg_reported_balance_count']:.1f}개에 그쳐 검열·커버리지 한계가 크다."
    )
    run = paragraph.add_run(text)
    set_run_font(run, size=10)

    heading = doc.add_paragraph()
    set_paragraph_spacing(heading, before=8, after=4)
    run = heading.add_run("핵심 수치")
    set_run_font(run, size=13, bold=True, color="2E74B5")

    table = doc.add_table(rows=1, cols=7)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    headers = ["프록시", "기간", "N", "EW 연환산", "t_EW", "VW 연환산", "t_VW"]
    for idx, header in enumerate(headers):
        set_cell_text(table.rows[0].cells[idx], header, bold=True, fill="F2F4F7", align_center=True)

    for _, row in summary.iterrows():
        cells = table.add_row().cells
        values = [
            row["proxy"],
            f"{row['first_period']}~{row['last_period']}",
            str(int(row["n_months"])),
            pct(row["ann_mean_ew"]),
            f"{row['t_ew']:.2f}",
            pct(row["ann_mean_vw"]),
            f"{row['t_vw']:.2f}",
        ]
        for idx, value in enumerate(values):
            set_cell_text(cells[idx], value, align_center=idx >= 1)

    note = doc.add_paragraph()
    set_paragraph_spacing(note, before=8, after=0)
    run = note.add_run(
        f"VW 집중도 점검: 대차거래잔고수량 기준 D10 단일종목 최대 비중이 50%를 넘은 달은 "
        f"{int(main['months_d10_max_weight_over_50pct'])}개월이며, 최대값은 {main['max_d10_max_weight']:.2%}이다."
    )
    set_run_font(run, size=9, color="555555")

    DOCX_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(DOCX_PATH)


def main() -> None:
    build_notebook()
    build_docx()
    print(NOTEBOOK_PATH.relative_to(ROOT))
    print(DOCX_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
