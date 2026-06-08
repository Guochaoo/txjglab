"""
Batch Test Runner for Cache Simulator Lab 4
===========================================
Runs all parameter combinations across all 4 trace files and exports results.
Generates a CSV summary for analysis and report writing.

Test matrix:
  4 traces × 4 cache sizes × 4 associativities × 4 block sizes = 256 combinations
"""

import os
import csv
import time
from cache_engine import CacheSimulator

TRACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trace')

TRACE_FILES = {
    "085.gcc.din": "GCC Compiler",
    "022.li.din": "Lisp Interpreter",
    "047.tomcatv.din": "Tomcatv (Vector)",
    "078.swm256.din": "Swim (Shallow Water)",
}

CACHE_SIZES = [8*1024, 16*1024, 32*1024, 64*1024]
CACHE_SIZE_LABELS = ["8KB", "16KB", "32KB", "64KB"]
ASSOCIATIVITIES = [1, 2, 4, 8]
BLOCK_SIZES = [16, 32, 64, 128]
BLOCK_SIZE_LABELS = ["16B", "32B", "64B", "128B"]

# By default, use first 200K lines for speed; set to -1 for complete traces
MAX_LINES = 200000


def run_batch(max_lines=MAX_LINES, output_csv="batch_results.csv"):
    """Run all parameter combinations."""
    results = []
    total = len(TRACE_FILES) * len(CACHE_SIZES) * len(ASSOCIATIVITIES) * len(BLOCK_SIZES)
    idx = 0
    start_time = time.time()

    print("=" * 80)
    print(f"CACHE SIMULATOR BATCH TEST")
    print(f"Max lines per trace: {max_lines if max_lines > 0 else 'ALL'}")
    print(f"Total test cases: {total}")
    print(f"Output: {output_csv}")
    print("=" * 80)

    for trace_name, trace_desc in sorted(TRACE_FILES.items()):
        trace_path = os.path.join(TRACE_DIR, trace_name)
        if not os.path.exists(trace_path):
            print(f"  [SKIP] Trace not found: {trace_path}")
            continue

        for size, size_label in zip(CACHE_SIZES, CACHE_SIZE_LABELS):
            for assoc in ASSOCIATIVITIES:
                for block, block_label in zip(BLOCK_SIZES, BLOCK_SIZE_LABELS):
                    idx += 1
                    sim = CacheSimulator(cache_size=size, associativity=assoc, block_size=block)
                    stats = sim.run_trace(trace_path, max_lines=max_lines)
                    d = stats.to_dict()
                    d['trace'] = trace_name
                    d['trace_desc'] = trace_desc
                    d['cache_size_label'] = size_label
                    d['cache_size'] = size
                    d['associativity'] = assoc
                    d['block_size_label'] = block_label
                    d['block_size'] = block
                    results.append(d)

                    elapsed = time.time() - start_time
                    eta = (elapsed / idx) * (total - idx) if idx > 0 else 0
                    print(
                        f"  [{idx:3d}/{total}] {trace_name:18s} {size_label:4s} "
                        f"{assoc}-way {block_label:3s} | "
                        f"Hit: {d['hit_rate']*100:6.2f}%  Miss: {d['miss_rate']*100:6.2f}% | "
                        f"Rep: {d['replacements']:6d}  WB: {d['writebacks']:6d} | "
                        f"Elapsed: {elapsed:.0f}s  ETA: {eta:.0f}s"
                    )

    # Export to CSV
    fieldnames = [
        'trace', 'trace_desc', 'cache_size_label', 'cache_size',
        'associativity', 'block_size_label', 'block_size',
        'total_accesses', 'reads', 'writes', 'instruction_fetches',
        'total_hits', 'total_misses', 'hit_rate', 'miss_rate',
        'read_hits', 'read_misses', 'read_hit_rate',
        'write_hits', 'write_misses', 'write_hit_rate',
        'instruction_hits', 'instruction_misses',
        'replacements', 'writebacks', 'lines_processed'
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)

    total_time = time.time() - start_time
    print()
    print("=" * 80)
    print(f"BATCH COMPLETE: {len(results)}/{total} test cases")
    print(f"Total time: {total_time:.1f}s")
    print(f"Results saved to: {output_csv}")
    print("=" * 80)

    # Print summary table
    print_summary(results)
    return results


def print_summary(results):
    """Print a summary table grouped by trace and cache size."""
    print()
    print("SUMMARY: Average Hit Rate by Cache Size and Associativity")
    print("-" * 70)

    # Group by cache_size_label and associativity
    from collections import defaultdict
    grouped = defaultdict(list)

    for r in results:
        key = (r['cache_size_label'], r['associativity'])
        grouped[key].append(r['hit_rate'])

    assocs = sorted(set(r['associativity'] for r in results))
    sizes = ["8KB", "16KB", "32KB", "64KB"]

    # Header
    header = f"{'Size':>6s}"
    for a in assocs:
        header += f"  {a}-way"
    print(header)
    print("-" * 70)

    for size in sizes:
        row = f"{size:>6s}"
        for a in assocs:
            rates = grouped.get((size, a), [])
            avg = sum(rates) / len(rates) * 100 if rates else 0
            row += f"  {avg:5.1f}%"
        print(row)

    print()
    print("SUMMARY: Best Configuration per Trace")
    print("-" * 70)
    print(f"{'Trace':<20s} {'Size':>6s} {'Assoc':>6s} {'Block':>6s} {'Hit Rate':>10s}")
    print("-" * 70)

    traces = sorted(set(r['trace'] for r in results))
    for trace in traces:
        trace_results = [r for r in results if r['trace'] == trace]
        best = max(trace_results, key=lambda r: r['hit_rate'])
        assoc_str = f"{best['associativity']}-way"
        print(
            f"{best['trace_desc']:<20s} "
            f"{best['cache_size_label']:>6s} "
            f"{assoc_str:>6s} "
            f"{best['block_size_label']:>6s} "
            f"{best['hit_rate']*100:>9.2f}%"
        )


if __name__ == '__main__':
    run_batch(max_lines=MAX_LINES, output_csv="batch_results.csv")
