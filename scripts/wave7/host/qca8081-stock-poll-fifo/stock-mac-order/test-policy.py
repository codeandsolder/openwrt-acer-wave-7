#!/usr/bin/env python3
"""Execute the real 0493 GMAC callbacks using fault-injected register writes."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root=Path(sys.argv[1])/"drivers/net/ethernet/qualcomm/ppe"
ppe=(root/"ppe_port.c").read_text()
edma=(root/"edma_port.c").read_text()
def definition(source,name):
    matches=list(re.finditer(r"^(?:static )?(?:void|int|bool) "+name+r"\([^;]*?\n\{.*?^\}",source,re.M|re.S))
    assert len(matches)==1,name
    return matches[0][0]

funcs=[definition(ppe,n) for n in (
    "ppe_port_wave7_phy","ppe_port_wave7_gmac_quiesce","ppe_port_mac_config",
    "ppe_port_gmac_link_up","ppe_port_mac_link_up","ppe_port_gmac_link_down",
    "ppe_port_mac_link_down","ppe_port_phylink_destroy")]
funcs.append(definition(edma,"edma_port_close"))
source=Path(__file__).with_name("fixture.c").read_text()
assert source.count("/* CALLBACKS */")==1
source=source.replace("/* CALLBACKS */","\n\n".join(funcs))
env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
cc=os.environ.get("CC","/usr/bin/gcc")
cache=os.environ.get("SCCACHE","/usr/local/bin/sccache")
with tempfile.TemporaryDirectory(prefix="wave7-mac-order-") as tmp:
    p=Path(tmp)
    (p/"test.c").write_text(source)
    subprocess.run([cache,cc,"-std=gnu11","-O2","-Wall","-Wextra","-Werror",
                    "-Wno-unused-parameter","-c",str(p/"test.c"),"-o",str(p/"test.o")],
                   check=True,env=env)
    subprocess.run([cc,str(p/"test.o"),"-o",str(p/"test")],check=True,env=env)
    subprocess.run([str(p/"test")],check=True,env=env)
