#!/usr/bin/env python3
"""Exercise actual RX page-pool allocation, refill, sync and fragment sizing."""
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
    rx = (root / 'dp_rx.c').read_text()
    wifi = (root / 'wifi7/dp_rx.c').read_text()
    header = (root / 'dp_rx.h').read_text()
    dp = (root / 'dp.c').read_text()
    build = one(rx, r'^static struct sk_buff \*ath12k_dp_rx_build_skb\(.*?^\}')
    refill = one(rx, r'^int ath12k_dp_rx_bufs_replenish\(.*?^\}')
    setup = one(rx, r'^static int ath12k_dp_rxdma_ring_buf_setup\(.*?^\}')
    unmap = one(header, r'^static inline void ath12k_dp_unmap_rx_buf\(.*?^\}')
    cut = one(rx, r'^static size_t ath12k_dp_list_cut_nodes\(.*?^\}')
    enqueue = one(rx, r'^static void ath12k_dp_rx_enqueue_free\(.*?^\}')
    defrag = one(wifi, r'^static int ath12k_wifi7_dp_rx_h_defrag\(.*?^\}')
    expand = one(defrag, r'^\textra_space = max_t.*?^\t\}')
    cleanup = one(dp, r'^static void ath12k_dp_cc_cleanup\(.*?^\}')
    assert cleanup.index('ath12k_dp_unmap_rx_buf(dp, skb)') < cleanup.index('dev_kfree_skb_any(skb)') < cleanup.index('page_pool_destroy(')
    assert cleanup.index('spin_unlock_bh(&dp->rx_desc_lock)') < cleanup.index('page_pool_destroy(')
    assert 'page_pool_destroy(' not in rx
    assert 'ath12k_dp_to_pdev_dp(partner_dp, pdev_idx)' in one(wifi, r'^int ath12k_wifi7_dp_rx_process_err\(.*?^\}')
    assert refill.index('if (!desc)') < refill.index('rx_desc->skb = skb;')
    assert defrag.index('first_frag->pp_recycle = 0') < defrag.index('skb_put_data(first_frag')
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define PAGE_SIZE 4096
#define DP_RX_BUFFER_SIZE 2048
#define DP_RX_POOL_HEADROOM 128
#define SKB_HEAD_ALIGN(x) (((x)+63)/64*64+320)
#define SKB_WITH_OVERHEAD(x) ((x)-320)
#define SKB_TRUESIZE(x) ((x)+320+256)
#define BUILD_BUG_ON(x) _Static_assert(!(x),"size")
#define GFP_ATOMIC 0
#define NUMA_NO_NODE -1
#define PP_FLAG_DMA_MAP 1
#define PP_FLAG_DMA_SYNC_DEV 2
#define min(a,b) ((a)<(b)?(a):(b))
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
#define IS_ERR(p) ((uintptr_t)(p)>(uintptr_t)-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define list_entry(p,t,m) container_of(p,t,m)
struct list_head {struct list_head *next,*prev;};
static void INIT_LIST_HEAD(struct list_head *h) {h->next=h->prev=h;}
#define LIST_HEAD(n) struct list_head n={&n,&n}
static bool list_empty(struct list_head *h) {return h->next==h;}
static void list_del(struct list_head *n) {n->prev->next=n->next;n->next->prev=n->prev;n->next=n->prev=NULL;}
static void list_add_tail(struct list_head *n,struct list_head *h) {n->next=h;n->prev=h->prev;h->prev->next=n;h->prev=n;}
static void list_cut_before(struct list_head *dst,struct list_head *src,struct list_head *cut) {
    INIT_LIST_HEAD(dst);
    while(src->next!=cut){struct list_head *n=src->next;list_del(n);list_add_tail(n,dst);}
}
static void list_splice_tail_init(struct list_head *src,struct list_head *dst){
    while(!list_empty(src)){struct list_head *n=src->next;list_del(n);list_add_tail(n,dst);}
}
#define list_for_each(cur,h) for(cur=(h)->next;cur!=(h);cur=cur->next)
#define list_for_each_entry_safe(cur,safe,h,m) \
    for(struct list_head *i=(h)->next,*next=i->next;i!=(h)&&((cur)=list_entry(i,__typeof__(*(cur)),m),(safe)=next==(h)?NULL:list_entry(next,__typeof__(*(safe)),m),true);i=next,next=i->next)
#define list_first_entry_or_null(h,t,m) (list_empty(h)?NULL:list_entry((h)->next,t,m))
enum dma_data_direction { DMA_BIDIRECTIONAL,DMA_TO_DEVICE,DMA_FROM_DEVICE };
struct page_pool_params {unsigned order,flags,pool_size,max_len,offset;int nid;enum dma_data_direction dma_dir;void *dev;};
struct page_pool {struct page_pool_params p;};
struct page {struct page_pool *pool;unsigned id;bool allocated,cpu;unsigned char buf[PAGE_SIZE] __attribute__((aligned(128)));};
struct ath12k_skb_rxcb {uintptr_t paddr;bool pool_mapped,is_frag;};
struct sk_buff {struct page *page;unsigned char *head,*data;unsigned len,tailroom,truesize;bool pp_recycle;struct ath12k_skb_rxcb cb;};
#define ATH12K_SKB_RXCB(s) (&(s)->cb)
#define skb_tailroom(s) ((s)->tailroom)
enum hal_rx_buf_return_buf_manager { RBM=3 };
struct ath12k_rx_desc_info {struct list_head list;bool in_use;struct sk_buff *skb;unsigned cookie;};
struct ath12k_buffer_addr {uintptr_t addr;unsigned cookie,mgr;};
struct hal_srng {int lock;unsigned free,published,attempts,fail_at;struct ath12k_buffer_addr entries[64];};
struct ath12k_base {void *dev;struct ath12k_dp *dp;};
struct hal {struct hal_srng srng_list[1];struct {enum hal_rx_buf_return_buf_manager rx_buf_rbm;} *hal_params;};
struct dp_rxdma_ring {struct {int ring_id;unsigned size;} refill_buf_ring;int bufs_max;struct page_pool *page_pool;};
struct ath12k_dp {struct ath12k_base *ab;struct hal *hal;void *dev;struct dp_rxdma_ring rx_refill_buf_ring;struct list_head rx_desc_free_list;int rx_desc_lock;};
#define HAL_RXDMA_BUF 0
#define u32 uint32_t
static struct page_pool pool;
static struct page pages[64];
static struct sk_buff skbs[64];
static unsigned allocs,builds,returned_pages,syncs,unmaps,fail_alloc,fail_build,fail_create,maps;
static bool expand_fail;
static unsigned expand_count;
static struct page_pool *page_pool_create(const struct page_pool_params *p) {
    if(fail_create)return (void*)(intptr_t)-ENOMEM;
    assert(p->order==0&&p->flags==3&&p->dma_dir==DMA_FROM_DEVICE&&p->max_len==2048&&p->offset==128&&p->pool_size==64&&p->dev&&p->nid==-1);
    pool.p=*p;return &pool;
}
static struct page *page_pool_dev_alloc_pages(struct page_pool *p){
    assert(p==&pool);if(++allocs==fail_alloc)return NULL;
    for(unsigned i=0;i<64;i++)if(!pages[i].allocated){
        if(!pages[i].pool) {pages[i].pool=p;maps++;}
        assert(pages[i].pool==p);
        pages[i].allocated=true;pages[i].cpu=false;pages[i].id=i;
        return &pages[i];
    }
    assert(0);return NULL;
}
static void page_pool_put_full_page(struct page_pool *p,struct page *page,bool direct){
    assert(p==page->pool&&page->allocated&&!direct);page->allocated=false;returned_pages++;
}
static void *page_address(struct page *p){return p->buf;}
static struct page *virt_to_head_page(void *data){return container_of(data,struct page,buf);}
static uintptr_t page_pool_get_dma_addr(struct page *p){return (uintptr_t)p->id*PAGE_SIZE;}
static struct sk_buff *build_skb(void *addr,unsigned size){
    if(++builds==fail_build)return NULL;
    struct page *p=virt_to_head_page(addr);assert(p->allocated&&size==SKB_HEAD_ALIGN(2176));
    struct sk_buff *s=&skbs[p->id];*s=(struct sk_buff){.page=p,.head=addr,.data=addr,.tailroom=SKB_WITH_OVERHEAD(size)};
    return s;
}
static void skb_reserve(struct sk_buff *s,unsigned n){assert(s->tailroom>=n);s->data+=n;s->tailroom-=n;}
static void skb_mark_for_recycle(struct sk_buff *s){s->pp_recycle=true;}
static void dev_kfree_skb_any(struct sk_buff *s){assert(s->pp_recycle);page_pool_put_full_page(s->page->pool,s->page,false);}
static void page_pool_dma_sync_for_cpu(struct page_pool *p,struct page *page,unsigned off,unsigned size){
    assert(p==page->pool&&page->allocated&&!page->cpu&&!off&&size==p->p.max_len);page->cpu=true;syncs++;
}
static void dma_unmap_single(void *dev,uintptr_t addr,unsigned len,enum dma_data_direction dir){
    assert(dev&&addr==0x1234&&len==2345&&dir==DMA_BIDIRECTIONAL);unmaps++;
}
static void spin_lock_bh(int *lock){assert(!*lock);*lock=1;}
static void spin_unlock_bh(int *lock){assert(*lock);*lock=0;}
static void ath12k_hal_srng_access_begin(struct ath12k_base *ab,struct hal_srng *s){assert(ab&&s->lock);}
static void ath12k_hal_srng_access_end(struct ath12k_base *ab,struct hal_srng *s){assert(ab&&s->lock);}
static int ath12k_hal_srng_src_num_free(struct ath12k_base *ab,struct hal_srng *s,bool sync){assert(ab&&s->lock&&sync);return s->free;}
static void *ath12k_hal_srng_src_get_next_entry(struct ath12k_base *ab,struct hal_srng *s){
    assert(ab&&s->lock);
    if(++s->attempts==s->fail_at||!s->free)return NULL;
    s->free--;return &s->entries[s->published++];
}
static void ath12k_hal_rx_buf_addr_info_set(struct hal *h,struct ath12k_buffer_addr *d,uintptr_t addr,unsigned cookie,unsigned mgr){assert(h&&mgr==RBM);*d=(struct ath12k_buffer_addr){addr,cookie,mgr};}
static unsigned ath12k_hal_srng_get_entrysize(struct ath12k_base *ab,int type){assert(ab&&type==HAL_RXDMA_BUF);return 16;}
static struct ath12k_dp *ath12k_ab_to_dp(struct ath12k_base *ab){return ab->dp;}
static int pskb_expand_head(struct sk_buff *s,int head,int tail,int flags){
    assert(!head&&tail>=0&&flags==GFP_ATOMIC);expand_count++;
    if(expand_fail)return -ENOMEM;
    s->tailroom+=tail;return 0;
}
''' + cut + '\n' + enqueue + '\n' + build + '\n' + refill + '\n' + setup + '\n' + unmap + r'''
static int expand_frag(struct sk_buff *first_frag,int msdu_len){
    int extra_space;
''' + expand + r'''
    return 0;
}
int main(void){
    struct {enum hal_rx_buf_return_buf_manager rx_buf_rbm;} params={RBM};
    struct hal hal={.hal_params=(void*)&params};
    struct ath12k_dp dp={.hal=&hal,.dev=&dp};
    struct ath12k_base ab={.dev=&dp,.dp=&dp};dp.ab=&ab;
    struct dp_rxdma_ring *ring=&dp.rx_refill_buf_ring;
    ring->refill_buf_ring.size=64*16;
    INIT_LIST_HEAD(&dp.rx_desc_free_list);
    fail_create=1;
    assert(ath12k_dp_rxdma_ring_buf_setup(&ab,ring)==-ENOMEM&&!ring->page_pool);
    fail_create=0;
    assert(!ath12k_dp_rxdma_ring_buf_setup(&ab,ring)&&ring->page_pool==&pool);
    unsigned cases=0;
    /* Exercise every requested/free/descriptor combination with independent
     * allocation, build and ring failures at beginning, middle and end. */
    for(unsigned requested=0;requested<=20;requested++)
    for(unsigned available=0;available<=64;available+=4)
    for(unsigned descriptors=0;descriptors<=24;descriptors+=4)
    for(unsigned preowned=0;preowned<2;preowned++)
    for(unsigned fail_kind=0;fail_kind<4;fail_kind++)
    for(unsigned fail=1;fail<=17;fail+=4){
        struct ath12k_rx_desc_info descs[64]={0};
        struct hal_srng *srng=&hal.srng_list[0];
        *srng=(struct hal_srng){.free=available,.fail_at=fail_kind==3?fail:0};
        LIST_HEAD(used);
        INIT_LIST_HEAD(&dp.rx_desc_free_list);
        for(unsigned i=0;i<descriptors;i++){
            descs[i].cookie=i+100;descs[i].in_use=preowned;
            list_add_tail(&descs[i].list,preowned?&used:&dp.rx_desc_free_list);
        }
        allocs=builds=returned_pages=syncs=maps=0;
        memset(pages,0,sizeof(pages));
        fail_alloc=fail_kind==1?fail:0;fail_build=fail_kind==2?fail:0;
        unsigned limit=requested?requested:(available>48?available:0);
        unsigned expected=min(min(limit,available),descriptors);
        if(fail_kind)expected=min(expected,fail-1);
        assert(ath12k_dp_rx_bufs_replenish(&dp,ring,&used,requested)==(int)expected);
        assert(srng->published==expected&&!srng->lock&&!dp.rx_desc_lock&&list_empty(&used));
        for(unsigned i=0;i<descriptors;i++){
            struct ath12k_rx_desc_info *d=&descs[i];
            assert(d->in_use==(i<expected));
            if(i<expected){
                struct sk_buff *s=d->skb;
                assert(s&&s->pp_recycle&&s->cb.pool_mapped&&s->data-s->head==128&&s->tailroom==2048&&s->truesize==4352);
                assert(srng->entries[i].addr==s->cb.paddr&&srng->entries[i].cookie==d->cookie&&!(s->cb.paddr&127));
                ath12k_dp_unmap_rx_buf(&dp,s);
                assert(!s->cb.pool_mapped&&s->page->cpu);
                dev_kfree_skb_any(s);
            }else assert(!d->skb);
        }
        for(unsigned i=0;i<64;i++)assert(!pages[i].allocated);
        assert(syncs==expected);
        /* Recycle a returned page without allocating a new DMA mapping. */
        if(expected){
            unsigned old_maps=maps;
            fail_alloc=fail_build=0;
            struct sk_buff *s=ath12k_dp_rx_build_skb(&pool);
            assert(s&&maps==old_maps);
            ath12k_dp_unmap_rx_buf(&dp,s);dev_kfree_skb_any(s);
        }
        cases++;
    }
    for(unsigned len=1;len<=2048;len+=31)
    for(unsigned tail=0;tail<=2048-len;tail+=47)
    for(unsigned total=len;total<=4096;total+=127)
    for(unsigned recycle=0;recycle<2;recycle++)
    for(unsigned fail=0;fail<2;fail++){
        struct sk_buff s={.len=len,.tailroom=tail,.pp_recycle=recycle};
        bool needs=total>len+tail||recycle;expand_count=0;expand_fail=fail;
        int ret=expand_frag(&s,total);
        assert(expand_count==needs);
        assert((ret!=0)==(needs&&fail));
        if(!ret)assert(!s.pp_recycle&&s.len+s.tailroom>=total);
        cases++;
    }
    struct sk_buff reinjected={.len=1234,.tailroom=1111,.cb={.paddr=0x1234,.is_frag=true}};
    ath12k_dp_unmap_rx_buf(&dp,&reinjected);assert(unmaps==1);
    printf("RX_PAGE_POOL_PASS cases=%u\n",cases);
}
'''
    c = args.output / 'rx-page-pool.c'
    obj = args.output / 'rx-page-pool.o'
    exe = args.output / 'rx-page-pool'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
