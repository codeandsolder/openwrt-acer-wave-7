#!/usr/bin/env python3
"""Check NSSCC's actual provider indexing against the exact candidate FIT DTB."""
import argparse
import hashlib
from pathlib import Path
import re
import runpy
import struct
import tempfile

PARSER = runpy.run_path(str(Path(__file__).resolve().parent.parent / "verify-fit.py"))
PROPERTIES = PARSER["properties"]
FIT_SHA = "c289598628e75f7a603ec127dbb5cbd1fdcf6128ba15cea6c4fe9b0aa0232b8e"
def cells(x):
    assert len(x) % 4 == 0
    return struct.unpack(f">{len(x)//4}I", x)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kernel", type=Path)
    p.add_argument("fit", type=Path)
    p.add_argument("--expect", choices=("correct", "swapped"), required=True)
    args = p.parse_args()
    k = args.kernel
    assert hashlib.sha256(args.fit.read_bytes()).hexdigest() == FIT_SHA
    _, fit = PROPERTIES(args.fit)
    PARSER["check_hashes"](fit)
    dtb = fit["/images/fdt-1", "data"]
    with tempfile.TemporaryDirectory(prefix="wave7-clock-dtb-") as tmp:
        f = Path(tmp) / "board.dtb"
        f.write_bytes(dtb)
        nodes, props = PROPERTIES(f)
    print("FIT DTB SHA256",hashlib.sha256(dtb).hexdigest())
    nss = "/soc@0/clock-controller@39b00000"
    phandles = {cells(props[n, "phandle"])[0]:n for n in nodes if (n,"phandle") in props}
    raw = cells(props[nss,"clocks"])
    clks = []
    i = 0
    while i < len(raw):
        node = phandles[raw[i]]
        count, = cells(props[node,"#clock-cells"])
        assert i + count < len(raw)
        clks.append((node,raw[i+1:i+1+count]))
        i += 1 + count
    names = props[nss,"clock-names"].decode().rstrip("\0").split("\0")
    assert len(names) == len(clks)
    header = (k/"include/dt-bindings/net/qcom,ipq9574-pcs.h").read_text()
    pcs_idx = {d:int(re.search(rf"^#define PCS_{d.upper()}_CLK\s+(\d+)$",header,re.M)[1]) for d in ("rx","tx")}
    driver = (k/"drivers/clk/qcom/nsscc-ipq5332.c").read_text()
    enum = re.search(r"enum\s*\{\s*(DT_CMN_PLL_NSS_CLK_200M,.*?)\};",driver,re.S)[1]
    inputs = [v.strip() for v in enum.split(",") if v.strip()]
    assert len(inputs)==8 and len(set(inputs))==8
    for port in (1,2):
        inst=port-1
        parent_map=re.search(rf"static const struct parent_map nss_cc_parent_map_{port}\[\] = \{{(.*?)\}};",driver,re.S)[1]
        parent_data=re.search(rf"static const struct clk_parent_data nss_cc_parent_data_{port}\[\] = \{{(.*?)\}};",driver,re.S)[1]
        selectors=re.findall(r"\{\s*(P_\w+),\s*(\d+)\s*\}",parent_map)
        indices=re.findall(r"\.index = (DT_\w+)",parent_data)
        assert len(selectors)==len(indices)
        for direction, selector in (("rx",3),("tx",4)):
            name=f"UNIPHY{inst}_NSS_{direction.upper()}_CLK"
            matches=[i for i,(src,cfg) in enumerate(selectors) if src=="P_"+name and int(cfg)==selector]
            assert len(matches)==1
            index=inputs.index(indices[matches[0]])
            node,spec=clks[index]
            assert node==f"/soc@0/ethernet-pcs@{0x7a00000+0x10000*inst:x}" and len(spec)==1
            expected=direction if args.expect=="correct" else ("rx" if direction=="tx" else "tx")
            assert names[index]==f"uniphy{inst}_{expected}" and spec==(pcs_idx[expected],),(port,direction,names[index],spec)
            print(f"port{port} {direction} selector={selector} DT_index={index} provider={names[index]} args={spec}")
    print("NSSCC_PARENT_ORDER_"+args.expect.upper()+"_PASS")
if __name__=="__main__":
    main()
