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
        self.minsize(920, 780)
        self.geometry("1200x860")

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

        # ── main content ─────────────────────────────────────────────────────
        # Layout:
        #   top_frame  ─┬─ left col (scrollable): Paths + Tests
        #               └─ right col:             Options + Run
        #   log_frame  — full-width log at the bottom

        top_frame = tk.Frame(self, bg=CLR_BG)
        top_frame.pack(fill="both", expand=True, padx=20, pady=(12, 0))
        # ── LEFT col — scrollable (Paths + Tests) ────────────────────────────
        left_outer = tk.Frame(top_frame, bg=CLR_BG)
        left_outer.pack(side="left", fill="both", expand=True, padx=(0, 10))

        left_canvas = tk.Canvas(left_outer, bg=CLR_BG, highlightthickness=0)
        left_scroll  = tk.Scrollbar(left_outer, orient="vertical",
                                    command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        left = tk.Frame(left_canvas, bg=CLR_BG)
        left_win = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_configure(event):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        def _on_canvas_resize(event):
            left_canvas.itemconfig(left_win, width=event.width)
        left.bind("<Configure>", _on_left_configure)
        left_canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        left_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._build_paths(left)
        self._build_tests(left)

        # ── RIGHT col — Options + Run ─────────────────────────────────────────
        right_top = tk.Frame(top_frame, bg=CLR_BG, width=420)
        right_top.pack(side="left", fill="both", padx=(0, 0))
        right_top.pack_propagate(False)

        self._build_options(right_top)
        self._build_actions(right_top)

        # ── BOTTOM — full-width log ───────────────────────────────────────────
        log_frame = tk.Frame(self, bg=CLR_BG)
        log_frame.pack(fill="both", expand=False, padx=20, pady=(8, 12))
        log_frame.configure(height=220)
        log_frame.pack_propagate(False)
        self._build_log(log_frame)

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

        self._var_subtitle = tk.StringVar(value="Pass/Fail Analysis vs Specification")
        tk.Label(inner, text="Subtitle:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9), anchor="w", width=12
                 ).grid(row=3, column=0, sticky="w", pady=4)
        tk.Entry(inner, textvariable=self._var_subtitle,
                 bg=CLR_INPUT, fg=CLR_FG, insertbackground=CLR_FG,
                 relief="flat", font=("Arial", 9)
                 ).grid(row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=4)

        self._var_author = tk.StringVar(value="IO Validation Team")
        tk.Label(inner, text="Author:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9), anchor="w", width=12
                 ).grid(row=4, column=0, sticky="w", pady=4)
        tk.Entry(inner, textvariable=self._var_author,
                 bg=CLR_INPUT, fg=CLR_FG, insertbackground=CLR_FG,
                 relief="flat", font=("Arial", 9)
                 ).grid(row=4, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=4)

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

    def _build_options(self, parent):
        inner = self._section(parent, "Analysis & Plot Options")
        inner.columnconfigure(1, weight=1)

        # Exclude IOs
        self._var_exclude = tk.StringVar(value="BRI_DT")
        tk.Label(inner, text="Exclude IOs:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9), anchor="w", width=14
                 ).grid(row=0, column=0, sticky="w", pady=4)
        tk.Entry(inner, textvariable=self._var_exclude,
                 bg=CLR_INPUT, fg=CLR_FG, insertbackground=CLR_FG,
                 relief="flat", font=("Arial", 9)
                 ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=4)
        tk.Label(inner, text="comma-separated, e.g. BRI_DT,GPIO_1",
                 bg=CLR_PANEL, fg=CLR_FG2, font=("Arial", 8)
                 ).grid(row=1, column=1, sticky="w", padx=6)

        # Cpk threshold
        self._var_cpk = tk.StringVar(value="1.33")
        tk.Label(inner, text="Cpk threshold:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9), anchor="w", width=14
                 ).grid(row=2, column=0, sticky="w", pady=4)
        tk.Entry(inner, textvariable=self._var_cpk, width=8,
                 bg=CLR_INPUT, fg=CLR_FG, insertbackground=CLR_FG,
                 relief="flat", font=("Arial", 9)
                 ).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=4)

        # Spec lines
        self._var_show_spec  = tk.BooleanVar(value=True)
        self._var_spec_color = tk.StringVar(value="#ff6d00")

        spec_row = tk.Frame(inner, bg=CLR_PANEL)
        spec_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 4))
        tk.Label(spec_row, text="Spec lines:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9), width=14, anchor="w"
                 ).pack(side="left")
        tk.Checkbutton(spec_row, text="Show", variable=self._var_show_spec,
                       bg=CLR_PANEL, fg=CLR_FG, selectcolor=CLR_ACCENT,
                       activebackground=CLR_PANEL, activeforeground=CLR_FG,
                       font=("Arial", 9), cursor="hand2"
                       ).pack(side="left", padx=(0, 14))
        tk.Label(spec_row, text="Color:", bg=CLR_PANEL, fg=CLR_FG2,
                 font=("Arial", 9)).pack(side="left", padx=(0, 4))
        tk.Entry(spec_row, textvariable=self._var_spec_color, width=9,
                 bg=CLR_INPUT, fg=CLR_FG, insertbackground=CLR_FG,
                 relief="flat", font=("Arial", 9)
                 ).pack(side="left", padx=(0, 4))
        self._spec_swatch = tk.Label(spec_row, text="  ", bg="#ff6d00", width=3)
        self._spec_swatch.pack(side="left", padx=(0, 4))
        tk.Button(spec_row, text="Pick…", command=self._pick_spec_color,
                  bg=CLR_BORDER, fg=CLR_FG, relief="flat",
                  font=("Arial", 8), padx=4, cursor="hand2"
                  ).pack(side="left")
        self._var_spec_color.trace_add("write", self._update_spec_swatch)

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
            btn_row, text="\u25b6  Start Analysis",
            command=self._start,
            bg=CLR_SUCCESS, fg="#fff", relief="flat",
            font=("Arial", 11, "bold"), padx=18, pady=8,
            activebackground="#27ae60", activeforeground="#fff",
            cursor="hand2",
        )
        self._btn_start.pack(side="left", padx=(0, 10))

        self._btn_open = tk.Button(
            btn_row, text="\U0001f310  Open HTML",
            command=self._open_report,
            bg=CLR_BORDER, fg=CLR_FG, relief="flat",
            font=("Arial", 10), padx=12, pady=8,
            state="disabled",
            activebackground=CLR_BTN, activeforeground=CLR_FG,
            cursor="hand2",
        )
        self._btn_open.pack(side="left", padx=(0, 6))

        self._btn_open_pptx = tk.Button(
            btn_row, text="\U0001f4ca  Open PPTX",
            command=self._open_pptx,
            bg=CLR_BORDER, fg=CLR_FG, relief="flat",
            font=("Arial", 10), padx=12, pady=8,
            state="disabled",
            activebackground=CLR_BTN, activeforeground=CLR_FG,
            cursor="hand2",
        )
        self._btn_open_pptx.pack(side="left")

        # ── Open existing reports ─────────────────────────────────────────────
        inner2 = self._section(parent, "Open Existing Reports")

        browse_row = tk.Frame(inner2, bg=CLR_PANEL)
        browse_row.pack(fill="x")

        tk.Button(
            browse_row, text="\U0001f310  Browse HTML Report",
            command=self._browse_open_html,
            bg=CLR_BTN, fg=CLR_FG, relief="flat",
            font=("Arial", 10), padx=12, pady=7,
            activebackground=CLR_BTN_HOV, activeforeground=CLR_FG,
            cursor="hand2",
        ).pack(side="left", padx=(0, 10), pady=4)

        tk.Button(
            browse_row, text="\U0001f4ca  Browse PPTX Report",
            command=self._browse_open_pptx,
            bg=CLR_BTN, fg=CLR_FG, relief="flat",
            font=("Arial", 10), padx=12, pady=7,
            activebackground=CLR_BTN_HOV, activeforeground=CLR_FG,
            cursor="hand2",
        ).pack(side="left", pady=4)

        # Quick-open last output folder
        tk.Button(
            inner2, text="\U0001f4c2  Open Output Folder",
            command=self._open_output_folder,
            bg=CLR_BORDER, fg=CLR_FG2, relief="flat",
            font=("Arial", 9), padx=10, pady=5,
            activebackground=CLR_BTN, activeforeground=CLR_FG,
            cursor="hand2",
        ).pack(anchor="w", pady=(6, 0))

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

    def _pick_spec_color(self):
        from tkinter import colorchooser
        color = colorchooser.askcolor(
            color=self._var_spec_color.get(), title="Spec Line Colour")
        if color and color[1]:
            self._var_spec_color.set(color[1])

    def _update_spec_swatch(self, *_):
        try:
            self._spec_swatch.configure(bg=self._var_spec_color.get())
        except Exception:
            pass

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

    def _browse_open_html(self):
        p = filedialog.askopenfilename(
            title="Open HTML Report",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")],
            initialdir=self._var_output.get() or ".",
        )
        if p:
            webbrowser.open(Path(p).as_uri())

    def _browse_open_pptx(self):
        import os
        p = filedialog.askopenfilename(
            title="Open PPTX Report",
            filetypes=[("PowerPoint files", "*.pptx"), ("All files", "*.*")],
            initialdir=self._var_output.get() or ".",
        )
        if p:
            os.startfile(str(p))

    def _open_output_folder(self):
        import os
        folder = self._var_output.get().strip() or "."
        p = Path(folder)
        if p.exists():
            os.startfile(str(p))
        else:
            messagebox.showinfo("Folder Not Found",
                                f"Output folder does not exist yet:\n{p}")

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

        subtitle_str   = self._var_subtitle.get().strip()
        author_str     = self._var_author.get().strip()
        exclude_raw    = self._var_exclude.get().strip()
        exclude_ios    = [x.strip() for x in exclude_raw.split(",") if x.strip()] if exclude_raw else []
        try:
            cpk_threshold = float(self._var_cpk.get())
        except ValueError:
            cpk_threshold = 1.33

        threading.Thread(
            target=self._run_pipeline,
            args=(data_path_str, output_str, title_str, selected,
                  self._var_pptx.get()),
            kwargs=dict(
                subtitle_str=subtitle_str,
                author_str=author_str,
                exclude_ios=exclude_ios,
                cpk_threshold=cpk_threshold,
                show_spec_lines=self._var_show_spec.get(),
                spec_color=self._var_spec_color.get(),
            ),
            daemon=True,
        ).start()

    def _run_pipeline(self, data_path_str, output_str, title_str,
                      selected_tests, gen_pptx=True,
                      subtitle_str="", author_str="",
                      exclude_ios=None, cpk_threshold=1.33,
                      show_spec_lines=True, spec_color="#ff6d00"):
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
            if subtitle_str:
                config.report.subtitle = subtitle_str
            if author_str:
                config.report.author = author_str
            if exclude_ios is not None:
                config.excluded_ios = exclude_ios
            config.cpk_threshold       = cpk_threshold
            config.plot.show_spec_lines = show_spec_lines
            config.plot.spec_line_color = spec_color

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
