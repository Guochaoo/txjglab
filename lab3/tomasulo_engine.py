from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum
import re

class OpType(Enum):

    LD = "LD"
    SD = "SD"
    ADD_D = "ADD.D"
    SUB_D = "SUB.D"
    MUL_D = "MUL.D"
    DIV_D = "DIV.D"

class FUType(Enum):

    LOAD = "Load"
    STORE = "Store"
    FP_ADDER = "FP_Adder"
    FP_MULTIPLIER = "FP_Multiplier"

@dataclass
class Instruction:

    op: OpType
    dest: Optional[int] = None
    src1: Optional[int] = None
    src2: Optional[int] = None
    offset: Optional[int] = None
    base: Optional[int] = None
    line: int = 0
    text: str = ""

    def __str__(self):
        return self.text

LATENCY: Dict[OpType, int] = {
    OpType.LD: 1,
    OpType.SD: 1,
    OpType.ADD_D: 2,
    OpType.SUB_D: 2,
    OpType.MUL_D: 10,
    OpType.DIV_D: 40,
}

OP_TO_FU: Dict[OpType, FUType] = {
    OpType.LD: FUType.LOAD,
    OpType.SD: FUType.STORE,
    OpType.ADD_D: FUType.FP_ADDER,
    OpType.SUB_D: FUType.FP_ADDER,
    OpType.MUL_D: FUType.FP_MULTIPLIER,
    OpType.DIV_D: FUType.FP_MULTIPLIER,
}

RS_COUNT: Dict[FUType, int] = {
    FUType.LOAD: 3,
    FUType.STORE: 3,
    FUType.FP_ADDER: 3,
    FUType.FP_MULTIPLIER: 2,
}

@dataclass
class ReservationStation:

    name: str
    fu_type: FUType
    busy: bool = False
    op: Optional[OpType] = None
    Vj: Optional[float] = None
    Vk: Optional[float] = None
    Qj: str = ""
    Qk: str = ""
    A: Optional[int] = None
    dest: Optional[int] = None
    cycles_remaining: int = 0
    inst_index: int = -1
    inst_text: str = ""
    started: bool = False

    store_value: Optional[float] = None

    def reset(self):
        self.busy = False
        self.op = None
        self.Vj = None
        self.Vk = None
        self.Qj = ""
        self.Qk = ""
        self.A = None
        self.dest = None
        self.cycles_remaining = 0
        self.inst_index = -1
        self.inst_text = ""
        self.started = False
        self.store_value = None

    @property
    def operands_ready(self) -> bool:

        return self.Qj == "" and self.Qk == ""

@dataclass
class CDBEntry:

    value: float
    source_rs: str
    dest_reg: Optional[int] = None
    cycle: int = 0

def parse_instruction(line: str, index: int = 0) -> Optional[Instruction]:

    line = line.strip()
    if not line or line.startswith('#'):
        return None

    if '#' in line:
        line = line[:line.index('#')].strip()
    if not line:
        return None

    text = line

    m = re.match(r'(LD|SD)\s+[FR](\d+)\s*,\s*(-?\d+)\s*\(\s*[FR](\d+)\s*\)', line, re.IGNORECASE)
    if m:
        op = OpType.LD if m.group(1).upper() == 'LD' else OpType.SD
        reg = int(m.group(2))
        offset = int(m.group(3))
        base = int(m.group(4))
        if op == OpType.LD:
            return Instruction(op=op, dest=reg, offset=offset, base=base,
                             line=index, text=text)
        else:
            return Instruction(op=op, src1=reg, offset=offset, base=base,
                             line=index, text=text)

    m = re.match(r'(ADD\.D|SUB\.D|MUL\.D|DIV\.D)\s+[FR](\d+)\s*,\s*[FR](\d+)\s*,\s*[FR](\d+)',
                 line, re.IGNORECASE)
    if m:
        op_map = {
            'ADD.D': OpType.ADD_D, 'SUB.D': OpType.SUB_D,
            'MUL.D': OpType.MUL_D, 'DIV.D': OpType.DIV_D
        }
        op = op_map[m.group(1).upper()]
        dest = int(m.group(2))
        src1 = int(m.group(3))
        src2 = int(m.group(4))
        return Instruction(op=op, dest=dest, src1=src1, src2=src2,
                         line=index, text=text)

    raise ValueError(f"Cannot parse instruction: {line}")

def load_program(filepath: str) -> List[Instruction]:

    instructions = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            inst = parse_instruction(line, i)
            if inst:
                instructions.append(inst)
    return instructions

def parse_program(text: str) -> List[Instruction]:

    instructions = []
    for i, line in enumerate(text.strip().split('\n')):
        inst = parse_instruction(line, i)
        if inst:
            instructions.append(inst)
    return instructions

class TomasuloSimulator:

    NUM_FP_REGS = 32
    NUM_GP_REGS = 32
    MEM_SIZE = 4096

    def __init__(self):

        self.fp_regs: List[float] = [0.0] * self.NUM_FP_REGS
        self.gp_regs: List[int] = [0] * self.NUM_GP_REGS

        self.reg_status: Dict[int, str] = {i: "" for i in range(self.NUM_FP_REGS)}

        self.store_reg_status: Dict[int, List[str]] = {i: [] for i in range(self.NUM_FP_REGS)}

        self.memory: Dict[int, float] = {}

        self._init_reservation_stations()

        self.instructions: List[Instruction] = []
        self.pc: int = 0

        self.clock: int = 0
        self.running: bool = False
        self.done: bool = False
        self.halted: bool = False

        self.cdb: Optional[CDBEntry] = None

        self.issue_count: int = 0
        self.exec_count: int = 0
        self.write_count: int = 0
        self.total_stalls: int = 0

        self.log: List[str] = []

        self.snapshots: List[dict] = []

    def _init_reservation_stations(self):

        self.fp_add_rs: List[ReservationStation] = [
            ReservationStation(name=f"Add{i+1}", fu_type=FUType.FP_ADDER)
            for i in range(RS_COUNT[FUType.FP_ADDER])
        ]
        self.fp_mul_rs: List[ReservationStation] = [
            ReservationStation(name=f"Mul{i+1}", fu_type=FUType.FP_MULTIPLIER)
            for i in range(RS_COUNT[FUType.FP_MULTIPLIER])
        ]
        self.load_buffers: List[ReservationStation] = [
            ReservationStation(name=f"Load{i+1}", fu_type=FUType.LOAD)
            for i in range(RS_COUNT[FUType.LOAD])
        ]
        self.store_buffers: List[ReservationStation] = [
            ReservationStation(name=f"Store{i+1}", fu_type=FUType.STORE)
            for i in range(RS_COUNT[FUType.STORE])
        ]

    def get_all_rs(self) -> List[ReservationStation]:

        return self.fp_add_rs + self.fp_mul_rs + self.load_buffers + self.store_buffers

    def get_rs_for_fu(self, fu_type: FUType) -> List[ReservationStation]:

        mapping = {
            FUType.FP_ADDER: self.fp_add_rs,
            FUType.FP_MULTIPLIER: self.fp_mul_rs,
            FUType.LOAD: self.load_buffers,
            FUType.STORE: self.store_buffers,
        }
        return mapping[fu_type]

    def read_memory(self, address: int) -> float:

        return self.memory.get(address, float(address))

    def write_memory(self, address: int, value: float):

        self.memory[address] = value

    def load(self, program: List[Instruction]):

        self.instructions = program
        self.reset()

    def reset(self):

        self.fp_regs = [float(i * 10) for i in range(self.NUM_FP_REGS)]
        self.gp_regs = [i * 8 for i in range(self.NUM_GP_REGS)]
        self.reg_status = {i: "" for i in range(self.NUM_FP_REGS)}
        self.store_reg_status = {i: [] for i in range(self.NUM_FP_REGS)}
        self.memory = {}
        for i in range(0, 256, 8):
            self.memory[i] = float(i + 100)
        self._init_reservation_stations()
        self.pc = 0
        self.clock = 0
        self.running = False
        self.done = False
        self.halted = False
        self.cdb = None
        self.issue_count = 0
        self.exec_count = 0
        self.write_count = 0
        self.total_stalls = 0
        self.log = []
        self.snapshots = []

    def step(self) -> bool:

        if self.done:
            return False

        self.snapshots.append(self._make_snapshot())
        self.clock += 1
        self.log.append(f"--- Cycle {self.clock} ---")

        self._write_result()

        self._issue()

        self._execute()

        self._check_completion()

        return not self.done

    def run_to_completion(self, max_cycles: int = 1000):

        self.running = True
        while self.running and not self.done and self.clock < max_cycles:
            self.step()
        self.running = False

    def run_cycles(self, n: int):

        for _ in range(n):
            if self.done:
                break
            self.step()

    def _issue(self):

        if self.pc >= len(self.instructions):
            return

        inst = self.instructions[self.pc]
        fu_type = OP_TO_FU[inst.op]
        rs_list = self.get_rs_for_fu(fu_type)

        free_rs = None
        for rs in rs_list:
            if not rs.busy:
                free_rs = rs
                break

        if free_rs is None:
            self.log.append(f"  Issue stall: no free {fu_type.value} RS for [{inst.text}]")
            self.total_stalls += 1
            return

        if inst.op == OpType.SD:

            pass

        free_rs.busy = True
        free_rs.op = inst.op
        free_rs.inst_index = self.pc
        free_rs.inst_text = inst.text
        free_rs.started = False
        free_rs.Qj = ""
        free_rs.Qk = ""
        free_rs.Vj = None
        free_rs.Vk = None
        free_rs.A = None
        free_rs.dest = None
        free_rs.store_value = None

        if inst.op in (OpType.LD, OpType.SD):

            free_rs.A = inst.offset + self.gp_regs[inst.base]
            free_rs.dest = inst.dest if inst.op == OpType.LD else None
            if inst.op == OpType.SD:
                free_rs.src1 = inst.src1
                free_rs.Qj = self.reg_status.get(inst.src1, "")
                if free_rs.Qj == "":
                    free_rs.Vj = self.fp_regs[inst.src1]
                free_rs.Qk = ""
                free_rs.Vk = None
            else:

                free_rs.Qj = ""
                free_rs.Qk = ""
        else:

            free_rs.dest = inst.dest
            free_rs.Qj = self.reg_status.get(inst.src1, "")
            free_rs.Qk = self.reg_status.get(inst.src2, "")
            if free_rs.Qj == "":
                free_rs.Vj = self.fp_regs[inst.src1]
            if free_rs.Qk == "":
                free_rs.Vk = self.fp_regs[inst.src2]

        if inst.op != OpType.SD:

            self.reg_status[inst.dest] = free_rs.name
            self.store_reg_status[inst.dest].append(free_rs.name)

        self.pc += 1
        self.issue_count += 1
        self.log.append(
            f"  Issue: [{inst.text}] -> {free_rs.name} "
            f"(Vj={free_rs.Vj}, Vk={free_rs.Vk}, Qj={free_rs.Qj}, Qk={free_rs.Qk})"
        )

    def _execute(self):

        for rs in self.get_all_rs():
            if not rs.busy:
                continue

            if not rs.started:

                if rs.operands_ready and rs.cycles_remaining == 0:

                    rs.cycles_remaining = LATENCY[rs.op]
                    rs.started = True
                    self.log.append(
                        f"  Exec start: {rs.name} [{rs.inst_text}] "
                        f"latency={rs.cycles_remaining}"
                    )

            if rs.started and rs.cycles_remaining > 0:
                rs.cycles_remaining -= 1

    def _write_result(self):

        for rs in self.get_all_rs():
            if not rs.busy or not rs.started:
                continue
            if rs.cycles_remaining != 0:
                continue

            self.exec_count += 1

            result = None
            if rs.op in (OpType.LD,):
                result = self.read_memory(rs.A)
            elif rs.op in (OpType.ADD_D,):
                result = rs.Vj + rs.Vk
            elif rs.op in (OpType.SUB_D,):
                result = rs.Vj - rs.Vk
            elif rs.op in (OpType.MUL_D,):
                result = rs.Vj * rs.Vk
            elif rs.op in (OpType.DIV_D,):
                result = rs.Vj / rs.Vk if rs.Vk != 0 else float('inf')
            elif rs.op in (OpType.SD,):
                result = rs.Vj
                self.write_memory(rs.A, result)
                self.log.append(
                    f"  Write Result: {rs.name} [{rs.inst_text}] "
                    f"value={result:.2f} -> MEM[{rs.A}#0x{rs.A:04X}]"
                )

            self.cdb = CDBEntry(
                value=result,
                source_rs=rs.name,
                dest_reg=rs.dest,
                cycle=self.clock
            )

            if rs.op != OpType.SD:
                self.log.append(
                    f"  Write Result: {rs.name} [{rs.inst_text}] "
                    f"value={result:.2f} -> F{rs.dest}"
                )

            self._broadcast_cdb(rs.name, result)

            if rs.op != OpType.SD and rs.dest is not None:
                self.fp_regs[rs.dest] = result

                if self.reg_status.get(rs.dest) == rs.name:
                    self.reg_status[rs.dest] = ""
                    self.store_reg_status[rs.dest] = [
                        s for s in self.store_reg_status.get(rs.dest, [])
                        if s != rs.name
                    ]

            rs.reset()
            self.write_count += 1

            return

    def _broadcast_cdb(self, source_name: str, value: float):

        for rs in self.get_all_rs():
            if not rs.busy:
                continue
            if rs.Qj == source_name:
                rs.Vj = value
                rs.Qj = ""
            if rs.Qk == source_name:
                rs.Vk = value
                rs.Qk = ""

    def _check_completion(self):

        if self.pc >= len(self.instructions):
            all_done = all(not rs.busy for rs in self.get_all_rs())
            if all_done:
                self.done = True
                self.running = False
                self.log.append(f"=== Program completed in {self.clock} cycles ===")

    def _make_snapshot(self) -> dict:

        rs_state = []
        for rs in self.get_all_rs():
            rs_state.append({
                'name': rs.name,
                'busy': rs.busy,
                'op': rs.op.value if rs.op else '',
                'Vj': rs.Vj,
                'Vk': rs.Vk,
                'Qj': rs.Qj,
                'Qk': rs.Qk,
                'A': rs.A,
                'dest': rs.dest,
                'cycles': rs.cycles_remaining,
                'inst': rs.inst_text,
                'started': rs.started,
            })

        return {
            'clock': self.clock,
            'pc': self.pc,
            'fp_regs': list(self.fp_regs),
            'reg_status': dict(self.reg_status),
            'rs_state': rs_state,
            'memory': dict(self.memory),
        }

    def get_snapshot(self, cycle: int = -1) -> Optional[dict]:

        if not self.snapshots:
            return None
        if cycle == -1 or cycle >= len(self.snapshots):
            return self.snapshots[-1]
        if cycle < 0:
            return None
        return self.snapshots[cycle]

    def get_stats(self) -> dict:

        total_insts = len(self.instructions)
        return {
            'total_instructions': total_insts,
            'total_cycles': self.clock,
            'issued': self.issue_count,
            'executed': self.exec_count,
            'writes': self.write_count,
            'stalls': self.total_stalls,
            'ipc': self.issue_count / max(1, self.clock),
            'cpi': self.clock / max(1, self.issue_count),
            'completion_rate': f"{self.exec_count}/{total_insts}"
                if total_insts > 0 else "0/0",
        }
