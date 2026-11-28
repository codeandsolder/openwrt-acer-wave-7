#!/usr/bin/env python3
"""Exercise the actual six-buffer HAL encoder, eligibility and DMA ownership."""
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
    tx = (root / 'wifi7/dp_tx.c').read_text()
    common = (root / 'dp_tx.c').read_text()
    desc = (root / 'wifi7/hal_desc.h').read_text()
    core = (root / 'core.h').read_text()
    defines = '\n'.join(re.findall(r'^#define HAL_TX_MSDU_EXT_INFO[01]_[^\n]+', desc, re.M))
    defines += '\n' + one(core, r'^#define ATH12K_TX_EXT_MAX_FRAGS [0-9]+$')
    structs = '\n'.join(one(desc, rf'^struct {name} \{{.*?^\}};') for name in
                        ('hal_tx_msdu_ext_buffer', 'hal_tx_msdu_ext_desc'))
    ext_cb = one(core, r'^struct ath12k_tx_ext_cb \{.*?^\};')
    helpers = '\n'.join(one(tx, rf'^static (?:void|bool)\s+{name}\(.*?^\}}') for name in
                        ('ath12k_wifi7_hal_tx_ext_set_buffer',
                         'ath12k_wifi7_hal_tx_cmd_ext_desc_setup',
                         'ath12k_wifi7_tx_sg_eligible'))
    helpers += '\n' + '\n'.join(one(common, rf'^void {name}\(.*?^\}}') for name in
                                  ('ath12k_dp_tx_unmap_payload', 'ath12k_dp_tx_unmap'))
    map_loop = one(tx, r'^\t\twhile \(sg && mapped_frags < skb_shinfo\(skb\)->nr_frags\) \{.*?^\t\t\}')
    submit = one(tx, r'^int ath12k_wifi7_dp_tx\(.*?^\}')
    assert submit.index('skb_linearize(skb)') < submit.index('ath12k_dp_tx_assign_buffer(')
    assert submit.index('skb_frag_dma_map(') < submit.index('ti.paddr = dma_map_single(dp->dev, skb_ext_desc->data,')
    assert submit.index('ATH12K_TX_EXT_CB(skb_ext_desc)->paddr = ti.paddr;') < submit.index('tcl_ring_sel:')
    assert submit.index('ath12k_dp_tx_unmap_payload(dp, skb, skb_ext_desc, mapped_frags);') < submit.index('kfree_skb(skb_ext_desc);')
    assert 'ath12k_dp_tx_unmap(dp, skb, tx_desc_info->skb_ext_desc);' in (root / 'dp.c').read_text()
    assert 'ath12k_dp_tx_unmap(dp, skb, params->skb_ext_desc);' in tx
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <errno.h>
typedef uint32_t __le32;
typedef uint64_t dma_addr_t;
#define BIT(n) (1u << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
#define BUILD_BUG_ON(x) _Static_assert(!(x), "layout")
#define lower_32_bits(x) ((uint32_t)(x))
#define upper_32_bits(x) ((uint32_t)((uint64_t)(x) >> 32))
#define DMA_TO_DEVICE 1
#define U16_MAX UINT16_MAX
#define ETH_HLEN 14
#define ATH12K_FLAG_RAW_MODE 0
#define ATH12K_SKB_HW_80211_ENCAP BIT(1)
#define HAL_TCL_ENCAP_TYPE_ETHERNET 2
#define test_bit(bit,ptr) (!!(*(ptr)&BIT(bit)))
static uint32_t le32_encode_bits(uint32_t v,uint32_t m){return (v<<__builtin_ctz(m))&m;}
''' + defines + '\n' + structs + '\n' + ext_cb + r'''
struct ath12k_skb_cb { dma_addr_t paddr; unsigned flags; };
typedef struct { unsigned len; dma_addr_t addr; } skb_frag_t;
struct skb_shared_info { unsigned nr_frags; skb_frag_t frags[8]; };
struct sk_buff {
    unsigned len, headlen;
    bool frag_list;
    struct skb_shared_info shinfo;
    struct ath12k_skb_cb cb;
    struct ath12k_tx_ext_cb ext_cb;
};
#define skb_shinfo(s) (&(s)->shinfo)
#define skb_headlen(s) ((s)->headlen)
#define skb_has_frag_list(s) ((s)->frag_list)
#define skb_frag_size(f) ((f)->len)
#define ATH12K_SKB_CB(s) (&(s)->cb)
#define ATH12K_TX_EXT_CB(s) (&(s)->ext_cb)
struct ath12k_hw_params { bool supports_tx_sg; unsigned iova_mask; };
struct ath12k_base { unsigned dev_flags; };
struct ath12k_dp { struct ath12k_hw_params *hw_params; struct ath12k_base *ab; void *dev; };
struct ath12k_dp_vif { unsigned tx_encap_type; };
struct hal_tx_info { dma_addr_t paddr; unsigned data_len, encap_type, encrypt_type; };
static struct sk_buff *payload, *extension;
static unsigned maps, fail_at, page_unmaps, head_unmaps, ext_unmaps, frees;
static dma_addr_t skb_frag_dma_map(void *dev, skb_frag_t *frag,unsigned off,unsigned len,int dir) {
    assert(dev&&dir==DMA_TO_DEVICE&&!off&&len==frag->len);
    assert(frag==&payload->shinfo.frags[maps]);
    return maps++==fail_at?UINT64_MAX:frag->addr;
}
#define dma_mapping_error(dev,addr) ((void)(dev),(addr)==UINT64_MAX)
static void dma_unmap_page(void *dev,dma_addr_t addr,unsigned len,int dir) {
    assert(dev&&dir==DMA_TO_DEVICE&&page_unmaps<payload->shinfo.nr_frags);
    skb_frag_t *f=&payload->shinfo.frags[page_unmaps++];
    assert(addr==f->addr&&len==f->len&&!frees);
}
static void dma_unmap_single(void *dev,dma_addr_t addr,unsigned len,int dir) {
    assert(dev&&dir==DMA_TO_DEVICE&&!frees);
    if(len==payload->headlen){assert(addr==payload->cb.paddr);++head_unmaps;}
    else {assert(extension&&len==extension->len&&addr==extension->ext_cb.paddr);++ext_unmaps;}
}
static void dev_kfree_skb_any(struct sk_buff *s){if(s){assert(s==extension);++frees;}}
''' + helpers + r'''
static int map_and_retire(struct ath12k_dp *dp,struct sk_buff *skb,struct sk_buff *skb_ext_desc,
                          struct hal_tx_msdu_ext_desc *msg,bool sg,bool ext_map_ok,bool ring_ok)
{
    unsigned mapped_frags=0;
    int ret=0;
''' + map_loop + r'''
    if(!ext_map_ok){ret=-ENOMEM;goto fail_free_ext_skb;}
    if(!ring_ok){dma_unmap_single(dp->dev,ATH12K_TX_EXT_CB(skb_ext_desc)->paddr,skb_ext_desc->len,DMA_TO_DEVICE);ret=-ENOMEM;goto fail_free_ext_skb;}
    ath12k_dp_tx_unmap(dp,skb,skb_ext_desc);
    return 0;
fail_free_ext_skb:
    ath12k_dp_tx_unmap_payload(dp,skb,skb_ext_desc,mapped_frags);
    dev_kfree_skb_any(skb_ext_desc);
    return ret;
}
int main(void)
{
    _Static_assert(sizeof(struct hal_tx_msdu_ext_desc)==72,"size");
    _Static_assert(offsetof(struct hal_tx_msdu_ext_desc,buf)==24,"offset");
    _Static_assert(sizeof(struct hal_tx_msdu_ext_buffer)==8,"stride");
    struct ath12k_hw_params hw={0};
    struct ath12k_base ab={0};
    struct ath12k_dp dp={.hw_params=&hw,.ab=&ab,.dev=&dp};
    struct ath12k_dp_vif vif={0};
    unsigned eligibility=0,mapping=0,encoding=0;
    for(unsigned flags=0;flags<64;flags++)
    for(unsigned nr=0;nr<=7;nr++)
    for(unsigned head=0;head<4;head++)
    for(unsigned frag=0;frag<4;frag++){
        unsigned heads[]={0,13,14,65536}, lens[]={0,1,65535,65536};
        struct sk_buff s={.headlen=heads[head],.frag_list=!!(flags&16),.shinfo={.nr_frags=nr}};
        for(unsigned i=0;i<nr;i++)s.shinfo.frags[i].len=lens[frag];
        hw.supports_tx_sg=!!(flags&1);hw.iova_mask=!!(flags&2);
        ab.dev_flags=(flags&4)?BIT(ATH12K_FLAG_RAW_MODE):0;
        s.cb.flags=(flags&8)?ATH12K_SKB_HW_80211_ENCAP:0;
        vif.tx_encap_type=(flags&32)?2:1;
        bool expected=flags==41&&nr&&nr<=5&&head==2&&(frag==1||frag==2);
        assert(ath12k_wifi7_tx_sg_eligible(&dp,&vif,&s)==expected);
        ++eligibility;
    }
    for(unsigned high=0;high<256;high++)
    for(unsigned len=1;len<=65535;len+=257)
    for(unsigned override=0;override<2;override++){
        struct hal_tx_msdu_ext_desc d={0};
        struct hal_tx_info ti={.paddr=((uint64_t)high<<32)|UINT32_C(0xa9876543),.data_len=len,.encap_type=2,.encrypt_type=7};
        ath12k_wifi7_hal_tx_cmd_ext_desc_setup(&d,&ti,override);
        assert(d.buf[0].info0==UINT32_C(0xa9876543));
        assert(d.buf[0].info1==(high|(len<<16)|(override?0x3d00:0)));
        for(unsigned i=1;i<=5;i++)assert(!d.buf[i].info0&&!d.buf[i].info1);
        ++encoding;
    }
    for(unsigned nr=1;nr<=5;nr++)
    for(unsigned zero=0;zero<=nr+1;zero++)
    for(unsigned fail=0;fail<=nr;fail++)
    for(unsigned ext_ok=0;ext_ok<2;ext_ok++)
    for(unsigned ring_ok=0;ring_ok<2;ring_ok++){
        struct sk_buff data={.headlen=64,.cb={.paddr=zero==0?0:0x1000},.shinfo={.nr_frags=nr}};
        struct sk_buff ext={.len=72,.ext_cb={.paddr=zero==nr+1?0:0x2000}};
        for(unsigned i=0;i<nr;i++){
            data.shinfo.frags[i]=(skb_frag_t){.len=1514+i,.addr=zero==i+1?0:((uint64_t)(0x80+i)<<32)|(0x3000+i*4096)};
        }
        struct hal_tx_msdu_ext_desc d={0};
        payload=&data;extension=&ext;maps=page_unmaps=head_unmaps=ext_unmaps=frees=0;fail_at=fail;
        bool success=fail==nr&&ext_ok&&ring_ok;
        assert((map_and_retire(&dp,&data,&ext,&d,true,ext_ok,ring_ok)==0)==success);
        assert(maps==(fail<nr?fail+1:nr)&&page_unmaps==fail&&head_unmaps==1&&frees==1);
        assert(ext_unmaps==(fail==nr&&ext_ok));
        for(unsigned i=0;i<fail;i++){
            skb_frag_t *f=&data.shinfo.frags[i];
            assert(d.buf[i+1].info0==lower_32_bits(f->addr));
            assert(d.buf[i+1].info1==(upper_32_bits(f->addr)|(f->len<<16)));
        }
        for(unsigned i=fail;i<5;i++)assert(!d.buf[i+1].info0&&!d.buf[i+1].info1);
        ++mapping;
    }
    printf("TX_SG_PASS eligibility=%u encoding=%u mapping=%u\n",eligibility,encoding,mapping);
}
'''
    c = args.output / 'tx-sg.c'
    obj = args.output / 'tx-sg.o'
    exe = args.output / 'tx-sg'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
