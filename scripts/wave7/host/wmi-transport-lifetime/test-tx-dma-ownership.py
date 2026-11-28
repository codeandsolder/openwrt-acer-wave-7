#!/usr/bin/env python3
"""Exercise the actual ring selection, DMA error unwind and alignment code."""
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
    common = (root / 'dp_tx.c').read_text()
    tx = (root / 'wifi7/dp_tx.c').read_text()
    function = one(tx, r'^int ath12k_wifi7_dp_tx\(.*?^\}')
    ring = one(function, r'^tcl_ring_sel:.*?(?=^\tspin_lock_bh\(&arvif->link_stats_lock\);)')
    unwind = one(function, r'^fail_unmap_dma_ext:.*?^\}')
    align = one(common, r'^static void ath12k_dp_tx_move_payload\(.*?^\}') + '\n' + one(common, r'^int ath12k_dp_tx_align_payload\(.*?^\}')
    assert function.count('ath12k_dp_tx_assign_buffer(') == 1
    assert function.count('dma_map_single(') == 2
    assert function.index('skb_cb->paddr = ti.paddr;') < function.index('ti.paddr = dma_map_single(dp->dev, skb_ext_desc->data,')
    assert function.index('ATH12K_TX_EXT_CB(skb_ext_desc)->paddr = ti.paddr;') < function.index('tcl_ring_sel:')
    assert function.index('tcl_ring_sel:') < function.index('tx_desc->skb = skb;')
    assert function.index('tx_desc->skb = skb;') < function.index('atomic_inc(&dp_pdev->num_tx_pending);')
    assert 'tx_desc->skb = NULL;' in common
    assert 'ath12k_dp_tx_unmap(dp, skb, tx_desc_info->skb_ext_desc);' in (root / 'dp.c').read_text()
    retire = one(tx, r'^static void ath12k_wifi7_tx_retire\(.*?^\}')
    assert 'ath12k_dp_tx_unmap(dp, skb, params->skb_ext_desc);' in retire
    unmap = one(common, r'^void ath12k_dp_tx_unmap_payload\(.*?^\}')
    assert 'if (skb_cb->paddr_ext_desc)' not in tx + common
    # Compile actual control-flow fragments, with explicit fake device ownership.
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BIT(n) (1u << (n))
#define DMA_TO_DEVICE 1
struct ath12k_skb_cb { uintptr_t paddr; };
struct ath12k_tx_ext_cb { uintptr_t paddr, frags[5]; };
struct skb_shared_info { unsigned nr_frags, frags[5]; };
struct sk_buff {
    struct ath12k_skb_cb cb;
    struct ath12k_tx_ext_cb ext_cb;
    struct skb_shared_info shinfo;
    unsigned char *data, *base;
    unsigned len, capacity;
    int header;
    bool cloned;
    uintptr_t addr;
};
#define ATH12K_SKB_CB(s) (&(s)->cb)
#define ATH12K_TX_EXT_CB(s) (&(s)->ext_cb)
#define skb_shinfo(s) (&(s)->shinfo)
#define skb_headlen(s) ((s)->len)
#define skb_frag_size(f) (*(f))
struct ath12k_hw_params { unsigned max_tx_ring; bool tcl_ring_retry; u32 iova_mask; };
struct hal_srng { int lock; unsigned ring; };
struct dp_tx_ring { struct { unsigned ring_id; } tcl_data_ring; };
struct ath12k_hal {
    struct { unsigned rbm_id; } tcl_to_wbm_rbm_map[8];
    struct hal_srng srng_list[8];
};
struct ath12k_base { int unused; };
struct ath12k_dp {
    struct ath12k_hw_params *hw_params;
    void *dev;
    struct dp_tx_ring tx_ring[8];
    struct { struct { unsigned desc_na[8]; } tx_err; } device_stats;
};
struct ath12k_tx_desc_info { unsigned unused; };
struct hal_tcl_data_cmd { int unused; };
struct ath12k_link_vif { int link_stats_lock; struct { unsigned tx_dropped; } link_stats; };
struct hal_tx_info { unsigned ring_id, rbm_id; };
static unsigned available, tried, released, data_unmaps, ext_unmaps, ext_frees;
static unsigned char aligned[2048] __attribute__((aligned(128)));
static unsigned char copied[2048] __attribute__((aligned(128)));
static bool cow_fail;
static unsigned cows;
static struct sk_buff *payload, *extension;
static void spin_lock_bh(int *lock) { assert(!*lock); *lock = 1; }
static void spin_unlock_bh(int *lock) { assert(*lock); *lock = 0; }
static void ath12k_hal_srng_access_begin(struct ath12k_base *ab, struct hal_srng *ring)
{ (void)ab; assert(ring->lock); }
static void ath12k_hal_srng_access_end(struct ath12k_base *ab, struct hal_srng *ring)
{ (void)ab; assert(ring->lock); }
static struct hal_tcl_data_cmd *ath12k_hal_srng_src_get_next_entry(struct ath12k_base *ab, struct hal_srng *ring)
{
    static struct hal_tcl_data_cmd cmd;
    (void)ab;
    assert(!(tried & BIT(ring->ring)));
    tried |= BIT(ring->ring);
    return available & BIT(ring->ring) ? &cmd : NULL;
}
static void dma_unmap_single(void *dev, uintptr_t addr, unsigned len, int dir)
{
    assert(dev && dir == DMA_TO_DEVICE);
    if (addr == payload->addr && len == payload->len) ++data_unmaps;
    else { assert(extension && addr == extension->addr && len == extension->len); ++ext_unmaps; }
}
static void dma_unmap_page(void *dev, uintptr_t addr, unsigned len, int dir)
{ (void)dev; (void)addr; (void)len; (void)dir; assert(0); }
static void kfree_skb(struct sk_buff *skb)
{ if (skb) { assert(skb == extension); ++ext_frees; } }
static void ath12k_dp_tx_release_txbuf(struct ath12k_dp *dp, struct ath12k_tx_desc_info *desc, u8 pool)
{ assert(dp && desc && pool == 0); ++released; }
static unsigned skb_headroom(struct sk_buff *s) { return s->data - s->base; }
static unsigned skb_tailroom(struct sk_buff *s) { return s->capacity - skb_headroom(s) - s->len; }
static bool skb_cloned(struct sk_buff *s) { return s->cloned; }
static void skb_push(struct sk_buff *s, unsigned delta) { assert(delta <= skb_headroom(s)); s->data -= delta; s->len += delta; }
static void skb_pull(struct sk_buff *s, unsigned delta) { assert(delta <= s->len); s->data += delta; s->len -= delta; }
static void skb_put(struct sk_buff *s, unsigned delta) { assert(delta <= skb_tailroom(s)); s->len += delta; }
static void skb_trim(struct sk_buff *s, unsigned n) { assert(n <= s->len); s->len = n; }
static void skb_headers_offset_update(struct sk_buff *s, int delta) { s->header += delta; }
static int skb_cow(struct sk_buff *s, unsigned headroom)
{
    ++cows;
    if (cow_fail) return -ENOMEM;
    assert(headroom < 512);
    unsigned old = skb_headroom(s);
    unsigned next = headroom + 17;
    memcpy(copied + next, s->data, s->len);
    s->data = copied + next; s->base = copied; s->capacity = sizeof(copied);
    s->header += (int)next - (int)old; s->cloned = false;
    return 0;
}
''' + unmap + '\n' + align + r'''
static int submit(struct ath12k_dp *dp, struct ath12k_hal *hal, unsigned selector,
                  bool ext, unsigned fail, uintptr_t data_addr, uintptr_t ext_addr)
{
    struct ath12k_base base = {0}, *ab = &base;
    struct ath12k_link_vif av = {0}, *arvif = &av;
    struct ath12k_tx_desc_info desc = {0}, *tx_desc = &desc;
    static struct sk_buff data, extra;
    data = (struct sk_buff){.len=1514, .addr=data_addr, .cb={data_addr}};
    extra = (struct sk_buff){.len=56, .addr=ext_addr, .ext_cb={.paddr=ext_addr}};
    struct sk_buff *skb = &data, *skb_ext_desc = ext ? &extra : NULL;
    unsigned mapped_frags = 0;
    struct hal_tx_info ti = {0};
    struct dp_tx_ring *tx_ring;
    struct hal_srng *tcl_ring;
    struct hal_tcl_data_cmd *hal_tcl_desc;
    u8 pool_id = 0, hal_ring_id, ring_selector = selector % dp->hw_params->max_tx_ring, ring_map = 0;
    int ret = -ENOMEM;
    payload = skb; extension = skb_ext_desc;
    switch (fail) {
    case 1: goto fail_remove_tx_buf; /* payload map failure */
    case 2: goto fail_unmap_dma; /* extension allocation failure */
    case 3: goto fail_free_ext_skb; /* extension preparation or map failure */
    default: break;
    }
''' + ring + r'''
    assert(hal_tcl_desc && (available & BIT(ti.ring_id)));
    ath12k_hal_srng_access_end(ab, tcl_ring);
    spin_unlock_bh(&tcl_ring->lock);
    return 0;
''' + unwind + r'''
int main(void)
{
    unsigned cases = 0, align_cases = 0;
    struct ath12k_hw_params hw = {0};
    struct ath12k_dp dp = {.hw_params=&hw, .dev=&dp};
    struct ath12k_hal hal = {0};
    for (unsigned i=0; i<8; ++i) {
        dp.tx_ring[i].tcl_data_ring.ring_id = i;
        hal.srng_list[i].ring = i;
    }
    for (unsigned n=1; n<=8; ++n)
    for (unsigned sel=0; sel<256; ++sel)
    for (unsigned retry=0; retry<2; ++retry)
    for (unsigned avail=0; avail<BIT(n); ++avail)
    for (unsigned ext=0; ext<2; ++ext)
    for (unsigned z=0; z<2; ++z) {
        hw.max_tx_ring=n; hw.tcl_ring_retry=retry; available=avail;
        tried=released=data_unmaps=ext_unmaps=ext_frees=0;
        bool success = retry ? avail != 0 : (avail & BIT(sel % n)) != 0;
        int ret = submit(&dp, &hal, sel, ext, 0, z ? 0 : 0x1000, z ? 0x2000 : 0);
        assert((ret==0)==success);
        assert(released==!success && data_unmaps==!success);
        assert(ext_unmaps==(ext && !success) && ext_frees==ext_unmaps);
        if (!success) assert(tried == (retry ? BIT(n)-1 : BIT(sel % n)));
        ++cases;
    }
    for (unsigned fail=1; fail<=3; ++fail)
    for (unsigned z=0; z<2; ++z) {
        tried=released=data_unmaps=ext_unmaps=ext_frees=0;
        assert(submit(&dp,&hal,0,fail==3,fail,z?0:0x1000,z?0x2000:0)==-ENOMEM);
        assert(!tried && released==1 && data_unmaps==(fail!=1) && !ext_unmaps && ext_frees==(fail==3));
        ++cases;
    }
    for (unsigned mask=1; mask<=127; mask=(mask<<1)|1)
    for (unsigned head=0; head<256; ++head)
    for (unsigned tail=0; tail<130; tail+=13)
    for (unsigned clone=0; clone<2; ++clone)
    for (unsigned fail=0; fail<2; ++fail) {
        struct sk_buff s = {.data=aligned+head,.base=aligned,.len=73,.capacity=head+73+tail,.header=head+14,.cloned=clone};
        unsigned char expected[73];
        for (unsigned i=0;i<sizeof(expected);++i) expected[i]=(unsigned char)(i*17+head);
        memcpy(s.data,expected,sizeof(expected));
        hw.iova_mask=mask; cows=0; cow_fail=fail;
        unsigned char *original=s.data;
        int ret=ath12k_dp_tx_align_payload(&dp,&s);
        assert(s.len==sizeof(expected) && !memcmp(s.data,expected,sizeof(expected)));
        assert(s.base+s.header==s.data+14);
        if (ret) assert(ret==-ENOMEM && cows==1 && s.data==original);
        else assert(!((uintptr_t)s.data&mask));
        ++align_cases;
    }
    printf("TX_DMA_OWNERSHIP_PASS ring_cases=%u alignment_cases=%u\n",cases,align_cases);
}
'''
    c = args.output / 'tx-dma.c'
    obj = args.output / 'tx-dma.o'
    exe = args.output / 'tx-dma'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
