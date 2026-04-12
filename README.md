# IO Electrical Validation Results Analysis

Automated analysis tool for IO Electrical Validation test results with pass/fail criteria vs specification limits. Generates plots and PowerPoint-compatible reports.

## Features

- **Multi-flow analysis**: Loads and analyzes data from Flow1, Flow2 (or any number of flows)
- **Pass/Fail vs Spec**: Automatic comparison of measured values against spec limits (min/max)
- **Statistical analysis**: Mean, Std, Min, Max, Cpk for each IO parameter
- **Plot generation**: 6 types of publication-quality plots:
  - Pass/Fail summary bar charts
  - Parameter vs Spec box plots
  - Distribution histograms with spec overlays
  - Cross-flow comparison charts
  - Cpk (Process Capability) bar charts
  - Per-DUT scatter plots with pass/fail coloring
- **PowerPoint report**: Auto-generated `.pptx` with all plots, summary tables, and analysis comments
- **CSV report**: Tabular summary of all results
- **Flexible data loading**: Supports CSV and Excel files, auto-detects wide/long format
- **Configurable**: Spec limits, plot settings, and report templates are all customizable

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Generate sample data (optional, for testing)

```bash
python generate_sample_data.py
```

### 3. Run the analysis

```bash
# Using sample data
python main.py --data-path ./sample_data --output ./output

# Using your own data path
python main.py --data-path "/path/to/your/Results" --output ./my_report

# With custom flow names and verbose logging
python main.py --data-path ./data --flows Flow1 Flow2 --output ./report -v
```

### 4. View results

The output directory will contain:
- `IO_Validation_Report.pptx` – PowerPoint report with all plots and analysis
- `analysis_results.csv` – Summary table of all results
- `plots/` – Individual plot images (PNG)

## Data Format

Place your test data files (`.csv` or `.xlsx`) inside flow subdirectories:

```
data_path/
├── Flow1/
│   ├── Flow1_IO_Results.csv
│   └── additional_results.xlsx
└── Flow2/
    ├── Flow2_IO_Results.csv
    └── more_data.csv
```

### Expected CSV columns

| Column | Description | Required |
|--------|------------|----------|
| `Parameter` | IO parameter name (e.g., VOH, VOL) | ✅ |
| `Value` | Measured value | ✅ |
| `Unit` | Unit of measurement (V, mA, ns, etc.) | Optional |
| `DUT_ID` | Device Under Test identifier | Optional |
| `Spec_Min` | Lower specification limit | Optional* |
| `Spec_Max` | Upper specification limit | Optional* |
| `Test_Condition` | Test condition description | Optional |

*If spec limits are not in the data files, default limits from `config.py` are used.

The tool auto-detects common column name variations (e.g., "Measured", "Result", "Sample", "LSL", "USL").

## Project Structure

```
├── main.py                          # CLI entry point
├── generate_sample_data.py          # Sample data generator
├── requirements.txt                 # Python dependencies
├── io_analysis/
│   ├── __init__.py
│   ├── config.py                    # Configuration & spec limits
│   ├── data/
│   │   ├── models.py                # Data models (TestResult, ParameterStats, etc.)
│   │   └── loader.py                # CSV/Excel loader with auto-detection
│   ├── analysis/
│   │   └── analyzer.py              # Statistical analysis & pass/fail engine
│   ├── plotting/
│   │   └── plotter.py               # 6 plot types for visualization
│   └── reporting/
│       └── report_generator.py      # PowerPoint & CSV report generation
├── sample_data/                     # Sample test data
│   ├── Flow1/
│   └── Flow2/
└── tests/
    └── test_analysis.py             # Unit tests (25 tests)
```

## Customizing Spec Limits

Edit `io_analysis/config.py` to modify default spec limits:

```python
DEFAULT_SPEC_LIMITS = {
    "VOH": SpecLimit("VOH", "V", spec_min=2.4, spec_max=None),
    "VOL": SpecLimit("VOL", "V", spec_min=None, spec_max=0.4),
    # Add or modify parameters...
}
```

Or provide spec limits directly in your CSV/Excel files.

## CLI Options

```
python main.py [OPTIONS]

  --data-path, -d   Path to data directory (default: sample_data)
  --output, -o      Output directory (default: output)
  --flows, -f       Flow subdirectory names (default: Flow1 Flow2)
  --title, -t       Report title
  --verbose, -v     Enable verbose logging
```
