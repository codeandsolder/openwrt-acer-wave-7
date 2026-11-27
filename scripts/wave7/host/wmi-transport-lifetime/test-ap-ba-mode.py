#!/usr/bin/env python3
"""Compile the actual AP BA-mode block against a WMI recorder."""
import argparse
from pathlib import Path
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path, help='ath12k source directory')
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    text = (a.source / 'mac.c').read_text()
    match = re.search(r'if \(arvif->is_up && info->he_support\) \{', text)
    assert match
    begin, end, depth = match.start(), match.end(), 1
    while depth:
        c = text[end]
        depth += (c == '{') - (c == '}')
        end += 1
    block = text[begin:end]
    h = (a.source / 'wmi.h').read_text()
    constants = '\n'.join(re.search(r'^#define '+name+r'\s+\d+$', h, re.M)[0] for name in ('WMI_BA_MODE_BUFFER_SIZE_256','WMI_BA_MODE_BUFFER_SIZE_1024'))
    fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#define WMI_VDEV_PARAM_BA_MODE 1
#define WMI_VDEV_PARAM_HEOPS_0_31 2
#define ATH12K_DBG_MAC 0
#define ath12k_warn(...) (++warnings)
#define ath12k_dbg(...) ((void)0)
struct radio { void *ab; };
struct link { bool is_up; unsigned vdev_id; };
struct bss { bool he_support, eht_support; struct { uint32_t params; } he_oper; };
static unsigned count, warnings, failures;
static unsigned params[2], values[2];
static int ath12k_wmi_vdev_set_param_cmd(struct radio *ar, unsigned vdev, unsigned param, unsigned value) {
    (void)ar; assert(vdev == 17); assert(count < 2);
    params[count] = param; values[count] = value;
    return (failures & (1U << count++)) ? -1 : 0;
}
static void run(struct radio *ar, struct link *arvif, struct bss *info) {
    unsigned param_id, param_value; int ret;
    SOURCE_BLOCK
}
int main(void) {
    struct radio radio = {0}; unsigned cases = 0;
    for (unsigned up=0; up<2; ++up) for (unsigned he=0; he<2; ++he)
      for (unsigned eht=0; eht<2; ++eht) for (unsigned op=0; op<2; ++op)
        for (failures=0; failures<4; ++failures) {
            struct link link = {up,17}; struct bss bss = {he,eht,{op ? 0x1234 : 0}};
            count=warnings=0; run(&radio,&link,&bss);
            unsigned expected=up && he ? 1+op : 0;
            assert(count == expected);
            if (expected) {
                assert(params[0] == WMI_VDEV_PARAM_BA_MODE);
                assert(values[0] == (eht ? 6 : 3));
                assert(warnings == (unsigned)(!!(failures&1) + (op && !!(failures&2))));
                if (op) { assert(params[1] == WMI_VDEV_PARAM_HEOPS_0_31); assert(values[1] == 0x1234); }
            } else assert(!warnings);
            ++cases;
        }
    printf("AP_BA_MODE_PASS cases=%u\n", cases);
}
'''
    a.out.mkdir(parents=True, exist_ok=True)
    src=a.out/'ap-ba-mode.c';obj=a.out/'ap-ba-mode.o';exe=a.out/'ap-ba-mode'
    src.write_text(constants+'\n'+fixture.replace('SOURCE_BLOCK',block))
    subprocess.run(['/usr/local/bin/sccache','/usr/bin/cc','-std=c11','-Wall','-Wextra','-Werror','-c',src,'-o',obj],check=True)
    subprocess.run(['/usr/bin/cc',obj,'-o',exe],check=True)
    subprocess.run([exe],check=True)


if __name__ == '__main__':
    main()
