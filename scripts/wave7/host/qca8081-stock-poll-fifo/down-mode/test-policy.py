#!/usr/bin/env python3
"""Compile the real PHY, phylink and PCS policy callbacks with mocked IO."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root=Path(sys.argv[1])
phy=(root/"drivers/net/phy/qcom/qca808x.c").read_text()
pl=(root/"drivers/net/phy/phylink.c").read_text()
pcs=(root/"drivers/net/pcs/pcs-qcom-ipq9574.c").read_text()

def func(src,name):
    return re.search(r"^static (?:int|void|bool) "+name+r"\([^;]*?\)\n\{.*?^\}",src,re.M|re.S)[0]

assert "qca8081_publish_down_mode(phydev, copper_link);" in func(phy,"qca808x_read_status")
assert func(phy,"qca808x_read_status").index("if (instant) {",func(phy,"qca808x_read_status").index("qca8081_stock_fifo_level(phydev, copper_link)")) < func(phy,"qca808x_read_status").index("qca8081_publish_down_mode(phydev, copper_link);")
assert "pl->wave7_down_config_failed = false;" in func(pl,"phylink_major_config")
assert "ipq_pcs_clear_prepared(qpcs->qpcs_mii[i]);" in func(pcs,"ipq_pcs_config_mode")
functions = [
    func(phy,"qca8081_has_independent_fifo"),func(phy,"qca8081_publish_down_mode"),
    func(pl,"phylink_wave7_direct_phy"),func(pl,"phylink_resolve"),
    func(pcs,"ipq_pcs_wave7_down_mode"),func(pcs,"ipq_pcs_clear_prepared"),
    func(pcs,"ipq_pcs_config_sgmii"),func(pcs,"ipq_pcs_config_2500basex"),
    func(pcs,"ipq_pcs_link_up_config_sgmii"),func(pcs,"ipq_pcs_link_up_config_2500basex"),
    func(pcs,"ipq_pcs_enable"),func(pcs,"ipq_pcs_disable"),
    func(pcs,"ipq_pcs_config"),func(pcs,"ipq_pcs_link_up"),
]
# Forward declarations let the IO boundary implement mode-reset invalidation.
fixture=Path(__file__).with_name("fixture.c").read_text()
assert fixture.count("/* EXTRACTED KERNEL FUNCTIONS */")==1
code=fixture.replace("/* EXTRACTED KERNEL FUNCTIONS */","\n".join(functions))
with tempfile.TemporaryDirectory(prefix="wave7-down-mode-test-") as t:
    p=Path(t); (p/"test.c").write_text(code)
    env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
    subprocess.run(["sccache","gcc","-std=gnu11","-Wall","-Wextra","-Werror",
                    "-Wno-unused-parameter","-O2","-c",str(p/"test.c"),"-o",str(p/"test.o")],check=True,env=env)
    subprocess.run(["gcc",str(p/"test.o"),"-o",str(p/"test")],check=True)
    subprocess.run([str(p/"test")],check=True)
