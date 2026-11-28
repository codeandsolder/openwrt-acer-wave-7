#!/usr/bin/env python3
"""Exercise the actual bounded WBM reader, poller, and NAPI dispatch."""
import argparse
from pathlib import Path
import re
import subprocess


def extract(text, pattern):
    matches = re.findall(pattern, text, re.M | re.S)
    if len(matches) != 1:
        raise ValueError(f'expected one function matching {pattern}')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tx = (args.source / 'wifi7/dp_tx.c').read_text()
    service = (args.source / 'wifi7/dp.c').read_text()
    reader = extract(tx, r'^static unsigned int\s+ath12k_wifi7_dp_tx_read_batch\(.*?^\}')
    poll = extract(tx, r'^bool ath12k_wifi7_dp_tx_completion_handler\(.*?^\}')
    dispatch = extract(service, r'^static int ath12k_wifi7_dp_service_srng\(.*?^\}')
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define NAPI_POLL_WEIGHT 64
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define BIT(i) (1u<<(i))
#define CAP 256
struct hal_wbm_completion_ring_tx {uint32_t words[8];};
struct hal_srng {
    int lock;
    unsigned read, write, snapshot, published, consumed, max_batch, refill;
    struct hal_wbm_completion_ring_tx entry[CAP];
};
struct dp_tx_ring {struct {unsigned ring_id;} tcl_comp_ring;};
struct ath12k_base {int num_radios;};
struct hal {struct hal_srng srng_list[4];};
struct ring_mask {u8 tx[1],rx_err[1],rx_wbm_rel[1],rx[1],rx_mon_status[1],rx_mon_dest[1],tx_mon_dest[1],reo_status[1],host2rxdma[1];};
struct hw_params {struct ring_mask *ring_mask;int num_rxdma_per_pdev;};
struct dp_rxdma_ring {int unused;};
struct ath12k_dp {struct ath12k_base *ab;struct hal *hal;struct dp_tx_ring tx_ring[4];struct hw_params *hw_params;struct dp_rxdma_ring rx_refill_buf_ring;};
struct napi_struct {int unused;};
struct ath12k_ext_irq_grp {struct napi_struct napi;int grp_id;};
enum dp_monitor_mode {ATH12K_DP_RX_MONITOR_MODE=1,ATH12K_DP_TX_MONITOR_MODE=2};
#define LIST_HEAD(x) int x=0
static unsigned rx_remaining, rx_done, maintenance;
static int fls(unsigned v) {return v?32-__builtin_clz(v):0;}
static void spin_lock_bh(int *lock) {assert(!*lock);*lock=1;}
static void spin_unlock_bh(int *lock) {assert(*lock);*lock=0;}
static void produce(struct hal_srng *r,unsigned n) {
    for(unsigned i=0;i<n;i++){
        assert(r->write-r->published<CAP);
        unsigned seq=r->write++;
        for(unsigned j=0;j<8;j++)r->entry[seq%CAP].words[j]=seq^((j+1)*0x1020304u);
    }
}
static void ath12k_hal_srng_access_begin(struct ath12k_base *ab,struct hal_srng *r) {
    assert(ab && r->lock && r->read==r->published);r->snapshot=r->write;
}
static void *ath12k_hal_srng_dst_get_next_entry(struct ath12k_base *ab,struct hal_srng *r){
    assert(ab && r->lock);
    if(r->read==r->snapshot)return NULL;
    return &r->entry[r->read++%CAP];
}
static void ath12k_hal_srng_access_end(struct ath12k_base *ab,struct hal_srng *r){
    assert(ab && r->lock);
    unsigned n=r->read-r->published;
    if(n>r->max_batch)r->max_batch=n;
    /* Hardware can reuse every returned slot before status reporting. */
    while(r->published<r->read)memset(&r->entry[r->published++%CAP],0xA5,sizeof(r->entry[0]));
    produce(r,n<r->refill?n:r->refill);
}
static void ath12k_wifi7_dp_tx_complete_record(struct ath12k_dp *dp,struct dp_tx_ring *tx,struct hal_wbm_completion_ring_tx *record){
    struct hal_srng *r=&dp->hal->srng_list[tx->tcl_comp_ring.ring_id];
    assert(!r->lock && r->consumed<r->published);
    unsigned seq=r->consumed++;
    for(unsigned j=0;j<8;j++)assert(record->words[j]==(seq^((j+1)*0x1020304u)));
}
static int rx(int budget){assert(budget>0);unsigned n=min_t(unsigned,budget,rx_remaining);rx_remaining-=n;rx_done+=n;return n;}
static int ath12k_wifi7_dp_rx_process_err(struct ath12k_dp *dp,struct napi_struct *n,int budget){assert(dp&&n);return rx(budget);}
static int ath12k_wifi7_dp_rx_process_wbm_err(struct ath12k_dp *dp,struct napi_struct *n,int budget){return ath12k_wifi7_dp_rx_process_err(dp,n,budget);}
static int ath12k_wifi7_dp_rx_process(struct ath12k_dp *dp,int i,struct napi_struct *n,int budget){assert(i>=0);return ath12k_wifi7_dp_rx_process_err(dp,n,budget);}
static int ath12k_wifi7_dp_mon_process_ring(struct ath12k_dp *dp,int id,struct napi_struct *n,int budget,int mode){assert(mode>=0);return ath12k_wifi7_dp_rx_process(dp,id,n,budget);}
static void ath12k_wifi7_dp_rx_process_reo_status(struct ath12k_dp *dp){assert(dp);maintenance++;}
static void ath12k_dp_rx_bufs_replenish(struct ath12k_dp *dp,struct dp_rxdma_ring *r,int *l,int n){assert(dp&&r&&l&&!n);maintenance++;}
''' + reader + '\n' + poll + '\n' + dispatch + r'''
static void init_ring(struct hal_srng *r,unsigned start,unsigned n,unsigned refill){
    memset(r,0,sizeof(*r));r->read=r->write=r->published=r->consumed=start;r->refill=refill;produce(r,n);
}
int main(void){
    struct ath12k_base ab={.num_radios=1};
    struct hal hal;
    struct ring_mask mask={0};
    struct hw_params hw={&mask,1};
    struct ath12k_dp dp={.ab=&ab,.hal=&hal,.hw_params=&hw};
    struct ath12k_ext_irq_grp grp={0};
    unsigned cases=0;
    for(unsigned i=0;i<4;i++)dp.tx_ring[i].tcl_comp_ring.ring_id=i;
    const unsigned starts[]={0,1,31,63,255};
    for(unsigned k=0;k<ARRAY_SIZE(starts);k++)
    for(unsigned budget=1;budget<=256;budget++)
    for(unsigned avail=0;avail<=CAP;avail++){
        struct hal_srng *r=&hal.srng_list[0];
        init_ring(r,starts[k],avail,0);
        unsigned expected=min_t(unsigned,budget,avail);
        bool more=ath12k_wifi7_dp_tx_completion_handler(&dp,0,budget);
        assert(more==(expected==budget));
        assert(r->consumed==starts[k]+expected&&r->read==r->published&&r->max_batch<=NAPI_POLL_WEIGHT/2);
        while(ath12k_wifi7_dp_tx_completion_handler(&dp,0,budget)){}
        assert(r->consumed==starts[k]+avail && r->write==r->published);
        cases++;
    }
    for(unsigned budget=1;budget<=256;budget++){
        struct hal_srng *r=&hal.srng_list[0];
        init_ring(r,255,CAP,CAP);
        assert(ath12k_wifi7_dp_tx_completion_handler(&dp,0,budget));
        assert(r->consumed==255+budget&&r->write-r->published==CAP&&r->max_batch<=32);
        cases++;
    }
    for(unsigned bits=0;bits<16;bits++)
    for(unsigned budget=0;budget<=127;budget++)
    for(unsigned rxavail=0;rxavail<=128;rxavail+=16)
    for(unsigned backlog=0;backlog<4;backlog++){
        unsigned limit=budget?budget:NAPI_POLL_WEIGHT;
        unsigned available[]={0,limit-1,limit,limit+1};
        bool more=false;
        mask.tx[0]=bits;
        mask.rx[0]=mask.reo_status[0]=mask.host2rxdma[0]=1;
        rx_remaining=rxavail;rx_done=maintenance=0;
        for(unsigned i=0;i<4;i++){unsigned n=available[(backlog+i)%4];init_ring(&hal.srng_list[i],255,n,0);more|=!!(bits&BIT(i))&&n>=limit;}
        int result=ath12k_wifi7_dp_service_srng(&dp,&grp,budget);
        unsigned expected_rx=min_t(unsigned,budget,rxavail);
        assert(rx_done==expected_rx && result==(int)(more?budget:expected_rx));
        assert(maintenance==((budget>0)?1u:0u)+((budget>expected_rx)?1u:0u));
        for(unsigned i=0;i<4;i++){
            unsigned n=available[(backlog+i)%4];
            unsigned expect=(bits&BIT(i))?min_t(unsigned,n,limit):0;
            assert(hal.srng_list[i].consumed==255+expect);
        }
        cases++;
    }
    printf("TX_COMPLETION_BATCHING_PASS cases=%u\n",cases);
}
'''
    c = args.output / 'tx-batching.c'
    obj = args.output / 'tx-batching.o'
    exe = args.output / 'tx-batching'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
