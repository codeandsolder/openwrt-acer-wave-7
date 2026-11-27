#!/usr/bin/env python3
"""Exercise the actual REO queue retirement state machine with fake DMA and workqueue."""
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
    common = (a.source / 'dp_rx.c').read_text()
    header = (a.source / 'dp_rx.h').read_text()
    states = header[header.index('enum ath12k_reo_queue_state {'):header.index('#define ATH12K_DP_RX_FRAGMENT_TIMEOUT_MS')]
    constants = '\n'.join(re.search(r'^#define\s+' + n + r'\s+[^\n]+', header, re.M).group() for n in ('ATH12K_DP_RX_REO_RETRY_MS', 'ATH12K_DP_RX_REO_DESC_FREE_TIMEOUT_MS'))
    for f, names in (('hal.h', ('HAL_LINK_DESC_ALIGN', 'HAL_DESC_REO_NON_QOS_TID')),
                     ('wifi7/hal.h', ('HAL_REO_CMD_FLG_NEED_STATUS', 'HAL_REO_CMD_FLG_FLUSH_FWD_ALL_MPDUS', 'HAL_REO_CMD_FLG_FLUSH_QUEUE_1K_DESC'))):
        h = (a.source / f).read_text()
        constants += '\n' + '\n'.join(re.search(r'^#define\s+' + n + r'\s+[^\n]+', h, re.M).group() for n in names)
    actual = '\n'.join(extract(common,s) for s in (
        'static void ath12k_dp_rx_tid_cleanup(',
        'static void ath12k_dp_reo_retire_work(',
        'void ath12k_dp_rx_reo_init(',
        'void ath12k_dp_rx_reo_stop(',
        'void ath12k_dp_rx_reo_cmd_cleanup(',
        'void ath12k_dp_reo_delete_done(',
        'void ath12k_dp_reo_flush_done(',
        'bool ath12k_dp_mark_tid_as_inactive(',
        'static void ath12k_dp_register_reo_queue('))
    actual += '\n' + extract((a.source / 'wifi7/dp_rx.c').read_text(), 'int ath12k_wifi7_dp_reo_cache_flush(')
    shim = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stddef.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t dma_addr_t;
#define BIT(n) (1U<<(n))
#define round_down(x,y) ((x)&~((y)-1))
#define lower_32_bits(x) ((u32)(x))
#define upper_32_bits(x) ((u32)((x)>>32))
#define IEEE80211_NUM_TIDS 16
#define DMA_BIDIRECTIONAL 0
#define WARN_ON_ONCE(x) (!!(x))
#define lockdep_assert_held(x) assert(*(x))
#define dev_warn_ratelimited(...) ((void)0)
#define msecs_to_jiffies(x) ((unsigned long)(x))
#define time_before(a,b) ((long)((a)-(b))<0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
/* CONSTANTS */
struct list_head {struct list_head *next,*prev;};
static void INIT_LIST_HEAD(struct list_head *h) {h->next=h->prev=h;}
static void list_del(struct list_head *e) {e->prev->next=e->next;e->next->prev=e->prev;e->next=e->prev=NULL;}
static void list_add_tail(struct list_head *e,struct list_head *h) {e->prev=h->prev;e->next=h;h->prev->next=e;h->prev=e;}
static void list_move_tail(struct list_head *e,struct list_head *h) {list_del(e);list_add_tail(e,h);}
#define list_for_each_entry(e,h,m) for(struct list_head *n_=(h)->next;n_!=(h)&&((e)=container_of(n_,__typeof__(*(e)),m),true);n_=n_->next)
#define list_for_each_entry_safe(e,tmp,h,m) for(struct list_head *n_=(h)->next;n_!=(h)&&((e)=container_of(n_,__typeof__(*(e)),m),(tmp)=n_->next==(h)?NULL:container_of(n_->next,__typeof__(*(tmp)),m),true);n_=(tmp)?&(tmp)->m:(h))
static unsigned count(struct list_head *h) {unsigned n=0;for(struct list_head *e=h->next;e!=h;e=e->next)n++;return n;}
struct work_struct {void (*fn)(struct work_struct *);};
struct delayed_work {struct work_struct work;bool pending;unsigned long due;};
static unsigned long jiffies;
#define to_delayed_work(p) container_of(p,struct delayed_work,work)
#define INIT_DELAYED_WORK(d,cb) do {(d)->work.fn=cb;(d)->pending=false;(d)->due=0;} while(0)
static bool schedule_delayed_work(struct delayed_work *w,unsigned long delay) {if(w->pending)return false;w->pending=true;w->due=jiffies+delay;return true;}
#define system_wq NULL
static bool mod_delayed_work(void *wq,struct delayed_work *w,unsigned long delay) {(void)wq;bool old=w->pending;w->pending=true;w->due=jiffies+delay;return old;}
static void cancel_delayed_work_sync(struct delayed_work *w) {w->pending=false;}
static void spin_lock_init(int *p) {*p=0;}
static void spin_lock_bh(int *p) {assert(!*p);*p=1;}
static void spin_unlock_bh(int *p) {assert(*p);*p=0;}
struct ath12k_reoq_buf {void *vaddr;dma_addr_t paddr_aligned;u32 size;};
/* STATES */
enum hal_reo_cmd_status {HAL_REO_CMD_SUCCESS,HAL_REO_CMD_BLOCKED,HAL_REO_CMD_FAILED,HAL_REO_CMD_RESOURCE_BLOCKED,HAL_REO_CMD_DRAIN=255};
struct ath12k_dp_rx_tid {u8 tid;struct ath12k_reoq_buf qbuf;};
struct ath12k_dp_peer {struct ath12k_dp_rx_tid rx_tid[17];};
struct ath12k_dp_link_peer {struct ath12k_dp_peer *dp_peer;bool primary_link;int peer_id;bool mlo;u16 ml_id;u32 rx_tid_active_bitmask;};
struct ath12k_base;
struct ath12k_dp {struct ath12k_base *ab;int dp_lock,reo_queue_lock,reo_cmd_lock;
    struct list_head reo_live_queues,reo_retired_queues;struct delayed_work reo_retire_work;
    bool reo_retire_stopped,reo_retire_initialized;unsigned reo_cmd_pending[256];};
struct ath12k_base {struct ath12k_dp dp;void *dev;};
#define ath12k_ab_to_dp(ab) (&(ab)->dp)
static unsigned allocations,frees,unmaps,delete_submits,flush_submits,resets;
static int submit_error;
static dma_addr_t refs[2][17];
static void *alloc(size_t n) {allocations++;return calloc(1,n);}
static void kfree(void *p) {assert(p);frees++;free(p);}
static void dma_unmap_single(void *d,dma_addr_t p,u32 size,int dir) {(void)d;(void)dir;assert(p&&size);unmaps++;}
static int ath12k_dp_arch_rx_tid_delete_handler(struct ath12k_dp *dp,struct ath12k_reo_queue *q) {assert(dp->reo_queue_lock&&q->state==ATH12K_REO_QUEUE_DELETE_PENDING);delete_submits++;return submit_error;}
struct ath12k_hal_reo_cmd {u32 addr_lo,addr_hi,flag;};
enum hal_reo_cmd_type {HAL_REO_CMD_FLUSH_CACHE};
void ath12k_dp_reo_flush_done(struct ath12k_dp *,void *,enum hal_reo_cmd_status);
int ath12k_wifi7_dp_reo_cache_flush(struct ath12k_base *,struct ath12k_reo_queue *);
static unsigned last_offset;static dma_addr_t last_address;static u32 last_flags;
static int ath12k_wifi7_dp_reo_cmd_send(struct ath12k_base *ab,enum hal_reo_cmd_type t,struct ath12k_hal_reo_cmd *cmd,void (*cb)(struct ath12k_dp *,void *,enum hal_reo_cmd_status),void *ctx) {
    struct ath12k_reo_queue *q=ctx;assert(ab->dp.reo_queue_lock&&q->state==ATH12K_REO_QUEUE_FLUSH_PENDING&&t==HAL_REO_CMD_FLUSH_CACHE&&cb==ath12k_dp_reo_flush_done);
    last_offset=q->flush_offset;last_address=((dma_addr_t)cmd->addr_hi<<32)|cmd->addr_lo;last_flags=cmd->flag;
    assert(last_address==q->qbuf.paddr_aligned+q->flush_offset);
    u32 want=HAL_REO_CMD_FLG_NEED_STATUS;if(!q->flush_offset){want|=HAL_REO_CMD_FLG_FLUSH_FWD_ALL_MPDUS;if(q->tid!=HAL_DESC_REO_NON_QOS_TID)want|=HAL_REO_CMD_FLG_FLUSH_QUEUE_1K_DESC;}
    assert(last_flags==want);flush_submits++;return submit_error;
}
static int ath12k_dp_arch_reo_cache_flush(struct ath12k_dp *dp,struct ath12k_reo_queue *q) {assert(dp->reo_queue_lock&&q->state==ATH12K_REO_QUEUE_FLUSH_PENDING);return ath12k_wifi7_dp_reo_cache_flush(dp->ab,q);}
static void ath12k_dp_arch_peer_rx_tid_qref_reset(struct ath12k_dp *dp,u16 peer,u16 tid,dma_addr_t expected) {assert(dp->dp_lock&&dp->reo_queue_lock);unsigned i=peer==0x8042?1:0;assert(peer==0x42||peer==0x8042);if(refs[i][tid]==expected){refs[i][tid]=0;resets++;}}
#define EXPORT_SYMBOL(x)
/* ACTUAL */
static void tick(struct ath12k_dp *dp,unsigned long time) {jiffies=time;struct delayed_work *w=&dp->reo_retire_work;if(w->pending&&!time_before(jiffies,w->due)){w->pending=false;w->work.fn(&w->work);}}
static struct ath12k_reo_queue *setup_size(struct ath12k_dp *dp,struct ath12k_dp_link_peer *peer,u8 tid,dma_addr_t addr,u32 size) {
    struct ath12k_dp_rx_tid *rx=&peer->dp_peer->rx_tid[tid];rx->tid=tid;rx->qbuf=(struct ath12k_reoq_buf){alloc(size),addr,size};
    struct ath12k_reo_queue *q=alloc(sizeof(*q));ath12k_dp_register_reo_queue(dp,peer,rx,q);peer->rx_tid_active_bitmask|=BIT(tid);refs[peer->mlo][tid]=addr;return q;
}
static struct ath12k_reo_queue *setup(struct ath12k_dp *dp,struct ath12k_dp_link_peer *peer,u8 tid,dma_addr_t addr) {return setup_size(dp,peer,tid,addr,HAL_LINK_DESC_ALIGN);}
int main(void) {
    struct ath12k_base ab={0};struct ath12k_dp *dp=&ab.dp;dp->ab=&ab;dp->dp_lock=1;
    ath12k_dp_rx_reo_stop(dp);ath12k_dp_rx_reo_cmd_cleanup(&ab); /* not initialized */
    ath12k_dp_rx_reo_init(dp);struct ath12k_dp_peer p={0};struct ath12k_dp_link_peer peer={.dp_peer=&p,.primary_link=true,.peer_id=0x42,.mlo=true,.ml_id=0x8042};
    unsigned cases=0;
    for (unsigned del=0;del<5;del++) for(unsigned flush=0;flush<5;flush++) for(unsigned submit=0;submit<2;submit++) {
        enum hal_reo_cmd_status errors[]={HAL_REO_CMD_SUCCESS,HAL_REO_CMD_BLOCKED,HAL_REO_CMD_FAILED,HAL_REO_CMD_RESOURCE_BLOCKED,HAL_REO_CMD_DRAIN};
        struct ath12k_reo_queue *old=setup(dp,&peer,3,1000+cases*10);unsigned prior_unmaps=unmaps;
        peer.primary_link=false;assert(!ath12k_dp_mark_tid_as_inactive(dp,&peer,3));peer.primary_link=true;
        assert(ath12k_dp_mark_tid_as_inactive(dp,&peer,3));assert(!ath12k_dp_mark_tid_as_inactive(dp,&peer,3));
        assert(!refs[1][3]&&!p.rx_tid[3].qbuf.vaddr&&count(&dp->reo_live_queues)==0&&count(&dp->reo_retired_queues)==1);
        struct ath12k_reo_queue *new=setup(dp,&peer,3,1001+cases*10);assert(new->qbuf.vaddr!=old->qbuf.vaddr);
        submit_error=submit?-ENOBUFS:0;tick(dp,jiffies);assert(old->state==(submit?ATH12K_REO_QUEUE_DELETE_PENDING:ATH12K_REO_QUEUE_DELETE_INFLIGHT)&&unmaps==prior_unmaps);
        submit_error=0;if(submit){tick(dp,jiffies+ATH12K_DP_RX_REO_RETRY_MS-1);assert(old->state==ATH12K_REO_QUEUE_DELETE_PENDING);tick(dp,jiffies+1);}
        assert(old->state==ATH12K_REO_QUEUE_DELETE_INFLIGHT);
        ath12k_dp_reo_delete_done(dp,old,errors[del]);assert(unmaps==prior_unmaps);
        if(del){assert(old->state==ATH12K_REO_QUEUE_DELETE_PENDING);tick(dp,jiffies+ATH12K_DP_RX_REO_RETRY_MS);assert(old->state==ATH12K_REO_QUEUE_DELETE_INFLIGHT);ath12k_dp_reo_delete_done(dp,old,HAL_REO_CMD_SUCCESS);}
        assert(old->state==ATH12K_REO_QUEUE_FLUSH_PENDING);unsigned long ready=jiffies+ATH12K_DP_RX_REO_DESC_FREE_TIMEOUT_MS;
        tick(dp,ready-1);assert(old->state==ATH12K_REO_QUEUE_FLUSH_PENDING&&unmaps==prior_unmaps);
        submit_error=submit?-EIO:0;tick(dp,ready+ATH12K_DP_RX_REO_RETRY_MS);submit_error=0;
        if(submit){assert(old->state==ATH12K_REO_QUEUE_FLUSH_PENDING);tick(dp,jiffies+ATH12K_DP_RX_REO_RETRY_MS);}
        assert(old->state==ATH12K_REO_QUEUE_FLUSH_INFLIGHT);
        ath12k_dp_reo_flush_done(dp,old,errors[flush]);
        if(flush){assert(unmaps==prior_unmaps&&old->state==ATH12K_REO_QUEUE_FLUSH_PENDING);tick(dp,jiffies+ATH12K_DP_RX_REO_RETRY_MS);assert(old->state==ATH12K_REO_QUEUE_FLUSH_INFLIGHT);ath12k_dp_reo_flush_done(dp,old,HAL_REO_CMD_SUCCESS);}
        assert(unmaps==prior_unmaps+1&&count(&dp->reo_retired_queues)==0&&count(&dp->reo_live_queues)==1&&refs[1][3]==new->qbuf.paddr_aligned);
        assert(ath12k_dp_mark_tid_as_inactive(dp,&peer,3));tick(dp,jiffies);ath12k_dp_reo_delete_done(dp,new,HAL_REO_CMD_SUCCESS);tick(dp,jiffies+ATH12K_DP_RX_REO_DESC_FREE_TIMEOUT_MS+ATH12K_DP_RX_REO_RETRY_MS);ath12k_dp_reo_flush_done(dp,new,HAL_REO_CMD_SUCCESS);
        assert(count(&dp->reo_retired_queues)==0&&count(&dp->reo_live_queues)==0&&unmaps==prior_unmaps+2&&allocations==frees);cases++;
    }
    unsigned line_cases=0;
    /* Real geometries and one partial terminal line, with high DMA address
     * crossing the 32-bit boundary. Fail each command independently. */
    const u32 sizes[]={128,256,384,512,1536,385};
    for(unsigned size_i=0;size_i<sizeof(sizes)/sizeof(sizes[0]);size_i++) for(unsigned tid_i=0;tid_i<2;tid_i++) {
        u32 size=sizes[size_i],tid=tid_i?HAL_DESC_REO_NON_QOS_TID:3;
        struct ath12k_reo_queue *q=setup_size(dp,&peer,tid,UINT64_C(0xffffff80),size);
        assert(ath12k_dp_mark_tid_as_inactive(dp,&peer,tid));tick(dp,jiffies);ath12k_dp_reo_delete_done(dp,q,HAL_REO_CMD_SUCCESS);
        unsigned offset=round_down(size-1,HAL_LINK_DESC_ALIGN),before=unmaps;
        assert(q->flush_offset==offset);tick(dp,jiffies+ATH12K_DP_RX_REO_DESC_FREE_TIMEOUT_MS-1);assert(q->state==ATH12K_REO_QUEUE_FLUSH_PENDING);
        jiffies+=ATH12K_DP_RX_REO_RETRY_MS;
        while(true) {
            submit_error=-ENOBUFS;tick(dp,jiffies);assert(last_offset==offset&&q->state==ATH12K_REO_QUEUE_FLUSH_PENDING&&q->flush_offset==offset&&unmaps==before);
            submit_error=0;tick(dp,jiffies+ATH12K_DP_RX_REO_RETRY_MS);assert(q->state==ATH12K_REO_QUEUE_FLUSH_INFLIGHT&&last_offset==offset);
            for(unsigned fail=1;fail<=3;fail++) {
                ath12k_dp_reo_flush_done(dp,q,(enum hal_reo_cmd_status)fail);
                assert(q->flush_offset==offset&&unmaps==before&&q->state==ATH12K_REO_QUEUE_FLUSH_PENDING);
                tick(dp,jiffies+ATH12K_DP_RX_REO_RETRY_MS);assert(q->state==ATH12K_REO_QUEUE_FLUSH_INFLIGHT&&last_offset==offset);
            }
            ath12k_dp_reo_flush_done(dp,q,HAL_REO_CMD_SUCCESS);line_cases++;
            if(!offset){assert(unmaps==before+1);break;}
            offset-=HAL_LINK_DESC_ALIGN;assert(q->flush_offset==offset&&q->state==ATH12K_REO_QUEUE_FLUSH_PENDING&&unmaps==before);
        }
        assert(allocations==frees&&count(&dp->reo_retired_queues)==0);
    }
    /* Invalid offsets must not publish. */
    struct ath12k_reo_queue invalid={.qbuf={0,0x1000,128},.flush_offset=128};unsigned submits=flush_submits;
    assert(ath12k_wifi7_dp_reo_cache_flush(&ab,&invalid)==-EINVAL);invalid.flush_offset=1;assert(ath12k_wifi7_dp_reo_cache_flush(&ab,&invalid)==-EINVAL&&flush_submits==submits);
    /* Stop with live, delete-in-flight and aged/flush-in-flight owners. */
    struct ath12k_reo_queue *a=setup(dp,&peer,2,9001),*b=setup(dp,&peer,3,9002);setup(dp,&peer,4,9003);
    assert(ath12k_dp_mark_tid_as_inactive(dp,&peer,2));tick(dp,jiffies);ath12k_dp_reo_delete_done(dp,a,HAL_REO_CMD_SUCCESS);tick(dp,jiffies+ATH12K_DP_RX_REO_DESC_FREE_TIMEOUT_MS+ATH12K_DP_RX_REO_RETRY_MS);
    assert(ath12k_dp_mark_tid_as_inactive(dp,&peer,3));tick(dp,jiffies);assert(a->state==ATH12K_REO_QUEUE_FLUSH_INFLIGHT&&b->state==ATH12K_REO_QUEUE_DELETE_INFLIGHT);
    unsigned before=unmaps;ath12k_dp_rx_reo_stop(dp);ath12k_dp_reo_flush_done(dp,a,HAL_REO_CMD_SUCCESS);ath12k_dp_reo_delete_done(dp,b,HAL_REO_CMD_SUCCESS);
    assert(unmaps==before&&!dp->reo_retire_work.pending);dp->reo_cmd_pending[0]=1;ath12k_dp_rx_reo_cmd_cleanup(&ab);
    assert(unmaps==before+3&&allocations==frees&&!dp->reo_cmd_pending[0]&&!dp->reo_retire_initialized);
    ath12k_dp_rx_reo_init(dp);assert(!dp->reo_retire_stopped);ath12k_dp_rx_reo_stop(dp);ath12k_dp_rx_reo_cmd_cleanup(&ab);
    printf("REO_RETIREMENT_PASS %u failure combinations, %u individually retried lines, ID reuse, stop/restart; %u allocations, %u DMA unmaps\n",cases,line_cases,allocations,unmaps);
}
'''
    a.output.mkdir(parents=True, exist_ok=True)
    c,obj,exe=(a.output/f'reo-retirement{s}' for s in ('.c','.o',''))
    c.write_text(shim.replace('/* CONSTANTS */',constants).replace('/* STATES */',states).replace('/* ACTUAL */',actual))
    subprocess.run(['/usr/local/bin/sccache','/usr/bin/cc','-std=gnu11','-O2','-Wall','-Wextra','-Werror','-c',str(c),'-o',str(obj)],check=True)
    subprocess.run(['/usr/bin/cc',str(obj),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    main()
