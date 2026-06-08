import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os

from cache_engine import CacheSimulator, CacheStats

TRACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trace')

TRACE_FILES = {
    "085.gcc.din": "GCC 编译器",
    "022.li.din": "Lisp 解释器",
    "047.tomcatv.din": "Tomcatv (向量)",
    "078.swm256.din": "Swim (浅水方程)",
}

CACHE_SIZES = ["8KB", "16KB", "32KB", "64KB"]
ASSOCIATIVITIES = ["1 (直接映射)", "2", "4", "8"]
BLOCK_SIZES = ["16B", "32B", "64B", "128B"]

RESULT_TEMPLATE = """======================================================================
  Cache 模拟结果
======================================================================
配置: {config}
Trace 文件: {trace_name}   处理行数: {lines}

  总访问: {total_accesses:>10,}    总命中: {total_hits:>10,}   命中率: {hit_rate:7.2%}
  读操作: {reads:>10,}    读命中: {read_hits:>10,}   读命中率: {read_hit_rate:7.2%}
  写操作: {writes:>10,}    写命中: {write_hits:>10,}   写命中率: {write_hit_rate:7.2%}
  取指令: {instruction_fetches:>10,}    取指命中: {instruction_hits:>10,}
  替换:   {replacements:>10,}    写回:   {writebacks:>10,}
======================================================================"""

class CacheGUI:

    def __init__(self):
        self.sim = CacheSimulator()
        self.batch_results = []
        self.sim_running = False

        self.root = tk.Tk()
        self.root.title("Cache模拟器")
        self.root.geometry("1050x680")
        self.root.configure(bg='#f5f5f5')

        self._build_layout()

        self.root.mainloop()

    def _build_layout(self):

        top_bar = ttk.Frame(self.root)
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 4))

        ttk.Label(top_bar, text="Cache 大小:").pack(side=tk.LEFT)
        self.size_var = tk.StringVar(value="16KB")
        ttk.Combobox(top_bar, textvariable=self.size_var, values=CACHE_SIZES,
                     state='readonly', width=6).pack(side=tk.LEFT, padx=(2, 12))

        ttk.Label(top_bar, text="相联度:").pack(side=tk.LEFT)
        self.assoc_var = tk.StringVar(value="4")
        ttk.Combobox(top_bar, textvariable=self.assoc_var, values=ASSOCIATIVITIES,
                     state='readonly', width=10).pack(side=tk.LEFT, padx=(2, 12))

        ttk.Label(top_bar, text="块大小:").pack(side=tk.LEFT)
        self.block_var = tk.StringVar(value="32B")
        ttk.Combobox(top_bar, textvariable=self.block_var, values=BLOCK_SIZES,
                     state='readonly', width=6).pack(side=tk.LEFT, padx=(2, 12))

        ttk.Separator(top_bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(top_bar, text="Trace:").pack(side=tk.LEFT)
        self.trace_var = tk.StringVar(value="085.gcc.din")
        ttk.Combobox(top_bar, textvariable=self.trace_var, values=list(TRACE_FILES.keys()),
                     state='readonly', width=18).pack(side=tk.LEFT, padx=(2, 12))

        ttk.Label(top_bar, text="行数:").pack(side=tk.LEFT)
        self.max_lines_var = tk.StringVar(value="100000")
        ttk.Entry(top_bar, textvariable=self.max_lines_var, width=8).pack(side=tk.LEFT, padx=(2, 12))

        self.geo_label = ttk.Label(top_bar, text="", font=('Consolas', 8), foreground='#888')
        self.geo_label.pack(side=tk.LEFT, padx=(10, 0))

        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(fill=tk.X, padx=10, pady=(2, 4))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(btn_bar, variable=self.progress_var, maximum=100, length=300)
        self.progress_bar.pack(side=tk.LEFT, padx=(0, 10))
        self.progress_label = ttk.Label(btn_bar, text="就绪", foreground='#888')
        self.progress_label.pack(side=tk.LEFT)

        ttk.Button(btn_bar, text="单次运行", command=self._run_single).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="批量运行", command=self._run_batch).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_bar, text="导出 CSV", command=self._export_batch_csv).pack(side=tk.RIGHT, padx=3)

        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

        left = ttk.Frame(main)
        self.stat_text = scrolledtext.ScrolledText(left, font=('Consolas', 10), wrap=tk.WORD,
                                                     state=tk.DISABLED)
        self.stat_text.pack(fill=tk.BOTH, expand=True)
        main.add(left, weight=3)

        right = ttk.Frame(main)
        chart_frame = ttk.LabelFrame(right, text="命中率")
        chart_frame.pack(fill=tk.X, padx=(0, 0), pady=(0, 4))
        self.chart_canvas = tk.Canvas(chart_frame, height=200, bg='white')
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        log_frame = ttk.LabelFrame(right, text="运行日志")
        self.log_text = scrolledtext.ScrolledText(log_frame, font=('Consolas', 8),
                                                   wrap=tk.WORD, state=tk.DISABLED, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        main.add(right, weight=1)

        self._update_geo_label()
        for cb in top_bar.winfo_children():
            if isinstance(cb, ttk.Combobox):
                cb.bind('<<ComboboxSelected>>', lambda e: self._update_geo_label())

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
        self.geo_label.config(
            text=f"  {num_sets}组×{associativity}路×{block_size}B | Tag:{tag_bits} Index:{index_bits} Offset:{block_offset}")

    def _get_trace_path(self):
        trace_name = self.trace_var.get()
        path = os.path.join(TRACE_DIR, trace_name)
        return path if os.path.exists(path) else os.path.join(os.path.dirname(os.path.abspath(__file__)), trace_name)

    def _save_results(self):
        filepath = filedialog.asksaveasfilename(
            title="保存结果", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self.stat_text.get("1.0", tk.END))
                self._log(f"结果已保存至 {filepath}")
            except Exception as e:
                messagebox.showerror("保存失败", str(e))

    def _progress_callback(self, current, total):
        if total > 0:
            self.progress_var.set((current / total) * 100)
            self.progress_label.config(text=f"{current}/{total} ({current/total*100:.1f}%)")
            self.root.update_idletasks()

    def _run_single(self):
        if self.sim_running:
            messagebox.showwarning("正在运行", "已有模拟正在运行中。")
            return
        trace_path = self._get_trace_path()
        if not os.path.exists(trace_path):
            messagebox.showerror("错误", f"Trace 文件未找到: {trace_path}")
            return
        cache_size, associativity, block_size = self._parse_config()
        try:
            max_lines = int(self.max_lines_var.get())
        except ValueError:
            max_lines = -1

        self.progress_var.set(0)
        self.progress_label.config(text="运行中...")
        self.sim_running = True

        def run_thread():
            try:
                self.sim.reconfigure(cache_size, associativity, block_size)
                stats = self.sim.run_trace(trace_path, max_lines=max_lines,
                                          progress_callback=self._progress_callback)
                self.root.after(0, lambda: self._display_results(stats))
            except Exception as e:
                self.root.after(0, lambda: self._on_error(str(e)))
        threading.Thread(target=run_thread, daemon=True).start()

    def _display_results(self, stats: CacheStats):
        self.sim_running = False
        self.progress_label.config(text="完成")
        self.progress_var.set(100)
        d = stats.to_dict()
        config = self.sim.get_config_description()
        text = RESULT_TEMPLATE.format(
            config=config, trace_name=self.trace_var.get(), lines=f"{d['lines_processed']:,}",
            total_accesses=d['total_accesses'], reads=d['reads'], writes=d['writes'],
            instruction_fetches=d['instruction_fetches'], total_hits=d['total_hits'],
            total_misses=d['total_misses'], hit_rate=d['hit_rate'], miss_rate=d['miss_rate'],
            read_hits=d['read_hits'], read_misses=d['read_misses'], read_hit_rate=d['read_hit_rate'],
            write_hits=d['write_hits'], write_misses=d['write_misses'], write_hit_rate=d['write_hit_rate'],
            instruction_hits=d['instruction_hits'], instruction_misses=d['instruction_misses'],
            replacements=d['replacements'], writebacks=d['writebacks'])
        self.stat_text.configure(state=tk.NORMAL)
        self.stat_text.delete("1.0", tk.END)
        self.stat_text.insert("1.0", text)
        self.stat_text.configure(state=tk.DISABLED)
        self._draw_chart(d)
        self._log(f"模拟完成。命中率: {d['hit_rate']*100:.2f}%")

    def _draw_chart(self, stats: dict):
        self.chart_canvas.delete("all")
        w = max(self.chart_canvas.winfo_width(), 200)
        h = max(self.chart_canvas.winfo_height(), 170)
        metrics = [("总命中率", stats['hit_rate'], '#4CAF50'),
                   ("读命中率", stats.get('read_hit_rate', 0), '#2196F3'),
                   ("写命中率", stats.get('write_hit_rate', 0), '#FF9800')]
        n = len(metrics)
        bar_w = max(30, (w - 60) // n - 30)
        x_start = (w - (bar_w + 30) * n + 10) // 2
        for i, (label, val, color) in enumerate(metrics):
            x = x_start + i * (bar_w + 30)
            bar_h = int(val * (h - 55))
            y = h - 30 - bar_h
            self.chart_canvas.create_rectangle(x, y, x + bar_w, h - 30, fill=color, outline='')
            self.chart_canvas.create_text(x + bar_w // 2, y - 8, text=f"{val*100:.1f}%",
                                         font=('Arial', 10, 'bold'))
            self.chart_canvas.create_text(x + bar_w // 2, h - 14, text=label,
                                         font=('Arial', 8), fill='#555')

    def _run_batch(self):
        if self.sim_running:
            messagebox.showwarning("正在运行", "已有模拟正在运行中。")
            return
        try:
            max_lines = int(self.max_lines_var.get())
            if max_lines < 0: max_lines = -1
        except ValueError:
            max_lines = 100000

        self.batch_results.clear()
        self.progress_var.set(0)
        self.sim_running = True

        def batch_thread():
            results = []
            total = len(TRACE_FILES) * len(CACHE_SIZES) * len(ASSOCIATIVITIES) * len(BLOCK_SIZES)
            idx = 0
            for trace_name in sorted(TRACE_FILES.keys()):
                tp = os.path.join(TRACE_DIR, trace_name)
                if not os.path.exists(tp): continue
                for ss in CACHE_SIZES:
                    for sa in ASSOCIATIVITIES:
                        for sb in BLOCK_SIZES:
                            idx += 1
                            self.root.after(0, lambda i=idx, t=total: self._bp(i, t))
                            try:
                                sim = CacheSimulator(int(ss.replace('KB',''))*1024,
                                                     int(sa.split()[0]), int(sb.replace('B','')))
                                s = sim.run_trace(tp, max_lines=max_lines).to_dict()
                                s['trace'] = trace_name
                                s['cache_size'] = ss; s['associativity'] = sa; s['block_size'] = sb
                                results.append(s)
                            except Exception as e:
                                self._log(f"[{idx}/{total}] 错误: {trace_name} → {e}")
            self.batch_results = results
            self.root.after(0, lambda: self._display_batch())

        threading.Thread(target=batch_thread, daemon=True).start()

    def _bp(self, current, total):
        self.progress_var.set((current / total) * 100)
        self.progress_label.config(text=f"批量: {current}/{total}")
        self.root.update_idletasks()

    def _display_batch(self):
        self.sim_running = False
        self.progress_label.config(text=f"批量完成 ({len(self.batch_results)}组)")
        self.progress_var.set(100)
        self._log(f"批量完成: {len(self.batch_results)} 组结果。")

        top = tk.Toplevel(self.root)
        top.title("批量对比结果")
        top.geometry("1000x500")
        cols = ('trace', 'cache_size', 'assoc', 'block', 'accesses',
                'hit_rate', 'miss_rate', 'read_hit', 'write_hit', 'replacements', 'writebacks')
        tree = ttk.Treeview(top, columns=cols, show='headings')
        heads = ['Trace', 'Cache大小', '相联度', '块大小', '访问次数',
                 '命中率', '缺失率', '读命中率', '写命中率', '替换次数', '写回次数']
        widths = [130, 75, 65, 65, 90, 80, 80, 80, 80, 100, 90]
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h); tree.column(c, width=w, anchor='center')
        tree.column('trace', anchor='w')
        tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        for r in self.batch_results:
            tree.insert('', tk.END, values=(
                r['trace'], r['cache_size'], r['associativity'], r['block_size'],
                f"{r['total_accesses']:,}", f"{r['hit_rate']*100:.2f}%", f"{r['miss_rate']*100:.2f}%",
                f"{r['read_hit_rate']*100:.2f}%", f"{r['write_hit_rate']*100:.2f}%",
                f"{r['replacements']:,}", f"{r['writebacks']:,}"))

    def _on_error(self, msg: str):
        self.sim_running = False
        self.progress_label.config(text="出错")
        messagebox.showerror("模拟错误", msg)

    def _export_batch_csv(self):
        if not self.batch_results:
            messagebox.showwarning("无数据", "请先运行批量测试。")
            return
        filepath = filedialog.asksaveasfilename(
            title="导出批量结果", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not filepath: return
        import csv
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            fields = ['trace', 'cache_size', 'associativity', 'block_size',
                     'total_accesses', 'hit_rate', 'miss_rate', 'read_hit_rate',
                     'write_hit_rate', 'reads', 'writes', 'instruction_fetches',
                     'read_hits', 'read_misses', 'write_hits', 'write_misses',
                     'instruction_hits', 'instruction_misses', 'replacements', 'writebacks']
            csv.DictWriter(f, fieldnames=fields, extrasaction='ignore').writerows(self.batch_results)
        self._log(f"批量结果已导出至 {filepath}")
        messagebox.showinfo("导出成功", f"结果已保存至 {filepath}")

    def _log(self, msg: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + '\n')
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

if __name__ == '__main__':
    CacheGUI()
