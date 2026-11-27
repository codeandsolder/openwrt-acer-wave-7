#!/usr/bin/env python3
"""Check page-pool counter identity, path accounting and reset handling."""
import importlib.util
from pathlib import Path

p = Path(__file__).with_name("load-ap-delta.py")
spec = importlib.util.spec_from_file_location("load_delta", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
zero = dict.fromkeys(mod.POOL_COUNTERS, 0)
counts = zero | dict(alloc_fast=90, alloc_refill=5, alloc_slow=5, alloc_empty=5,
                     recycle_cached=20, recycle_ring=70, recycle_cache_full=80,
                     recycle_ring_full=5, recycle_released_refcnt=5)
lines = [f"{k} {v}" for k, v in counts.items()]
assert mod.parse_page_pool(lines) == counts
delta = mod.page_pool_delta({"radio": zero}, {"radio": counts})["radio"]
assert delta["allocation_calls"] == 100
assert delta["cache_or_ring_served_pct"] == 95
assert delta["return_events"] == 100 and delta["recycled_return_pct"] == 90
empty = mod.page_pool_delta({"radio": zero}, {"radio": zero})["radio"]
assert empty["cache_or_ring_served_pct"] is None and empty["recycled_return_pct"] is None
cases = [lines[:-1], lines + [lines[0]], ["invalid 1"] + lines[1:],
         [f"{lines[0].split()[0]} -1"] + lines[1:],
         [f"{lines[0].split()[0]} {2**64}"] + lines[1:]]
for broken in cases:
    try:
        mod.parse_page_pool(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted corrupt page pool statistics")
for a, b in [({"radio": counts}, {"radio": zero}), ({"radio": zero}, {"other": zero})]:
    try:
        mod.page_pool_delta(a, b)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted reset or changed radio")
print("PAGE_POOL_TELEMETRY_PASS valid=2 rejected=7")
