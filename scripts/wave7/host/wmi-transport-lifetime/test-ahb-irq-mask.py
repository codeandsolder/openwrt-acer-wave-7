#!/usr/bin/env python3
"""Exercise the actual AHB TX IRQ selection block over all ring masks."""
import argparse
from pathlib import Path
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    text = (a.source / 'ahb.c').read_text()
    start = text.index('static int ath12k_ahb_config_ext_irq(')
    tail = text[start:]
    match = re.search(r'\n\s*for \(j = 0;[^\n]+\n\s*if \(ring_mask->tx\[i\].*?\n\s*}\n\s*}', tail, re.S)
    if not match:
        raise ValueError('missing TX IRQ selection block')
    # The physical WBM table is intentionally nonidentity at logical TCL3.
    shim = '''#include <assert.h>
#include <stdio.h>
#define BIT(i) (1U << (i))
#define ATH12K_EXT_IRQ_NUM_MAX 4
#define DP_TCL_NUM_RING_MAX 4
#define wbm2host_tx_completions_ring1 63
struct mask { unsigned tx[1]; };
struct params { int max_tx_ring; };
struct hal_map { int wbm_ring_num; };
struct base { struct params *hw_params; struct { struct hal_map tcl_to_wbm_rbm_map[4]; } hal; };
struct group { int irqs[4]; };
static void check(int rings, unsigned mask, unsigned occupied) {
    struct mask masks = {{mask}};
    struct mask *ring_mask = &masks;
    struct params params = {rings};
    struct base base = {&params, {{{0}, {1}, {2}, {4}}}};
    struct base *ab = &base;
    struct group group = {{-1,-1,-1,-1}};
    struct group *irq_grp = &group;
    int i = 0, j;
    unsigned num_irq = occupied;
    (void)ab;
/* ACTUAL BLOCK */
    unsigned expected = occupied;
    for (int ring = 0; ring < rings && expected < ATH12K_EXT_IRQ_NUM_MAX; ++ring) {
        if (mask & BIT(ring)) {
            assert(group.irqs[expected] == wbm2host_tx_completions_ring1 - ring);
            ++expected;
        }
    }
    assert(num_irq == expected);
    for (unsigned k = 0; k < occupied; ++k) assert(group.irqs[k] == -1);
    for (unsigned k = expected; k < ATH12K_EXT_IRQ_NUM_MAX; ++k) assert(group.irqs[k] == -1);
}
int main(void) {
    unsigned cases = 0;
    for (int rings = 1; rings <= 4; ++rings)
        for (unsigned mask = 0; mask < 32; ++mask)
            for (unsigned occupied = 0; occupied <= 4; ++occupied) {
                check(rings, mask, occupied);
                ++cases;
            }
    printf("AHB_TX_IRQ_MASK_PASS cases=%u\\n", cases);
}
'''
    a.output.mkdir(parents=True, exist_ok=True)
    c = a.output / 'ahb-irq-mask.c'
    obj = a.output / 'ahb-irq-mask.o'
    exe = a.output / 'ahb-irq-mask'
    c.write_text(shim.replace('/* ACTUAL BLOCK */', match[0]))
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
