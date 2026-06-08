"""Quick test script for the Cache engine."""
import os
from cache_engine import CacheSimulator

TRACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trace')

# Test with GCC trace
trace_path = os.path.join(TRACE_DIR, '085.gcc.din')
print(f'Testing Cache Simulator with {trace_path}')
print(f'File exists: {os.path.exists(trace_path)}')

if os.path.exists(trace_path):
    sim = CacheSimulator(cache_size=16*1024, associativity=4, block_size=32)
    print(f'Config: {sim.get_config_description()}')

    stats = sim.run_trace(trace_path, max_lines=50000)
    d = stats.to_dict()
    print(f"Processed: {d['lines_processed']:,} lines")
    print(f"Total accesses: {d['total_accesses']:,}")
    print(f"Hit rate: {d['hit_rate']*100:.2f}%")
    print(f"Miss rate: {d['miss_rate']*100:.2f}%")
    print(f"Read hit rate: {d['read_hit_rate']*100:.2f}%")
    print(f"Write hit rate: {d['write_hit_rate']*100:.2f}%")
    print(f"Replacements: {d['replacements']:,}")
    print(f"Writebacks: {d['writebacks']:,}")
    print()
    print('Test passed!')
else:
    print(f'Trace file not found at {trace_path}')
    # List what's in the trace dir
    if os.path.exists(TRACE_DIR):
        print(f'Contents of {TRACE_DIR}:')
        for f in os.listdir(TRACE_DIR):
            print(f'  {f}')
    else:
        print(f'Trace dir {TRACE_DIR} does not exist')
