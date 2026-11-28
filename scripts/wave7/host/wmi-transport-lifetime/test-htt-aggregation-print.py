#!/usr/bin/env python3
"""Exercise the actual HTT C printers and parse their output with the host reader."""
import argparse
from pathlib import Path
import re
import runpy
import subprocess


def one(text, pattern):
    hits = re.findall(pattern, text, re.M | re.S)
    if len(hits) != 1:
        raise ValueError(f'expected unique {pattern}, got {len(hits)}')
    return hits[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    src = (args.source / 'debugfs_htt_stats.c').read_text()
    hdr = (args.source / 'debugfs_htt_stats.h').read_text()
    defs = '\n'.join(one(hdr, rf'^#define {macro}[^\n]*') for macro in (
        'ATH12K_HTT_STATS_BUF_SIZE', 'ATH12K_HTT_PDEV_PPDU_DUR_HIST_BINS'))
    structs = '\n'.join(one(hdr, rf'^struct ath12k_htt_tx_pdev_{name}_tlv \{{.*?^\}} __packed;')
                       for name in ('tried_mpdu_cnt_hist', 'ppdu_dur'))
    funcs = '\n'.join(one(src, rf'^static (?:u32|void)\n{name}\(.*?^\}}') for name in (
        'print_array_to_buf_index', 'print_array_to_buf', 'print_array_to_buf_s8',
        'ath12k_htt_print_tried_mpdu_hist', 'ath12k_htt_print_tx_ppdu_duration'))
    code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef int8_t s8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef unsigned long long u64;
typedef uint32_t __le32;
#define __packed __attribute__((packed))
#define le32_to_cpu(x) (x)
static int scnprintf(u8 *buf, size_t size, const char *fmt, ...)
    __attribute__((format(printf,3,4)));
static int scnprintf(u8 *buf, size_t size, const char *fmt, ...)
{
    if (!size) return 0;
    va_list ap;
    va_start(ap,fmt);
    int ret=vsnprintf((char *)buf,size,fmt,ap);
    va_end(ap);
    assert(ret>=0);
    return (size_t)ret>=size ? (int)size-1 : ret;
}
''' + defs + '\n' + structs + r'''
struct debug_htt_stats_req {
    u32 buf_len;
    u8 buf[ATH12K_HTT_STATS_BUF_SIZE+8];
};
''' + funcs + r'''
#define CAP ATH12K_HTT_STATS_BUF_SIZE
static struct debug_htt_stats_req req;
static __le32 vals[1022];
static s8 signed_vals[1022];
static char expected[32768];
static void reset(u32 offset)
{
    req.buf_len=offset;
    memset(req.buf,0x55,sizeof(req.buf));
    if(offset<CAP) req.buf[offset]=0;
}
static void check_guard(void)
{
    for(unsigned i=CAP;i<sizeof(req.buf);++i) assert(req.buf[i]==0x55);
}
static unsigned reference(unsigned n, int signed_kind, const char *header,
                          const char *footer, unsigned start)
{
    unsigned len=0;
    if(header) len+=snprintf(expected+len,sizeof(expected)-len,"%s = ",header);
    for(unsigned i=0;i<n;++i) {
        if(signed_kind) len+=snprintf(expected+len,sizeof(expected)-len,"%s%u:%d",
                                      i?", ":" ",start+i,signed_vals[i]);
        else len+=snprintf(expected+len,sizeof(expected)-len,"%s%u:%u",
                           i?", ":" ",start+i,vals[i]);
    }
    if(footer) len+=snprintf(expected+len,sizeof(expected)-len,"%s",footer);
    expected[len]=0;
    return len;
}
int main(void)
{
    for(unsigned i=0;i<1022;++i) {
        vals[i]=0x12340000u+i;
        signed_vals[i]=(s8)(i-128);
    }
    unsigned array_cases=0;
    const unsigned ns[]={0,1,2,10,255,256,257,1022};
    const unsigned offsets[]={0,1,CAP-32768,CAP-31,CAP-2,CAP-1,CAP,CAP+1};
    for(unsigned j=0;j<sizeof(ns)/sizeof(ns[0]);++j)
    for(unsigned k=0;k<sizeof(offsets)/sizeof(offsets[0]);++k)
    for(unsigned s=0;s<2;++s)
    for(unsigned hdr=0;hdr<2;++hdr)
    for(unsigned ftr=0;ftr<2;++ftr) {
        unsigned n=ns[j], off=offsets[k];
        const char *header=hdr?"array":NULL, *footer=ftr?"\n":NULL;
        unsigned full=reference(n,s,header,footer,5);
        unsigned want=off>=CAP?0:(full<CAP-off-1?full:CAP-off-1);
        reset(off);
        unsigned len=s?print_array_to_buf_s8(req.buf,off,header,5,signed_vals,n,footer):
                       print_array_to_buf_index(req.buf,off,header,5,vals,n,footer);
        assert(len==want);
        if(off<CAP) {
            assert(!memcmp(req.buf+off,expected,want));
            assert(req.buf[off+want]==0);
        }
        check_guard();
        ++array_cases;
    }
    /* Every possible 4-byte-aligned array length in a 12-bit HTT TLV. */
    u32 payload[1023];
    payload[0]=30;
    for(unsigned i=1;i<1023;++i) payload[i]=i;
    for(unsigned n=1;n<=1022;++n) {
        reset(0);
        ath12k_htt_print_tried_mpdu_hist(payload,4*(n+1),&req);
        assert(strstr((char*)req.buf,"hist_bin_size = 30\n"));
        char end[64];
        snprintf(end,sizeof(end),"%u:%u\n\n",n-1,n);
        assert(req.buf_len>=strlen(end));
        assert(!strcmp((char*)req.buf+req.buf_len-strlen(end),end));
        check_guard();
    }
    unsigned invalid=0;
    for(unsigned len=0;len<4096;++len) {
        if(len>=8 && !(len%4)) continue;
        reset(0);
        ath12k_htt_print_tried_mpdu_hist(NULL,len,&req);
        assert(strstr((char*)req.buf,"invalid_length = "));
        check_guard();
        ++invalid;
    }
    _Static_assert(sizeof(struct ath12k_htt_tx_pdev_ppdu_dur_tlv)==152,"wire size");
    struct ath12k_htt_tx_pdev_ppdu_dur_tlv dur={0};
    for(unsigned i=0;i<16;++i) {
        dur.tx_ppdu_dur_hist[i]=100+i;
        dur.tx_ofdma_ppdu_dur_hist[i]=200+i;
    }
    dur.tx_success_time_us_high=0x12345678;
    dur.tx_success_time_us_low=0xabcdef01;
    dur.tx_fail_time_us_high=1;
    dur.tx_fail_time_us_low=3;
    dur.pdev_up_time_us_high=9;
    dur.pdev_up_time_us_low=2;
    for(unsigned len=0;len<sizeof(dur);++len) {
        reset(0);
        ath12k_htt_print_tx_ppdu_duration(NULL,len,&req);
        assert(strstr((char*)req.buf,"invalid_length = "));
        check_guard();
    }
    reset(0);
    ath12k_htt_print_tried_mpdu_hist(payload,44,&req);
    puts((char*)req.buf);
    reset(0);
    ath12k_htt_print_tx_ppdu_duration(&dur,sizeof(dur),&req);
    check_guard();
    puts((char*)req.buf);
    printf("HTT_AGGREGATION_PRINT_PASS array_cases=%u valid_hist=1022 invalid_hist=%u invalid_duration=152\n",
           array_cases,invalid);
}
'''
    c = args.output / 'htt-aggregation.c'
    obj = args.output / 'htt-aggregation.o'
    exe = args.output / 'htt-aggregation'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-Wno-address-of-packed-member',
                    '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    raw = subprocess.check_output([str(exe)], text=True)
    (args.output / 'printer-output.txt').write_text(raw)
    tx = runpy.run_path(str(Path(__file__).with_name('htt-tx-stats.py')))
    rate = runpy.run_path(str(Path(__file__).with_name('htt-rate-stats.py')))
    lines=raw.splitlines()
    assert tx['mpdu_histogram'](lines)=={'bin_size':30,'bins':list(range(1,11))}
    assert rate['scalar'](lines,'tx_success_time_us',2**64)==0x12345678abcdef01
    assert rate['scalar'](lines,'tx_fail_time_us',2**64)==2**32+3
    assert rate['scalar'](lines,'pdev_up_time_us',2**64)==9*2**32+2
    assert rate['histogram'](lines,'tx_ppdu_dur_hist',0,16)==list(range(100,116))
    assert rate['histogram'](lines,'tx_ofdma_ppdu_dur_hist',0,16)==list(range(200,216))
    print(lines[-1], 'HOST_PARSE_PASS')


if __name__ == '__main__':
    main()
