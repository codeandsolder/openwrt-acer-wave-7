#!/usr/bin/env python3
"""Exhaust hardware TX count, release-source, reason and list-position fields."""
import argparse
from pathlib import Path
import re
import subprocess


def one(text, pattern):
    matches = re.findall(pattern, text, re.M | re.S)
    if len(matches) != 1:
        raise ValueError(f'expected one match for {pattern}, got {len(matches)}')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.source
    dp = (root / 'dp.h').read_text()
    tx = (root / 'wifi7/dp_tx.c').read_text()
    hal = (root / 'hal.h').read_text()
    desc = (root / 'wifi7/hal_desc.h').read_text()
    txh = (root / 'wifi7/hal_tx.h').read_text()
    mac = (root / 'mac.h').read_text()
    dims = '\n'.join(re.findall(r'^#define ATH12K_TX_ATTEMPT_(?:REASONS|COUNTS) [^\n]+', dp, re.M))
    assert len(dims.splitlines()) == 2
    enums = '\n'.join(one(header, rf'^enum {name} \{{.*?^\}};')
                     for header, name in ((hal, 'hal_wbm_rel_src_module'),
                                          (hal, 'hal_tx_rate_stats_pkt_type'),
                                          (hal, 'hal_tx_rate_stats_sgi'),
                                          (mac, 'ath12k_supported_bw'),
                                          (desc, 'hal_wbm_tqm_rel_reason'),
                                          (dp, 'ath12k_tx_attempt_class')))
    structs = '\n'.join(one(header, rf'^struct {name} \{{.*?^\}}[^\n]*;')
                       for header, name in ((desc, 'hal_tx_rate_stats'),
                                            (desc, 'hal_wbm_completion_ring_tx'),
                                            (dp, 'ath12k_tx_attempt_stats'),
                                            (txh, 'hal_tx_status')))
    defs = '\n'.join(re.findall(r'^#define HAL_(?:WBM_COMPL_TX_INFO\d|TX_RATE_STATS_INFO0|TX_STATUS_FLAGS)_\w+[^\n]+',
                               desc + '\n' + txh, re.M))
    parse = one(tx, r'^static void\nath12k_wifi7_dp_tx_status_parse\(.*?^\}')
    helper = one(tx, r'^static void\nath12k_wifi7_dp_tx_count_attempts\(.*?^\}')
    complete = one(tx, r'^static void ath12k_wifi7_dp_tx_complete_msdu\(.*?^\}')
    assert complete.count('ath12k_wifi7_dp_tx_count_attempts(dp->tx_attempt_stats, ts);') == 1
    assert complete.index('ath12k_wifi7_dp_tx_count_attempts(') < complete.index('switch (ts->status)')
    parse_call = 'ath12k_wifi7_dp_tx_status_parse(' + ('NULL, ' if 'struct ath12k_dp *dp,' in parse else '') + '&desc, &ts);'
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef int8_t s8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint32_t __le32;
typedef uint64_t atomic64_t;
#define atomic64_inc(p) (++*(p))
#define BIT(n) (UINT32_C(1) << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
#define u32_get_bits(v,m) (((v)&(m)) >> __builtin_ctz(m))
#define le32_get_bits(v,m) u32_get_bits(v,m)
#define le32_to_cpu(v) (v)
#define cpu_to_le32(v) (v)
#define __packed __attribute__((packed))
struct ath12k_dp { unsigned unused; };
''' + dims + '\n' + enums + '\n' + defs + '\n' + structs + '\n' + helper + '\n' + parse + r'''
static struct ath12k_tx_attempt_stats actual, expected;
int main(void)
{
    unsigned cases = 0;
    struct hal_tx_status ts = {};
    for (unsigned src=0; src<8; ++src)
    for (unsigned reason=0; reason<16; ++reason)
    for (unsigned count=0; count<128; ++count)
    for (unsigned flags=0; flags<16; ++flags) {
        struct hal_wbm_completion_ring_tx desc = {
            .info0=src | (reason<<13) | ((flags&1)?BIT(31):0),
            .info1=(count<<24) | ((flags&2)?BIT(31):0) | 0xabcdef,
            .info2=((flags&4)?BIT(8):0) | ((flags&8)?BIT(9):0) | 73,
            .info3=0x4567,
        };
        /* Reuse the status exactly as the isolated completion loop does. */
        ''' + parse_call + r'''
        assert(ts.buf_rel_source == src);
        if(src==HAL_WBM_REL_SRC_MODULE_TQM) {
            unsigned group = 0;
            if(flags&1) group=ATH12K_TX_ATTEMPT_CLASSES;
            else if(flags&2) group=1+!!(flags&4)+2*!!(flags&8);
            assert(ts.status==reason && ts.try_cnt==count && ts.attempt_class==group);
            assert(ts.ppdu_id==0xabcdef && ts.peer_id==0x4567 && ts.ack_rssi==73);
            if(group<ATH12K_TX_ATTEMPT_CLASSES) ++expected.count[reason][group][count];
        }
        ath12k_wifi7_dp_tx_count_attempts(&actual,&ts);
        ath12k_wifi7_dp_tx_count_attempts(NULL,&ts);
        ++cases;
    }
    assert(!memcmp(&actual,&expected,sizeof(actual)));
    ts=(struct hal_tx_status){.buf_rel_source=HAL_WBM_REL_SRC_MODULE_TQM,.status=255};
    ath12k_wifi7_dp_tx_count_attempts(&actual,&ts);
    ts.status=0; ts.try_cnt=255;
    ath12k_wifi7_dp_tx_count_attempts(&actual,&ts);
    ts.try_cnt=0; ts.attempt_class=255;
    ath12k_wifi7_dp_tx_count_attempts(&actual,&ts);
    assert(!memcmp(&actual,&expected,sizeof(actual)));
    printf("TX_ATTEMPT_TELEMETRY_PASS cases=%u bins=%zu\n",cases,sizeof(actual)/sizeof(atomic64_t));
}
'''
    c = args.output / 'tx-attempt.c'
    obj = args.output / 'tx-attempt.o'
    exe = args.output / 'tx-attempt'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
