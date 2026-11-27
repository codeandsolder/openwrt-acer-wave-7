#!/usr/bin/env python3
"""Exercise the actual driver refill dispatch and DMA unmap helper with host shims."""
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
    parser.add_argument('source', type=Path, help='prepared ath12k source directory')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = args.source
    args.output.mkdir(parents=True, exist_ok=True)
    rx = (root / 'wifi7/dp_rx.c').read_text()
    header = (root / 'dp_rx.h').read_text()
    maximum = one((root / 'cmn_defs.h').read_text(), r'^#define ATH12K_MAX_DEVICES [0-9]+$')
    wbm = one(rx, r'^int ath12k_wifi7_dp_rx_process_wbm_err\(.*?^\}')
    loop = one(wbm, r'^\tfor \(device_id = 0; device_id < ATH12K_MAX_DEVICES; device_id\+\+\) \{\n\t\tif \(!num_buffs_reaped\[device_id\]\).*?^\t\}')
    normal = one(rx, r'^int ath12k_wifi7_dp_rx_process\(.*?^\}')
    epilogue = normal.split('\n\tspin_unlock_bh(&srng->lock);\n', 1)[1]
    helper = one(header, r'^static inline void ath12k_dp_unmap_rx_buf\(.*?^\}')
    # The exact reinjection mapping must publish the DMA address before either
    # descriptor-allocation failure or release-ring admission failure can unwind.
    reinject = one(rx, r'^static int ath12k_wifi7_dp_rx_h_defrag_reo_reinject\(.*?^\}')
    mapping = one(reinject, r'buf_paddr = dma_map_single\(.*?\);')
    assert 'DMA_BIDIRECTIONAL' in mapping
    assert reinject.index('ATH12K_SKB_RXCB(defrag_skb)->paddr = buf_paddr;') < reinject.index('goto err_unmap_dma;')
    assert 'err_unmap_dma:\n\tath12k_dp_unmap_rx_buf(dp, defrag_skb);' in reinject
    code = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
''' + maximum + r'''
struct page_pool { unsigned id; };
struct page { unsigned id; };
struct dp_rxdma_ring { unsigned id; struct page_pool *page_pool; };
struct list_head { unsigned id; unsigned count; };
struct ath12k_dp { unsigned id; void *dev; struct dp_rxdma_ring rx_refill_buf_ring; };
struct ath12k_dp_hw_group { struct ath12k_dp devices[ATH12K_MAX_DEVICES]; };
struct ath12k_skb_rxcb { uintptr_t paddr; unsigned is_frag; bool pool_mapped; };
struct sk_buff { unsigned len, tailroom; struct ath12k_skb_rxcb cb; struct page *head; };
#define DP_RX_BUFFER_SIZE 2048
#define virt_to_head_page(x) (x)
#define ATH12K_SKB_RXCB(skb) (&(skb)->cb)
#define skb_tailroom(skb) ((skb)->tailroom)
enum dma_data_direction { DMA_BIDIRECTIONAL, DMA_TO_DEVICE, DMA_FROM_DEVICE };
static unsigned count[ATH12K_MAX_DEVICES];
static unsigned unmaps, syncs;
static void page_pool_dma_sync_for_cpu(struct page_pool *p, struct page *page, unsigned offset, unsigned size)
{ assert(p && page && p->id == page->id && !offset && size == DP_RX_BUFFER_SIZE); ++syncs; }
struct sk_buff_head { unsigned pending; };
struct napi_struct { int dummy; };
static unsigned purged, delivered;
static void __attribute__((unused)) __skb_queue_purge(struct sk_buff_head *list)
{
    purged += list->pending;
    list->pending = 0;
}
static void ath12k_wifi7_dp_rx_process_received_packets(struct ath12k_dp *dp,
    struct napi_struct *napi, struct sk_buff_head *list, int ring_id)
{
    (void)dp; (void)napi; (void)ring_id;
    delivered += list->pending;
    list->pending = 0;
}
static void *expected_dev;
static uintptr_t expected_addr;
static unsigned expected_len;
static enum dma_data_direction expected_dir;
static struct ath12k_dp *ath12k_dp_hw_grp_to_dp(struct ath12k_dp_hw_group *group, unsigned id)
{
    assert(id < ATH12K_MAX_DEVICES);
    return &group->devices[id];
}
static void ath12k_dp_rx_bufs_replenish(struct ath12k_dp *dp, struct dp_rxdma_ring *ring,
                                      struct list_head *list, int n)
{
    assert(n > 0);
    assert(ring == &dp->rx_refill_buf_ring && dp->id == list->id);
    assert(list->count == (unsigned)n && count[dp->id] == 0);
    count[dp->id] = n;
}
static void dma_unmap_single(void *dev, uintptr_t addr, unsigned len, enum dma_data_direction dir)
{
    assert(dev == expected_dev && addr == expected_addr && len == expected_len && dir == expected_dir);
    ++unmaps;
}
''' + helper + r'''
static void refill(struct ath12k_dp *dp, struct ath12k_dp_hw_group *dp_hw_grp,
                   struct list_head *rx_desc_used_list, int *num_buffs_reaped)
{
    unsigned device_id;
    struct ath12k_dp *partner_dp;
    struct dp_rxdma_ring *rx_ring;
    (void)dp;
''' + loop + r'''
}
static int finish_rx(struct ath12k_dp *dp, struct ath12k_dp_hw_group *dp_hw_grp,
    struct list_head *rx_desc_used_list, int *num_buffs_reaped,
    unsigned pending, int total_msdu_reaped)
{
    struct sk_buff_head msdu_list = {pending};
    struct napi_struct *napi = NULL;
    int ring_id = 0;
    unsigned device_id;
    struct ath12k_dp *partner_dp;
    struct dp_rxdma_ring *rx_ring;
''' + epilogue + r'''
int main(void)
{
    struct ath12k_dp_hw_group group = {0};
    struct page_pool pools[ATH12K_MAX_DEVICES];
    struct page pages[ATH12K_MAX_DEVICES];
    unsigned cases = 0;
    for (unsigned i = 0; i < ATH12K_MAX_DEVICES; ++i) {
        group.devices[i].id = i;
        group.devices[i].dev = &group.devices[i];
        group.devices[i].rx_refill_buf_ring.id = i;
        pools[i].id = pages[i].id = i;
        group.devices[i].rx_refill_buf_ring.page_pool = &pools[i];
    }
    /* Every owner/collector combination; inactive owners have no reaped buffers. */
    for (unsigned collector = 0; collector < ATH12K_MAX_DEVICES; ++collector) {
        for (unsigned mask = 0; mask < (1u << ATH12K_MAX_DEVICES); ++mask) {
            for (unsigned batch = 1; batch <= 64; ++batch) {
                int reaped[ATH12K_MAX_DEVICES];
                struct list_head lists[ATH12K_MAX_DEVICES];
                memset(count, 0, sizeof(count));
                for (unsigned i = 0; i < ATH12K_MAX_DEVICES; ++i) {
                    reaped[i] = mask & (1u << i) ? batch + i : 0;
                    lists[i] = (struct list_head){i, (unsigned)reaped[i]};
                }
                refill(&group.devices[collector], &group, lists, reaped);
                for (unsigned i = 0; i < ATH12K_MAX_DEVICES; ++i)
                    assert(count[i] == (unsigned)reaped[i]);
                for (unsigned kind = 0; kind < 3; ++kind) {
                    unsigned complete = kind == 2;
                    unsigned pending = kind && mask ? batch : 0;
                    if (kind && !pending)
                        continue;
                    memset(count, 0, sizeof(count));
                    purged = delivered = 0;
                    assert(finish_rx(&group.devices[collector], &group, lists,
                        reaped, pending, complete) == (int)complete);
                    for (unsigned i = 0; i < ATH12K_MAX_DEVICES; ++i)
                        assert(count[i] == (unsigned)reaped[i]);
                    assert(purged == (complete ? 0 : pending));
                    assert(delivered == (complete ? pending : 0));
                    ++cases;
                }
            }
        }
        for (unsigned frag = 0; frag < 2; ++frag) {
            for (unsigned len = 0; len < 4096; len += 31) {
                struct sk_buff skb = {.len=len, .tailroom=4096-len, .cb={.paddr=0x12345000u+len,.is_frag=frag}};
                expected_dev = group.devices[collector].dev;
                expected_addr = skb.cb.paddr;
                expected_len = 4096;
                expected_dir = frag ? DMA_BIDIRECTIONAL : DMA_FROM_DEVICE;
                ath12k_dp_unmap_rx_buf(&group.devices[collector], &skb);
                skb.cb.pool_mapped = true;
                skb.head = &pages[collector];
                unsigned old_unmaps = unmaps, old_syncs = syncs;
                ath12k_dp_unmap_rx_buf(&group.devices[collector], &skb);
                assert(!skb.cb.pool_mapped && unmaps == old_unmaps && syncs == old_syncs + 1);
            }
        }
    }
    printf("RX_DMA_OWNERSHIP_PASS refill_cases=%u unmaps=%u pool_syncs=%u\n", cases, unmaps, syncs);
}
'''
    c = args.output / 'rx-dma.c'
    obj = args.output / 'rx-dma.o'
    exe = args.output / 'rx-dma'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
