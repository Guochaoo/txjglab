from __future__ import annotations

import copy
import re
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


REG_COUNT = 32
STAGES = ("IF", "ID", "EX", "MEM", "WB")


@dataclass
class Instruction:
    op: str
    args: list[str]
    raw: str
    index: int
    label: str | None = None

    def display(self) -> str:
        return f"I{self.index}: {self.raw}"


@dataclass
class PipeEntry:
    instr: Instruction
    result: int | None = None
    address: int | None = None
    store_value: int | None = None
    branch_taken: bool = False
    branch_target: int | None = None

    def clone(self) -> "PipeEntry":
        return copy.deepcopy(self)


class ParseError(Exception):
    pass


def reg_index(name: str) -> int:
    token = name.strip().lower().replace("$", "")
    if token.startswith("r"):
        token = token[1:]
    if not token.isdigit():
        raise ParseError(f"invalid register: {name}")
    idx = int(token)
    if idx < 0 or idx >= REG_COUNT:
        raise ParseError(f"register out of range: {name}")
    return idx


def split_args(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def parse_program(source: str) -> tuple[list[Instruction], dict[int, int], dict[str, int]]:
    labels: dict[str, int] = {}
    data_labels: dict[str, int] = {}
    memory: dict[int, int] = {}
    instructions: list[Instruction] = []
    section = ".text"
    next_data_addr = 100
    pending_text: list[tuple[str, str | None]] = []

    for raw_line in source.splitlines():
        line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low == ".text":
            section = ".text"
            continue
        if low == ".data":
            section = ".data"
            continue

        label = None
        if ":" in line:
            before, after = line.split(":", 1)
            label = before.strip()
            line = after.strip()
            if section == ".text":
                labels[label] = len(pending_text)
            else:
                data_labels[label] = next_data_addr
        if section == ".data":
            if not line:
                continue
            match = re.match(r"\.word\s+(.+)$", line, re.IGNORECASE)
            if not match:
                raise ParseError(f"unsupported data directive: {raw_line}")
            values = [int(x.strip(), 0) for x in match.group(1).split(",")]
            for value in values:
                memory[next_data_addr] = value
                next_data_addr += 4
            continue
        if line:
            pending_text.append((line, label))

    for idx, (line, label) in enumerate(pending_text):
        parts = line.strip().split(None, 1)
        op = parts[0].upper()
        args = split_args(parts[1]) if len(parts) > 1 else []
        if op == "LOAD":
            op = "LW"
        elif op == "STORE":
            op = "SW"
        elif op == "ADDI":
            op = "ADDIU"
        instructions.append(Instruction(op=op, args=args, raw=line, index=idx + 1, label=label))

    return instructions, memory, data_labels | labels


class PipelineSimulator:
    def __init__(self) -> None:
        self.instructions: list[Instruction] = []
        self.initial_memory: dict[int, int] = {}
        self.labels: dict[str, int] = {}
        self.forwarding = True
        self.reset_runtime()

    def load_program(self, source: str) -> None:
        self.instructions, self.initial_memory, self.labels = parse_program(source)
        self.reset_runtime()

    def reset_runtime(self) -> None:
        self.pc = 0
        self.clock = 0
        self.registers = [0] * REG_COUNT
        self.memory = dict(getattr(self, "initial_memory", {}))
        self.pipeline: dict[str, PipeEntry | None] = {stage: None for stage in STAGES}
        self.finished = False
        self.history: list[dict[str, str]] = []
        self.completed = 0
        self.data_hazards = 0
        self.control_hazards = 0
        self.stall_cycles = 0
        self.last_event = "Program loaded."

    def set_forwarding(self, enabled: bool) -> None:
        self.forwarding = enabled

    def _resolve_value(self, token: str) -> int:
        token = token.strip()
        if token in self.labels:
            return self.labels[token]
        return int(token, 0)

    def _parse_mem_operand(self, token: str) -> tuple[int, int]:
        match = re.match(r"(-?\w+)\((\$?r?\d+)\)$", token.strip(), re.IGNORECASE)
        if not match:
            raise ParseError(f"invalid memory operand: {token}")
        offset_token, base_token = match.groups()
        offset = self._resolve_value(offset_token)
        return offset, reg_index(base_token)

    def dest_reg(self, instr: Instruction | None) -> int | None:
        if instr is None:
            return None
        if instr.op in {"ADD", "ADDIU", "SUBI", "LW"}:
            return reg_index(instr.args[0])
        return None

    def source_regs(self, instr: Instruction | None) -> list[int]:
        if instr is None:
            return []
        op = instr.op
        args = instr.args
        if op == "ADD":
            return [reg_index(args[1]), reg_index(args[2])]
        if op in {"ADDIU", "SUBI"}:
            return [reg_index(args[1])]
        if op == "LW":
            return [self._parse_mem_operand(args[1])[1]]
        if op == "SW":
            return [reg_index(args[0]), self._parse_mem_operand(args[1])[1]]
        if op == "BEQZ":
            return [reg_index(args[0])]
        return []

    def _read_reg(self, idx: int) -> int:
        if idx == 0:
            return 0
        if self.forwarding:
            for stage in ("MEM", "WB"):
                entry = self.pipeline[stage]
                if entry and self.dest_reg(entry.instr) == idx and entry.result is not None:
                    return entry.result
        return self.registers[idx]

    def _has_data_hazard(self) -> bool:
        id_entry = self.pipeline["ID"]
        if not id_entry:
            return False
        srcs = set(self.source_regs(id_entry.instr))
        if not srcs:
            return False
        if self.forwarding:
            ex_entry = self.pipeline["EX"]
            return bool(
                ex_entry
                and ex_entry.instr.op == "LW"
                and self.dest_reg(ex_entry.instr) in srcs
            )
        for stage in ("EX", "MEM"):
            entry = self.pipeline[stage]
            if entry and self.dest_reg(entry.instr) in srcs:
                return True
        return False

    def _execute_ex(self, entry: PipeEntry | None) -> PipeEntry | None:
        if not entry:
            return None
        instr = entry.instr
        args = instr.args
        op = instr.op
        if op == "ADD":
            entry.result = self._read_reg(reg_index(args[1])) + self._read_reg(reg_index(args[2]))
        elif op == "ADDIU":
            entry.result = self._read_reg(reg_index(args[1])) + self._resolve_value(args[2])
        elif op == "SUBI":
            entry.result = self._read_reg(reg_index(args[1])) - self._resolve_value(args[2])
        elif op in {"LW", "SW"}:
            offset, base = self._parse_mem_operand(args[1])
            entry.address = self._read_reg(base) + offset
            if op == "SW":
                entry.store_value = self._read_reg(reg_index(args[0]))
        elif op == "BEQZ":
            entry.branch_taken = self._read_reg(reg_index(args[0])) == 0
            entry.branch_target = self._branch_target(args[1])
        elif op == "J":
            entry.branch_taken = True
            entry.branch_target = self._branch_target(args[0])
        else:
            raise ParseError(f"unsupported instruction: {instr.raw}")
        return entry

    def _branch_target(self, token: str) -> int:
        token = token.strip()
        if token in self.labels:
            return self.labels[token]
        return int(token, 0)

    def _execute_mem(self, entry: PipeEntry | None) -> PipeEntry | None:
        if not entry:
            return None
        instr = entry.instr
        if instr.op == "LW":
            entry.result = self.memory.get(entry.address or 0, 0)
        elif instr.op == "SW":
            self.memory[entry.address or 0] = entry.store_value or 0
        return entry

    def _commit_wb(self, entry: PipeEntry | None) -> None:
        if not entry:
            return
        dest = self.dest_reg(entry.instr)
        if dest is not None and dest != 0 and entry.result is not None:
            self.registers[dest] = entry.result
        self.completed += 1

    def _fetch(self) -> PipeEntry | None:
        if self.pc >= len(self.instructions):
            return None
        entry = PipeEntry(self.instructions[self.pc])
        self.pc += 1
        return entry

    def step(self) -> None:
        if self.finished:
            self.last_event = "Program already finished."
            return

        self.clock += 1
        self.last_event = "Normal advance."
        current = {stage: (entry.clone() if entry else None) for stage, entry in self.pipeline.items()}

        self._commit_wb(current["WB"])
        mem_done = self._execute_mem(current["MEM"])
        ex_done = self._execute_ex(current["EX"])

        branch_flush = bool(ex_done and ex_done.branch_taken)
        if branch_flush and ex_done.branch_target is not None:
            self.pc = ex_done.branch_target
            self.control_hazards += 1
            self.stall_cycles += 2
            self.last_event = f"Control hazard: branch taken by {ex_done.instr.display()}, flush IF/ID."

        stall = False if branch_flush else self._has_data_hazard()
        if stall:
            self.data_hazards += 1
            self.stall_cycles += 1
            self.last_event = f"RAW hazard: stall before {current['ID'].instr.display()}."

        next_pipe: dict[str, PipeEntry | None] = {stage: None for stage in STAGES}
        next_pipe["WB"] = mem_done
        next_pipe["MEM"] = ex_done
        if branch_flush:
            next_pipe["EX"] = None
            next_pipe["ID"] = None
            next_pipe["IF"] = None
        elif stall:
            next_pipe["EX"] = None
            next_pipe["ID"] = current["ID"]
            next_pipe["IF"] = current["IF"]
        else:
            next_pipe["EX"] = current["ID"]
            next_pipe["ID"] = current["IF"]
            next_pipe["IF"] = self._fetch()

        self.pipeline = next_pipe
        self.registers[0] = 0
        self._record_history()

        if self.pc >= len(self.instructions) and all(entry is None for entry in self.pipeline.values()):
            self.finished = True
            self.last_event = "Program finished."

    def run(self, max_cycles: int = 500) -> None:
        while not self.finished and self.clock < max_cycles:
            self.step()
        if self.clock >= max_cycles:
            self.last_event = "Stopped: max cycle limit reached."

    def _record_history(self) -> None:
        row = {"cycle": str(self.clock)}
        for stage in STAGES:
            entry = self.pipeline[stage]
            row[stage] = entry.instr.display() if entry else "-"
        row["event"] = self.last_event
        self.history.append(row)

    def stats(self) -> dict[str, float | int | str]:
        total = len(self.instructions)
        cpi = self.clock / total if total else 0
        return {
            "instructions": total,
            "completed": self.completed,
            "cycles": self.clock,
            "cpi": round(cpi, 3),
            "stalls": self.stall_cycles,
            "raw_hazards": self.data_hazards,
            "control_hazards": self.control_hazards,
            "forwarding": "ON" if self.forwarding else "OFF",
        }


DEFAULT_PROGRAM = """.text
main:
ADDIU $r1,$r0,A
LW $r2,0($r1)
LW $r3,4($r1)
ADDIU $r4,$r0,B
SW $r2,0($r4)
SW $r2,4($r4)

.data
A: .word 1, 2, 4, 8
B: .word 1, 2, 3, 4
"""


class SimulatorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MIPS 五段流水线模拟器")
        self.geometry("1180x760")
        self.sim = PipelineSimulator()
        self.forwarding_var = tk.BooleanVar(value=True)
        self.break_cycle_var = tk.StringVar(value="20")
        self._build_ui()
        self.load_source(DEFAULT_PROGRAM)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(toolbar, text="载入文件", command=self.open_file).pack(side="left", padx=3)
        ttk.Button(toolbar, text="重置", command=self.reset).pack(side="left", padx=3)
        ttk.Button(toolbar, text="单步执行", command=self.step).pack(side="left", padx=3)
        ttk.Button(toolbar, text="运行到底", command=self.run_all).pack(side="left", padx=3)
        ttk.Label(toolbar, text="断点周期").pack(side="left", padx=(20, 4))
        ttk.Entry(toolbar, textvariable=self.break_cycle_var, width=6).pack(side="left")
        ttk.Button(toolbar, text="运行到断点", command=self.run_to_break).pack(side="left", padx=3)
        ttk.Checkbutton(toolbar, text="启用定向路径", variable=self.forwarding_var, command=self.reset).pack(side="left", padx=20)

        left = ttk.Frame(self, padding=(8, 0, 4, 8))
        left.grid(row=1, column=0, sticky="nsew")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="代码区").grid(row=0, column=0, sticky="w")
        self.code_text = tk.Text(left, height=12, wrap="none", font=("Consolas", 11))
        self.code_text.grid(row=1, column=0, sticky="nsew")
        ttk.Button(left, text="载入编辑区代码", command=self.load_editor_code).grid(row=2, column=0, sticky="ew", pady=4)

        table_frame = ttk.Frame(left)
        table_frame.grid(row=3, column=0, sticky="nsew")
        left.rowconfigure(3, weight=2)
        self.pipeline_table = ttk.Treeview(table_frame, columns=("cycle", *STAGES, "event"), show="headings", height=14)
        widths = {"cycle": 55, "IF": 140, "ID": 140, "EX": 140, "MEM": 140, "WB": 140, "event": 330}
        headings = {"cycle": "周期", "IF": "IF 取指", "ID": "ID 译码", "EX": "EX 执行", "MEM": "MEM 访存", "WB": "WB 写回", "event": "事件"}
        for col in ("cycle", *STAGES, "event"):
            self.pipeline_table.heading(col, text=headings[col])
            self.pipeline_table.column(col, width=widths[col], anchor="w")
        self.pipeline_table.pack(fill="both", expand=True)

        right = ttk.Frame(self, padding=(4, 0, 8, 8))
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        right.rowconfigure(5, weight=1)

        ttk.Label(right, text="性能统计").grid(row=0, column=0, sticky="w")
        self.stats_text = tk.Text(right, height=8, font=("Consolas", 11))
        self.stats_text.grid(row=1, column=0, sticky="nsew")

        ttk.Label(right, text="寄存器状态").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.reg_text = tk.Text(right, height=12, font=("Consolas", 11))
        self.reg_text.grid(row=3, column=0, sticky="nsew")

        ttk.Label(right, text="内存状态").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.mem_text = tk.Text(right, height=8, font=("Consolas", 11))
        self.mem_text.grid(row=5, column=0, sticky="nsew")

    def load_source(self, source: str) -> None:
        self.code_text.delete("1.0", "end")
        self.code_text.insert("1.0", source)
        self.load_editor_code()

    def load_editor_code(self) -> None:
        try:
            self.sim.load_program(self.code_text.get("1.0", "end"))
            self.sim.set_forwarding(self.forwarding_var.get())
            self.sim.reset_runtime()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("解析错误", str(exc))

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("汇编程序", "*.asm *.s *.txt"), ("所有文件", "*.*")])
        if filename:
            self.load_source(Path(filename).read_text(encoding="utf-8"))

    def reset(self) -> None:
        self.sim.set_forwarding(self.forwarding_var.get())
        self.sim.reset_runtime()
        self.refresh()

    def step(self) -> None:
        self.sim.step()
        self.refresh()

    def run_all(self) -> None:
        self.sim.run()
        self.refresh()

    def run_to_break(self) -> None:
        try:
            target = int(self.break_cycle_var.get())
        except ValueError:
            target = self.sim.clock + 1
        while not self.sim.finished and self.sim.clock < target:
            self.sim.step()
        self.refresh()

    def refresh(self) -> None:
        for item in self.pipeline_table.get_children():
            self.pipeline_table.delete(item)
        for row in self.sim.history:
            self.pipeline_table.insert("", "end", values=[row["cycle"], *(row[s] for s in STAGES), row["event"]])
        children = self.pipeline_table.get_children()
        if children:
            self.pipeline_table.see(children[-1])

        stats = self.sim.stats()
        self.stats_text.delete("1.0", "end")
        for key, value in stats.items():
            self.stats_text.insert("end", f"{key:16}: {value}\n")
        self.stats_text.insert("end", f"last_event      : {self.sim.last_event}\n")

        self.reg_text.delete("1.0", "end")
        for i in range(0, REG_COUNT, 4):
            line = "  ".join(f"$r{j:<2}={self.sim.registers[j]:<6}" for j in range(i, i + 4))
            self.reg_text.insert("end", line + "\n")

        self.mem_text.delete("1.0", "end")
        for addr in sorted(self.sim.memory)[:32]:
            self.mem_text.insert("end", f"{addr:04d}: {self.sim.memory[addr]}\n")


def run_app() -> None:
    app = SimulatorApp()
    app.mainloop()


if __name__ == "__main__":
    run_app()
