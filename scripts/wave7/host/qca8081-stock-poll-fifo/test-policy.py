#!/usr/bin/env python3
"""Compile the actual experimental C helper with a locked mock MDIO bus."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
helper = re.search(r"^static int qca8081_stock_fifo_level\(.*?^\}", source, re.M | re.S)[0]
# Require its single call site before interface selection and no second
# owner in the notify callback. This is an ordering experiment.
status = re.search(r"^static int qca808x_read_status\(.*?^\}", source, re.M | re.S)[0]
assert status.index("at803x_read_specific_status") < status.index("qca8081_stock_fifo_level") < status.index("if (phydev->link)")
assert "if (phydev->phy_id == QCA8081_PHY_ID)" in status
notify = re.search(r"^static void qca808x_link_change_notify\(.*?^\}", source, re.M | re.S)[0]
assert "mdiobus_c45_" not in notify and "fifo_action=stock_status_poll" in notify
program = r"""
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#define MDIO_MMD_PMAPMD 1
#define QCA8081_PHY_SERDES_MMD1_FIFO_CTRL 0x9072
#define QCA8081_PHY_FIFO_RSTN (1 << 11)
struct mutex { bool held; };
struct mii_bus { struct mutex mdio_lock; };
struct phy_device { struct { struct mii_bus *bus; int addr; } mdio; bool link; };
static struct mutex *lock(struct mutex *m) { assert(!m->held); m->held=true; return m; }
static void unlock(struct mutex **m) { assert((*m)->held); (*m)->held=false; }
#define guard(mutex) __attribute__((cleanup(unlock))) struct mutex *held=lock
static int read_value, write_value, write_error, reads, writes;
static int __mdiobus_c45_read(struct mii_bus *b,int a,int d,int r)
{
    assert(b->mdio_lock.held && a==25 && d==1 && r==0x9072);
    ++reads;
    return read_value;
}
static int __mdiobus_c45_write(struct mii_bus *b,int a,int d,int r,int v)
{
    assert(b->mdio_lock.held && a==25 && d==1 && r==0x9072);
    ++writes;
    write_value=v;
    return write_error;
}
""" + helper + r"""
int main(void)
{
    struct mii_bus bus={0};
    struct phy_device p={.mdio={.bus=&bus,.addr=24}};
    for (int link=0;link<2;link++) {
        p.link=link;
        for (int value=0;value<65535;value++) {
            read_value=value; reads=writes=0;
            assert(qca8081_stock_fifo_level(&p)==0);
            assert(reads==1 && writes==1 && !bus.mdio_lock.held);
            assert(write_value==((value&~0x800)|(link?0x800:0)));
        }
    }
    for (int error=-1;error>=-255;error--) {
        read_value=error; reads=writes=0;
        assert(qca8081_stock_fifo_level(&p)==error);
        assert(reads==1 && writes==0 && !bus.mdio_lock.held);
    }
    read_value=0xffff; reads=writes=0;
    assert(qca8081_stock_fifo_level(&p)==-EIO);
    assert(reads==1 && writes==0 && !bus.mdio_lock.held);
    read_value=0x0844; write_error=-EIO; reads=writes=0;
    assert(qca8081_stock_fifo_level(&p)==-EIO);
    assert(reads==1 && writes==1 && !bus.mdio_lock.held);
    puts("QCA8081_STOCK_FIFO_LEVEL_PASS 131070 values, 256 read failures, write failure");
}
"""
env = {**os.environ, "SCCACHE_NO_AUTO_START_SERVER":"1", "SCCACHE_START_SERVER":"0"}
cc = os.environ.get("CC","/usr/bin/gcc")
cache = os.environ.get("SCCACHE","/usr/local/bin/sccache")
with tempfile.TemporaryDirectory(prefix="wave7-stock-fifo-test-") as tmp:
    p=Path(tmp)
    (p/"test.c").write_text(program)
    subprocess.run([cache,cc,"-std=gnu11","-Wall","-Wextra","-Werror","-O2","-c",str(p/"test.c"),"-o",str(p/"test.o")],check=True,env=env)
    subprocess.run([cc,str(p/"test.o"),"-o",str(p/"test")],check=True,env=env)
    subprocess.run([str(p/"test")],check=True,env=env)
