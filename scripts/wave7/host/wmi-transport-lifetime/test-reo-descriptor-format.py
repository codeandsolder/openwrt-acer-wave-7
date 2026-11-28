#!/usr/bin/env python3
"""Check exact REO initial queue bytes against Qualcomm Wi-Fi 7 ABI."""
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
    parser.add_argument('source', type=Path, help='ath12k source directory')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    hal = (args.source / 'hal.h').read_text()
    desc = (args.source / 'wifi7/hal_desc.h').read_text()
    hdr = (args.source / 'wifi7/hal_rx.h').read_text()
    src = (args.source / 'wifi7/hal_rx.c').read_text()
    c = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <endian.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint32_t __le32;
#define __packed __attribute__((packed))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
static __le32 le32_encode_bits(u32 v, u32 mask) {
    return htole32((v << __builtin_ctz(mask)) & mask);
}
static unsigned ath12k_tid_to_ac(u32 tid) { return tid & 3; }
'''
    for text, kind, name in (
        (hal, 'struct', 'ath12k_buffer_addr'),
        (hal, 'enum', 'hal_pn_type'),
        (desc, 'enum', 'hal_desc_owner'),
        (desc, 'enum', 'hal_desc_buf_type'),
        (desc, 'struct', 'hal_desc_header'),
        (desc, 'struct', 'hal_rx_mpdu_link_ptr'),
        (desc, 'struct', 'hal_rx_reo_queue_ext'),
        (desc, 'enum', 'hal_rx_reo_queue_pn_size'),
        (desc, 'struct', 'hal_rx_reo_queue'),
        (desc, 'struct', 'hal_rx_reo_queue_1k'),
    ):
        c += one(text, rf'^{kind} {name} \{{.*?^\}}(?: __packed)?;') + '\n'
    c += '\n'.join(re.findall(
        r'^#define (?:HAL_DESC_HDR_INFO0_\w+|HAL_RX_REO_QUEUE_(?:RX_QUEUE_NUMBER|INFO0_\w+|INFO1_\w+))[^\n]*',
        desc, re.M)) + '\n'
    c += one(hal, r'^#define HAL_DESC_REO_NON_QOS_TID[^\n]*') + '\n'
    c += '\n'.join(re.findall(r'^#define REO_QUEUE_DESC_MAGIC_DEBUG_PATTERN_\d+[^\n]*', hdr, re.M)) + '\n'
    for name in ('ath12k_wifi7_hal_reo_set_desc_hdr', 'ath12k_wifi7_hal_reo_qdesc_size',
                 'ath12k_wifi7_hal_reo_qdesc_setup'):
        c += one(src, rf'^(?:void|u32) {name}\(.*?^\}}') + '\n'
    c += r'''
static u32 word(const unsigned char *p) {
    u32 v; memcpy(&v, p, sizeof(v)); return le32toh(v);
}
static void zeros(const unsigned char *p, unsigned n) {
    for (unsigned i=0; i<n; i++) assert(p[i]==0);
}
static void check(unsigned tid, unsigned ba, unsigned seq, enum hal_pn_type pn) {
    unsigned char data[1536+32] __attribute__((aligned(128)));
    memset(data, 0, sizeof(data));
    unsigned len=ath12k_wifi7_hal_reo_qdesc_size(tid==16?ba:1024,tid);
    assert(len==(tid==16?128:1536));
    memset(data+len, 0xA7, sizeof(data)-len);
    struct hal_rx_reo_queue *q=(void *)data;
    ath12k_wifi7_hal_reo_qdesc_setup(q,tid,ba,seq,pn);
    assert((word(data)&0xff)==0x84);
    assert((word(data+4)&0xffff)==tid);
    unsigned effective=ba?ba:1;
    if(effective==1 && tid!=16) effective=2;
    assert(((word(data+8)>>11)&1023)==effective-1);
    assert(((word(data+12)>>1)&4095)==(seq<=4095?seq:0));
    assert(!(word(data+12)&1));
    if(pn==HAL_PN_TYPE_WPA) {
        assert(word(data+8)&(1u<<21));
        assert(((word(data+8)>>25)&3)==1);
    } else assert(!(word(data+8)&(1u<<21)));
    if(tid!=16) {
        unsigned offset=128, n=3;
        if(ba>256) {
            assert(word(data+offset)==0x94);
            zeros(data+offset+4,124);
            offset+=128; n=10;
        }
        for(unsigned i=0;i<n;i++,offset+=128) {
            assert((word(data+offset)&0xff)==0xa4);
            zeros(data+offset+4,124);
        }
        zeros(data+offset,len-offset);
    }
    for(unsigned i=len;i<sizeof(data);i++) assert(data[i]==0xA7);
}
int main(void) {
    _Static_assert(sizeof(struct hal_rx_reo_queue)==128,"base ABI");
    _Static_assert(sizeof(struct hal_rx_reo_queue_1k)==128,"bitmap ABI");
    _Static_assert(sizeof(struct hal_rx_reo_queue_ext)==128,"extension ABI");
    assert(HAL_DESC_BUF_TYPE_RX_REO_QUEUE==8);
    assert(HAL_DESC_BUF_TYPE_RX_REO_QUEUE_1K==9);
    assert(HAL_DESC_BUF_TYPE_RX_REO_QUEUE_EXT==10);
    assert(HAL_DESC_BUF_TYPE_RX_BUFFER==11 && HAL_DESC_BUF_TYPE_IDLE_LINK==12);
    unsigned cases=0;
    for(unsigned tid=0;tid<=16;tid++)
      for(unsigned ba=0;ba<=(tid==16?1:1024);ba++)
        for(unsigned s=0;s<3;s++)
          for(unsigned pn=0;pn<4;pn++) {
              unsigned seqs[]={0,4095,4096};
              check(tid,ba,seqs[s],pn); cases++;
          }
    printf("REO_DESCRIPTOR_FORMAT_PASS cases=%u\n",cases);
}
'''
    path = args.output / 'reo-descriptor-format.c'
    obj = path.with_suffix('.o')
    exe = path.with_suffix('')
    path.write_text(c)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-c', str(path), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
