#!/usr/bin/env python3
"""Exercise the compiled driver worker, lifecycle and real FIFO helper."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root=Path(sys.argv[1])
src=(root/"drivers/net/phy/qcom/qca808x.c").read_text()
def func(name):
    return re.search(r"^static (?:int|bool|void) "+name+r"\([^;]*?\)\n\{.*?^\}",src,re.M|re.S)[0]
names=("qca8081_has_independent_fifo","qca8081_stock_fifo_level",
       "qca8081_fifo_poll_work","qca8081_fifo_poll_start","qca8081_suspend",
       "qca8081_resume","qca808x_remove")
# Exclude forward declaration from the worker extraction.
read=func("qca808x_read_status")
assert read.count("qca8081_fifo_poll_start(phydev);")==1
assert read.index("qca8081_stock_fifo_level(phydev, copper_link)") < read.index("qca8081_fifo_poll_start(phydev);")
assert src.count("INIT_DELAYED_WORK(&priv->fifo_poll_work, qca8081_fifo_poll_work)")==1
assert src.count("mutex_init(&priv->fifo_poll_lock)")==1
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BIT(x) (1U<<(x))
#define HZ 100UL
#define QCA8081_PHY_ID 0x004dd101
#define QCA8081_SS_COPPER_LINK BIT(10)
#define QCA8081_PHY_FIFO_RSTN BIT(11)
#define AT803X_SPECIFIC_STATUS 17
#define MDIO_MMD_PMAPMD 1
#define QCA8081_PHY_SERDES_MMD1_FIFO_CTRL 0x9072
#define time_before(a,b) ((long)((a)-(b))<0)
enum { PHY_DOWN,PHY_READY,PHY_HALTED,PHY_ERROR,PHY_UP,PHY_RUNNING,PHY_NOLINK,PHY_CABLETEST };
struct mutex { int held,rank; };
struct mii_bus { struct mutex mdio_lock; };
struct work_struct { int dummy; };
struct delayed_work { struct work_struct work; bool pending; unsigned long due; };
struct phy_device;
struct qca808x_priv {
    struct delayed_work diag_serdes_work,fifo_poll_work;
    struct mutex fifo_poll_lock;
    struct phy_device *diag_phydev;
    bool fifo_poll_running,fifo_poll_paused,fifo_poll_stopping;
    u8 fifo_poll_pair,diag_phy_path_window;
    u32 fifo_poll_tick,diag_phy_path_edges;
    unsigned long fifo_poll_due;
};
struct phy_device {
    struct mutex lock;
    struct { struct mii_bus *bus; int addr; } mdio;
    u32 phy_id,link;
    int state;
    bool suspended,loopback_enabled;
    struct qca808x_priv *priv;
};
#define container_of(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
#define to_delayed_work(ptr) container_of(ptr,struct delayed_work,work)
static struct phy_device p;
static struct qca808x_priv priv;
static struct mii_bus bus;
static unsigned long jiffies;
static int ranks[3],depth;
static bool board=true;
static int reads,writes,status_reads,logs,queues,cancels,sync_cancels;
static int status_value,fifo_value,write_error,suspend_error,resume_error;
static int system_percpu_wq;
static void mutex_lock(struct mutex *m) {
    assert(!m->held && depth<3 && (!depth || ranks[depth-1]<m->rank));
    ranks[depth++]=m->rank; m->held=1;
}
static void mutex_unlock(struct mutex *m) {
    assert(m->held && depth && ranks[depth-1]==m->rank);
    --depth;m->held=0;
}
static struct mutex *lock(struct mutex *m) { mutex_lock(m);return m; }
static void unlock(struct mutex **m) { mutex_unlock(*m); }
#define JOIN_(a,b) a##b
#define JOIN(a,b) JOIN_(a,b)
#define guard(mutex) __attribute__((cleanup(unlock))) struct mutex *JOIN(held_,__LINE__)=lock
static bool of_machine_is_compatible(const char *s) { assert(!strcmp(s,"acer,wave7"));return board; }
static bool queue_delayed_work(int wq,struct delayed_work *d,unsigned long delay) {
    assert(wq==system_percpu_wq && d==&priv.fifo_poll_work && priv.fifo_poll_lock.held);
    assert(delay>0 && delay<=HZ);
    if(d->pending)return false;
    ++queues;d->pending=true;d->due=jiffies+delay;return true;
}
static bool cancel_delayed_work(struct delayed_work *d) {
    assert(d==&priv.fifo_poll_work && priv.fifo_poll_lock.held);
    ++cancels;bool old=d->pending;d->pending=false;return old;
}
static bool cancel_delayed_work_sync(struct delayed_work *d) {
    assert(depth==0 && (d==&priv.fifo_poll_work || d==&priv.diag_serdes_work));
    if(d==&priv.fifo_poll_work)assert(priv.fifo_poll_stopping && !priv.fifo_poll_running);
    ++sync_cancels;bool old=d->pending;d->pending=false;return old;
}
static int genphy_suspend(struct phy_device *phy) {
    assert(phy==&p);
    if(board && p.mdio.addr==24 && p.phy_id==QCA8081_PHY_ID)
        assert(priv.fifo_poll_lock.held && priv.fifo_poll_paused && !priv.fifo_poll_running);
    return suspend_error;
}
static int genphy_resume(struct phy_device *phy) {
    assert(phy==&p);
    if(board && p.mdio.addr==24 && p.phy_id==QCA8081_PHY_ID)assert(priv.fifo_poll_lock.held);
    return resume_error;
}
static int phy_read(struct phy_device *phy,int reg) {
    assert(phy==&p && reg==17 && depth==2 && p.lock.held && priv.fifo_poll_lock.held);
    ++status_reads;return status_value;
}
static int __mdiobus_c45_read(struct mii_bus *b,int addr,int mmd,int reg) {
    assert(b==&bus && b->mdio_lock.held && depth==3 && addr==25 && mmd==1 && reg==0x9072);
    ++reads;return fifo_value;
}
static int __mdiobus_c45_write(struct mii_bus *b,int addr,int mmd,int reg,int val) {
    assert(b==&bus && b->mdio_lock.held && depth==3 && addr==25 && mmd==1 && reg==0x9072);
    ++writes;if(!write_error)fifo_value=val;return write_error;
}
static void phydev_info(struct phy_device *phy,const char *fmt,...) {
    assert(phy==&p && strstr(fmt,"fifo-worker"));++logs;
}
"""+"\n".join(func(n) for n in names)+r"""
static void start(void) {
    mutex_lock(&p.lock);qca8081_fifo_poll_start(&p);mutex_unlock(&p.lock);
}
static void fire(void) {
    priv.fifo_poll_work.pending=false;
    qca8081_fifo_poll_work(&priv.fifo_poll_work.work);
    assert(!depth);
}
static void tick(void) {
    assert(priv.fifo_poll_work.pending);
    jiffies=priv.fifo_poll_work.due;fire();
}
static void init(void) {
    memset(&priv,0,sizeof(priv));memset(&p,0,sizeof(p));memset(&bus,0,sizeof(bus));
    p.lock.rank=1;priv.fifo_poll_lock.rank=2;bus.mdio_lock.rank=3;
    p.priv=&priv;priv.diag_phydev=&p;p.mdio.bus=&bus;p.mdio.addr=24;p.phy_id=QCA8081_PHY_ID;
    p.state=PHY_RUNNING;p.link=1;jiffies=0;board=true;
    reads=writes=status_reads=logs=queues=cancels=sync_cancels=0;
    status_value=0x400;fifo_value=0x8044;write_error=suspend_error=resume_error=0;
}
int main(void) {
    init();assert(qca8081_has_independent_fifo(&p));
    board=false;assert(!qca8081_has_independent_fifo(&p));assert(!qca8081_suspend(&p) && !qca8081_resume(&p) && !cancels);
    board=true;p.mdio.addr=23;assert(!qca8081_has_independent_fifo(&p));p.mdio.addr=24;
    p.phy_id=0;assert(!qca8081_has_independent_fifo(&p));p.phy_id=QCA8081_PHY_ID;
    for(int state=PHY_DOWN;state<=PHY_CABLETEST;state++){
        init();p.state=state;start();
        assert(priv.fifo_poll_work.pending==(state==PHY_UP || state==PHY_RUNNING || state==PHY_NOLINK));
        if(priv.fifo_poll_work.pending){tick();assert(status_reads==(state==PHY_RUNNING||state==PHY_NOLINK));}
    }
    init();jiffies=ULONG_MAX-50;start();
    assert(priv.fifo_poll_work.due==49);start();assert(queues==1);
    jiffies=ULONG_MAX-20;fire();assert(!status_reads && priv.fifo_poll_work.due==49);
    tick();assert(status_reads==1 && reads==1 && writes==1 && fifo_value==0x8844);
    assert(priv.fifo_poll_work.due==149 && logs==1);
    tick();assert(writes==2 && logs==1);
    status_value=0;tick();assert(writes==3 && fifo_value==0x8044 && logs==2 && p.link==1);
    p.link=0;status_value=0x400;tick();assert(writes==4 && fifo_value==0x8844 && p.link==0);
    for(int ss=0;ss<65536;ss++) {
        status_value=ss;fifo_value=0x9544;
        int prev=writes;tick();
        assert(writes==prev+(ss!=65535));
        assert(fifo_value==(ss==65535?0x9544:((0x9544&~0x800)|((ss&0x400)?0x800:0))));
    }
    for(int e=-1;e>=-255;e--) {
        status_value=e;int old=reads;tick();assert(reads==old);
        status_value=0x400;fifo_value=e;old=writes;tick();assert(writes==old);
        fifo_value=0x44;write_error=e;tick();assert(fifo_value==0x44);
    }
    init();start();tick();assert(writes==1);
    mutex_lock(&p.lock);assert(qca8081_suspend(&p)==0);mutex_unlock(&p.lock);
    p.suspended=true;assert(!priv.fifo_poll_work.pending && cancels==1);fire();start();assert(writes==1 && !priv.fifo_poll_work.pending);
    resume_error=-EIO;assert(qca8081_resume(&p)==-EIO);start();assert(!priv.fifo_poll_work.pending);
    resume_error=0;assert(!qca8081_resume(&p));p.suspended=false;start();
    unsigned long due=priv.fifo_poll_due;jiffies=due-1;fire();assert(writes==1 && priv.fifo_poll_work.due==due);
    tick();assert(writes==2);
    suspend_error=-EIO;assert(qca8081_suspend(&p)==-EIO);start();tick();assert(writes==3);
    p.loopback_enabled=true;tick();assert(writes==3 && !priv.fifo_poll_running);start();assert(!priv.fifo_poll_work.pending);
    p.loopback_enabled=false;start();tick();assert(writes==4);
    p.state=PHY_HALTED;tick();assert(writes==4 && !priv.fifo_poll_running);
    p.state=PHY_RUNNING;start();tick();assert(writes==5);
    qca808x_remove(&p);assert(sync_cancels==2 && !priv.fifo_poll_work.pending);
    start();fire();assert(writes==5 && !priv.fifo_poll_work.pending);
    puts("QCA8081_INDEPENDENT_FIFO_PASS 65536 status values, 765 error cases, lifecycle, locking and restart deadline");
}
"""
env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
with tempfile.TemporaryDirectory(prefix="wave7-independent-fifo-") as tmp:
    d=Path(tmp);(d/"test.c").write_text(code)
    cc=os.environ.get("CC","/usr/bin/gcc")
    subprocess.run([os.environ.get("SCCACHE","/usr/local/bin/sccache"),cc,"-std=gnu11","-Wall","-Wextra","-Werror","-O2","-c",str(d/"test.c"),"-o",str(d/"test.o")],check=True,env=env)
    subprocess.run([cc,str(d/"test.o"),"-o",str(d/"test")],check=True,env=env)
    subprocess.run([str(d/"test")],check=True,env=env)
