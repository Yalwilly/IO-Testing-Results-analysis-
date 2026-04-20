"""
IO Testing Results Analysis — GUI Launcher
Run this file directly or build to an exe with build_exe.bat
"""

import logging
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ── make sure the package is importable when running from source ──────────────
_ROOT = Path(__file__).parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from io_analysis.plotting.plotter import TEST_SECTION_ORDER

# ── colour palette ────────────────────────────────────────────────────────────
CLR_BG      = "#1e2530"
CLR_PANEL   = "#252d3a"
CLR_BORDER  = "#2e3a4a"
CLR_ACCENT  = "#3498db"
CLR_SUCCESS = "#2ecc71"
CLR_WARN    = "#e67e22"
CLR_FG      = "#ecf0f1"
CLR_FG2     = "#95a5a6"
CLR_INPUT   = "#2c3a4a"
CLR_BTN     = "#2980b9"
CLR_BTN_HOV = "#1a6699"
CLR_LOG_BG  = "#141b24"
CLR_LOG_FG  = "#a8d8a8"


class QueueHandler(logging.Handler):
    """Send log records to a queue so the GUI thread can read them."""
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("IO Testing Results Analysis")
        self.configure(bg=CLR_BG)
        self.resizable(True, True)
        self.minsize(820, 700)

        self._report_path = None  # type: Optional[Path]
        self._pptx_path   = None  # type: Optional[Path]
        self._log_queue: queue.Queue = queue.Queue()
        self._running = False

        self._build_ui()
        self._setup_logging()
        self._poll_log()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg="#17202b", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="IO Testing Results Analysis",
                 font=("Arial", 18, "bold"), bg="#17202b", fg=CLR_FG
                 ).pack(side="left", padx=28)
        tk.Label(hdr, text="Intel IO Electrical Validation",
                 font=("Arial", 10), bg="#17202b", fg=CLR_FG2
                 ).pack(side="left", padx=4)

        # ── main content (scrollable) ─────────────────────────────────────────
        outer = tk.Frame(self, bg=CLR_BG)
        outer.pack(fill="both", expand=True, padx=20, pady=12)

        # Left column
        left = tk.Frame(outer, bg=CLR_BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self._build_paths(left)
        self._build_tests(left)
        self._build_actions(left)

        # Right column — log
        right = tk.Frame(outer, bg=CLR_BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_log(right)

    def _section(self, parent, title):
        """Titled card panel."""
        frame = tk.Frame(parent, bg=CLR_PANEL, bd=0,
                         highlightthickness=1, highlightbackground=CLR_BORDER)
        frame.pack(fill="x", pady=(0, 10))
        tk.Label(frame, text=f"  {title}", font=("Arial", 10, "bold"),
                 bg=CLR_BORDER, fg=CLR_FG, anchor="w", pady=5
                 ).pack(fill="x")
        inner = tk.Frame(frame, bg=CLR_PANEL, padx=14, pady=10)
        inner.pack(fill="x")
        return inner

    def _build_paths(self, parent):
        inner = self._section(parent, "Data & Output Paths")

        def path_row(lbl, var, browse_fn, row):
            tk.Label(inner, text=lbl, bg=CLR_PANEL, fg=CLR_FG2,
                     font=("Arial", 9), anchor="w", width=12
                     ).grid(row=row, column=0, sticky="w", pady=4)
            ent = tk.Entry(inner, textvariable=var, bg=CLR_INPUT, fg=CLR_FG,
                           insertbackground=CLR_FG, relief="flat",
                           font=("Arial", 9), width=44)
            ent.grid(row=row, column=1, sticky="ew", padx=(6, 6))
            btn = tk.Button(inner, text="Browse…", command=browse_fn,
                            bg=CLR_BTN, fg=CLR_FG, relief="flat",
                            font=("Arial", 9), padx=6,
                            activebackground=CLR_BTN_HOV, activeforeground=CLR_FG,
                            cursor="hand2")
            btn.grid(row=row, column=2, pady=4)

        inner.columnconfigure(1, weight=1)

        self._var_data   = tk.StringVar(value="")
        self._var_output = tk.StringVar(value="output_real")
        self._var_title  = tk.StringVar(value="IO Electrical Validation Results")

        path_row("Data path:",   self._var_data,   self._browse_data,   0)
        path_row("Output path:", self._var_output, self._browse_output, 1)

        tk.Label(inner, text="Report title:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9), anchor="w", width=12
                 ).grid(row=2, column=0, sticky="w", pady=4)
        tk.Entry(inner, textvariable=self._var_title,
                 bg=CLR_INPUT, fg=CLR_FG, insertbackground=CLR_FG,
                 relief="flat", font=("Arial", 9)
                 ).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=4)

    def _build_tests(self, parent):
        inner = self._section(parent, "Tests to Include")

        self._test_vars: dict[str, tk.BooleanVar] = {}
        cols = 2
        for idx, test in enumerate(TEST_SECTION_ORDER):
            var = tk.BooleanVar(value=True)
            self._test_vars[test] = var
            row, col = divmod(idx, cols)
            cb = tk.Checkbutton(
                inner, text=test, variable=var,
                bg=CLR_PANEL, fg=CLR_FG, selectcolor=CLR_ACCENT,
                activebackground=CLR_PANEL, activeforeground=CLR_FG,
                font=("Arial", 9), anchor="w", cursor="hand2",
            )
            cb.grid(row=row, column=col, sticky="w", padx=8, pady=2)

        # Select / Deselect all
        btn_row = tk.Frame(inner, bg=CLR_PANEL)
        btn_row.grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Button(btn_row, text="Select All",   command=self._select_all,
                  bg=CLR_BORDER, fg=CLR_FG, relief="flat", font=("Arial", 8),
                  padx=6, cursor="hand2").pack(side="left", padx=(0, 6))
        tk.Button(btn_row, text="Deselect All", command=self._deselect_all,
                  bg=CLR_BORDER, fg=CLR_FG, relief="flat", font=("Arial", 8),
                  padx=6, cursor="hand2").pack(side="left")

        # Output format options
        fmt_row = tk.Frame(inner, bg=CLR_PANEL)
        fmt_row.grid(row=11, column=0, columnspan=2, sticky="w", pady=(14, 0))
        tk.Label(fmt_row, text="Output formats:",
                 bg=CLR_PANEL, fg=CLR_FG2, font=("Arial", 9)
                 ).pack(side="left", padx=(0, 10))
        self._var_pptx = tk.BooleanVar(value=True)
        tk.Checkbutton(
            fmt_row, text="PowerPoint (.pptx)",
            variable=self._var_pptx,
            bg=CLR_PANEL, fg=CLR_FG, selectcolor=CLR_ACCENT,
            activebackground=CLR_PANEL, activeforeground=CLR_FG,
            font=("Arial", 9), cursor="hand2",
        ).pack(side="left", padx=(0, 12))
        self._var_html = tk.BooleanVar(value=True)
        tk.Checkbutton(
            fmt_row, text="HTML report",
            variable=self._var_html,
            bg=CLR_PANEL, fg=CLR_FG, selectcolor=CLR_ACCENT,
            activebackground=CLR_PANEL, activeforeground=CLR_FG,
            font=("Arial", 9), cursor="hand2",
        ).pack(side="left")

    def _build_actions(self, parent):
        inner = self._section(parent, "Run")

        # Progress bar
        self._progress = ttk.Progressbar(inner, mode="indeterminate", length=320)
        self._progress.pack(fill="x", pady=(0, 8))

        # Status label
        self._lbl_status = tk.Label(inner, text="Ready", bg=CLR_PANEL,
                                    fg=CLR_FG2, font=("Arial", 9))
        self._lbl_status.pack(anchor="w")

        btn_row = tk.Frame(inner, bg=CLR_PANEL)
        btn_row.pack(fill="x", pady=(10, 0))

        self._btn_start = tk.Button(
            btn_row, text="▶  Start Analysis",
            command=self._start,
            bg=CLR_SUCCESS, fg="#fff", relief="flat",
            font=("Arial", 11, "bold"), padx=18, pady=8,
            activebackground="#27ae60", activeforeground="#fff",
            cursor="hand2",
        )
        self._btn_start.pack(side="left", padx=(0, 10))

        self._btn_open = tk.Button(
            btn_row, text="🌐  Open HTML",
            command=self._open_report,
            bg=CLR_BORDER, fg=CLR_FG, relief="flat",
            font=("Arial", 10), padx=12, pady=8,
            state="disabled",
            activebackground=CLR_BTN, activeforeground=CLR_FG,
            cursor="hand2",
        )
        self._btn_open.pack(side="left", padx=(0, 6))

        self._btn_open_pptx = tk.Button(
            btn_row, text="📊  Open PPTX",
            command=self._open_pptx,
            bg=CLR_BORDER, fg=CLR_FG, relief="flat",
            font=("Arial", 10), padx=12, pady=8,
            state="disabled",
            activebackground=CLR_BTN, activeforeground=CLR_FG,
            cursor="hand2",
        )
        self._btn_open_pptx.pack(side="left")

    def _build_log(self, parent):
        tk.Label(parent, text="Output Log", font=("Arial", 10, "bold"),
                 bg=CLR_BG, fg=CLR_FG2, anchor="w"
                 ).pack(fill="x", pady=(0, 4))
        self._log_widget = scrolledtext.ScrolledText(
            parent, bg=CLR_LOG_BG, fg=CLR_LOG_FG,
            font=("Consolas", 8), relief="flat",
            wrap="word", state="disabled",
        )
        self._log_widget.pack(fill="both", expand=True)

        # Tag colours
        self._log_widget.tag_config("INFO",    foreground="#a8d8a8")
        self._log_widget.tag_config("WARNING", foreground="#f0c040")
        self._log_widget.tag_config("ERROR",   foreground="#e87070")
        self._log_widget.tag_config("DEBUG",   foreground="#7090a0")

        tk.Button(parent, text="Clear Log", command=self._clear_log,
                  bg=CLR_BORDER, fg=CLR_FG2, relief="flat",
                  font=("Arial", 8), cursor="hand2"
                  ).pack(anchor="e", pady=(4, 0))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _browse_data(self):
        d = filedialog.askdirectory(title="Select Data Root Directory")
        if d:
            self._var_data.set(d)

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select Output Directory")
        if d:
            self._var_output.set(d)

    def _select_all(self):
        for v in self._test_vars.values():
            v.set(True)

    def _deselect_all(self):
        for v in self._test_vars.values():
            v.set(False)

    def _open_pptx(self):
        if self._pptx_path and self._pptx_path.exists():
            import subprocess, os
            os.startfile(str(self._pptx_path))

    def _open_report(self):
        if self._report_path and self._report_path.exists():
            webbrowser.open(self._report_path.as_uri())

    def _clear_log(self):
        self._log_widget.configure(state="normal")
        self._log_widget.delete("1.0", "end")
        self._log_widget.configure(state="disabled")

    # ── logging ───────────────────────────────────────────────────────────────

    def _setup_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        handler = QueueHandler(self._log_queue)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))
        root_logger.addHandler(handler)

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _append_log(self, msg: str):
        self._log_widget.configure(state="normal")
        lvl = "INFO"
        if "[WARNING]" in msg:
            lvl = "WARNING"
        elif "[ERROR]" in msg:
            lvl = "ERROR"
        elif "[DEBUG]" in msg:
            lvl = "DEBUG"
        self._log_widget.insert("end", msg + "\n", lvl)
        self._log_widget.see("end")
        self._log_widget.configure(state="disabled")

    def _set_status(self, msg, color=CLR_FG2):
        self._lbl_status.configure(text=msg, fg=color)

    # ── analysis runner ───────────────────────────────────────────────────────

    def _start(self):
        data_path_str = self._var_data.get().strip()
        output_str    = self._var_output.get().strip() or "output"
        title_str     = self._var_title.get().strip() or "IO Electrical Validation Results"

        if not data_path_str:
            messagebox.showerror("Missing Input", "Please select a Data Path.")
            return

        selected = {t for t, v in self._test_vars.items() if v.get()}
        if not selected:
            messagebox.showerror("No Tests Selected",
                                 "Please select at least one test to include.")
            return

        self._btn_start.configure(state="disabled")
        self._btn_open.configure(state="disabled")
        self._btn_open_pptx.configure(state="disabled")
        self._report_path = None
        self._pptx_path   = None
        self._running = True
        self._progress.start(12)
        self._set_status("Running analysis…", CLR_WARN)
        self._clear_log()

        threading.Thread(
            target=self._run_pipeline,
            args=(data_path_str, output_str, title_str, selected,
                  self._var_pptx.get()),
            daemon=True,
        ).start()

    def _run_pipeline(self, data_path_str, output_str, title_str,
                      selected_tests, gen_pptx=True):
        logger = logging.getLogger(__name__)
        try:
            from io_analysis.config import Config
            from io_analysis.data.loader import load_all_flows
            from io_analysis.analysis.analyzer import run_analysis
            from io_analysis.plotting.plotter import generate_all_plots
            from io_analysis.reporting.report_generator import generate_report

            data_path   = Path(data_path_str)
            output_path = Path(output_str)

            if not data_path.exists():
                raise FileNotFoundError(f"Data path not found: {data_path}")

            config = Config(data_path=data_path, output_path=output_path)
            config.report.title = title_str

            logger.info("=" * 50)
            logger.info("Step 1 — Loading data")
            flows = load_all_flows(config)
            if not flows:
                raise RuntimeError(
                    "No data loaded. Check data path and file structure."
                )
            for name, fd in flows.items():
                logger.info(
                    f"  {name}: {fd.record_count} measurements, "
                    f"{len(fd.dut_ids)} DUTs"
                )

            logger.info("Step 2 — Analysing")
            result = run_analysis(flows, config)
            logger.info(f"  Pass rate: {result.total_pass_rate:.1f}%")

            logger.info("Step 3 — Generating plots")
            plot_paths = generate_all_plots(
                result, config, selected_tests=selected_tests
            )

            logger.info("Step 4 — Building report")
            reports = generate_report(
                result, plot_paths, config,
                selected_tests=selected_tests,
                generate_pptx=gen_pptx,
            )

            html_path = reports.get("html")
            self._report_path = html_path
            pptx_path = reports.get("pptx")
            if pptx_path:
                self._pptx_path = pptx_path
                logger.info(f"PPTX saved: {pptx_path}")
            logger.info(f"Report saved: {html_path}")
            logger.info("=" * 50)
            logger.info("Done!")

            self.after(0, self._on_success, str(html_path))

        except Exception as exc:
            logger.error(f"Analysis failed: {exc}", exc_info=True)
            self.after(0, self._on_error, str(exc))

    def _on_success(self, report_path_str):
        self._progress.stop()
        self._running = False
        self._btn_start.configure(state="normal")
        self._btn_open.configure(state="normal")
        if self._pptx_path:
            self._btn_open_pptx.configure(state="normal")
        self._set_status(f"Complete — {report_path_str}", CLR_SUCCESS)

    def _on_error(self, msg):
        self._progress.stop()
        self._running = False
        self._btn_start.configure(state="normal")
        self._set_status(f"Error: {msg}", "#e74c3c")
        messagebox.showerror("Analysis Error", msg)


def main():
    # On Windows, prevent the console window from appearing when frozen
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
