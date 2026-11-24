#!/usr/bin/env python3
"""Compile and test the actual patched C policy (no duplicate implementation).

Usage: uv run --no-project python test-policy.py PATCHED_RTL8365MB_MAIN_C
Uses the existing managed sccache; all temporary outputs are removed.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()

def extract(pattern):
    match = re.search(pattern, source, re.MULTILINE | re.DOTALL)
    if match is None:
        raise ValueError(f"missing source fragment: {pattern}")
    return match.group(0)

policy = "\n".join((
    extract(r"^struct rtl8365mb_sds_rx_sample \{.*?^\};"),
    extract(r"^struct rtl8365mb_sds_rx_health \{.*?^\};"),
    extract(r"^#define RTL8365MB_D_SDS_RX_MIN_ERRORS[^\n]*"),
    extract(r"^#define RTL8365MB_D_SDS_RX_MIN_INTERVALS[^\n]*"),
    extract(r"^static bool\nrtl8365mb_sds_rx_fault\(.*?^\}"),
))

tests = r"""
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
"""
body = r"""
static bool sample(struct rtl8365mb_sds_rx_health *h,
                   u32 ucast, u32 mcast, u32 bcast, u32 fcs, u32 fragments)
{
    struct rtl8365mb_sds_rx_sample s = { { ucast, mcast, bcast }, fcs, fragments };
    return rtl8365mb_sds_rx_fault(h, &s);
}
int main(void)
{
    struct rtl8365mb_sds_rx_health h = {0};

    // First sample is only a baseline: historic errors are not evidence.
    assert(!sample(&h, 0, 0, 0, 71, 55));
    assert(!sample(&h, 0, 0, 0, 71, 55)); // idle
    // Synthetic split of captured +11 CRC / +4 fragment fault.
    assert(!sample(&h, 0, 0, 0, 76, 57));
    assert(sample(&h, 0, 0, 0, 82, 59));
    assert(h.bad_events == 15 && h.bad_intervals == 2);

    // After a relatch, old observations must not trigger another edge.
    h.valid = false;
    assert(!sample(&h, 0, 0, 0, 82, 59));
    assert(!sample(&h, 0, 0, 0, 90, 59));
    assert(!sample(&h, 0, 0, 0, 90, 59)); // idle breaks streak
    assert(!sample(&h, 0, 0, 0, 94, 59));
    assert(sample(&h, 0, 0, 0, 98, 59)); // exact threshold

    // Real valid ingress breaks a corrupt-only episode, even if errors
    // also increase. Independently cover all three frame counter types.
    for (int i = 0; i < 3; ++i) {
        struct rtl8365mb_sds_rx_sample s = h.last;
        s.good[i]++;
        s.fcs+=100;
        assert(!rtl8365mb_sds_rx_fault(&h, &s));
        assert(h.bad_events == 0 && h.bad_intervals == 0);
    }
    h=(struct rtl8365mb_sds_rx_health){0};
    assert(!sample(&h, 0, 0, 0, 0, 0));
    for (u32 i=1;i<8;++i)
        assert(!sample(&h, 0, 0, 0, i, 0));
    assert(sample(&h, 0, 0, 0, 8, 0)); // sustained sparse corruption

    // Reset or wrap of any sampled 32-bit counter is not traffic evidence.
    h=(struct rtl8365mb_sds_rx_health){0};
    assert(!sample(&h, 0, 0, 0, UINT32_MAX-10, 0));
    assert(!sample(&h, 0, 0, 0, UINT32_MAX, 0));
    assert(!sample(&h, 0, 0, 0, 1, 0));
    assert(h.bad_events == 0);
    assert(!sample(&h, 0, 0, 0, 5, 0));
    h.valid=false; // failed read
    assert(!sample(&h, 0, 0, 0, 20, 0));
    assert(h.bad_events == 0);
    assert(!sample(&h, 0, 0, 0, 25, 0));
    assert(sample(&h, 0, 0, 0, 30, 0));

    // Neither stale errors nor ordinary healthy busy traffic are faults.
    h=(struct rtl8365mb_sds_rx_health){0};
    for (u32 i=0;i<1000;++i)
        assert(!sample(&h, i, i*3, i*4, i, i));
    puts("RTL8367D_TRUNK_POLICY_PASS");
    return 0;
}
"""
env = {**os.environ, "SCCACHE_NO_AUTO_START_SERVER": "1", "SCCACHE_START_SERVER": "0"}
cc = os.environ.get("CC", "/usr/bin/gcc")
cache = os.environ.get("SCCACHE", "/usr/local/bin/sccache")
with tempfile.TemporaryDirectory(prefix="wave7-trunk-test-") as temp:
    d = Path(temp)
    c = d / "test.c"
    c.write_text(tests + policy + "\n" + body)
    subprocess.run([cache, cc, "-std=c11", "-Wall", "-Wextra",
                    "-Werror", "-Wno-sign-compare", "-O2", "-c", str(c),
                    "-o", str(d/"test.o")], check=True, env=env)
    subprocess.run([cc, str(d/"test.o"), "-o", str(d/"test")], check=True, env=env)
    subprocess.run([str(d/"test")], check=True, env=env)
