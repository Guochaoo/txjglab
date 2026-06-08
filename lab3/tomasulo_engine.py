"""
Tomasulo Algorithm Simulator - Core Engine
==========================================
Self-designed Module A implementation for Lab 3.
Simulates dynamic instruction scheduling using Tomasulo's algorithm
for a MIPS-like floating-point pipeline.

Supports: LD, SD, ADD.D, SUB.D, MUL.D, DIV.D
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum
import re


# ============================================================
# Data Structures
# ============================================================

class OpType(Enum):
    """MIPS floating-point instruction opcodes."""
    LD = "LD"
    SD = "SD"
    ADD_D = "ADD.D"
    SUB_D = "SUB.D"
    MUL_D = "MUL.D"
    DIV_D = "DIV.D"


class FUType(Enum):
    """Functional unit type."""
    LOAD = "Load"
    STORE = "Store"
    FP_ADDER = "FP_Adder"
    FP_MULTIPLIER = "FP_Multiplier"


@dataclass
class Instruction:
    """A parsed MIPS FP instruction."""
    op: OpType
    dest: Optional[int] = None       # destination register number (None for SD)
    src1: Optional[int] = None       # first source register
    src2: Optional[int] = None       # second source register (None for LD/SD)
    offset: Optional[int] = None     # offset for load/store
    base: Optional[int] = None       # base register for load/store
    line: int = 0                    # source line number
    text: str = ""                   # original text

    def __str__(self):
        return self.text


# Latency table (cycles)
LATENCY: Dict[OpType, int] = {
    OpType.LD: 1,
    OpType.SD: 1,
    OpType.ADD_D: 2,
    OpType.SUB_D: 2,
    OpType.MUL_D: 10,
    OpType.DIV_D: 40,
}

# Functional unit type for each op
OP_TO_FU: Dict[OpType, FUType] = {
    OpType.LD: FUType.LOAD,
    OpType.SD: FUType.STORE,
    OpType.ADD_D: FUType.FP_ADDER,
    OpType.SUB_D: FUType.FP_ADDER,
    OpType.MUL_D: FUType.FP_MULTIPLIER,
    OpType.DIV_D: FUType.FP_MULTIPLIER,
}

# Number of reservation stations per functional unit
RS_COUNT: Dict[FUType, int] = {
    FUType.LOAD: 3,
    FUType.STORE: 3,
    FUType.FP_ADDER: 3,
    FUType.FP_MULTIPLIER: 2,
}


@dataclass
class ReservationStation:
    """A single reservation station entry."""
    name: str                        # e.g., "Add1", "Load2"
    fu_type: FUType
    busy: bool = False
    op: Optional[OpType] = None
    Vj: Optional[float] = None       # value of source operand 1
    Vk: Optional[float] = None       # value of source operand 2
    Qj: str = ""                     # RS producing source 1 (empty = ready)
    Qk: str = ""                     # RS producing source 2 (empty = ready)
    A: Optional[int] = None          # effective address for load/store
    dest: Optional[int] = None       # destination register (None for store)
    cycles_remaining: int = 0        # execution time left (0 = done or idle)
    inst_index: int = -1             # instruction index in program
    inst_text: str = ""              # original instruction text
    started: bool = False            # has execution started?
    # For store buffers: the value to store
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
        """Both operands are available."""
        return self.Qj == "" and self.Qk == ""


@dataclass
class CDBEntry:
    """Common Data Bus entry for result broadcast."""
    value: float
    source_rs: str                   # which RS produced this
    dest_reg: Optional[int] = None   # destination register
    cycle: int = 0


# ============================================================
# Instruction Parser
# ============================================================

def parse_instruction(line: str, index: int = 0) -> Optional[Instruction]:
    """
    Parse a single line of MIPS floating-point assembly.

    Supported formats:
        LD Fdest, offset(Rbase)
        SD Fsrc, offset(Rbase)
        ADD.D Fdest, Fsrc1, Fsrc2
        SUB.D Fdest, Fsrc1, Fsrc2
        MUL.D Fdest, Fsrc1, Fsrc2
        DIV.D Fdest, Fsrc1, Fsrc2
        # comment lines

    Registers: F0-F31, R0-R31
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None

    # Remove comments
    if '#' in line:
        line = line[:line.index('#')].strip()
    if not line:
        return None

    text = line

    # Match LD/SD
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

    # Match ADD.D / SUB.D / MUL.D / DIV.D
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
    """Load a program from a text file."""
    instructions = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            inst = parse_instruction(line, i)
            if inst:
                instructions.append(inst)
    return instructions


def parse_program(text: str) -> List[Instruction]:
    """Parse a program from a multi-line string."""
    instructions = []
    for i, line in enumerate(text.strip().split('\n')):
        inst = parse_instruction(line, i)
        if inst:
            instructions.append(inst)
    return instructions


# ============================================================
# Tomasulo Simulator Engine
# ============================================================

class TomasuloSimulator:
    """
    Tomasulo Algorithm Simulator.

    Architecture:
    - 32 FP registers (F0-F31)
    - 32 GP registers (R0-R31) for addressing
    - 3 FP Adder reservation stations (Add1-Add3)
    - 2 FP Multiplier reservation stations (Mul1-Mul2)
    - 3 Load buffers (Load1-Load3)
    - 3 Store buffers (Store1-Store3)
    - Single Common Data Bus (CDB)
    - 4KB main memory
    """

    NUM_FP_REGS = 32
    NUM_GP_REGS = 32
    MEM_SIZE = 4096  # bytes

    def __init__(self):
        # Register files
        self.fp_regs: List[float] = [0.0] * self.NUM_FP_REGS
        self.gp_regs: List[int] = [0] * self.NUM_GP_REGS
        # Register result status: Fx -> RS name producing value ("" = ready)
        self.reg_status: Dict[int, str] = {i: "" for i in range(self.NUM_FP_REGS)}
        # Store result status: for WAR/WAW, track which RS will store
        self.store_reg_status: Dict[int, List[str]] = {i: [] for i in range(self.NUM_FP_REGS)}

        # Memory
        self.memory: Dict[int, float] = {}  # address -> double value

        # Reservation Stations
        self._init_reservation_stations()

        # Instruction queue
        self.instructions: List[Instruction] = []
        self.pc: int = 0           # next instruction to issue

        # Execution state
        self.clock: int = 0
        self.running: bool = False
        self.done: bool = False
        self.halted: bool = False

        # CDB
        self.cdb: Optional[CDBEntry] = None

        # Statistics
        self.issue_count: int = 0
        self.exec_count: int = 0
        self.write_count: int = 0
        self.total_stalls: int = 0

        # Log for GUI display
        self.log: List[str] = []

        # Snapshot history for rollback
        self.snapshots: List[dict] = []

    def _init_reservation_stations(self):
        """Initialize all reservation stations."""
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
        """Return all reservation stations."""
        return self.fp_add_rs + self.fp_mul_rs + self.load_buffers + self.store_buffers

    def get_rs_for_fu(self, fu_type: FUType) -> List[ReservationStation]:
        """Get reservation stations for a given functional unit."""
        mapping = {
            FUType.FP_ADDER: self.fp_add_rs,
            FUType.FP_MULTIPLIER: self.fp_mul_rs,
            FUType.LOAD: self.load_buffers,
            FUType.STORE: self.store_buffers,
        }
        return mapping[fu_type]

    # ----------------------------------------------------------
    # Memory access
    # ----------------------------------------------------------
    def read_memory(self, address: int) -> float:
        """Read a double from memory at the given byte address."""
        return self.memory.get(address, float(address))  # default = address for demo

    def write_memory(self, address: int, value: float):
        """Write a double to memory at the given byte address."""
        self.memory[address] = value

    # ----------------------------------------------------------
    # Program loading
    # ----------------------------------------------------------
    def load(self, program: List[Instruction]):
        """Load a program into the simulator."""
        self.instructions = program
        self.reset()

    def reset(self):
        """Reset simulator state."""
        self.fp_regs = [float(i * 10) for i in range(self.NUM_FP_REGS)]  # demo init
        self.gp_regs = [i * 8 for i in range(self.NUM_GP_REGS)]
        self.reg_status = {i: "" for i in range(self.NUM_FP_REGS)}
        self.store_reg_status = {i: [] for i in range(self.NUM_FP_REGS)}
        self.memory = {}
        for i in range(0, 256, 8):
            self.memory[i] = float(i + 100)  # demo values
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

    # ----------------------------------------------------------
    # Core simulation: one cycle
    # ----------------------------------------------------------
    def step(self) -> bool:
        """
        Execute one clock cycle. Returns True if more cycles remain.

        Cycle order:
        1. Write Result (CDB broadcast) - check for completing instructions
        2. Issue - dispatch new instruction from queue
        3. Execute - decrement remaining cycles
        """
        if self.done:
            return False

        self.snapshots.append(self._make_snapshot())
        self.clock += 1
        self.log.append(f"--- Cycle {self.clock} ---")

        # Phase 1: Write Result (broadcast on CDB)
        self._write_result()

        # Phase 2: Issue
        self._issue()

        # Phase 3: Execute (decrement counters)
        self._execute()

        # Check if all instructions are done
        self._check_completion()

        return not self.done

    def run_to_completion(self, max_cycles: int = 1000):
        """Run until all instructions complete or max_cycles reached."""
        self.running = True
        while self.running and not self.done and self.clock < max_cycles:
            self.step()
        self.running = False

    def run_cycles(self, n: int):
        """Run for exactly n more cycles."""
        for _ in range(n):
            if self.done:
                break
            self.step()

    # ----------------------------------------------------------
    # Issue phase
    # ----------------------------------------------------------
    def _issue(self):
        """Issue up to one instruction per cycle."""
        if self.pc >= len(self.instructions):
            return

        inst = self.instructions[self.pc]
        fu_type = OP_TO_FU[inst.op]
        rs_list = self.get_rs_for_fu(fu_type)

        # Find a free reservation station
        free_rs = None
        for rs in rs_list:
            if not rs.busy:
                free_rs = rs
                break

        if free_rs is None:
            self.log.append(f"  Issue stall: no free {fu_type.value} RS for [{inst.text}]")
            self.total_stalls += 1
            return

        # Check for structural hazard on store buffers:
        # For SD, also check if there are prior pending stores (simplification)
        if inst.op == OpType.SD:
            # Check WAR/WAW: cannot issue if an earlier store to same dest is pending
            # In Tomasulo, this is handled by renaming
            pass

        # Allocate RS
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

        # Set up operands
        if inst.op in (OpType.LD, OpType.SD):
            # Load/Store: compute effective address
            free_rs.A = inst.offset + self.gp_regs[inst.base]
            free_rs.dest = inst.dest if inst.op == OpType.LD else None
            if inst.op == OpType.SD:
                free_rs.src1 = inst.src1
                free_rs.Qj = self.reg_status.get(inst.src1, "")
                if free_rs.Qj == "":
                    free_rs.Vj = self.fp_regs[inst.src1]
                free_rs.Qk = ""  # No second operand for store
                free_rs.Vk = None
            else:
                # LD: no source register operand
                free_rs.Qj = ""
                free_rs.Qk = ""
        else:
            # FP arithmetic: ADD.D, SUB.D, MUL.D, DIV.D
            free_rs.dest = inst.dest
            free_rs.Qj = self.reg_status.get(inst.src1, "")
            free_rs.Qk = self.reg_status.get(inst.src2, "")
            if free_rs.Qj == "":
                free_rs.Vj = self.fp_regs[inst.src1]
            if free_rs.Qk == "":
                free_rs.Vk = self.fp_regs[inst.src2]

        # Update register result status (register renaming for dest)
        if inst.op != OpType.SD:
            # WAW hazard: this new write supersedes older pending writes
            self.reg_status[inst.dest] = free_rs.name
            self.store_reg_status[inst.dest].append(free_rs.name)

        self.pc += 1
        self.issue_count += 1
        self.log.append(
            f"  Issue: [{inst.text}] -> {free_rs.name} "
            f"(Vj={free_rs.Vj}, Vk={free_rs.Vk}, Qj={free_rs.Qj}, Qk={free_rs.Qk})"
        )

    # ----------------------------------------------------------
    # Execute phase
    # ----------------------------------------------------------
    def _execute(self):
        """Decrement remaining cycle counters and start execution when ready."""
        for rs in self.get_all_rs():
            if not rs.busy:
                continue

            if not rs.started:
                # Check if operands are ready
                if rs.operands_ready and rs.cycles_remaining == 0:
                    # Start execution
                    rs.cycles_remaining = LATENCY[rs.op]
                    rs.started = True
                    self.log.append(
                        f"  Exec start: {rs.name} [{rs.inst_text}] "
                        f"latency={rs.cycles_remaining}"
                    )

            if rs.started and rs.cycles_remaining > 0:
                rs.cycles_remaining -= 1

    # ----------------------------------------------------------
    # Write Result phase (CDB broadcast)
    # ----------------------------------------------------------
    def _write_result(self):
        """Check for completed operations and broadcast results on CDB."""
        # Only one result can be written per cycle (single CDB)
        for rs in self.get_all_rs():
            if not rs.busy or not rs.started:
                continue
            if rs.cycles_remaining != 0:
                continue

            # This RS has finished execution → write result on CDB
            self.exec_count += 1

            # Compute result
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
                result = rs.Vj  # store value
                self.write_memory(rs.A, result)
                self.log.append(
                    f"  Write Result: {rs.name} [{rs.inst_text}] "
                    f"value={result:.2f} -> MEM[{rs.A}#0x{rs.A:04X}]"
                )

            # Broadcast result on CDB
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

            # Update all waiting reservation stations
            self._broadcast_cdb(rs.name, result)

            # Update register file
            if rs.op != OpType.SD and rs.dest is not None:
                self.fp_regs[rs.dest] = result
                # Clear register status if this RS was the expected producer
                if self.reg_status.get(rs.dest) == rs.name:
                    self.reg_status[rs.dest] = ""
                    self.store_reg_status[rs.dest] = [
                        s for s in self.store_reg_status.get(rs.dest, [])
                        if s != rs.name
                    ]

            # Free the RS
            rs.reset()
            self.write_count += 1

            # Only one write per cycle
            return

    def _broadcast_cdb(self, source_name: str, value: float):
        """
        Broadcast CDB result to all waiting reservation stations.
        Updates Vj/Vk and clears Qj/Qk for any RS waiting on source_name.
        Also updates register file for any pending loads.
        """
        for rs in self.get_all_rs():
            if not rs.busy:
                continue
            if rs.Qj == source_name:
                rs.Vj = value
                rs.Qj = ""
            if rs.Qk == source_name:
                rs.Vk = value
                rs.Qk = ""

    # ----------------------------------------------------------
    # Completion check
    # ----------------------------------------------------------
    def _check_completion(self):
        """Check if all instructions have been issued and executed."""
        if self.pc >= len(self.instructions):
            all_done = all(not rs.busy for rs in self.get_all_rs())
            if all_done:
                self.done = True
                self.running = False
                self.log.append(f"=== Program completed in {self.clock} cycles ===")

    # ----------------------------------------------------------
    # Snapshots for rollback/display
    # ----------------------------------------------------------
    def _make_snapshot(self) -> dict:
        """Create a snapshot of current state."""
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
        """Get the snapshot for a specific cycle (-1 = latest)."""
        if not self.snapshots:
            return None
        if cycle == -1 or cycle >= len(self.snapshots):
            return self.snapshots[-1]
        if cycle < 0:
            return None
        return self.snapshots[cycle]

    # ----------------------------------------------------------
    # Statistics
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        """Return execution statistics."""
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
