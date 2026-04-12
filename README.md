# IO Testing Results Analysis

An OOP-based Python framework for analysing **Electrical Validation IO raw test data**, generating statistical summaries, interactive plots, and a self-contained HTML report.

---

## Features

| Area | What it does |
|---|---|
| **Data loading** | Reads CSV / Excel results files from `Flow1` and `Flow2` sub-folders; normalises 20+ column-name variants automatically |
| **Analysis** | Per-parameter statistics (mean, std, min/max, Cpk/Cp, skewness, kurtosis); cross-flow Welch's t-test; IQR outlier detection; Shapiro-Wilk normality test |
| **Plotting** | Yield bar chart, pass/fail heatmap, parameter distributions, box-plot comparison, Cpk bar chart, skewness chart, cross-flow scatter — all saved as PNG |
| **Reporting** | Styled HTML report with embedded KPI cards, all plots, yield table, statistics table, cross-flow comparison table, and outlier listing; CSV exports of every result DataFrame |
| **CLI** | Single `main.py` entry-point with `--path`, `--output`, `--flows`, `--cpk-target`, `--title`, `--dpi`, `-v` flags |

---

## Project Structure

```
IO-Testing-Results-analysis-/
├── main.py                          # CLI entry point
├── requirements.txt
├── io_analysis/
│   ├── config.py                    # AnalysisConfig dataclass + default IO parameter specs
│   ├── data/
│   │   ├── models.py                # TestRecord, ParameterSummary, FlowData
│   │   └── loader.py                # DataLoader – discovers, reads, normalises data
│   ├── analysis/
│   │   ├── statistics.py            # Cpk, Cp, t-test, outlier detection, normality
│   │   └── analyzer.py              # IOAnalyzer – orchestrates all analysis
│   ├── plotting/
│   │   └── plotter.py               # IOPlotter – 7 chart types
│   └── reporting/
│       ├── report_generator.py      # ReportGenerator – HTML + CSV export
│       └── templates/report.html    # Jinja2 HTML template
└── tests/
    ├── generate_sample_data.py      # Generates synthetic Flow1/Flow2 CSVs
    ├── sample_data/
    │   ├── Flow1/results_merged.csv
    │   └── Flow2/results_merged.csv
    ├── test_data_loader.py
    ├── test_analyzer.py
    └── test_plotter_reporter.py
```

---

## Quick Start

### 1 – Install dependencies

```bash
pip install -r requirements.txt
```

### 2 – Run with bundled sample data

```bash
python main.py
# Report written to: output/io_analysis_report.html
```

### 3 – Run against your real results folder

```bash
python main.py \
  --path "\\ger.corp.intel.com\ec\proj\ha\WCS\HDVI\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww09'26 PeP_SVT_TC_EFV IO_cross Skew Materials cycle\Results" \
  --output "C:\Reports\ww09_26" \
  --title "IO EFV Analysis – WW09'26 PeP SVT TC" \
  --cpk-target 1.67
```

The tool expects the `--path` folder to contain **`Flow1/`** and **`Flow2/`** sub-directories, each holding one or more `.csv` or `.xlsx` merged result files.

### 4 – CLI flags reference

| Flag | Default | Description |
|---|---|---|
| `--path` | `tests/sample_data` | Root folder containing Flow1 / Flow2 sub-folders |
| `--output` | `output` | Where plots and the report are written |
| `--flows` | `Flow1 Flow2` | Space-separated flow sub-folder names |
| `--cpk-target` | `1.33` | Minimum acceptable Cpk (colours in charts and report) |
| `--title` | IO Electrical Validation … | Title shown in the report header |
| `--dpi` | `150` | Plot image resolution |
| `-v` | off | Verbose (DEBUG) logging |

---

## Input File Format

Each merged result file must contain (at minimum) **Parameter** and **Value** columns.
The loader accepts many common column-name variants automatically:

| Canonical name | Accepted aliases |
|---|---|
| `parameter` | `Parameter`, `Test`, `param` |
| `value` | `Value`, `Result`, `Measured` |
| `dut_id` | `DUT`, `Device`, `DUT_ID` |
| `pin` | `Pin`, `PinName` |
| `condition` | `Condition`, `Corner` |
| `unit` | `Unit`, `UnitName` |
| `low_limit` | `LowLimit`, `LoLimit` |
| `high_limit` | `HighLimit`, `HiLimit` |
| `status` | `Status`, `PASS_FAIL`, `Pass/Fail` |

If limits are absent from the file, the built-in specification table (VOH, VOL, VIH, VIL, IOH, IOL, IIH, IIL, tpd, tr, tf, Skew) is used automatically.

---

## Running Tests

```bash
python -m pytest tests/ -v
```

38 tests covering the loader, statistical helpers, analyser, plotter, and report generator.

---

## Programmatic API

```python
from io_analysis import AnalysisConfig, DataLoader, IOAnalyzer, IOPlotter, ReportGenerator

config = AnalysisConfig(
    results_root="/path/to/Results",
    output_dir="./reports",
    cpk_target=1.67,
)
config.ensure_output_dir()

flows    = DataLoader(config).load_all()
analysis = IOAnalyzer(config).analyze(flows)
plots    = IOPlotter(config).plot_all(flows, analysis)
report   = ReportGenerator(config).generate(flows, analysis, plots)

print("Report:", report)
```
