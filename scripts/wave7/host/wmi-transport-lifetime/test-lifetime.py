#!/usr/bin/env python3
"""Exercise the actual WMI gate and regulatory replay bodies with a deterministic shim."""
import argparse
from pathlib import Path
import re
import subprocess

def function(path, name):
    s=path.read_text()
    m=re.search(r"(?m)^(?:static )?(?:int|void) "+name+r"\(",s)
    if m is None:
        raise ValueError(name)
    start=s.index("{",m.start())
    depth=1
    end=start+1
    while depth:
        depth+=(s[end]=="{")-(s[end]=="}")
        end+=1
    return s[m.start():end]+"\n"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("ath12k_source",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    fixture=Path(__file__).with_name("fixture.c")
    text=fixture.read_text()
    wmi=("ath12k_wmi_tx_close","ath12k_wmi_tx_start",
         "ath12k_wmi_tx_publish","ath12k_wmi_tx_get_generation","ath12k_wmi_cmd_send")
    reg=("ath12k_reg_apply_country","ath12k_reg_replay_country","ath12k_reg_request_country")
    bodies="\n".join(function(a.ath12k_source/"wmi.c",n) for n in wmi)
    bodies+="\n".join(function(a.ath12k_source/"reg.c",n) for n in reg)
    assert text.count("/* EXTRACTED BODIES */")==1
    generated=a.output/"fixture-expanded.c"
    generated.write_text(text.replace("/* EXTRACTED BODIES */",bodies))
    obj=a.output/"fixture.o"
    exe=a.output/"fixture"
    subprocess.run(["/usr/local/bin/sccache","cc","-std=gnu11","-O2","-g",
                    "-Wall","-Wextra","-Werror","-c",str(generated),"-o",str(obj)],check=True)
    subprocess.run(["cc",str(obj),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

if __name__=="__main__":
    main()
