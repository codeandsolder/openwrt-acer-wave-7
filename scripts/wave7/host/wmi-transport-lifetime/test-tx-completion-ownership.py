#!/usr/bin/env python3
"""Exercise actual ath12k TX completion ownership and record decoding."""
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
    hal = (root / 'hal.h').read_text()
    desc = (root / 'wifi7/hal_desc.h').read_text()
    dp = (root / 'dp.h').read_text()
    take = one(common, r'^struct ath12k_pdev_dp \*\nath12k_dp_tx_take_completed\(.*?^\}')
    classify = one(tx, r'^static bool\s+ath12k_wifi7_tx_completion_is_release\(.*?^\}')
    retire = one(tx, r'^static void ath12k_wifi7_tx_retire\(.*?^\}')
    parse = one(tx, r'^static void\nath12k_wifi7_dp_tx_status_parse\(.*?^\}')
    ext = one(tx, r'^static void\nath12k_wifi7_hal_tx_cmd_ext_desc_setup\(.*?^\}')
    ext_buf = one(tx, r'^static void\nath12k_wifi7_hal_tx_ext_set_buffer\(.*?^\}')
    unmap = one(common, r'^void ath12k_dp_tx_unmap_payload\(.*?^\}') + '\n' + one(common, r'^void ath12k_dp_tx_unmap\(.*?^\}')
    ext_structs = one(desc, r'^struct hal_tx_msdu_ext_buffer \{.*?^\};') + '\n' + one(desc, r'^struct hal_tx_msdu_ext_desc \{.*?^\};')
    handler = one(tx, r'^static void\nath12k_wifi7_dp_tx_complete_record\(.*?^\}')
    assert handler.index('ath12k_wifi7_tx_completion_is_release(') < handler.index('desc_va =')
    assert handler.index('guard(rcu)();') < handler.index('ath12k_dp_tx_take_completed(')
    assert handler.index('ath12k_dp_tx_take_completed(') < handler.index('ath12k_wifi7_tx_retire(')
    assert handler.index('ath12k_wifi7_tx_retire(') < handler.index('ath12k_dp_tx_process_htt_tx_complete(')
    assert handler.index('ath12k_wifi7_dp_tx_complete_msdu(') < handler.index('atomic_dec_and_test(')
    assert handler.index('struct hal_tx_status ts = {};') < handler.index('ath12k_wifi7_dp_tx_status_parse(')
    for name in ('ath12k_dp_tx_htt_tx_complete_buf','ath12k_dp_tx_process_htt_tx_complete','ath12k_wifi7_dp_tx_complete_msdu'):
        fn = one(tx, rf'^static void\s+{name}\(.*?^\}}')
        assert 'dma_unmap_single(' not in fn and 'num_tx_pending' not in fn
    constants = '\n'.join(re.findall(r'^#define (?:HAL_WBM_COMPL_TX_INFO[0-3]_|HAL_TX_RATE_STATS_INFO0_|HAL_TX_MSDU_EXT_INFO[01]_)[^\n]+',desc,re.M))
    constants += '\n' + '\n'.join(re.findall(r'^#define MAX_(?:TQM_RELEASE_REASON|FW_TX_STATUS) [0-9]+$',dp,re.M))
    enums = '\n'.join(one(hal,rf'^enum {tag} \{{.*?^\}};') for tag in
                       ('hal_wbm_rel_src_module','hal_wbm_htt_tx_comp_status'))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32, __le32;
typedef uint64_t dma_addr_t;
#define ATH12K_TX_EXT_MAX_FRAGS 5
#define BUILD_BUG_ON(x) _Static_assert(!(x), "layout")
#define lower_32_bits(x) ((u32)(x))
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define BIT(n) (UINT32_C(1) << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
#define DMA_TO_DEVICE 1
#define HAL_TX_STATUS_FLAGS_RATE_STATS_VALID BIT(3)
#define upper_32_bits(x) ((u32)((uint64_t)(x) >> 32))
#define le32_to_cpu(x) (x)
static u32 le32_encode_bits(u32 val,u32 mask) {return (val<<__builtin_ctz(mask))&mask;}
static u32 le32_get_bits(u32 val,u32 mask) {return (val&mask)>>__builtin_ctz(mask);}
#define u32_get_bits le32_get_bits
''' + constants + '\n' + enums + r'''
struct ath12k_base { unsigned warnings; };
#define ath12k_warn(ab, ...) (++(ab)->warnings)
struct ath12k_link_vif { int link_stats_lock; struct { unsigned tx_completed; } link_stats; };
struct ath12k_vif { struct ath12k_link_vif *link[4]; };
struct ieee80211_vif { struct ath12k_vif priv; };
struct ath12k_skb_cb { uintptr_t paddr; struct ieee80211_vif *vif; u8 link_id; };
struct ath12k_tx_ext_cb { uintptr_t paddr, frags[5]; };
struct skb_shared_info { unsigned nr_frags, frags[5]; };
struct sk_buff { unsigned len; struct ath12k_skb_cb cb; struct ath12k_tx_ext_cb ext_cb; struct skb_shared_info shinfo; };
#define ATH12K_TX_EXT_CB(s) (&(s)->ext_cb)
#define skb_shinfo(s) (&(s)->shinfo)
#define skb_headlen(s) ((s)->len)
#define skb_frag_size(f) (*(f))
#define skb_is_nonlinear(s) ((s)->shinfo.nr_frags != 0)
struct list_head { unsigned id; };
struct ath12k_tx_desc_info { struct list_head list; struct sk_buff *skb,*skb_ext_desc; u8 mac_id,pool_id; };
struct ath12k_tx_desc_params { struct sk_buff *skb,*skb_ext_desc; };
struct ath12k_pdev_dp { struct ath12k_dp *dp; };
struct ath12k_tx_completion_stats {
    unsigned tx_wbm_rel_source[HAL_WBM_REL_SRC_MODULE_MAX];
    unsigned tqm_rel_reason[MAX_TQM_RELEASE_REASON];
    unsigned fw_tx_status[MAX_FW_TX_STATUS];
    unsigned completed, sg_completed;
};
struct ath12k_dp {
    struct ath12k_base *ab;
    int tx_desc_lock[4];
    struct list_head tx_desc_free_list[4];
    struct ath12k_pdev_dp *dp_pdevs[3];
    void *dev, *hw_params;
    struct {
        struct ath12k_tx_completion_stats tx_completion[4];
    } device_stats;
};
struct hal_tx_info { uint64_t paddr; unsigned data_len,encap_type,encrypt_type; };
''' + ext_structs + r'''
struct hal_wbm_completion_ring_tx {u32 info0,info1,info2,info3; struct {u32 info0;} rate_stats;};
struct hal_tx_status {enum hal_wbm_rel_src_module buf_rel_source; unsigned status,ppdu_id,peer_id,ack_rssi,flags,pkt_type,mcs,sgi,bw,tones,ofdma;};
static unsigned moves,unmaps,ext_unmaps,ext_frees;
static bool in_rcu;
static struct sk_buff *payload,*extension;
static void spin_lock_bh(int *lock) {assert(!*lock);*lock=1;}
static void spin_unlock_bh(int *lock) {assert(*lock);*lock=0;}
static int ath12k_hw_mac_id_to_pdev_id(void *hw,unsigned mac) {(void)hw;return mac==255?-1:(int)mac;}
static struct ath12k_pdev_dp *ath12k_dp_to_pdev_dp(struct ath12k_dp *dp,int id)
{assert(in_rcu);return dp->dp_pdevs[id];}
static void list_move_tail(struct list_head *node,struct list_head *head) {node->id=head->id;++moves;}
static void dma_unmap_single(void *dev,uintptr_t addr,unsigned len,int dir)
{assert(dev && dir==DMA_TO_DEVICE && in_rcu); if(len==payload->len){assert(addr==payload->cb.paddr);++unmaps;}else{assert(extension && len==extension->len && addr==extension->ext_cb.paddr);++ext_unmaps;}}
static void dma_unmap_page(void *dev, uintptr_t addr, unsigned len, int dir)
{ (void)dev; (void)addr; (void)len; (void)dir; assert(0); }
static void dev_kfree_skb_any(struct sk_buff *s) {if(s){assert(s==extension);++ext_frees;}}
#define ATH12K_SKB_CB(s) (&(s)->cb)
#define rcu_dereference(p) (assert(in_rcu),(p))
static struct ath12k_vif *ath12k_vif_to_ahvif(struct ieee80211_vif *vif) {return &vif->priv;}
''' + unmap + '\n' + take + '\n' + classify + '\n' + retire + '\n' + parse + '\n' + ext_buf + '\n' + ext + r'''
int main(void)
{
    struct ath12k_base ab={0};
    struct ath12k_dp dp={.ab=&ab,.dev=&dp};
    struct ath12k_pdev_dp radios[3];
    unsigned cases=0;
    for(unsigned i=0;i<4;i++)dp.tx_desc_free_list[i].id=i+10;
    for(unsigned i=0;i<3;i++)radios[i].dp=&dp;
    for(unsigned ring=0;ring<4;ring++)
    for(unsigned src=0;src<8;src++)
    for(unsigned status=0;status<16;status++){
        memset(&dp.device_stats,0,sizeof(dp.device_stats));
        bool expected=src==HAL_WBM_REL_SRC_MODULE_TQM ||
            (src==HAL_WBM_REL_SRC_MODULE_FW && status<MAX_FW_TX_STATUS &&
            status!=HAL_WBM_REL_HTT_TX_COMP_STATUS_MEC_NOTIFY);
        assert(ath12k_wifi7_tx_completion_is_release(&dp,&dp.device_stats.tx_completion[ring],src,status)==expected);
        for(unsigned i=0;i<ARRAY_SIZE(dp.device_stats.tx_completion[ring].tx_wbm_rel_source);i++)
            assert(dp.device_stats.tx_completion[ring].tx_wbm_rel_source[i]==(i==src));
        for(unsigned i=0;i<MAX_TQM_RELEASE_REASON;i++)
            assert(dp.device_stats.tx_completion[ring].tqm_rel_reason[i]==(src==HAL_WBM_REL_SRC_MODULE_TQM && i==status));
        for(unsigned i=0;i<MAX_FW_TX_STATUS;i++)
            assert(dp.device_stats.tx_completion[ring].fw_tx_status[i]==(src==HAL_WBM_REL_SRC_MODULE_FW && i==status));
        for(unsigned other=0;other<4;other++) {
            if(other==ring)continue;
            struct ath12k_tx_completion_stats zero={0};
            assert(!memcmp(&dp.device_stats.tx_completion[other],&zero,sizeof(zero)));
        }
        ++cases;
    }
    for(unsigned pool=0;pool<4;pool++)
    for(unsigned mac=0;mac<256;mac++)
    for(unsigned mask=0;mask<8;mask++)
    for(unsigned published=0;published<2;published++)
    for(unsigned ext=0;ext<2;ext++){
        struct sk_buff data={.len=1514},extra={.len=32};
        struct ath12k_tx_desc_info desc={.list={99},.skb=published?&data:NULL,.skb_ext_desc=published&&ext?&extra:NULL,.mac_id=mac,.pool_id=pool};
        struct ath12k_tx_desc_params out={0};
        for(unsigned i=0;i<3;i++)dp.dp_pdevs[i]=(mask&BIT(i))?&radios[i]:NULL;
        moves=0;in_rcu=true;
        bool success=published && mac<3 && (mask&BIT(mac));
        assert(ath12k_dp_tx_take_completed(&dp,&desc,&out)==(success?&radios[mac]:NULL));
        assert(moves==success);
        if(success){
            assert(out.skb==&data && out.skb_ext_desc==(ext?&extra:NULL));
            assert(!desc.skb && !desc.skb_ext_desc && desc.list.id==pool+10);
            assert(!ath12k_dp_tx_take_completed(&dp,&desc,&out) && moves==1);
        }else{
            assert(desc.skb==(published?&data:NULL) && desc.skb_ext_desc==(published&&ext?&extra:NULL) && desc.list.id==99);
            assert(!out.skb);
        }
        assert(!dp.tx_desc_lock[pool]);in_rcu=false;
        ++cases;
    }
    for(unsigned ring=0;ring<4;ring++)
    for(unsigned ext=0;ext<2;ext++)
    for(unsigned zero=0;zero<2;zero++)
    for(unsigned vif_present=0;vif_present<2;vif_present++)
    for(unsigned link_present=0;link_present<2;link_present++){
        struct ath12k_link_vif link={0};
        struct ieee80211_vif vif={0};
        vif.priv.link[2]=link_present?&link:NULL;
        struct sk_buff data={.len=1514,.cb={.paddr=zero?0:0x1000,.vif=vif_present?&vif:NULL,.link_id=2}},extra={.len=32,.ext_cb={.paddr=zero?0x2000:0}};
        struct ath12k_tx_desc_params out={&data,ext?&extra:NULL};
        memset(&dp.device_stats,0,sizeof(dp.device_stats));
        payload=&data;extension=&extra;unmaps=ext_unmaps=ext_frees=0;in_rcu=true;
        ath12k_wifi7_tx_retire(&radios[0],&out,ring);
        assert(unmaps==1 && ext_unmaps==ext && ext_frees==ext);
        assert(link.link_stats.tx_completed==(vif_present&&link_present));
        for(unsigned i=0;i<4;i++)assert(dp.device_stats.tx_completion[i].completed==(i==ring));
        in_rcu=false;++cases;
    }
    for(unsigned high=0;high<256;high++)
    for(unsigned len=1;len<65536;len+=257){
        struct hal_tx_info info={.paddr=((uint64_t)high<<32)|UINT32_C(0xa9876543),.data_len=len,.encap_type=2,.encrypt_type=7};
        struct hal_tx_msdu_ext_desc d={0};
        ath12k_wifi7_hal_tx_cmd_ext_desc_setup(&d,&info,true);
        assert(d.buf[0].info0==UINT32_C(0xa9876543));
        assert(le32_get_bits(d.buf[0].info1,HAL_TX_MSDU_EXT_INFO1_BUF_PTR_HI)==high);
        assert(le32_get_bits(d.buf[0].info1,HAL_TX_MSDU_EXT_INFO1_BUF_LEN)==len);
        assert(le32_get_bits(d.buf[0].info1,HAL_TX_MSDU_EXT_INFO1_EXTN_OVERRIDE)==1);
        assert(le32_get_bits(d.buf[0].info1,HAL_TX_MSDU_EXT_INFO1_ENCAP_TYPE)==2);
        assert(le32_get_bits(d.buf[0].info1,HAL_TX_MSDU_EXT_INFO1_ENCRYPT_TYPE)==7);
        ++cases;
    }
    for(unsigned src=0;src<8;src++)
    for(unsigned valid=0;valid<2;valid++)
    for(unsigned mcs=0;mcs<16;mcs++){
        struct hal_wbm_completion_ring_tx d={.info0=src,.rate_stats.info0=le32_encode_bits(valid,HAL_TX_RATE_STATS_INFO0_VALID)|le32_encode_bits(mcs,HAL_TX_RATE_STATS_INFO0_MCS)};
        struct hal_tx_status ts={0};
        ath12k_wifi7_dp_tx_status_parse(&d,&ts);
        assert((unsigned)ts.buf_rel_source==src);
        assert(!!(ts.flags&HAL_TX_STATUS_FLAGS_RATE_STATS_VALID)==(src==HAL_WBM_REL_SRC_MODULE_TQM&&valid));
        assert(ts.mcs==(src==HAL_WBM_REL_SRC_MODULE_TQM&&valid?mcs:0));
        ++cases;
    }
    printf("TX_COMPLETION_OWNERSHIP_PASS cases=%u warnings=%u\n",cases,ab.warnings);
}
'''
    c = args.output / 'tx-completion.c'
    obj = args.output / 'tx-completion.o'
    exe = args.output / 'tx-completion'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache','cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                    '-c',str(c),'-o',str(obj)],check=True)
    subprocess.run(['cc',str(obj),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    main()
