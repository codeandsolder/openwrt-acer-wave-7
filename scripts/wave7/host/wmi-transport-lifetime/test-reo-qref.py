#!/usr/bin/env python3
"""Compile actual REO queue lookup and retirement routines against fake DMA/LUTs."""
import argparse
from pathlib import Path
import re
import subprocess


def extract(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path, help='ath12k source directory')
    p.add_argument('output', type=Path)
    a = p.parse_args()
    wifi = (a.source / 'wifi7/dp_rx.c').read_text()
    constants = '\n'.join(re.search(r'^#define\s+' + name + r'\s+[^\n]+', (a.source / f).read_text(), re.M).group() for f, name in (
        ('dp.h', 'DP_MAX_PEER_ID'), ('dp.h', 'DP_REOQ_LUT_SIZE'), ('dp.h', 'DP_REO_QREF_NUM'),
        ('dp.h', 'DP_BA_WIN_SZ_MAX'), ('dp_peer.h', 'ATH12K_PEER_ML_ID_VALID'),
        ('hal.h', 'BUFFER_ADDR_INFO0_ADDR'), ('hal.h', 'BUFFER_ADDR_INFO1_ADDR'),
        ('hal.h', 'HAL_LINK_DESC_ALIGN'), ('hal.h', 'HAL_DESC_REO_NON_QOS_TID')))
    actual = '\n\n'.join(extract(wifi, s) for s in (
        'static struct ath12k_reo_queue_ref *\nath12k_wifi7_peer_rx_tid_qref(',
        'void ath12k_wifi7_peer_rx_tid_qref_setup(',
        'void ath12k_wifi7_peer_rx_tid_qref_reset(',
        'int ath12k_wifi7_dp_rx_assign_reoq('))
    shim = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;typedef uint64_t dma_addr_t;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((UINT32_MAX>>(31-(h))) & (UINT32_MAX<<(l)))
#define IEEE80211_NUM_TIDS 16
/* CONSTANTS */
#define lower_32_bits(x) ((u32)(x))
#define upper_32_bits(x) ((u32)((x)>>32))
#define u32_encode_bits(x,m) (((u32)(x)<<__builtin_ctz(m))&(m))
#define u32_get_bits(x,m) (((x)&(m))>>__builtin_ctz(m))
#define WARN_ON_ONCE(x) (!!(x))
#define lockdep_assert_held(x) assert(*(x))
#define GFP_ATOMIC 0
#define DMA_BIDIRECTIONAL 0
#define PTR_ALIGN(p,a) ((void *)(((uintptr_t)(p)+(a)-1)&~((uintptr_t)(a)-1)))
enum hal_pn_type { HAL_PN_TYPE_NONE };
struct ath12k_reo_queue_ref { u32 info0,info1; };
struct ath12k_reo_q_addr_lut { void *vaddr; };
struct ath12k_reoq_buf {void *vaddr;dma_addr_t paddr_aligned;u32 size;};
struct ath12k_dp_rx_tid {u8 tid;u32 ba_win_sz;struct ath12k_reoq_buf qbuf;};
struct ath12k_dp {int dp_lock;struct ath12k_reo_q_addr_lut reoq_lut,ml_reoq_lut;};
struct hw {bool reoq_lut_support;};
struct ath12k_base {struct ath12k_dp dp;struct hw *hw_params;void *dev;};
#define ath12k_ab_to_dp(ab) (&(ab)->dp)
static unsigned barriers,clears,allocs,frees,maps;static bool oom,mapfail;
static void dma_wmb(void) {barriers++;}
static void ath12k_hal_reo_shared_qaddr_cache_clear(struct ath12k_base *ab) {assert(ab->dp.dp_lock && barriers==clears+1);clears++;}
static void *kzalloc(size_t n,int flags) {(void)flags;if(oom)return NULL;allocs++;return calloc(1,n);}
static void kfree(void *p) {frees++;free(p);}
static dma_addr_t dma_map_single(void *d,void *v,u32 size,int dir) {(void)d;(void)v;(void)size;(void)dir;maps++;return mapfail?0:((u64)maps<<32)|0x123400;}
static bool dma_mapping_error(void *d,dma_addr_t p) {(void)d;return !p;}
static u32 ath12k_wifi7_hal_reo_qdesc_size(u32 sz,u8 tid) {(void)tid;return sz*4+128;}
static void ath12k_wifi7_hal_reo_qdesc_setup(void *v,u8 tid,u32 sz,u16 ssn,enum hal_pn_type pn) {(void)v;(void)tid;(void)sz;(void)ssn;(void)pn;}
/* ACTUAL */
static u64 addr(const struct ath12k_reo_queue_ref *q) {return ((u64)u32_get_bits(q->info1,BUFFER_ADDR_INFO1_ADDR)<<32)|q->info0;}
int main(void) {
    struct hw h={true};struct ath12k_base a={.hw_params=&h};a.dp.dp_lock=1;
    assert(DP_REOQ_LUT_SIZE==(DP_MAX_PEER_ID+1)*17*sizeof(struct ath12k_reo_queue_ref));
    struct ath12k_reo_queue_ref *normal=calloc(1,DP_REOQ_LUT_SIZE),*mlo=calloc(1,DP_REOQ_LUT_SIZE);
    a.dp.reoq_lut.vaddr=normal;a.dp.ml_reoq_lut.vaddr=mlo;
    unsigned cases=0;
    for(unsigned ml=0;ml<2;ml++) for(unsigned peer=0;peer<=DP_MAX_PEER_ID;peer++) for(unsigned tid=0;tid<=16;tid++) {
        u16 id=peer|(ml?ATH12K_PEER_ML_ID_VALID:0);struct ath12k_reo_queue_ref *q=(ml?mlo:normal)+peer*17+tid;
        u64 old=0x9a00000000ULL|(peer<<16)|(tid<<7),new=old+128;
        ath12k_wifi7_peer_rx_tid_qref_setup(&a,id,tid,old);assert(addr(q)==old);
        ath12k_wifi7_peer_rx_tid_qref_setup(&a,id,tid,new);assert(addr(q)==new);
        unsigned before=clears;
        ath12k_wifi7_peer_rx_tid_qref_reset(&a,id,tid,old);assert(addr(q)==new && clears==before);
        ath12k_wifi7_peer_rx_tid_qref_reset(&a,id,tid,new);assert(!addr(q) && clears==before+1 && u32_get_bits(q->info1,DP_REO_QREF_NUM)==tid);
        cases++;
    }
    unsigned before=clears;
    for(unsigned i=0;i<2;i++) {u16 id=(DP_MAX_PEER_ID+1)|(i?ATH12K_PEER_ML_ID_VALID:0);
        ath12k_wifi7_peer_rx_tid_qref_setup(&a,id,0,123);ath12k_wifi7_peer_rx_tid_qref_reset(&a,id,0,123);}
    ath12k_wifi7_peer_rx_tid_qref_setup(&a,0,17,123);ath12k_wifi7_peer_rx_tid_qref_reset(&a,0,17,123);
    h.reoq_lut_support=false;ath12k_wifi7_peer_rx_tid_qref_setup(&a,0,0,123);ath12k_wifi7_peer_rx_tid_qref_reset(&a,0,0,123);h.reoq_lut_support=true;
    assert(clears==before && barriers==clears);
    struct ath12k_dp_rx_tid storage={.tid=3,.ba_win_sz=64};
    struct ath12k_dp_rx_tid *tid=&storage;
    oom=true;assert(ath12k_wifi7_dp_rx_assign_reoq(&a,tid,0,HAL_PN_TYPE_NONE)==-ENOMEM&&!tid->qbuf.vaddr);
    oom=false;mapfail=true;assert(ath12k_wifi7_dp_rx_assign_reoq(&a,tid,0,HAL_PN_TYPE_NONE)==-EIO&&!tid->qbuf.vaddr&&allocs==frees);
    mapfail=false;assert(!ath12k_wifi7_dp_rx_assign_reoq(&a,tid,0,HAL_PN_TYPE_NONE));
    struct ath12k_reoq_buf first=tid->qbuf;unsigned n=allocs;assert(!ath12k_wifi7_dp_rx_assign_reoq(&a,tid,0,HAL_PN_TYPE_NONE)&&allocs==n);
    tid->qbuf=(struct ath12k_reoq_buf){};
    assert(!ath12k_wifi7_dp_rx_assign_reoq(&a,tid,0,HAL_PN_TYPE_NONE));assert(tid->qbuf.vaddr!=first.vaddr&&tid->qbuf.paddr_aligned!=first.paddr_aligned);
    ath12k_wifi7_peer_rx_tid_qref_setup(&a,42,3,tid->qbuf.paddr_aligned);
    ath12k_wifi7_peer_rx_tid_qref_reset(&a,42,3,first.paddr_aligned);
    assert(addr(normal+42*17+3)==tid->qbuf.paddr_aligned);
    kfree(first.vaddr);kfree(tid->qbuf.vaddr);assert(allocs==frees);free(normal);free(mlo);
    printf("REO_QREF_PASS %u LUT generations plus stale allocation, allocation and DMA failures\n",cases);
}
'''
    a.output.mkdir(parents=True, exist_ok=True)
    c, obj, exe = (a.output / f'reo-qref{s}' for s in ('.c','.o',''))
    c.write_text(shim.replace('/* CONSTANTS */', constants).replace('/* ACTUAL */', actual))
    subprocess.run(['/usr/local/bin/sccache', '/usr/bin/cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['/usr/bin/cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
