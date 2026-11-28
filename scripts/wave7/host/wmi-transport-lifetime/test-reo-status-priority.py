#!/usr/bin/env python3
"""Check that each positive-budget poll services mapped REO status before RX."""
import argparse
from pathlib import Path
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    s = (a.source / "wifi7/dp.c").read_text()
    m = re.findall(r"^static int ath12k_wifi7_dp_service_srng\(.*?^\}", s, re.M | re.S)
    assert len(m) == 1
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef uint8_t u8;
#define BIT(i) (1u<<(i))
#define NAPI_POLL_WEIGHT 64
#define LIST_HEAD(x) int x=0
struct napi_struct {int unused;};
struct ath12k_ext_irq_grp {struct napi_struct napi;int grp_id;};
struct ath12k_base {int num_radios;};
struct ring_mask {u8 tx[1],rx_err[1],rx_wbm_rel[1],rx[1],rx_mon_status[1],rx_mon_dest[1],tx_mon_dest[1],reo_status[1],host2rxdma[1];};
struct hw_params {struct ring_mask *ring_mask;int num_rxdma_per_pdev;};
struct dp_rxdma_ring {int unused;};
struct ath12k_dp {struct ath12k_base *ab;struct hw_params *hw_params;struct dp_rxdma_ring rx_refill_buf_ring;};
enum dp_monitor_mode {ATH12K_DP_RX_MONITOR_MODE=1,ATH12K_DP_TX_MONITOR_MODE=2};
static unsigned demand[6], calls[6], status_calls, tx_calls, refill_calls;
static bool status_expected, tx_more;
static int fls(unsigned v){return v?32-__builtin_clz(v):0;}
static bool tx(struct ath12k_dp *dp,int ring){assert(dp&&ring>=0);tx_calls++;return tx_more;}
#define ath12k_wifi7_dp_tx_completion_handler(dp,i,...) tx(dp,i)
static int rx(unsigned i,int budget){
    assert(budget>=0);
    if(budget) assert(status_calls==(unsigned)status_expected);
    calls[i]++;
    unsigned n=demand[i]<(unsigned)budget?demand[i]:(unsigned)budget;
    return n;
}
static int ath12k_wifi7_dp_rx_process_err(struct ath12k_dp *dp,struct napi_struct *n,int budget){assert(dp&&n);return rx(0,budget);}
static int ath12k_wifi7_dp_rx_process_wbm_err(struct ath12k_dp *dp,struct napi_struct *n,int budget){assert(dp&&n);return rx(1,budget);}
static int ath12k_wifi7_dp_rx_process(struct ath12k_dp *dp,int i,struct napi_struct *n,int budget){assert(dp&&n&&i>=0);return rx(2,budget);}
static int ath12k_wifi7_dp_mon_process_ring(struct ath12k_dp *dp,int id,struct napi_struct *n,int budget,int mode){assert(dp&&n&&id>=0&&mode>=0);return rx(3+mode,budget);}
static void ath12k_wifi7_dp_rx_process_reo_status(struct ath12k_dp *dp){assert(dp);status_calls++;}
static void ath12k_dp_rx_bufs_replenish(struct ath12k_dp *dp,struct dp_rxdma_ring *r,int *l,int n){assert(dp&&r&&l&&!n);refill_calls++;}
''' + m[0] + r'''
int main(void){
    struct ath12k_base ab={.num_radios=1};
    struct ring_mask mask={0};
    struct hw_params hw={&mask,1};
    struct ath12k_dp dp={.ab=&ab,.hw_params=&hw};
    struct ath12k_ext_irq_grp grp={0};
    unsigned cases=0;
    for(unsigned b=1;b<=128;b++)
    for(unsigned bits=0;bits<128;bits++)
    for(unsigned workload=0;workload<4;workload++){
        mask.tx[0]=1;
        mask.rx_err[0]=!!(bits&1);mask.rx_wbm_rel[0]=!!(bits&2);mask.rx[0]=!!(bits&4);
        mask.rx_mon_status[0]=!!(bits&8);mask.rx_mon_dest[0]=!!(bits&16);mask.tx_mon_dest[0]=!!(bits&32);
        mask.reo_status[0]=!!(bits&64);mask.host2rxdma[0]=1;
        status_expected=mask.reo_status[0];status_calls=tx_calls=refill_calls=0;tx_more=false;
        for(unsigned i=0;i<6;i++){calls[i]=0;demand[i]=(workload==0?0:workload==1?b:b/3+workload+i);}
        unsigned remain=b;
        for(unsigned i=0;i<6&&remain;i++)if(bits&BIT(i))remain-=demand[i]<remain?demand[i]:remain;
        assert(ath12k_wifi7_dp_service_srng(&dp,&grp,b)==(int)(b-remain));
        assert(status_calls==(unsigned)status_expected&&tx_calls==1&&refill_calls==(unsigned)(remain!=0));
        cases++;
    }
    printf("REO_STATUS_PRIORITY_PASS cases=%u\n",cases);
}
'''
    c=a.output/"reo-status.c"
    obj=a.output/"reo-status.o"
    exe=a.output/"reo-status"
    c.write_text(code)
    subprocess.run(["/usr/local/bin/sccache","cc","-std=gnu11","-O2","-Wall","-Wextra","-Werror",
                    "-c",str(c),"-o",str(obj)],check=True)
    subprocess.run(["cc",str(obj),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


if __name__ == "__main__":
    main()
