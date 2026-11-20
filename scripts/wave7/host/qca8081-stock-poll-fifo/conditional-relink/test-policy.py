#!/usr/bin/env python3
"""Compile the actual patched PCS and PPE callbacks against a mock bus.

The mode calibration, clock hardware and GMAC hardware are explicit
failure-injectable boundaries. The preservation decision, real SGMII
force/speed/adapter operations, and PPE commit/invalidation order are
taken verbatim from the supplied prepared kernel sources.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root=Path(sys.argv[1])
pcs=(root/"drivers/net/pcs/pcs-qcom-ipq9574.c").read_text()
ppe=(root/"drivers/net/ethernet/qualcomm/ppe/ppe_port.c").read_text()
def definition(source,name):
    matches=list(re.finditer(r"^(?:static )?(?:void|int|bool) "+name+r"\([^;]*?\n\{.*?^\}",source,re.M|re.S))
    assert len(matches)==1,name
    return matches[0][0]

mode=definition(pcs,"ipq_pcs_config_mode")
assert mode.index("ipq_pcs_relink_invalidate")<mode.index("ipq_pcs_disable_port_clks")
put=definition(pcs,"ipq_pcs_put")
assert put.index("ipq_pcs_relink_invalidate")<put.index("put_device")
assert "qpcs_mii->relink.enabled = false;" in put
wait=definition(ppe,"ppe_port_wait_for_phy")
assert "ppe_port->wave7_relink = ppe_port_wave7_phy" in wait
setup=definition(ppe,"ppe_port_phylink_setup")
assert setup.index("ipq_pcs_wave7_relink_enable") < setup.index("phylink_create")
types=re.search(r"^enum ipq_pcs_relink_phase \{.*?^\};\n\nstruct ipq_pcs_relink \{.*?^\};",pcs,re.M|re.S)[0]
funcs=[definition(pcs,n) for n in ("ipq_pcs_relink_invalidate","ipq_pcs_wave7_relink_invalidate","ipq_pcs_wave7_relink_enable")]
rest=[definition(pcs,n) for n in ("ipq_pcs_config_sgmii","ipq_pcs_link_up_config_sgmii","ipq_pcs_apply_link_up","ipq_pcs_link_up","ipq_pcs_wave7_mac_prepare","ipq_pcs_wave7_mac_finish","ipq_pcs_enable","ipq_pcs_disable","ipq_pcs_config")]
rest.extend(definition(ppe,n) for n in ("ppe_port_wave7_phy","ppe_port_mac_config","ppe_port_mac_link_up","ppe_port_mac_link_down"))
fixture=Path(__file__).with_name("fixture.c").read_text()
for marker,val in (("/* STRUCTS */",types),("/* INVALIDATION */","\n\n".join(funcs)),("/* CALLBACKS */","\n\n".join(rest))):
    assert fixture.count(marker)==1
    fixture=fixture.replace(marker,val)
env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
cc=os.environ.get("CC","/usr/bin/gcc")
cache=os.environ.get("SCCACHE","/usr/local/bin/sccache")
with tempfile.TemporaryDirectory(prefix="wave7-relink-") as tmp:
    p=Path(tmp)
    (p/"test.c").write_text(fixture)
    subprocess.run([cache,cc,"-std=gnu11","-O2","-Wall","-Wextra","-Werror","-Wno-unused-parameter","-c",str(p/"test.c"),"-o",str(p/"test.o")],check=True,env=env)
    subprocess.run([cc,str(p/"test.o"),"-o",str(p/"test")],check=True,env=env)
    subprocess.run([str(p/"test")],check=True,env=env)
