#!/usr/bin/env python3
"""Exercise actual EDMA lifecycle and per-packet feature policy."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

kernel = Path(sys.argv[1])
source = kernel / "drivers/net/ethernet/qualcomm/ppe/edma_port.c"
s = source.read_text()
opening = s[s.index("static int edma_port_open("):s.index("static int edma_port_close(")]
assert not re.search(r"netdev->(?:features|hw_features|vlan_features|wanted_features)\s*[|&^]?=", opening)
start = s.index("int edma_port_prepare(")
end = s.index("int edma_port_register(", start)
prepare = s[start:end]
statements = re.findall(r"netdev->(features|hw_features|vlan_features|wanted_features)\s*\|=\s*EDMA_NETDEV_FEATURES;", prepare)
assert statements == ["features", "hw_features", "vlan_features"]
assert prepare.index("netdev->vlan_features |= EDMA_NETDEV_FEATURES;") < prepare.index("ppe_port_phylink_setup(")
assert "register_netdev(netdev)" in s[end:s.index("\n}", end)]
assert "netdev->wanted_features |= EDMA_NETDEV_FEATURES;" not in s

def function(text, name):
    return re.search(r"^static(?: inline)? [^\n]*\b"+name+r"\([^;]*?\)\n\{.*?^\}", text, re.M|re.S)[0]

features = (kernel/"include/linux/netdev_features.h").read_text()
enum = features[features.index("enum {"):features.index("/* Finds the next feature")]
masks = features[features.index("#define NETIF_F_GSO_MASK"):features.index("#define NETIF_F_ALL_TSO")]
vlan = function((kernel/"include/linux/if_vlan.h").read_text(), "vlan_features_check")
dsa = function((kernel/"include/net/dsa.h").read_text(), "netdev_uses_dsa")
policy = function(s, "edma_port_feature_check")
fixture = Path(__file__).with_name("feature-check-fixture.c").read_text()
code = fixture.replace("/* FEATURE DEFINITIONS */", enum+masks).replace("/* ACTUAL FUNCTIONS */", "\n".join((vlan,dsa,policy)))
with tempfile.TemporaryDirectory(prefix="wave7-edma-policy-") as work:
    p=Path(work)
    (p/"fixture.c").write_text(code)
    env={**os.environ, "SCCACHE_NO_AUTO_START_SERVER":"1", "SCCACHE_START_SERVER":"0"}
    subprocess.run(["sccache","gcc","-std=gnu11","-Wall","-Wextra","-Werror",
                    "-O2","-c",str(p/"fixture.c"),"-o",str(p/"fixture.o")],check=True,env=env)
    subprocess.run(["gcc",str(p/"fixture.o"),"-o",str(p/"fixture")],check=True)
    subprocess.run([str(p/"fixture")],check=True)
print("EDMA_FEATURE_INIT_LIFECYCLE_PASS")
