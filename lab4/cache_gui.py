import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os

from cache_engine import CacheSimulator, CacheStats

TRACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trace')

TRACE_FILES = {
    "085.gcc.din": "GCC Compiler",
    "022.li.din": "Lisp Interpreter",
    "047.tomcatv.din": "Tomcatv (Vector)",
    "078.swm256.din": "Swim (Shallow Water)",
}

CACHE_SIZES = ["8KB", "16KB", "32KB", "64KB"]
ASSOCIATIVITIES = ["1 (Direct)", "2", "4", "8"]
BLOCK_SIZES = ["16B", "32B", "64B", "128B"]

class CacheGUI:

    def __init__(self):
        self.sim = CacheSimulator()
        self.batch_results = []
        self.sim_thread = None
        self.sim_running = False

        self.root = tk.Tk()
        self.root.title("Cache Simulator - Module A (Self-Designed)")
        self.root.geometry("1200x850")
        self.root.configure(bg='#f0f0f0')

        self._build_menu()
        self._build_layout()

        self.root.mainloop()

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Select Trace File...", command=self._select_trace)
        file_menu.add_command(label="Save Results...", command=self._save_results)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def _build_layout(self):

        config_frame = ttk.LabelFrame(self.root, text="Cache Configuration")
        config_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        row1 = ttk.Frame(config_frame)
        row1.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(row1, text="Cache Size:").pack(side=tk.LEFT, padx=(0, 5))
        self.size_var = tk.StringVar(value="16KB")
        size_cb = ttk.Combobox(row1, textvariable=self.size_var, values=CACHE_SIZES,
                               state='readonly', width=10)
        size_cb.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row1, text="Associativity:").pack(side=tk.LEFT, padx=(0, 5))
        self.assoc_var = tk.StringVar(value="4")
        assoc_cb = ttk.Combobox(row1, textvariable=self.assoc_var, values=ASSOCIATIVITIES,
                                state='readonly', width=12)
        assoc_cb.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row1, text="Block Size:").pack(side=tk.LEFT, padx=(0, 5))
        self.block_var = tk.StringVar(value="32B")
        block_cb = ttk.Combobox(row1, textvariable=self.block_var, values=BLOCK_SIZES,
                                state='readonly', width=10)
        block_cb.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row1, text="Replacement: LRU").pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(row1, text="Write Policy: Write-Allocate").pack(side=tk.LEFT)

        row2 = ttk.Frame(config_frame)
        row2.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(row2, text="Trace File:").pack(side=tk.LEFT, padx=(0, 5))
        self.trace_var = tk.StringVar(value="085.gcc.din")
        trace_cb = ttk.Combobox(row2, textvariable=self.trace_var,
                                values=list(TRACE_FILES.keys()), state='readonly', width=25)
        trace_cb.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row2, text="Max Lines (-1=all):").pack(side=tk.LEFT, padx=(0, 5))
        self.max_lines_var = tk.StringVar(value="100000")
        ttk.Entry(row2, textvariable=self.max_lines_var, width=10).pack(side=tk.LEFT, padx=(0, 20))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(row2, variable=self.progress_var,
                                            maximum=100, length=200)
        self.progress_bar.pack(side=tk.LEFT, padx=(0, 10))

        self.progress_label = ttk.Label(row2, text="")
        self.progress_label.pack(side=tk.LEFT)

        ttk.Button(row2, text="Run Single", command=self._run_single).pack(
            side=tk.RIGHT, padx=2)
        ttk.Button(row2, text="Run Batch All", command=self._run_batch).pack(
            side=tk.RIGHT, padx=2)
        ttk.Button(row2, text="Stop", command=self._stop_sim).pack(
            side=tk.RIGHT, padx=2)

        row3 = ttk.Frame(config_frame)
        row3.pack(fill=tk.X, padx=10, pady=2)
        self.geo_label = ttk.Label(row3, text="", font=('Consolas', 9))
        self.geo_label.pack(side=tk.LEFT)
        self._update_geo_label()

        for cb in [size_cb, assoc_cb, block_cb]:
            cb.bind('<<ComboboxSelected>>', lambda e: self._update_geo_label())

        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        result_frame = ttk.Frame(nb)
        nb.add(result_frame, text="Single Run Results")

        self.stat_text = scrolledtext.ScrolledText(result_frame, font=('Consolas', 10),
                                                     height=12, wrap=tk.WORD)
        self.stat_text.pack(fill=tk.X, padx=5, pady=5)

        chart_frame = ttk.LabelFrame(result_frame, text="Hit Rate Visualization")
        chart_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chart_canvas = tk.Canvas(chart_frame, height=150, bg='white')
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        batch_frame = ttk.Frame(nb)
        nb.add(batch_frame, text="Batch Comparison")

        batch_columns = ('trace', 'cache_size', 'assoc', 'block', 'accesses',
                        'hit_rate', 'miss_rate', 'read_hit', 'write_hit',
                        'replacements', 'writebacks')
        self.batch_tree = ttk.Treeview(batch_frame, columns=batch_columns,
                                        show='headings', height=15)
        batch_headings = ['Trace', 'Cache', 'Assoc', 'Block', 'Accesses',
                         'Hit Rate', 'Miss Rate', 'Read Hit%', 'Write Hit%',
                         'Replacements', 'Writebacks']
        batch_widths = [130, 70, 60, 60, 90, 80, 80, 80, 80, 100, 90]
        for col, h, w in zip(batch_columns, batch_headings, batch_widths):
            self.batch_tree.heading(col, text=h)
            self.batch_tree.column(col, width=w, anchor='center')
        self.batch_tree.column('trace', anchor='w')

        batch_scroll_y = ttk.Scrollbar(batch_frame, orient=tk.VERTICAL,
                                       command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=batch_scroll_y.set)
        self.batch_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        batch_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        batch_btn_frame = ttk.Frame(batch_frame)
        batch_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(batch_btn_frame, text="Export Batch CSV",
                   command=self._export_batch_csv).pack(side=tk.RIGHT)

        log_frame = ttk.Frame(nb)
        nb.add(log_frame, text="Execution Log")
        self.log_text = scrolledtext.ScrolledText(log_frame, font=('Consolas', 9),
                                                   wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _parse_config(self):

        cache_size = int(self.size_var.get().replace('KB', '')) * 1024
        assoc_str = self.assoc_var.get().split()[0]
        associativity = int(assoc_str)
        block_size = int(self.block_var.get().replace('B', ''))
        return cache_size, associativity, block_size

    def _update_geo_label(self):
        cache_size, associativity, block_size = self._parse_config()
        num_sets = cache_size // (associativity * block_size)
        block_offset = CacheSimulator._log2(block_size)
        index_bits = CacheSimulator._log2(num_sets) if num_sets > 0 else 0
        tag_bits = 32 - index_bits - block_offset
        text = (f"Geometry: {num_sets} sets × {associativity} ways × {block_size}B = {cache_size//1024}KB | "
                f"Address: [Tag:{tag_bits}|Index:{index_bits}|Offset:{block_offset}]")
        self.geo_label.config(text=text)

    def _get_trace_path(self) -> str:

        trace_name = self.trace_var.get()
        path = os.path.join(TRACE_DIR, trace_name)
        if not os.path.exists(path):

            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), trace_name)
        return path

    def _select_trace(self):
        filepath = filedialog.askopenfilename(
            title="Select Trace File",
            filetypes=[("DIN files", "*.din"), ("All files", "*.*")]
        )
        if filepath:
            self.trace_var.set(os.path.basename(filepath))

    def _save_results(self):
        filepath = filedialog.asksaveasfilename(
            title="Save Results",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self.stat_text.get("1.0", tk.END))
                self._log(f"Results saved to {filepath}")
            except Exception as e:
                messagebox.showerror("Save Error", str(e))

    def _progress_callback(self, current, total):
        if total > 0:
            pct = (current / total) * 100
            self.progress_var.set(pct)
            self.progress_label.config(text=f"{current}/{total} ({pct:.1f}%)")
            self.root.update_idletasks()

    def _run_single(self):

        if self.sim_running:
            messagebox.showwarning("Running", "A simulation is already running.")
            return

        trace_path = self._get_trace_path()
        if not os.path.exists(trace_path):
            messagebox.showerror("Error", f"Trace file not found: {trace_path}")
            return

        cache_size, associativity, block_size = self._parse_config()
        try:
            max_lines = int(self.max_lines_var.get())
            if max_lines == -1:
                max_lines = -1
        except ValueError:
            max_lines = -1

        self.progress_var.set(0)
        self.progress_label.config(text="Running...")
        self._log(f"Starting: {cache_size//1024}KB, {associativity}-way, {block_size}B, trace={os.path.basename(trace_path)}")

        self.sim_running = True

        def run_thread():
            try:
                self.sim.reconfigure(cache_size, associativity, block_size)
                stats = self.sim.run_trace(trace_path, max_lines=max_lines,
                                          progress_callback=self._progress_callback)

                self.root.after(0, lambda: self._display_results(stats))
            except Exception as e:
                self.root.after(0, lambda: self._on_error(str(e)))

        thread = threading.Thread(target=run_thread, daemon=True)
        thread.start()

    def _display_results(self, stats: CacheStats):

        self.sim_running = False
        self.progress_label.config(text="Done")
        self.progress_var.set(100)

        d = stats.to_dict()
        cache_size, assoc, block = self._parse_config()
        config = self.sim.get_config_description()

        text = f
        self.stat_text.delete("1.0", tk.END)
        self.stat_text.insert("1.0", text)

        self._draw_hitrate_chart(d)
        self._log(f"Simulation complete. Hit rate: {d['hit_rate']*100:.2f}%")

    def _draw_hitrate_chart(self, stats: dict):

        self.chart_canvas.delete("all")
        w = self.chart_canvas.winfo_width()
        h = self.chart_canvas.winfo_height()
        if w < 50:
            w = 500
        if h < 50:
            h = 150

        metrics = [
            ("Total Hit Rate", stats['hit_rate']),
            ("Read Hit Rate", stats.get('read_hit_rate', 0)),
            ("Write Hit Rate", stats.get('write_hit_rate', 0)),
        ]
        bar_w = (w - 80) // len(metrics) - 20
        x_start = 60
        max_val = 1.0

        for i, (label, val) in enumerate(metrics):
            x = x_start + i * (bar_w + 30)
            bar_h = int((val / max_val) * (h - 60))
            y = h - 40 - bar_h

            colors = ['#4CAF50', '#2196F3', '#FF9800']
            self.chart_canvas.create_rectangle(x, y, x + bar_w, h - 40,
                                               fill=colors[i], outline='')

            self.chart_canvas.create_text(x + bar_w // 2, y - 10,
                                         text=f"{val*100:.1f}%",
                                         font=('Arial', 10, 'bold'))

            self.chart_canvas.create_text(x + bar_w // 2, h - 20,
                                         text=label, font=('Arial', 9),
                                         anchor='n')

    def _run_batch(self):

        if self.sim_running:
            messagebox.showwarning("Running", "A simulation is already running.")
            return

        try:
            max_lines = int(self.max_lines_var.get())
            if max_lines < 0:
                max_lines = -1
        except ValueError:
            max_lines = 100000

        self.batch_results.clear()
        for item in self.batch_tree.get_children():
            self.batch_tree.delete(item)

        self._log(f"Starting batch simulation: 4 traces × 4 sizes × 4 assoc × 4 blocks = 256 runs")

        self.sim_running = True
        self.progress_var.set(0)

        def batch_thread():
            results = []
            total_runs = len(TRACE_FILES) * len(CACHE_SIZES) * len(ASSOCIATIVITIES) * len(BLOCK_SIZES)
            run_idx = 0

            for trace_name in sorted(TRACE_FILES.keys()):
                trace_path = os.path.join(TRACE_DIR, trace_name)
                if not os.path.exists(trace_path):
                    continue

                for size_str in CACHE_SIZES:
                    cache_size = int(size_str.replace('KB', '')) * 1024
                    for assoc_str in ASSOCIATIVITIES:
                        assoc = int(assoc_str.split()[0])
                        for block_str in BLOCK_SIZES:
                            block_size = int(block_str.replace('B', ''))

                            run_idx += 1
                            self.root.after(0, lambda ri=run_idx, tr=total_runs:
                                           self._update_batch_progress(ri, tr))

                            try:
                                sim = CacheSimulator(cache_size, assoc, block_size)
                                stats = sim.run_trace(trace_path, max_lines=max_lines)
                                d = stats.to_dict()
                                d['trace'] = trace_name
                                d['cache_size'] = size_str
                                d['associativity'] = assoc_str
                                d['block_size'] = block_str
                                results.append(d)
                                self._log(f"[{run_idx}/{total_runs}] {trace_name} {size_str} {assoc_str}-way {block_str}B → Hit: {d['hit_rate']*100:.2f}%")
                            except Exception as e:
                                self._log(f"[{run_idx}/{total_runs}] ERROR: {trace_name} {size_str} {assoc_str}-way {block_str}B → {e}")

            self.batch_results = results
            self.root.after(0, lambda: self._display_batch_results())

        thread = threading.Thread(target=batch_thread, daemon=True)
        thread.start()

    def _update_batch_progress(self, current, total):
        self.progress_var.set((current / total) * 100)
        self.progress_label.config(text=f"Batch: {current}/{total}")
        self.root.update_idletasks()

    def _display_batch_results(self):

        self.sim_running = False
        self.progress_label.config(text="Batch complete")
        self.progress_var.set(100)

        for item in self.batch_tree.get_children():
            self.batch_tree.delete(item)

        for r in self.batch_results:
            self.batch_tree.insert('', tk.END, values=(
                r['trace'],
                r['cache_size'],
                r['associativity'],
                r['block_size'],
                f"{r['total_accesses']:,}",
                f"{r['hit_rate']*100:.2f}%",
                f"{r['miss_rate']*100:.2f}%",
                f"{r['read_hit_rate']*100:.2f}%",
                f"{r['write_hit_rate']*100:.2f}%",
                f"{r['replacements']:,}",
                f"{r['writebacks']:,}",
            ))

        self._log(f"Batch complete: {len(self.batch_results)} results.")

    def _stop_sim(self):

        self.sim_running = False
        self._log("Simulation stop requested.")

    def _on_error(self, msg: str):
        self.sim_running = False
        self.progress_label.config(text="Error")
        messagebox.showerror("Simulation Error", msg)

    def _export_batch_csv(self):

        if not self.batch_results:
            messagebox.showwarning("No Data", "Run batch simulation first.")
            return

        filepath = filedialog.asksaveasfilename(
            title="Export Batch Results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not filepath:
            return

        import csv
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            if self.batch_results:
                fields = ['trace', 'cache_size', 'associativity', 'block_size',
                         'total_accesses', 'hit_rate', 'miss_rate', 'read_hit_rate',
                         'write_hit_rate', 'reads', 'writes', 'instruction_fetches',
                         'read_hits', 'read_misses', 'write_hits', 'write_misses',
                         'instruction_hits', 'instruction_misses', 'replacements', 'writebacks']
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(self.batch_results)

        self._log(f"Batch results exported to {filepath}")
        messagebox.showinfo("Export", f"Results saved to {filepath}")

    def _log(self, msg: str):

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + '\n')
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

if __name__ == '__main__':
    CacheGUI()
