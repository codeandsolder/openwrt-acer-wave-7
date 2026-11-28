#!/usr/bin/env python3
"""Exercise real error attribution and reserved-code bounds from the driver."""
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
    hdr = (root / 'dp.h').read_text()
    rx = (root / 'wifi7/dp_rx.c').read_text()
    hal = (root / 'hal.h').read_text()
    dims = '\n'.join(re.findall(r'^#define ATH12K_RX_ERROR_(?:CODES|LINKS|TIDS) [^\n]+', hdr, re.M))
    assert len(dims.splitlines()) == 3
    structs = '\n'.join([one(hdr, r'^enum ath12k_rx_error_source \{.*?^\};'),
                         one(hdr, r'^struct ath12k_rx_error_stats \{.*?^\};')])
    enums = '\n'.join(one(hal, rf'^enum {name} \{{.*?^\}};')
                      for name in ('hal_reo_dest_ring_error_code', 'hal_reo_entr_rxdma_ecode'))
    helpers = '\n'.join(one(rx, rf'^static (?:bool |void\n){name}\(.*?^\}}')
                        for name in ('ath12k_wifi7_dp_rx_count_error', 'ath12k_wifi7_dp_rx_h_reo_err',
                                     'ath12k_wifi7_dp_rx_h_rxdma_err'))
    assert rx.index('ath12k_wifi7_dp_rx_count_error(dp->rx_error_stats') < rx.index(
        'switch (rxcb->err_rel_src)', rx.index('ath12k_wifi7_dp_rx_count_error(dp->rx_error_stats'))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint64_t atomic64_t;
#define atomic64_inc(p) (++*(p))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define ATH12K_GROUP_MAX_RADIO 6
#define IEEE80211_NUM_TIDS 16
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define fallthrough __attribute__((fallthrough))
#define HAL_RX_MPDU_ERR_TKIP_MIC 1
#define HAL_WBM_REL_SRC_MODULE_REO 1
#define HAL_WBM_REL_SRC_MODULE_RXDMA 2
''' + dims + '\n' + structs + '\n' + enums + r'''
struct ath12k_skb_rxcb {u8 err_code, err_rel_src, hw_link_id; bool is_continuation;};
struct sk_buff {struct ath12k_skb_rxcb cb;};
#define ATH12K_SKB_RXCB(s) (&(s)->cb)
struct hal_rx_desc_data {bool msdu_done; u8 tid; unsigned err_bitmap;};
struct sk_buff_head {int dummy;};
struct ath12k_device_dp_stats {
    unsigned rxdma_error[HAL_REO_ENTR_RING_RXDMA_ECODE_MAX];
    unsigned reo_error[HAL_REO_DEST_RING_ERROR_CODE_MAX];
    unsigned sentinel;
};
struct ath12k_dp {struct ath12k_device_dp_stats device_stats;};
struct ath12k_pdev_dp {struct ath12k_dp *dp;};
static bool ath12k_wifi7_dp_rx_h_unauth_wds_err(struct ath12k_pdev_dp *dp,struct sk_buff *skb,struct hal_rx_desc_data *rx)
{(void)dp;(void)skb;(void)rx;return false;}
static bool ath12k_wifi7_dp_rx_h_tkip_mic_err(struct ath12k_pdev_dp *dp,struct sk_buff *skb,struct hal_rx_desc_data *rx)
{(void)dp;(void)skb;(void)rx;return false;}
static bool ath12k_wifi7_dp_rx_h_null_q_desc(struct ath12k_pdev_dp *dp,struct sk_buff *skb,struct hal_rx_desc_data *rx,struct sk_buff_head *list)
{(void)dp;(void)skb;(void)rx;(void)list;return false;}
''' + helpers + r'''
static struct ath12k_rx_error_stats stats, expected;
int main(void)
{
    unsigned cases=0, dispatch=0;
    for(unsigned src=0;src<4;src++)
    for(unsigned code=0;code<256;code++)
    for(unsigned li=0;li<=ATH12K_GROUP_MAX_RADIO+1;li++)
    for(unsigned ti=0;ti<=IEEE80211_NUM_TIDS+1;ti++)
    for(unsigned flags=0;flags<4;flags++){
        unsigned link=li==ATH12K_GROUP_MAX_RADIO+1?255:li;
        unsigned tid=ti==IEEE80211_NUM_TIDS+1?255:ti;
        struct ath12k_skb_rxcb cb={.err_rel_src=src,.err_code=code,.hw_link_id=link,.is_continuation=!!(flags&1)};
        struct hal_rx_desc_data rx={.msdu_done=!!(flags&2),.tid=tid};
        ath12k_wifi7_dp_rx_count_error(&stats,&cb,&rx);
        ath12k_wifi7_dp_rx_count_error(NULL,&cb,&rx);
        if((src==1||src==2)&&code<32){
            unsigned l=link<6?link:6;
            unsigned t=flags==2&&tid<16?tid:16;
            expected.count[src-1][code][l][t]++;
        }
        ++cases;
    }
    assert(!memcmp(&stats,&expected,sizeof(stats)));
    struct ath12k_dp dp={.device_stats={.sentinel=0xdeadbeef}};
    struct ath12k_pdev_dp p={.dp=&dp};
    struct sk_buff_head list={0};
    for(unsigned code=0;code<256;code++)
    for(unsigned mic=0;mic<2;mic++){
        struct sk_buff s={.cb={.err_code=code}};
        struct hal_rx_desc_data rx={.err_bitmap=mic};
        bool reo_drop=ath12k_wifi7_dp_rx_h_reo_err(&p,&s,&rx,&list);
        bool dma_drop=ath12k_wifi7_dp_rx_h_rxdma_err(&p,&s,&rx);
        assert(reo_drop==(code!=HAL_REO_DEST_RING_ERROR_CODE_DESC_ADDR_ZERO));
        assert(dma_drop==!(code==HAL_REO_ENTR_RING_RXDMA_ECODE_UNAUTH_WDS_ERR||
               (mic&&(code==HAL_REO_ENTR_RING_RXDMA_ECODE_DECRYPT_ERR||
                      code==HAL_REO_ENTR_RING_RXDMA_ECODE_TKIP_MIC_ERR))));
        ++dispatch;
    }
    for(unsigned i=0;i<ARRAY_SIZE(dp.device_stats.reo_error);i++)assert(dp.device_stats.reo_error[i]==2);
    for(unsigned i=0;i<ARRAY_SIZE(dp.device_stats.rxdma_error);i++)assert(dp.device_stats.rxdma_error[i]==2);
    assert(dp.device_stats.sentinel==0xdeadbeef);
    printf("RX_ERROR_ATTRIBUTION_PASS classification=%u dispatch=%u\n",cases,dispatch);
}
'''
    c = args.output / 'rx-error.c'
    obj = args.output / 'rx-error.o'
    exe = args.output / 'rx-error'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
