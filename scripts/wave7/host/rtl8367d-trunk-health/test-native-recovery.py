#!/usr/bin/env python3
"""Compile the actual candidate recovery + worker code with an injected ASIC bus.

Test order, lock lifetime, ambiguous writes, bounded release retries and
recovery choice. No router access. Uses the managed sccache for compilation.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source=Path(sys.argv[1]).read_text()

def extract(pattern):
    match=re.search(pattern,source,re.M|re.S)
    if match is None:
        raise ValueError(f"missing source fragment {pattern}")
    return match[0]

def function(name):
    return extract(r"^static [^\n]*\b"+name+r"\(.*?^\}")

def macro(name):
    lines=source.splitlines()
    for i,line in enumerate(lines):
        if re.match(r"^#define[ \t]+"+name+r"\b",line):
            end=i
            while lines[end].endswith("\\"):
                end+=1
            return "\n".join(lines[i:end+1])
    raise ValueError(f"missing macro {name}")

defines="\n".join(macro(name) for name in (
    "RTL8365MB_D_SDS_EXT0_INDEX",
    "RTL8365MB_D_SDS_RECOVERY_OUTER_REG",
    "RTL8365MB_D_SDS_RECOVERY_OUTER_MASK",
    "RTL8365MB_D_SDS_RECOVERY_INNER_REG",
    "RTL8365MB_D_SDS_RECOVERY_INNER_MASK",
    "RTL8365MB_D_SDS_RECOVERY_OUTER",
    "RTL8365MB_D_SDS_RECOVERY_INNER",
    "RTL8365MB_D_SDS_RESTORE_TRIES",
    "RTL8365MB_D_SDS_RELATCH_INTERVAL",
    "RTL8365MB_D_SDS_RELATCH_MAX_TRIES",
    "RTL8365MB_D_SDS_HEALTHCHECK_INTERVAL",
    "RTL8365MB_D_SDS_MISC_MODE_FIELD_MASK",
    "RTL8365MB_D_SDS_MISC_PA33PC_EN",
    "RTL8365MB_D_SDS_MISC_PA12PC_EN",
    "RTL8365MB_D_SDS_MISC_MAC6_SEL_SDS0",
    "RTL8365MB_D_SDS_MISC_CFG_MASK",
    "RTL8365MB_D_PORT_SDS_MODE_DISABLE",
    "RTL8365MB_SDS_MISC_REG",
    "RTL8365MB_SDS_REG_LINK_STATUS",
    "RTL8365MB_SDS_LINK_STATUS_LINK_MASK",
    "RTL8365MB_D_SDS_RX_MIN_ERRORS",
    "RTL8365MB_D_SDS_RX_MIN_INTERVALS",
))
# The candidate also uses the mask declared as a multiline macro.
structs="\n".join(extract(r"^struct "+name+r" \{.*?^\};") for name in (
    "rtl8365mb_sds_rx_sample","rtl8365mb_sds_rx_health"))
headers=r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define BIT(x) (1u << (x))
#define GENMASK(h,l) (((1u << ((h)+1))-1) & ~((1u << (l))-1))
#define HZ 100
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define ERR_PTR(x) (x)
#define dev_err_ratelimited(...) (++logged_errors)
#define dev_warn_ratelimited(...) (++logged_warnings)
#define dev_warn(...) (++logged_warnings)
#define dev_info_ratelimited(...) (++logged_info)
#define dev_dbg(...) ((void)0)
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; unsigned long delay; };
static struct delayed_work *to_delayed_work(struct work_struct *w) {
    return container_of(w,struct delayed_work,work);
}
static void schedule_delayed_work(struct delayed_work *w,unsigned long delay) {
    w->delay=delay;
}
struct mutex { bool held; };
static struct mutex *lock(struct mutex *m) { assert(!m->held); m->held=true; return m; }
static void unlock(struct mutex **m) { assert((*m)->held); (*m)->held=false; }
#define guard(mutex) __attribute__((cleanup(unlock))) struct mutex *guard_lock=lock
#define lockdep_assert_held(m) assert((m)->held)
struct realtek_priv { void *chip_data; void *dev; void *map; };
struct rtl8365mb_chip_info { bool sds_pulse_recovery; };
"""
mocks=r"""
struct rtl8365mb {
    struct realtek_priv *priv;
    struct mutex sds_lock;
    const struct rtl8365mb_chip_info *chip_info;
    struct delayed_work sds_relatch;
    unsigned int sds_relatch_count;
    u32 sds_misc_target_val;
    struct rtl8365mb_sds_rx_health sds_rx_health;
    unsigned int sds_recovery_pending;
    bool sds_link_pulse_next;
};
static u16 outer,inner,status;
static u32 misc;
static unsigned op,fail_at,fail_from,fail_to,logged_errors,logged_warnings,logged_info;
static bool ambiguous;
static unsigned parks,restores;
static int log_addr[64], log_val[64], log_n;
static struct rtl8365mb_sds_rx_sample counter;
static bool fail(void) {
    ++op;
    return op==fail_at || (fail_from && op>=fail_from && op<=fail_to);
}
static u16 *regptr(u16 reg) {
    switch (reg) {
    case RTL8365MB_D_SDS_RECOVERY_OUTER_REG: return &outer;
    case RTL8365MB_D_SDS_RECOVERY_INNER_REG: return &inner;
    case RTL8365MB_SDS_REG_LINK_STATUS: return &status;
    default: assert(0); return NULL;
    }
}
static int rtl8365mb_sds_read_locked(struct realtek_priv *p,u8 index,u16 reg,u16 *v) {
    struct rtl8365mb *mb=p->chip_data;
    assert(mb->sds_lock.held && index==13);
    if (fail()) return -EIO;
    *v=*regptr(reg);
    return 0;
}
static int rtl8365mb_sds_write_locked(struct realtek_priv *p,u8 index,u16 reg,u16 v) {
    struct rtl8365mb *mb=p->chip_data;
    assert(mb->sds_lock.held && index==13);
    assert(log_n<64);
    log_addr[log_n]=reg; log_val[log_n++]=v;
    bool error=fail();
    if (!error || ambiguous) *regptr(reg)=v;
    return error ? -EIO : 0;
}
static int rtl8365mb_sds_read(struct realtek_priv *p,u8 index,u16 reg,u16 *v) {
    struct rtl8365mb *mb=p->chip_data;
    guard(mutex)(&mb->sds_lock);
    return rtl8365mb_sds_read_locked(p,index,reg,v);
}
static void usleep_range(unsigned a,unsigned b) { assert(a<=b); }
static int regmap_read(void *p,unsigned reg,u32 *val) {
    assert(p==NULL && reg==RTL8365MB_SDS_MISC_REG);
    *val=misc; return 0;
}
static int regmap_update_bits(void *p,unsigned reg,u32 mask,u32 val) {
    assert(p==NULL && reg==RTL8365MB_SDS_MISC_REG);
    misc=(misc&~mask)|(val&mask);
    if ((val&RTL8365MB_D_SDS_MISC_MODE_FIELD_MASK)==0x1f) parks++;
    else restores++;
    return 0;
}
"""
core="\n".join(function(name) for name in (
    "rtl8365mb_d_sds_recovery_step","rtl8365mb_d_sds_recovery_clear_locked",
    "rtl8365mb_d_sds_recovery_finish_locked","rtl8365mb_d_sds_recovery_finish",
    "rtl8365mb_d_sds_recovery_pulse"))
policy=extract(r"^static bool\nrtl8365mb_sds_rx_fault\(.*?^\}")
worker="\n".join(function(name) for name in (
    "rtl8365mb_sds_relatch_start","rtl8365mb_sds_relatch_restore",
    "rtl8365mb_sds_relatch_work"))
shim=r"""
static bool rtl8365mb_sds_rx_unhealthy(struct rtl8365mb *mb) {
    return rtl8365mb_sds_rx_fault(&mb->sds_rx_health,&counter);
}
"""
body=r"""
static struct rtl8365mb mb;
static struct realtek_priv priv;
static struct rtl8365mb_chip_info chip;
static void reset(void) {
    memset(&mb,0,sizeof(mb));
    memset(&counter,0,sizeof(counter));
    chip.sds_pulse_recovery=true; mb.chip_info=&chip;
    mb.priv=&priv; priv.chip_data=&mb;
    mb.sds_misc_target_val=0xe12; misc=0xe12;
    outer=0x9501; inner=0xa512; status=0x10;
    op=fail_at=fail_from=fail_to=logged_errors=logged_warnings=logged_info=0;
    ambiguous=false; log_n=parks=restores=0;
}

static void assert_clear(void) {
    assert(outer==0x9501 && inner==0xa512);
    assert(mb.sds_recovery_pending==0 && !mb.sds_lock.held);
}

static void work(void) { rtl8365mb_sds_relatch_work(&mb.sds_relatch.work); }
static void corrupt(void) { counter.fcs+=8; work(); }

int main(void) {
    reset();
    assert(!rtl8365mb_d_sds_recovery_pulse(&mb));
    assert(op==8 && log_n==4);
    const int addr[]={0x3f,0x400,0x400,0x3f};
    const int vals[]={0x9521,0xa516,0xa512,0x9501};
    for (int i=0;i<4;i++) {
        assert(log_addr[i]==addr[i] && log_val[i]==vals[i]);
    }
    assert_clear();

    // Both pre-write and ambiguous (write reached ASIC) transport errors,
    // at every read/write boundary, including repeated release attempts.
    for (unsigned n=1;n<=8;n++) for (int a=0;a<=1;a++) {
        reset(); fail_at=n; ambiguous=a;
        int ret=rtl8365mb_d_sds_recovery_pulse(&mb);
        assert(n<=4 ? ret==-EIO : ret==0);
        assert_clear();
    }

    // Inner release fails all three times. Keep outer asserted, retry
    // on the next worker invocation without issuing another pulse/edge.
    for (int a=0;a<=1;a++) {
        reset(); fail_from=5; fail_to=7; ambiguous=a;
        assert(rtl8365mb_d_sds_recovery_pulse(&mb)==-EIO);
        assert(mb.sds_recovery_pending!=0 && logged_errors==1);
        assert(outer==0x9521 && inner==0xa516);
        fail_from=fail_to=0;
        work();
        assert_clear();
        assert(!parks && !restores && mb.sds_relatch.delay==HZ);
    }

    // Outer release fails after successfully clearing inner. A later
    // cleanup must never reassert inner or overwrite unrelated bits.
    reset(); fail_from=7; fail_to=9;
    assert(rtl8365mb_d_sds_recovery_pulse(&mb)==-EIO);
    assert(mb.sds_recovery_pending==RTL8365MB_D_SDS_RECOVERY_OUTER);
    assert(inner==0xa512 && outer==0x9521);
    outer ^= 0x800; // independent hardware-owned bit changes
    fail_from=fail_to=0;
    assert(!rtl8365mb_d_sds_recovery_finish(&mb));
    assert(outer==0x9d01 && inner==0xa512 && !mb.sds_recovery_pending);

    // Start exactly with the historical edge; only persistent corruption
    // triggers the native pulse. A good sample resets the escalation.
    reset(); rtl8365mb_sds_relatch_start(&mb); work();
    corrupt(); corrupt();
    assert(parks==1 && restores==1 && !log_n && mb.sds_rx_health.relatch_attempted);
    work(); corrupt(); corrupt();
    assert(parks==1 && log_n==4 && logged_info==1 && !mb.sds_rx_health.relatch_attempted);
    assert(mb.sds_relatch.delay==10*HZ);
    work(); corrupt(); corrupt();
    assert(parks==2 && log_n==4);
    work(); counter.good[0]++; work();
    assert(!mb.sds_rx_health.relatch_attempted);
    corrupt(); corrupt();
    assert(parks==3 && log_n==4);

    // Idle/valid ingress must not actuate recovery, and the uncovered
    // silicon uses only the original edge even after persistent errors.
    reset(); rtl8365mb_sds_relatch_start(&mb);
    for (int i=0;i<100;i++) { counter.good[1]++; counter.fcs+=2; work(); }
    assert(!parks && !log_n);
    reset(); chip.sds_pulse_recovery=false; rtl8365mb_sds_relatch_start(&mb);
    for (int i=0;i<12;i++) corrupt();
    assert(parks>1 && !log_n);

    // All fifteen fast startup retries remain mode edges. The next
    // iteration reports exhaustion, then stock pulse and mode edge
    // alternate at the slow cadence.
    reset(); status=0; rtl8365mb_sds_relatch_start(&mb);
    for (int i=0;i<15;i++) { work(); assert(mb.sds_relatch.delay==HZ); }
    assert(parks==15 && !log_n);
    work(); assert(parks==15 && !log_n && mb.sds_relatch.delay==10*HZ);
    work(); assert(parks==15 && log_n==4 && mb.sds_relatch.delay==10*HZ);
    work(); assert(parks==16 && log_n==4);
    status=0x10; work(); assert(mb.sds_relatch_count==0);
    status=0; work(); assert(parks==17 && log_n==4 && mb.sds_relatch.delay==HZ);
    puts("RTL8367D_NATIVE_RECOVERY_TEST_PASS");
}
"""
env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
cc=os.environ.get("CC","/usr/bin/gcc")
cache=os.environ.get("SCCACHE","/usr/local/bin/sccache")
with tempfile.TemporaryDirectory(prefix="wave7-native-test-") as temp:
    d=Path(temp)
    c=d/"test.c"
    c.write_text("\n".join((headers,defines,structs,mocks,core,policy,shim,worker,body)))
    subprocess.run([cache,cc,"-std=gnu11","-O2","-Wall","-Wextra","-Werror",
                    "-Wno-sign-compare","-c",str(c),"-o",str(d/"test.o")],check=True,env=env)
    subprocess.run([cc,str(d/"test.o"),"-o",str(d/"test")],check=True,env=env)
    subprocess.run([str(d/"test")],check=True,env=env)
