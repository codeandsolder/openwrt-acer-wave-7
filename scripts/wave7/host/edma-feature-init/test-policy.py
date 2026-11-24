#!/usr/bin/env python3
"""Verify placement and feature lifecycle in the actual patched C."""
from pathlib import Path
import re
import sys

source = Path(sys.argv[1]) / "drivers/net/ethernet/qualcomm/ppe/edma_port.c"
s = source.read_text()
start = s.index("static int edma_port_open(")
end = s.index("static int edma_port_close(", start)
opening = s[start:end]
assert not re.search(r"netdev->(?:features|hw_features|vlan_features|wanted_features)\s*[|&^]?=", opening)
start = s.index("int edma_port_prepare(")
end = s.index("int edma_port_register(", start)
prepare = s[start:end]
statements = re.findall(r"netdev->(features|hw_features|vlan_features|wanted_features)\s*\|=\s*EDMA_NETDEV_FEATURES;", prepare)
assert statements == ["features", "hw_features", "vlan_features"]
assert prepare.index("netdev->vlan_features |= EDMA_NETDEV_FEATURES;") < prepare.index("ppe_port_phylink_setup(")
register = s[end:s.index("\n}", end)]
assert "register_netdev(netdev)" in register
assert s.count("netdev->wanted_features |= EDMA_NETDEV_FEATURES;") == 0
print("EDMA_FEATURE_INIT_LIFECYCLE_PASS")
