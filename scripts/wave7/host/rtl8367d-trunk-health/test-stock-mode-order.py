#!/usr/bin/env python3
"""Compile actual original and candidate pcs_config against a mock ASIC bus."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

baseline, candidate = (Path(arg).read_text() for arg in sys.argv[1:])
def function(source, name):
    match = re.search(r"^static int " + name + r"\([^;]*?\n\{.*?^\}", source, re.M | re.S)
    assert match
    return match[0]

def definitions(source):
    lines = source.splitlines()
    result = {}
    for i, line in enumerate(lines):
        match = re.match(r"^#define\s+(RTL8365MB_\w+)(?:\(|\s)", line)
        if not match:
            continue
        end = i
        while lines[end].endswith("\\"):
            end += 1
        result[match[1]] = "\n".join(lines[i:end+1])
    return result

functions = [function(baseline, "rtl8365mb_pcs_config").replace(
                 "rtl8365mb_pcs_config(", "baseline_config("),
             function(candidate, "rtl8365mb_pcs_config").replace(
                 "rtl8365mb_pcs_config(", "candidate_config(")]
tables = "\n".join(re.findall(
    r"^static const struct rtl8365mb_jam_tbl_entry rtl8365mb_(?:d_)?sds_jam_(?:hsgmii|sgmii)\[\] = \{.*?^\};",
    candidate, re.M | re.S))
assert tables.count("static const") == 4
defs = definitions(candidate)
needed = set(re.findall(r"\bRTL8365MB_\w+", "\n".join(functions)))
selected = {}
while needed:
    name = needed.pop()
    if name in selected or name not in defs:
        continue
    selected[name] = defs[name]
    needed.update(re.findall(r"\bRTL8365MB_\w+", defs[name]) - selected.keys())

prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef unsigned phy_interface_t;
#define BIT(n) (1u << (n))
#define GENMASK(h,l) (((~0u) >> (31-(h))) & ((~0u) << (l)))
#define BMCR_ANENABLE 0x1000
#define BMCR_ISOLATE 0x0400
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define WRITE_ONCE(a,b) ((a)=(b))
#define READ_ONCE(a) (a)
#define guard(x) mock_guard
#define PHY_INTERFACE_MODE_SGMII 1
#define PHY_INTERFACE_MODE_2500BASEX 2
#define RTL8365MB_FAMILY_D 1
#define RTL8365MB_FAMILY_C 0
struct rtl8365mb_jam_tbl_entry { u16 reg, val; };
struct phylink_pcs { int dummy; };
struct chip { bool sds_ordered_mode; unsigned family; };
struct realtek_priv { void *map; };
struct rtl8365mb {
    struct phylink_pcs pcs;
    struct realtek_priv *priv;
    const struct chip *chip_info;
    int sds_cfg_lock, sds_relatch;
    bool sds_relatch_armed, sds_conduit_up;
    u32 sds_misc_target_val;
};
#define pcs_to_rtl8365mb(p) ((struct rtl8365mb *)(p))
static unsigned family, starts, cancels, calls, fail_at, n;
struct event { u32 kind, lane, addr, val; };
static struct event events[64];
static u32 regs[65536], sds[16][2048];
static int fail(void) { return ++calls == fail_at ? -EIO : 0; }
static void record(u32 kind,u32 lane,u32 addr,u32 val)
{
    assert(n < ARRAY_SIZE(events));
    events[n++] = (struct event){kind,lane,addr,val};
}
static void mock_guard(int *lock) { (void)lock; }
static void cancel_delayed_work_sync(int *work) { (void)work; cancels++; }
static unsigned rtl8365mb_get_family(struct realtek_priv *priv)
{
    (void)priv; return family;
}
static int rtl8365mb_d_sds_recovery_finish(struct rtl8365mb *mb)
{
    (void)mb; return fail();
}
static void rtl8365mb_sds_relatch_start(struct rtl8365mb *mb)
{
    assert(mb->sds_relatch_armed); starts++;
}
static int regmap_update_bits_base(void *map,u32 addr,u32 mask,u32 val,
                                  void *changed,bool async,bool force)
{
    (void)map; (void)changed; assert(!async);
    if (fail()) return -EIO;
    assert(addr < ARRAY_SIZE(regs));
    u32 next = (regs[addr] & ~mask) | (val & mask);
    if (force || next != regs[addr]) {
        regs[addr] = next;
        record(0,0,addr,next);
    }
    return 0;
}
static int regmap_update_bits(void *map,u32 addr,u32 mask,u32 val)
{
    return regmap_update_bits_base(map,addr,mask,val,NULL,false,false);
}
static int regmap_write_bits(void *map,u32 addr,u32 mask,u32 val)
{
    return regmap_update_bits_base(map,addr,mask,val,NULL,false,true);
}
static int rtl8365mb_sds_write(struct realtek_priv *priv,u8 lane,u16 addr,u16 val)
{
    (void)priv;
    if (fail()) return -EIO;
    assert(lane < 16 && addr < 2048);
    sds[lane][addr]=val;
    record(1,lane,addr,val);
    return 0;
}
static int rtl8365mb_sds_read(struct realtek_priv *priv,u8 lane,u16 addr,u16 *val)
{
    (void)priv;
    if (fail()) return -EIO;
    *val=sds[lane][addr];
    record(2,lane,addr,*val);
    return 0;
}
"""
tests = r"""
typedef int (*config_fn)(struct phylink_pcs*,unsigned,phy_interface_t,
                         const unsigned long*,bool);
static struct chip chip;
static struct realtek_priv priv;
static struct rtl8365mb mb;
static void setup(unsigned fam,bool ordered,u32 misc,u32 nway,bool conduit)
{
    memset(regs,0,sizeof(regs)); memset(sds,0,sizeof(sds));
    memset(&mb,0,sizeof(mb));
    family=fam; chip=(struct chip){ordered,fam};
    mb.priv=&priv; mb.chip_info=&chip;
    mb.sds_conduit_up=conduit; mb.sds_relatch_armed=true;
    regs[0x1d11]=misc;
    regs[0x03f7]=0xfffd; /* already clear: stock still writes */
    regs[0x13e8]=0xa565; /* already correct: stock still writes */
    sds[13][2]=sds[0][2]=nway;
    n=starts=cancels=calls=fail_at=0;
}
static void event(unsigned i,u32 kind,u32 lane,u32 addr,u32 val)
{
    struct event expected={kind,lane,addr,val};
    assert(i<n && !memcmp(&expected,&events[i],sizeof(expected)));
}
int main(void)
{
    unsigned cases=0, faults=0;
    const u32 states[]={0,0x1f,0x0e12,0xa5a5,0xffff};
    const u32 nways[]={0,0x200,0x55aa,0xffff};
    for(unsigned f=0;f<2;f++)
    for(unsigned m=1;m<=2;m++)
    for(unsigned s=0;s<ARRAY_SIZE(states);s++)
    for(unsigned w=0;w<ARRAY_SIZE(nways);w++)
    for(unsigned c=0;c<2;c++) {
        u32 misc=states[s], nway=nways[w];
        setup(f,false,misc,nway,c);
        assert(!baseline_config(&mb.pcs,0,m,NULL,false));
        struct event old[64]; memcpy(old,events,n*sizeof(*events));
        unsigned old_n=n, old_calls=calls, old_starts=starts;
        u32 old_misc=regs[0x1d11];
        setup(f,false,misc,nway,c);
        assert(!candidate_config(&mb.pcs,0,m,NULL,false));
        assert(n==old_n && calls==old_calls && starts==old_starts);
        assert(!memcmp(old,events,n*sizeof(*events)));
        cases++;
        if(f!=RTL8365MB_FAMILY_D) continue;
        setup(f,true,misc,nway,c);
        assert(!candidate_config(&mb.pcs,0,m,NULL,false));
        /* Skip the original DW8051 hold/reset writes; no change there. */
        unsigned i=0;
        while(i<n && events[i].addr!=0x03f7) i++;
        event(i++,0,0,0x03f7,0xfffd);
        misc|=1u<<9;
        event(i++,0,0,0x1d11,misc);
        const struct rtl8365mb_jam_tbl_entry *table=m==2?
            rtl8365mb_d_sds_jam_hsgmii:rtl8365mb_d_sds_jam_sgmii;
        for(unsigned j=0;j<10;j++)
            event(i++,1,13,table[j].reg,table[j].val);
        event(i++,0,0,0x13e8,0xa565);
        misc|=1u<<10; event(i++,0,0,0x1d11,misc);
        misc|=1u<<11; event(i++,0,0,0x1d11,misc);
        misc=(misc&~31u)|(m==2?18:2);
        event(i++,0,0,0x1d11,misc);
        event(i++,1,13,3,0x7106);
        event(i++,1,13,0,0x1401);
        event(i++,1,13,0,0x1403);
        event(i++,2,13,2,nway);
        event(i++,1,13,2,(nway&~512u)|256u);
        assert(i==n && regs[0x1d11]==old_misc);
        assert(mb.sds_relatch_armed==(m==2) && starts==(m==2&&c));
        assert(mb.sds_misc_target_val==(misc&0xe1fu));
        cases++;
        unsigned total=calls;
        for(unsigned fail=1;fail<=total;fail++) {
            setup(f,true,states[s],nway,c); fail_at=fail;
            assert(candidate_config(&mb.pcs,0,m,NULL,false)==-EIO);
            assert(calls==fail && starts==0 && !mb.sds_relatch_armed);
            faults++;
        }
    }
    printf("%u successful cases, %u fault-injection cases\n",cases,faults);
}
"""
with tempfile.TemporaryDirectory(prefix="stock-mode-") as tmp:
    path = Path(tmp)/"test.c"
    binary = Path(tmp)/"test"
    path.write_text(prefix + "\n".join(selected[name] for name in sorted(selected)) + "\n" +
                    tables + "\n" + "\n".join(functions) + tests)
    subprocess.run(["/usr/local/bin/sccache","cc","-std=gnu11","-O2",
                    "-Wall","-Wextra","-Werror","-Wno-unused-parameter",
                    "-Wno-sign-compare",str(path),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
