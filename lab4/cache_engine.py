from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import struct
import time

@dataclass
class CacheLine:

    tag: int = 0
    valid: bool = False
    dirty: bool = False
    lru_age: int = 0

    def reset(self):
        self.tag = 0
        self.valid = False
        self.dirty = False
        self.lru_age = 0

@dataclass
class CacheSet:

    ways: List[CacheLine] = field(default_factory=list)

    def __init__(self, associativity: int):
        self.ways = [CacheLine() for _ in range(associativity)]
        self._lru_counter = 0

    def access(self, tag: int, is_write: bool = False) -> Tuple[bool, bool, bool]:

        for way in self.ways:
            if way.valid and way.tag == tag:

                self._lru_counter += 1
                way.lru_age = self._lru_counter
                if is_write:
                    way.dirty = True
                return True, False, False

        lru_way = None
        lru_min_age = float('inf')
        for way in self.ways:
            if not way.valid:

                lru_way = way
                break
            if way.lru_age < lru_min_age:
                lru_min_age = way.lru_age
                lru_way = way

        replaced = lru_way.valid
        was_dirty = lru_way.dirty
        lru_way.valid = True
        lru_way.tag = tag
        lru_way.dirty = is_write
        self._lru_counter += 1
        lru_way.lru_age = self._lru_counter

        return False, replaced, was_dirty

    def find_line(self, tag: int) -> Optional[CacheLine]:

        for way in self.ways:
            if way.valid and way.tag == tag:
                return way
        return None

@dataclass
class CacheStats:

    total_accesses: int = 0
    reads: int = 0
    writes: int = 0
    read_hits: int = 0
    write_hits: int = 0
    read_misses: int = 0
    write_misses: int = 0
    replacements: int = 0
    writebacks: int = 0
    instruction_fetches: int = 0
    instruction_hits: int = 0
    instruction_misses: int = 0
    lines_processed: int = 0

    @property
    def total_hits(self) -> int:
        return self.read_hits + self.write_hits + self.instruction_hits

    @property
    def total_misses(self) -> int:
        return self.read_misses + self.write_misses + self.instruction_misses

    @property
    def hit_rate(self) -> float:
        return self.total_hits / max(1, self.total_accesses)

    @property
    def miss_rate(self) -> float:
        return self.total_misses / max(1, self.total_accesses)

    @property
    def read_hit_rate(self) -> float:
        return self.read_hits / max(1, self.reads)

    @property
    def write_hit_rate(self) -> float:
        return self.write_hits / max(1, self.writes)

    def to_dict(self) -> dict:
        return {
            'total_accesses': self.total_accesses,
            'reads': self.reads,
            'writes': self.writes,
            'instruction_fetches': self.instruction_fetches,
            'total_hits': self.total_hits,
            'total_misses': self.total_misses,
            'read_hits': self.read_hits,
            'read_misses': self.read_misses,
            'write_hits': self.write_hits,
            'write_misses': self.write_misses,
            'instruction_hits': self.instruction_hits,
            'instruction_misses': self.instruction_misses,
            'hit_rate': self.hit_rate,
            'miss_rate': self.miss_rate,
            'read_hit_rate': self.read_hit_rate,
            'write_hit_rate': self.write_hit_rate,
            'replacements': self.replacements,
            'writebacks': self.writebacks,
            'lines_processed': self.lines_processed,
        }

class CacheSimulator:

    VALID_SIZES = {8 * 1024, 16 * 1024, 32 * 1024, 64 * 1024}
    VALID_ASSOC = {1, 2, 4, 8}
    VALID_BLOCK = {16, 32, 64, 128}

    def __init__(self, cache_size: int = 16 * 1024,
                 associativity: int = 4,
                 block_size: int = 32):

        if cache_size not in self.VALID_SIZES:
            raise ValueError(f"cache_size must be one of {self.VALID_SIZES}")
        if associativity not in self.VALID_ASSOC:
            raise ValueError(f"associativity must be one of {self.VALID_ASSOC}")
        if block_size not in self.VALID_BLOCK:
            raise ValueError(f"block_size must be one of {self.VALID_BLOCK}")

        self.cache_size = cache_size
        self.associativity = associativity
        self.block_size = block_size

        self.num_sets = cache_size // (associativity * block_size)
        self.block_offset_bits = self._log2(block_size)
        self.index_bits = self._log2(self.num_sets) if self.num_sets > 0 else 0
        self.tag_bits = 32 - self.index_bits - self.block_offset_bits

        self.block_mask = (1 << self.block_offset_bits) - 1
        self.index_mask = ((1 << self.index_bits) - 1) if self.index_bits > 0 else 0
        self.tag_mask = 0xFFFFFFFF & ~(self.block_mask | (self.index_mask << self.block_offset_bits))

        self.sets: List[CacheSet] = [
            CacheSet(associativity) for _ in range(max(1, self.num_sets))
        ]

        self.stats = CacheStats()

        self.lines_processed = 0

    @staticmethod
    def _log2(x: int) -> int:

        if x <= 1:
            return 0
        bits = 0
        while x > 1:
            x >>= 1
            bits += 1
        return bits

    def _decompose_address(self, address: int) -> Tuple[int, int, int]:

        block_offset = address & self.block_mask
        index = (address >> self.block_offset_bits) & self.index_mask if self.index_bits > 0 else 0
        tag = address >> (self.block_offset_bits + self.index_bits) if (self.block_offset_bits + self.index_bits) > 0 else address
        return tag, index, block_offset

    def access(self, address: int, access_type: int) -> Tuple[bool, bool, bool]:

        tag, index, offset = self._decompose_address(address)
        is_write = (access_type == 1)

        self.stats.total_accesses += 1
        if access_type == 0:
            self.stats.reads += 1
        elif access_type == 1:
            self.stats.writes += 1
        elif access_type == 2:
            self.stats.instruction_fetches += 1

        cache_set = self.sets[index]
        hit, replaced, was_dirty = cache_set.access(tag, is_write)

        if hit:
            if access_type == 0:
                self.stats.read_hits += 1
            elif access_type == 1:
                self.stats.write_hits += 1
            elif access_type == 2:
                self.stats.instruction_hits += 1
        else:

            if access_type == 0:
                self.stats.read_misses += 1
            elif access_type == 1:
                self.stats.write_misses += 1

            elif access_type == 2:
                self.stats.instruction_misses += 1

            if replaced:
                self.stats.replacements += 1
            if was_dirty:
                self.stats.writebacks += 1

        return hit, replaced, was_dirty

    def run_trace(self, trace_file: str, max_lines: int = -1,
                  progress_callback=None) -> CacheStats:

        self.reset_stats()
        start_time = time.time()

        total_lines = 0
        if progress_callback:
            with open(trace_file, 'r') as f:
                for _ in f:
                    total_lines += 1
                    if max_lines > 0 and total_lines >= max_lines:
                        break

        with open(trace_file, 'r') as f:
            for line_num, line in enumerate(f):
                if max_lines > 0 and line_num >= max_lines:
                    break

                line = line.strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) < 2:
                    continue

                try:
                    access_type = int(parts[0])
                    address = int(parts[1], 16)
                except ValueError:
                    continue

                self.access(address, access_type)
                self.lines_processed = line_num + 1

                if progress_callback and total_lines > 0 and line_num % 50000 == 0:
                    progress_callback(line_num, total_lines)

        self.stats.lines_processed = self.lines_processed
        return self.stats

    def reset_stats(self):

        self.stats = CacheStats()
        self.lines_processed = 0

    def reset_cache(self):

        for s in self.sets:
            for way in s.ways:
                way.reset()
        self.reset_stats()

    def reconfigure(self, cache_size: int = None, associativity: int = None,
                    block_size: int = None):

        if cache_size is not None:
            self.cache_size = cache_size
        if associativity is not None:
            self.associativity = associativity
        if block_size is not None:
            self.block_size = block_size

        self.num_sets = self.cache_size // (self.associativity * self.block_size)
        self.block_offset_bits = self._log2(self.block_size)
        self.index_bits = self._log2(self.num_sets) if self.num_sets > 0 else 0
        self.tag_bits = 32 - self.index_bits - self.block_offset_bits

        self.block_mask = (1 << self.block_offset_bits) - 1
        self.index_mask = ((1 << self.index_bits) - 1) if self.index_bits > 0 else 0
        self.tag_mask = 0xFFFFFFFF & ~(self.block_mask | (self.index_mask << self.block_offset_bits))

        self.sets = [CacheSet(self.associativity) for _ in range(max(1, self.num_sets))]
        self.reset_stats()

    def get_config_description(self) -> str:

        if self.associativity == 1:
            assoc_str = "Direct-mapped"
        elif self.associativity == self.cache_size // self.block_size:
            assoc_str = "Fully-associative"
        else:
            assoc_str = f"{self.associativity}-way set-associative"

        return (f"Cache: {self.cache_size // 1024}KB, {assoc_str}, "
                f"Block={self.block_size}B, Sets={self.num_sets}, "
                f"Replacement=LRU, WritePolicy=Write-Allocate")
