#!/usr/bin/env python3
"""Compile actual original and candidate MAC force routines against a mock ASIC bus."""
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

functions = [function(source, "rtl8365mb_ext_config_forcemode").replace(
    "rtl8365mb_ext_config_forcemode(", name + "(")
    for source, name in ((baseline, "old_force"), (candidate, "new_force"))]
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
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define BIT(n) (1u << (n))
#define GENMASK(h,l) (((~0u) >> (31-(h))) & ((~0u) << (l)))
#define FIELD_PREP(m,v) (((u32)(v) << __builtin_ctz(m)) & (m))
#define SPEED_10 10
#define SPEED_100 100
#define SPEED_1000 1000
#define SPEED_2500 2500
#define DUPLEX_HALF 0
#define DUPLEX_FULL 1
#define RTL8365MB_FAMILY_C 0
#define RTL8365MB_FAMILY_D 1
#define dev_err(...) ((void)0)
struct chip { bool mac_force_link_last; };
struct rtl8365mb { struct chip *chip_info; };
struct realtek_priv { void *map; struct rtl8365mb *chip_data; };
struct rtl8365mb_extint { int id; };
static struct chip chip;
static struct rtl8365mb mb={&chip};
static struct realtek_priv priv={0,&mb};
static struct rtl8365mb_extint ext;
static unsigned family, calls, fail_at, n;
static u32 regs[65536];
struct event { u32 addr, val; };
static struct event events[4];
static int rtl8365mb_get_family(struct realtek_priv *p)
{ (void)p; return family; }
static const struct rtl8365mb_extint *rtl8365mb_get_port_extint(struct realtek_priv *p,int port)
{ (void)p; ext.id=port-6; return port==6 || port==7 ? &ext : 0; }
static int regmap_write(void *map,u32 addr,u32 val)
{
    (void)map;
    if (++calls==fail_at) return -EIO;
    assert(n<4);
    regs[addr]=val;
    events[n++]=(struct event){addr,val};
    return 0;
}
static int regmap_write_bits(void *map,u32 addr,u32 mask,u32 val)
{ return regmap_write(map,addr,(regs[addr]&~mask)|(val&mask)); }
"""
tests = r"""
static void setup(unsigned f,bool last,int port,u32 initial)
{
    memset(regs,0,sizeof(regs)); memset(events,0,sizeof(events));
    family=f; chip.mac_force_link_last=last; calls=n=fail_at=0;
    regs[0x12c0+port]=initial;
}
static void event(unsigned i,u32 addr,u32 val)
{ assert(i<n && events[i].addr==addr && events[i].val==val); }
int main(void)
{
    unsigned cases=0, faults=0;
    int rates[]={10,100,1000,2500};
    u32 initials[]={0,0x1075,0xa5a5,0xffff};
    for(unsigned f=0;f<2;f++)
    for(int port=6;port<=7;port++)
    for(unsigned s=0;s<4;s++)
    for(unsigned d=0;d<2;d++)
    for(unsigned l=0;l<2;l++)
    for(unsigned tx=0;tx<2;tx++)
    for(unsigned rx=0;rx<2;rx++)
    for(unsigned i=0;i<4;i++) {
        setup(f,false,port,initials[i]);
        assert(old_force(&priv,port,l,rates[s],d,tx,rx)==0);
        struct event baseline[4]; memcpy(baseline,events,sizeof(events));
        unsigned count=n;
        setup(f,false,port,initials[i]);
        assert(new_force(&priv,port,l,rates[s],d,tx,rx)==0);
        assert(n==count && !memcmp(events,baseline,sizeof(events)));
        cases++;
        if(f!=1) continue;
        setup(f,true,port,initials[i]);
        assert(new_force(&priv,port,l,rates[s],d,tx,rx)==0);
        u32 addr=0x12c0+port, en=addr+8, val=baseline[0].val;
        assert(n==(l?4:3));
        event(0,addr,initials[i]&~16u);
        event(1,addr,val&~16u);
        event(2,en,0xffff);
        if(l) event(3,addr,val);
        assert(regs[addr]==val && regs[en]==0xffff);
        unsigned steps=n; cases++;
        for(unsigned k=1;k<=steps;k++) {
            setup(f,true,port,initials[i]); fail_at=k;
            assert(new_force(&priv,port,l,rates[s],d,tx,rx)==-EIO);
            assert(calls==k && n==k-1);
            faults++;
        }
    }
    setup(1,true,6,0);
    assert(new_force(&priv,5,true,1000,1,1,1)==-ENODEV);
    assert(new_force(&priv,6,true,5000,1,1,1)==-EINVAL);
    assert(new_force(&priv,6,true,1000,2,1,1)==-EINVAL);
    assert(n==0 && calls==0);
    printf("functional=%u injected_error=%u invalid=3 PASS\n",cases,faults);
}
"""
with tempfile.TemporaryDirectory() as directory:
    source=Path(directory)/"test.c"
    binary=Path(directory)/"test"
    source.write_text(prefix+"\n"+"\n".join(selected.values())+"\n"+"\n".join(functions)+"\n"+tests)
    subprocess.run(["/usr/local/bin/sccache","gcc","-std=c11","-Wall","-Wextra","-Werror",str(source),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
