#!/usr/bin/env python3
"""Exercise the actual MIB reader against an address-edge-triggered ASIC latch."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

source = Path(sys.argv[1]).read_text()
functions = []
for name in ("rtl8365mb_mib_select", "rtl8365mb_mib_read_latch", "rtl8365mb_mib_counter_read"):
    matches = re.findall(r"^static int " + name + r"\([^;]*?\n\{.*?^\}", source, re.M | re.S)
    assert len(matches) == 1, name
    functions.append(matches[0])

diag = re.findall(r"^static void rtl8365mb_mib_probe_same_row\([^;]*?\n\{.*?^\}", source, re.M | re.S)
assert len(diag)==1
counter = re.search(r"RTL8365MB_MAKE_MIB_COUNTER\((\d+), (\d+), ifInUcastPkts\)", source)
assert counter

harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define RTL8365MB_MIB_ADDRESS_PORT_OFFSET 124
#define RTL8365MB_MIB_ADDRESS(p,x) (((p)*124+(x))>>2)
#define RTL8365MB_MIB_ADDRESS_REG 0x1004
#define RTL8365MB_MIB_CTRL0_REG 0x1005
#define RTL8365MB_MIB_CTRL0_BUSY_MASK 1
#define RTL8365MB_MIB_CTRL0_RESET_MASK 2
#define RTL8365MB_MIB_COUNTER_REG(x) (0x1000+(x))
struct chip { bool mib_refresh_same_address; };
struct rtl8365mb { struct chip *chip_info; };
struct realtek_priv { struct rtl8365mb *chip_data; void *map; void *dev; };
static u32 selected, rows[256][4], latch[4];
static unsigned writes, reads, ignored, busy, reset, fault, fail_write;
static unsigned history[16];
static bool refresh_on_same;
static int regmap_write(void *map, u32 reg, u32 val)
{
    (void)map;
    assert(reg == 0x1004 && val < 256 && writes < 16);
    history[writes++] = val;
    if (fail_write && writes == fail_write) return -EIO;
    if (ignored) { ignored--; return 0; }
    if (selected != val || refresh_on_same) {
        selected = val;
        for (unsigned i=0;i<4;i++) latch[i]=rows[val][i];
    }
    return 0;
}
static int regmap_read(void *map, u32 reg, u32 *val)
{
    (void)map;
    if (reg == 0x1004) { *val=selected; return 0; }
    if (reg == 0x1005) { *val=busy?1:reset?2:0; return 0; }
    assert(reg>=0x1000 && reg<=0x1003);
    reads++;
    if (fault) return -EIO;
    *val=latch[reg-0x1000];
    return 0;
}
#define regmap_read_poll_timeout(map,reg,val,cond,delay,timeout) \
    ({ int rc=regmap_read(map,reg,&val); rc?rc:(cond)?0:-ETIMEDOUT; })
"""
diag_harness = r"""
struct rtl8365mb_mib_counter {u32 offset,length;};
#define RTL8365MB_MIB_ifInUcastPkts 0
static const struct rtl8365mb_mib_counter rtl8365mb_mib_counters[] = {
    { OFFSET, LENGTH }
};
static u64 mock_ns, recorded[6];
static unsigned log_ok, log_error, slept, traffic;
static void msleep(unsigned ms)
{
    assert(ms==250);
    slept++;
    mock_ns+=(u64)ms*1000000;
    rows[selected][0]+=traffic;
}
static u64 ktime_get_boottime_ns(void)
{
    return mock_ns+=1000;
}
#define ERR_PTR(err) (err)
#define dev_info(dev,fmt,port,row,initial,same,refreshed,first_ns,same_ns,refreshed_ns) do { \
    (void)(dev); (void)(fmt); assert((port)==6 && (row)==190); \
    recorded[0]=initial; recorded[1]=same; recorded[2]=refreshed; \
    recorded[3]=first_ns; recorded[4]=same_ns; recorded[5]=refreshed_ns; log_ok++; \
} while (0)
#define dev_err(dev,fmt,port,row,err) do { \
    (void)(dev); (void)(fmt); assert((port)==6 && (row)==190 && (err)<0); log_error++; \
} while (0)
""".replace("OFFSET",counter[1]).replace("LENGTH",counter[2])
tests = r"""
static void reset_test(u32 addr)
{
    selected=addr; writes=reads=ignored=busy=reset=fault=fail_write=0;
    for(unsigned i=0;i<4;i++) { rows[addr][i]=i+5; latch[i]=i+1; }
}
int main(void)
{
    struct chip chip={true}; struct rtl8365mb mb={&chip};
    struct realtek_priv priv={&mb,0,0};
    u64 out;
    unsigned count=0;
    for(int port=0;port<8;port++) {
        for(u32 offset=0;offset<124;offset+=2) {
            u32 addr=RTL8365MB_MIB_ADDRESS(port,offset);
            reset_test(addr);
            assert(rtl8365mb_mib_counter_read(&priv,port,offset,2,&out)==0);
            unsigned high=(offset+1)%4;
            assert(out==(((u64)(high+5)<<16)|(high+4)));
            assert(writes==2 && reads==2 && history[1]==addr);
            assert(history[0]/31==(unsigned)port && history[0]!=addr);
            count++;
        }
    }
    reset_test(186);
    assert(!rtl8365mb_mib_counter_read(&priv,6,0,4,&out));
    assert(out==0x0008000700060005ULL);
    reset_test(185);
    rows[186][0]=9; rows[186][1]=10;
    assert(!rtl8365mb_mib_counter_read(&priv,6,0,2,&out));
    assert(writes==1 && out==0x000a0009ULL);
    reset_test(186); ignored=1;
    assert(!rtl8365mb_mib_counter_read(&priv,6,0,2,&out) && writes==3);
    reset_test(186); ignored=3; out=0x1234;
    assert(rtl8365mb_mib_counter_read(&priv,6,0,2,&out)==-EIO);
    assert(writes==3 && reads==0 && out==0x1234);
    reset_test(186); busy=1;
    assert(rtl8365mb_mib_counter_read(&priv,6,0,2,&out)==-ETIMEDOUT);
    assert(writes==1 && reads==0);
    reset_test(186); reset=1;
    assert(rtl8365mb_mib_counter_read(&priv,6,0,2,&out)==-EIO && reads==0);
    reset_test(186); fail_write=2;
    assert(rtl8365mb_mib_counter_read(&priv,6,0,2,&out)==-EIO && reads==0);
    reset_test(186); fault=1; out=0x1234;
    assert(rtl8365mb_mib_counter_read(&priv,6,0,2,&out)==-EIO && out==0x1234);
    reset_test(186); chip.mib_refresh_same_address=false;
    assert(!rtl8365mb_mib_counter_read(&priv,6,0,2,&out));
    assert(writes==1 && out==0x00020001ULL);
    printf("%u same-row cases plus 9 targeted cases passed\n",count);
    unsigned diag_count=0;
    chip.mib_refresh_same_address=true;
    for(unsigned fresh=0;fresh<2;fresh++) for(unsigned advance=0;advance<2;advance++) {
        reset_test(190);
        refresh_on_same=fresh;
        traffic=advance?17:0;
        log_ok=log_error=slept=mock_ns=0;
        rtl8365mb_mib_probe_same_row(&priv,6);
        assert(log_ok==1 && !log_error && slept==1 && writes==5);
        assert(history[0]==191 && history[1]==190 && history[2]==190 &&
               history[3]==191 && history[4]==190);
        assert(recorded[0]==0x00060005ULL);
        assert(recorded[1]==recorded[0]+(fresh?traffic:0));
        assert(recorded[2]==recorded[0]+traffic);
        assert(recorded[4]-recorded[3]==250001000 && recorded[5]-recorded[4]==1000);
        diag_count++;
    }
    for(unsigned bad=1;bad<=5;bad++) {
        reset_test(190);
        refresh_on_same=false;
        traffic=17;
        log_ok=log_error=slept=mock_ns=0;
        fail_write=bad;
        rtl8365mb_mib_probe_same_row(&priv,6);
        assert(!log_ok && log_error==1 && writes==bad);
        assert(slept==(bad>2));
        diag_count++;
    }
    printf("%u latch diagnostic cases passed\n",diag_count);

}
"""
# Compile the actual extracted code, rather than a duplicate implementation.
with tempfile.TemporaryDirectory(prefix="mib-test-") as temp:
    path = Path(temp) / "test.c"
    binary = Path(temp) / "test"
    path.write_text(harness + "\n".join(functions) + diag_harness + "\n".join(diag) + tests)
    subprocess.run(["/usr/local/bin/sccache", "cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                    "-O2", str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
