#!/usr/bin/env python3
"""Compile actual PCS selection, configuration, calibration and link-up code against mocked IO."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

pcs=(Path(sys.argv[1])/"drivers/net/pcs/pcs-qcom-ipq9574.c").read_text()

def func(name):
    return re.search(r"^static (?:int|void|bool) "+name+r"\([^;]*?\)\n\{.*?^\}",pcs,re.M|re.S)[0]

names=("ipq_pcs_wave7_serial_speed","ipq_pcs_config_mode","ipq_pcs_config_sgmii",
       "ipq_pcs_config_2500basex","ipq_pcs_link_up_config_sgmii",
       "ipq_pcs_link_up_config_2500basex","ipq_pcs_config","ipq_pcs_link_up")
if "static void ipq_pcs_wave7_handoff(" in pcs:
    names=("ipq_pcs_wave7_handoff",)+names
# Derive register offsets/bit definitions from the actual driver rather than restating them.
definitions=["#define HAS_HANDOFF 1\n"] if "ipq_pcs_wave7_handoff" in names else []
continuation=False
for line in pcs.splitlines(keepends=True):
    if continuation or re.match(r"^#define (PCS_(MII_|MODE_|MISC2|VCO_CAL|PLL_RESET|ANA_SW_RESET|CALIBRATION|LINK_DETECT|DETECT_LOS|CLKOUT|QP_USXG)|XPCS_)",line):
        definitions.append(line)
        continuation=line.rstrip().endswith("\\")
fixture=Path(__file__).with_name("fixture.c").read_text()
code=fixture.replace("/* DRIVER DEFINITIONS */","".join(definitions)).replace("/* DRIVER FUNCTIONS */","\n".join(map(func,names)))
with tempfile.TemporaryDirectory(prefix="wave7-serial-speed-") as work:
    p=Path(work);(p/"fixture.c").write_text(code)
    env={**os.environ,"SCCACHE_NO_AUTO_START_SERVER":"1","SCCACHE_START_SERVER":"0"}
    subprocess.run(["sccache","gcc","-std=gnu11","-Wall","-Wextra","-Werror",
                    "-Wno-unused-parameter","-O2","-c",str(p/"fixture.c"),"-o",str(p/"fixture.o")],check=True,env=env)
    subprocess.run(["gcc",str(p/"fixture.o"),"-o",str(p/"fixture")],check=True)
    subprocess.run([str(p/"fixture")],check=True)
