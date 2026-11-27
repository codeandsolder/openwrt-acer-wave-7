#!/usr/bin/env python3
"""Compile the actual management admission function with an eager consumer."""
import argparse
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    text = a.source.read_text()
    start = text.index('int ath12k_mac_mgmt_tx(struct ath12k *ar, struct sk_buff *skb,')
    end = text.index('EXPORT_SYMBOL(ath12k_mac_mgmt_tx);', start)
    actual = text[start:end]
    shim = r'''#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#define ATH12K_FLAG_CRASH_FLUSH 0
#define ATH12K_PRB_RSP_DROP_THRESHOLD 32
#define ATH12K_TX_MGMT_NUM_PENDING_MAX 512
struct base { unsigned long dev_flags; };
struct sk_buff { int unused; };
struct sk_buff_head { unsigned qlen; int lock; };
struct hw { void *wiphy; };
struct ath12k { struct base *ab; struct sk_buff_head wmi_mgmt_tx_queue; int num_pending_mgmt_tx; int wmi_mgmt_tx_work; struct hw hw; };
static struct ath12k *active;
static bool eager, published;
static int underflow;
#define test_bit(bit, flags) (!!(*(flags) & (1UL << (bit))))
#define atomic_read(x) (*(x))
#define atomic_inc(x) (++*(x))
#define ath12k_warn(...) ((void)0)
#define ath12k_ar_to_hw(ar) (&(ar)->hw)
#define wiphy_work_queue(wiphy, work) ((void)(wiphy), (void)(work))
#define skb_queue_len(q) ((q)->qlen)
#define skb_queue_len_lockless(q) ((q)->qlen)
static void consume(void) {
    if (!eager || !published || active->wmi_mgmt_tx_queue.lock) return;
    published = false;
    assert(active->wmi_mgmt_tx_queue.qlen > 0);
    active->wmi_mgmt_tx_queue.qlen--;
    if (active->num_pending_mgmt_tx > 0) active->num_pending_mgmt_tx--;
    else underflow++;
}
#define spin_lock_irqsave(lock, flags) do { (flags)=0; assert(!*(lock)); *(lock)=1; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); assert(*(lock)); *(lock)=0; consume(); } while (0)
static __attribute__((unused)) void __skb_queue_tail(struct sk_buff_head *q, struct sk_buff *skb) {
    (void)skb; assert(q->lock); q->qlen++; published=true; consume();
}
/* Keep the original API too, so the negative control compiles and fails
 * under exactly the eager-consumer interleaving it permits. */
static __attribute__((unused)) void skb_queue_tail(struct sk_buff_head *q, struct sk_buff *skb) {
    (void)skb; assert(!q->lock); q->qlen++; published=true; consume();
}
/* ACTUAL */
int main(void) {
    unsigned cases=0;
    for (unsigned q=0;q<=512;q++)
        for (unsigned extra=0;extra<=2;extra++)
            for (unsigned probe=0;probe<2;probe++)
                for (unsigned crash=0;crash<2;crash++)
                    for (unsigned fast=0;fast<2;fast++) {
                        struct base b={crash}; struct ath12k ar={.ab=&b,.wmi_mgmt_tx_queue={q,0},.num_pending_mgmt_tx=(int)(q+extra)};
                        struct sk_buff skb={0}; active=&ar; eager=fast; published=false; underflow=0;
                        int old=ar.num_pending_mgmt_tx;
                        int expected=crash?-ESHUTDOWN:((probe && old>32)||q>=512)?-ENOSPC:0;
                        int result=ath12k_mac_mgmt_tx(&ar,&skb,probe);
                        assert(result==expected && !ar.wmi_mgmt_tx_queue.lock && !underflow);
                        assert(ar.num_pending_mgmt_tx==old+(expected==0 && !fast));
                        assert(ar.wmi_mgmt_tx_queue.qlen==q+(expected==0 && !fast));
                        cases++;
                    }
    printf("MGMT_PUBLICATION_PASS cases=%u\n", cases);
}
'''
    a.output.mkdir(parents=True, exist_ok=True)
    c, obj, exe = (a.output / f'mgmt-publication{suffix}' for suffix in ('.c','.o',''))
    c.write_text(shim.replace('/* ACTUAL */', actual))
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
