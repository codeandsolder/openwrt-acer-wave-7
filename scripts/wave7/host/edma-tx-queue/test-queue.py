#!/usr/bin/env python3
"""Execute actual queue-index and stop/recheck functions from the driver."""
import re
from pathlib import Path
import subprocess
import sys
import tempfile

kernel = Path(sys.argv[1])
ppe = kernel/"drivers/net/ethernet/qualcomm/ppe"
tx=(ppe/"edma_tx.c").read_text()
header=(ppe/"edma_tx.h").read_text()
port=(ppe/"edma_port.c").read_text()
def function(text, name):
    return re.search(r"^(?:static(?: inline)? )?[^\n]*\b"+name+r"\([^;]*?\)\n\{.*?^\}", text, re.M|re.S)[0]
queue=function(header,"edma_tx_queue_index")
stop=function(tx,"edma_tx_stop_if_full")
complete=function(tx,"edma_tx_complete")
xmit=function(port,"edma_port_xmit")
assert "edma_tx_queue_index(txcmpl_ring->id" in complete
assert "netdev_get_tx_queue(ndev, queue_id)" in complete
assert "__netif_tx_lock(nq, smp_processor_id())" in complete
assert "netif_tx_queue_stopped(nq) && netif_running(ndev)" in complete
assert complete.index("smp_mb();") < complete.index("netif_tx_queue_stopped(nq)")
assert "netif_tx_start_all_queues(netdev);" in function(port,"edma_port_open")
assert "netif_tx_stop_all_queues(netdev);" in function(port,"edma_port_close")
assert "if (edma_tx_stop_if_full(nq, txdesc_ring, skb))" in xmit
assert xmit.count("ret = edma_tx_ring_xmit(dev, skb, txdesc_ring, stats);")==3
assert function(tx,"edma_tx_ring_xmit").count("return EDMA_TX_FAIL_NO_DESC;")==2
fixture=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32;
struct netdev_queue { bool stopped; unsigned step; };
struct edma_txdesc_ring { u32 avail_desc, prod_idx, actual; };
struct sk_buff { u32 descriptors; };
static struct netdev_queue *observed;
static void netif_tx_stop_queue(struct netdev_queue *q) {
    assert(!q->stopped && q->step==0); q->stopped=true; q->step=1; observed=q;
}
static void smp_mb__after_atomic(void) {
    assert(observed->stopped && observed->step==1); observed->step=2;
}
static void netif_tx_start_queue(struct netdev_queue *q) {
    assert(q->stopped && q->step==3); q->stopped=false; q->step=4;
}
static bool skb_is_nonlinear(struct sk_buff *s) { return s->descriptors>1; }
static u32 edma_tx_num_descs_for_sg(struct sk_buff *s) { return s->descriptors; }
static u32 edma_tx_avail_desc(struct edma_txdesc_ring *r,u32 prod) {
    assert(observed->stopped && observed->step==2);
    assert(prod==r->prod_idx); observed->step=3; return r->actual;
}
''' + "\n"+queue+"\n"+stop+r'''
int main(void) {
    unsigned count=0;
    for (u32 queues=1;queues<=8;queues*=2)
        for (u32 start=0;start<32;start++)
            for (u32 port=0;port<6;port++)
                for (u32 q=0;q<queues;q++) {
                    assert(edma_tx_queue_index(start+port*queues+q,start,queues)==q);
                    count++;
                }
    for (u32 needed=1;needed<=32;needed++)
        for (u32 actual=0;actual<2048;actual++)
            for (u32 prod=0;prod<2048;prod+=511) {
                struct netdev_queue q={0};
                struct edma_txdesc_ring ring={.avail_desc=0,.prod_idx=prod,.actual=actual};
                struct sk_buff skb={.descriptors=needed};
                bool stopped=edma_tx_stop_if_full(&q,&ring,&skb);
                assert(stopped==(actual<needed));
                assert(q.stopped==stopped && ring.avail_desc==actual);
                assert(q.step==(stopped?3u:4u));
                count++;
            }
    printf("EDMA_TX_QUEUE_FIXTURE_PASS cases=%u\n",count);
}
'''
with tempfile.TemporaryDirectory(prefix=".queue-fixture-",dir=kernel.parent) as work:
    p=Path(work)
    (p/"fixture.c").write_text(fixture)
    subprocess.run(["sccache","gcc","-std=gnu11","-Wall","-Wextra","-Werror",
                    "-O2","-c",str(p/"fixture.c"),"-o",str(p/"fixture.o")],check=True)
    subprocess.run(["gcc",str(p/"fixture.o"),"-o",str(p/"fixture")],check=True)
    subprocess.run([str(p/"fixture")],check=True)
