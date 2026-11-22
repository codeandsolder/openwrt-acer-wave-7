#!/usr/bin/env python3
"""Compile the actual FIFO policy and vendor-status helper with mock MDIO."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
source = (root/"drivers/net/phy/qcom/qca808x.c").read_text()
lib = (root/"drivers/net/phy/qcom/qcom-phy-lib.c").read_text()
header = (root/"drivers/net/phy/qcom/qcom.h").read_text()
helper = re.search(r"^static int qca8081_stock_fifo_level\(.*?^\}", source, re.M | re.S)[0]
status = re.search(r"^static int qca808x_read_status\(.*?^\}", source, re.M | re.S)[0]
block = re.search(r"^\tif \(phydev->phy_id == QCA8081_PHY_ID\) \{.*?^\t\}", status, re.M | re.S)[0]
specific = re.search(r"^int at803x_read_specific_status\(.*?^\}", lib, re.M | re.S)[0]
assert status.index("at803x_read_specific_status") < status.index(block) < status.index("if (phydev->link)")
assert "if (ret < 0)" in status[status.index("at803x_read_specific_status"):status.index(block)]
assert "QCA8081_SS_COPPER_LINK" in block
assert source.count("qca8081_stock_fifo_level(") == 2
assert "return ss;" in specific
# Both in-tree callers treat nonnegative results as success and return
# their own success code. Their exported symbol prototypes are unchanged.
caller = re.search(r"^int at803x_read_status\(.*?^\}", lib, re.M | re.S)[0]
assert "err = at803x_read_specific_status(phydev, ss_mask);\n\tif (err < 0)" in caller
defines = "\n".join(line for line in header.splitlines()
                    if re.match(r"#define (?:AT803X_SFC_|AT803X_SPECIFIC_|AT803X_SS_|QCA808[1X]_SS_)", line))
program = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)>>(31-(h)))&(~0U<<(l)))
#define FIELD_GET(m,x) (((x)&(m))>>__builtin_ctz(m))
#define MDIO_MMD_PMAPMD 1
#define QCA8081_PHY_SERDES_MMD1_FIFO_CTRL 0x9072
#define QCA8081_PHY_FIFO_RSTN BIT(11)
#define QCA8081_PHY_ID 0x004dd101
#define SPEED_10 10
#define SPEED_100 100
#define SPEED_1000 1000
#define SPEED_2500 2500
#define DUPLEX_FULL 1
#define DUPLEX_HALF 0
#define ETH_TP_MDI_X 2
#define ETH_TP_MDI 1
#define ETH_TP_MDI_AUTO 3
typedef uint8_t u8;
typedef uint16_t u16;
struct mutex { bool held; };
struct mii_bus { struct mutex mdio_lock; };
struct qca808x_priv { u8 diag_fifo_link_pair; };
struct phy_device {
    struct { struct mii_bus *bus; int addr; } mdio;
    unsigned link, phy_id;
    int speed, duplex, mdix, mdix_ctrl;
    struct qca808x_priv *priv;
};
struct at803x_ss_mask { unsigned speed_mask, speed_shift; };
static bool board=true;
static int vendor_status, function_control, vendor_reads, sfc_reads;
static int fifo_value, fifo_written, read_count, write_count, write_error, log_count;
static bool of_machine_is_compatible(const char *s)
{ assert(!strcmp(s,"acer,wave7")); return board; }
static void phydev_info(struct phy_device *p,const char *fmt,...)
{ assert(p && strstr(fmt,"fifo-instant")); ++log_count; }
static int phy_read(struct phy_device *p,int reg)
{ assert(p); if(reg==17){++vendor_reads;return vendor_status;} assert(reg==16);++sfc_reads;return function_control; }
static struct mutex *lock(struct mutex *m) { assert(!m->held);m->held=true;return m; }
static void unlock(struct mutex **m) { assert((*m)->held);(*m)->held=false; }
#define guard(mutex) __attribute__((cleanup(unlock))) struct mutex *held=lock
static int expected_addr=25;
static int __mdiobus_c45_read(struct mii_bus *b,int a,int d,int r)
{ assert(b->mdio_lock.held && a==expected_addr && d==1 && r==0x9072);++read_count;return fifo_value; }
static int __mdiobus_c45_write(struct mii_bus *b,int a,int d,int r,int v)
{ assert(b->mdio_lock.held && a==expected_addr && d==1 && r==0x9072);++write_count;fifo_written=v;return write_error; }
""" + defines + "\n" + specific + "\n" + helper + r"""
static int poll(struct phy_device *phydev)
{
    struct qca808x_priv *priv=phydev->priv;
    struct at803x_ss_mask mask={QCA808X_SS_SPEED_MASK,7};
    int ret=at803x_read_specific_status(phydev,mask);
    if(ret<0)return ret;
""" + block + r"""
    return 0;
}
static void clear(void)
{ vendor_reads=sfc_reads=read_count=write_count=log_count=0; }
int main(void)
{
    struct mii_bus bus={0};
    struct qca808x_priv priv={0};
    struct phy_device p={.mdio={&bus,24},.phy_id=QCA8081_PHY_ID,.priv=&priv};
    /* Every vendor status, independently of phylib's link bit.
     * All FIFO register values are exercised too, in a separate loop. */
    for(int link=0;link<2;link++) {
        p.link=link; fifo_value=0x8544;
        for(int ss=0;ss<65536;ss++) {
            vendor_status=ss; clear();
            int ret=poll(&p);
            assert(vendor_reads==1 && sfc_reads==!!(ss&BIT(11)));
            assert(p.link==(unsigned)link && !bus.mdio_lock.held);
            if(ss==65535){assert(ret==-EIO && read_count==0 && write_count==0);continue;}
            assert(ret==0 && read_count==1 && write_count==1);
            assert(fifo_written==((fifo_value&~0x800)|((ss&0x400)?0x800:0)));
        }
    }
    for(int copper=0;copper<2;copper++){
        vendor_status=copper?0x400:0;
        for(int v=0;v<65535;v++){
            clear();fifo_value=v;
            assert(poll(&p)==0 && write_count==1 && read_count==1);
            assert(fifo_written==((v&~0x800)|(copper?0x800:0)));
        }
    }
    /* Do not change the 0491 decision on another board, PHY address or ID. */
    fifo_value=0x8544; vendor_status=0x400; p.link=0; board=false;
    clear();assert(poll(&p)==0 && fifo_written==0x8544 && log_count==0);
    board=true;p.mdio.addr=23;expected_addr=24;
    clear();assert(poll(&p)==0 && fifo_written==0x8544 && log_count==0);
    p.mdio.addr=24;expected_addr=25;p.phy_id=0x004dd180;
    clear();assert(poll(&p)==0 && read_count==0 && write_count==0);
    p.phy_id=QCA8081_PHY_ID;
    /* Fail before writing on invalid vendor status or failed SFC;
     * fail before writing for all unreadable FIFO register outcomes. */
    for(int e=-1;e>=-255;e--){
        vendor_status=e;clear();assert(poll(&p)==e && !read_count && !write_count);
        vendor_status=0x800;function_control=e;clear();assert(poll(&p)==e && !read_count && !write_count);
        function_control=0;vendor_status=0x400;fifo_value=e;clear();
        assert(poll(&p)==e && read_count==1 && !write_count && !bus.mdio_lock.held);
    }
    fifo_value=0xffff;clear();assert(poll(&p)==-EIO && read_count==1 && !write_count);
    fifo_value=0x844;write_error=-EIO;clear();assert(poll(&p)==-EIO && write_count==1 && !log_count);
    write_error=0;priv.diag_fifo_link_pair=0;
    clear();assert(poll(&p)==0 && log_count==1);
    clear();assert(poll(&p)==0 && log_count==0);
    p.link=1;clear();assert(poll(&p)==0 && log_count==1);
    puts("QCA8081_INSTANT_FIFO_PASS 131072 status cases, 131070 FIFO words, 765 read failures, scope and logging");
}
"""
env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
cc=os.environ.get("CC","/usr/bin/gcc")
cache=os.environ.get("SCCACHE","/usr/local/bin/sccache")
with tempfile.TemporaryDirectory(prefix="wave7-instant-fifo-") as tmp:
    p=Path(tmp)
    (p/"test.c").write_text(program)
    subprocess.run([cache,cc,"-std=gnu11","-Wall","-Wextra","-Werror","-O2","-c",str(p/"test.c"),"-o",str(p/"test.o")],check=True,env=env)
    subprocess.run([cc,str(p/"test.o"),"-o",str(p/"test")],check=True,env=env)
    subprocess.run([str(p/"test")],check=True,env=env)
