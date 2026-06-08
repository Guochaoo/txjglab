import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tomasulo_engine import (
    TomasuloSimulator, Instruction, parse_program, load_program,
    FUType, LATENCY, OpType
)
from typing import Optional

TEST_NO_CONFLICT = """# 测试1: 无冲突 — 所有指令相互独立
LD F0, 0(R1)
LD F2, 8(R1)
LD F4, 16(R1)
ADD.D F6, F0, F2
MUL.D F8, F0, F4
SUB.D F10, F2, F4
DIV.D F12, F8, F6
SD F10, 32(R1)
SD F12, 40(R1)
"""

TEST_RAW = """# 测试2: RAW冲突 — 真数据依赖链
LD F0, 0(R1)
ADD.D F2, F0, F4
MUL.D F6, F2, F8
SUB.D F10, F6, F0
DIV.D F12, F10, F2
SD F12, 32(R1)
"""

TEST_WAR = """# 测试3: WAR冲突 — 反依赖 (Tomasulo通过重命名消除)
MUL.D F0, F2, F4
ADD.D F6, F0, F8
SUB.D F0, F10, F12
DIV.D F14, F0, F6
LD F16, 0(R1)
MUL.D F18, F16, F14
SD F0, 32(R1)
SD F18, 40(R1)
"""

TEST_PROGRAMS = {
    "无冲突": TEST_NO_CONFLICT,
    "RAW冲突": TEST_RAW,
    "WAR冲突": TEST_WAR,
}

STAT_LABELS = {
    'total_instructions': '总指令数',
    'total_cycles': '总周期数',
    'issued': '已流出',
    'executed': '已执行',
    'stalls': '停顿次数',
    'ipc': 'IPC',
    'cpi': 'CPI',
}

class TomasuloGUI:

    def __init__(self):
        self.sim = TomasuloSimulator()
        self.max_display_cycle = 0

        self.root = tk.Tk()
        self.root.title("Tomasulo算法模拟器")
        self.root.geometry("1280x900")
        self.root.configure(bg='#f0f0f0')

        self._build_menu()
        self._build_layout()
        self._apply_test_program("RAW冲突")

        self.root.mainloop()

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开程序文件...", command=self._load_file)
        file_menu.add_command(label="保存日志...", command=self._save_log)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        test_menu = tk.Menu(menubar, tearoff=0)
        test_menu.add_command(label="无冲突", command=lambda: self._apply_test_program("无冲突"))
        test_menu.add_command(label="RAW冲突", command=lambda: self._apply_test_program("RAW冲突"))
        test_menu.add_command(label="WAR冲突", command=lambda: self._apply_test_program("WAR冲突"))
        menubar.add_cascade(label="测试程序", menu=test_menu)

        self.root.config(menu=menubar)

    def _build_layout(self):
        main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pw.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.Frame(main_pw)
        right_frame = ttk.Frame(main_pw)
        main_pw.add(left_frame, weight=1)
        main_pw.add(right_frame, weight=2)

        code_frame = ttk.LabelFrame(left_frame, text="程序代码 (MIPS 浮点汇编)")
        code_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.code_text = tk.Text(code_frame, height=15, width=50, font=('Consolas', 10),
                                 wrap=tk.NONE)
        code_scroll_y = ttk.Scrollbar(code_frame, orient=tk.VERTICAL,
                                      command=self.code_text.yview)
        code_scroll_x = ttk.Scrollbar(code_frame, orient=tk.HORIZONTAL,
                                      command=self.code_text.xview)
        self.code_text.configure(yscrollcommand=code_scroll_y.set,
                                 xscrollcommand=code_scroll_x.set)
        self.code_text.grid(row=0, column=0, sticky='nsew')
        code_scroll_y.grid(row=0, column=1, sticky='ns')
        code_scroll_x.grid(row=1, column=0, sticky='ew')
        code_frame.grid_rowconfigure(0, weight=1)
        code_frame.grid_columnconfigure(0, weight=1)

        ctrl_frame = ttk.LabelFrame(left_frame, text="控制")
        ctrl_frame.pack(fill=tk.X, pady=(0, 5))

        btn_row1 = ttk.Frame(ctrl_frame)
        btn_row1.pack(fill=tk.X, padx=5, pady=3)
        ttk.Button(btn_row1, text="加载并重置", command=self._load_program).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row1, text="单步 (1周期)", command=self._step_one).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row1, text="多步 (N周期)...", command=self._step_n).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row1, text="运行至结束", command=self._run_all).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row1, text="重置", command=self._reset).pack(
            side=tk.LEFT, padx=2)

        btn_row2 = ttk.Frame(ctrl_frame)
        btn_row2.pack(fill=tk.X, padx=5, pady=3)
        ttk.Button(btn_row2, text="◀ 上一周期", command=self._prev_cycle).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(btn_row2, text="下一周期 ▶", command=self._next_cycle).pack(
            side=tk.LEFT, padx=2)
        ttk.Label(btn_row2, text="当前周期:").pack(side=tk.LEFT, padx=(10, 2))
        self.cycle_var = tk.StringVar(value="0")
        ttk.Label(btn_row2, textvariable=self.cycle_var, font=('Arial', 12, 'bold'),
                  foreground='blue').pack(side=tk.LEFT)

        stat_frame = ttk.LabelFrame(left_frame, text="统计信息")
        stat_frame.pack(fill=tk.X)

        self.stat_vars = {}
        for i, key in enumerate(STAT_LABELS.keys()):
            ttk.Label(stat_frame, text=f"{STAT_LABELS[key]}:").grid(
                row=i // 2, column=(i % 2) * 2, sticky='w', padx=5, pady=1)
            var = tk.StringVar(value="-")
            self.stat_vars[key] = var
            ttk.Label(stat_frame, textvariable=var, font=('Arial', 9, 'bold')).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky='w', padx=5, pady=1)

        self.notebook = ttk.Notebook(right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_rs_tab()
        self._build_reg_tab()
        self._build_mem_tab()
        self._build_log_tab()

    def _build_rs_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="保留站")

        ttk.Label(frame, text="浮点加法保留站", font=('Microsoft YaHei', 10, 'bold')).grid(
            row=0, column=0, sticky='w', padx=5, pady=(5, 2))
        self.rs_tree_add = self._create_rs_tree(frame, row=1, col=0)

        ttk.Label(frame, text="浮点乘除保留站", font=('Microsoft YaHei', 10, 'bold')).grid(
            row=2, column=0, sticky='w', padx=5, pady=(10, 2))
        self.rs_tree_mul = self._create_rs_tree(frame, row=3, col=0)

        ttk.Label(frame, text="Load 缓冲器", font=('Microsoft YaHei', 10, 'bold')).grid(
            row=0, column=1, sticky='w', padx=5, pady=(5, 2))
        self.rs_tree_load = self._create_rs_tree(frame, row=1, col=1)

        ttk.Label(frame, text="Store 缓冲器", font=('Microsoft YaHei', 10, 'bold')).grid(
            row=2, column=1, sticky='w', padx=5, pady=(10, 2))
        self.rs_tree_store = self._create_rs_tree(frame, row=3, col=1)

        for i in range(4):
            frame.grid_rowconfigure(i, weight=1 if i in (1, 3) else 0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

    def _create_rs_tree(self, parent, row, col):
        columns = ('name', 'busy', 'op', 'Vj', 'Vk', 'Qj', 'Qk', 'A', 'dest', 'cycles', 'inst')
        tree = ttk.Treeview(parent, columns=columns, show='headings', height=5)
        widths = [55, 40, 55, 65, 65, 48, 48, 60, 45, 50, 160]
        headings = ['名称', '占用', '操作', 'Vj', 'Vk', 'Qj', 'Qk', '地址', '目标', '剩余周期', '指令']
        for c, w, h in zip(columns, widths, headings):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor='center')
        tree.column('inst', anchor='w')

        scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=row, column=col, sticky='nsew', padx=5, pady=2)
        scroll.grid(row=row, column=col, sticky='nse')
        return tree

    def _build_reg_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="寄存器状态")

        ttk.Label(frame, text="浮点寄存器文件及状态", font=('Microsoft YaHei', 11, 'bold')).pack(
            anchor='w', padx=5, pady=5)

        columns = ('reg', 'value', 'status')
        self.reg_tree = ttk.Treeview(frame, columns=columns, show='headings', height=16)
        self.reg_tree.heading('reg', text='寄存器')
        self.reg_tree.heading('value', text='值')
        self.reg_tree.heading('status', text='Qi (等待的RS)')
        self.reg_tree.column('reg', width=80, anchor='center')
        self.reg_tree.column('value', width=120, anchor='center')
        self.reg_tree.column('status', width=200, anchor='center')
        self.reg_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.reg_tree.yview)
        self.reg_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_mem_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="内存")

        columns = ('addr', 'value')
        self.mem_tree = ttk.Treeview(frame, columns=columns, show='headings', height=20)
        self.mem_tree.heading('addr', text='地址 (十六进制)')
        self.mem_tree.heading('value', text='值 (双精度浮点)')
        self.mem_tree.column('addr', width=160, anchor='center')
        self.mem_tree.column('value', width=160, anchor='center')
        self.mem_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.mem_tree.yview)
        self.mem_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_log_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="执行日志")

        self.log_text = scrolledtext.ScrolledText(frame, font=('Consolas', 9),
                                                   wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _load_program(self):

        code = self.code_text.get("1.0", tk.END)
        try:
            program = parse_program(code)
            if not program:
                messagebox.showwarning("程序为空", "未找到有效指令。")
                return
            self.sim.load(program)
            self.max_display_cycle = 0
            self._refresh_all()
            self._log_message("程序加载成功。")
        except Exception as e:
            messagebox.showerror("解析错误", str(e))

    def _load_file(self):

        filepath = filedialog.askopenfilename(
            title="打开程序文件",
            filetypes=[("文本文件", "*.txt"), ("汇编文件", "*.s *.asm"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.code_text.delete("1.0", tk.END)
                self.code_text.insert("1.0", f.read())
            self._load_program()
        except Exception as e:
            messagebox.showerror("文件错误", str(e))

    def _save_log(self):

        filepath = filedialog.asksaveasfilename(
            title="保存执行日志",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(self.log_text.get("1.0", tk.END))

    def _apply_test_program(self, name: str):

        self.code_text.delete("1.0", tk.END)
        self.code_text.insert("1.0", TEST_PROGRAMS[name])
        self._load_program()

    def _step_one(self):

        if not self.sim.instructions:
            messagebox.showwarning("未加载程序", "请先加载程序。")
            return
        if self.sim.done:
            messagebox.showinfo("已完成", "程序已执行完毕。")
            return

        self.sim.step()
        self.max_display_cycle = len(self.sim.snapshots) - 1
        self._refresh_all()

    def _step_n(self):

        if not self.sim.instructions:
            messagebox.showwarning("未加载程序", "请先加载程序。")
            return
        if self.sim.done:
            messagebox.showinfo("已完成", "程序已执行完毕。")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("多步执行")
        dialog.geometry("280x130")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="执行周期数:").pack(pady=(15, 5))
        n_var = tk.StringVar(value="5")
        entry = ttk.Entry(dialog, textvariable=n_var, width=10)
        entry.pack(pady=5)
        entry.focus_set()

        def do_step():
            try:
                n = int(n_var.get())
                if n <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("输入错误", "请输入正整数。")
                return
            dialog.destroy()
            for _ in range(n):
                if self.sim.done:
                    break
                self.sim.step()
            self.max_display_cycle = len(self.sim.snapshots) - 1
            self._refresh_all()

        ttk.Button(dialog, text="执行", command=do_step).pack(pady=5)
        entry.bind('<Return>', lambda e: do_step())

    def _run_all(self):

        if not self.sim.instructions:
            messagebox.showwarning("未加载程序", "请先加载程序。")
            return
        if self.sim.done:
            messagebox.showinfo("已完成", "程序已执行完毕。")
            return

        self.sim.run_to_completion(max_cycles=500)
        self.max_display_cycle = len(self.sim.snapshots) - 1
        self._refresh_all()
        self._log_message(f"程序执行完毕，共 {self.sim.clock} 周期。")

    def _reset(self):

        if self.sim.instructions:
            self.sim.load(self.sim.instructions)
        self.max_display_cycle = 0
        self._refresh_all()
        self._log_message("模拟器已重置。")

    def _prev_cycle(self):

        if self.max_display_cycle > 0:
            self.max_display_cycle -= 1
            self._refresh_all(use_snapshot=self.max_display_cycle)

    def _next_cycle(self):

        if self.max_display_cycle < len(self.sim.snapshots) - 1:
            self.max_display_cycle += 1
            self._refresh_all(use_snapshot=self.max_display_cycle)

    def _refresh_all(self, use_snapshot: int = -1):
        snap = self.sim.get_snapshot(use_snapshot)
        self._refresh_rs(snap)
        self._refresh_registers(snap)
        self._refresh_memory(snap)
        self._refresh_stats()
        self._refresh_log()
        self.cycle_var.set(str(snap['clock']) if snap else "0")

    def _refresh_rs(self, snap: Optional[dict]):
        if snap is None:
            return

        rs_groups = {
            self.rs_tree_add: [],
            self.rs_tree_mul: [],
            self.rs_tree_load: [],
            self.rs_tree_store: [],
        }
        for entry in snap['rs_state']:
            if 'Add' in entry['name']:
                rs_groups[self.rs_tree_add].append(entry)
            elif 'Mul' in entry['name']:
                rs_groups[self.rs_tree_mul].append(entry)
            elif 'Load' in entry['name']:
                rs_groups[self.rs_tree_load].append(entry)
            elif 'Store' in entry['name']:
                rs_groups[self.rs_tree_store].append(entry)

        for tree, entries in rs_groups.items():
            for item in tree.get_children():
                tree.delete(item)
            for e in entries:
                tree.insert('', tk.END, values=(
                    e['name'],
                    '是' if e['busy'] else '否',
                    e['op'],
                    f"{e['Vj']:.1f}" if e['Vj'] is not None else '',
                    f"{e['Vk']:.1f}" if e['Vk'] is not None else '',
                    e['Qj'],
                    e['Qk'],
                    f"0x{e['A']:04X}" if e['A'] is not None else '',
                    f"F{e['dest']}" if e['dest'] is not None else '',
                    e['cycles'],
                    e['inst'][:50],
                ))

    def _refresh_registers(self, snap: Optional[dict]):
        for item in self.reg_tree.get_children():
            self.reg_tree.delete(item)
        if snap is None:
            return

        fp_regs = snap.get('fp_regs', [])
        reg_status = snap.get('reg_status', {})

        for i in range(min(16, len(fp_regs))):
            status = reg_status.get(i, "")
            if status:
                status_text = f"等待 {status}"
            else:
                status_text = "就绪"
            self.reg_tree.insert('', tk.END, values=(
                f"F{i}", f"{fp_regs[i]:.4f}", status_text
            ))

    def _refresh_memory(self, snap: Optional[dict]):
        for item in self.mem_tree.get_children():
            self.mem_tree.delete(item)
        if snap is None:
            return

        mem = snap.get('memory', {})
        for addr in sorted(mem.keys())[:30]:
            self.mem_tree.insert('', tk.END, values=(
                f"0x{addr:04X}", f"{mem[addr]:.4f}"
            ))

    def _refresh_stats(self):
        stats = self.sim.get_stats()
        for key, var in self.stat_vars.items():
            val = stats.get(key, '-')
            if isinstance(val, float):
                val = f"{val:.3f}"
            var.set(str(val))

    def _refresh_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        log_lines = self.sim.log[-100:]
        self.log_text.insert("1.0", '\n'.join(log_lines))
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _log_message(self, msg: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + '\n')
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

if __name__ == '__main__':
    TomasuloGUI()
