#!/usr/bin/env python3
"""Execute the stock DW8051 lane recovery routine against a mocked register bus.

Only opcodes reachable from the specific stock routine are implemented.
The ASIC access and delay subroutines are intercepted at their entry points;
no hardware access, cycle timing or analog behavior is simulated.
"""
import hashlib
import json
import sys
from pathlib import Path

FIRMWARE_SHA = "ec5332a6bcc1a67a2202ffbf7b44a87c8fad412a907c9f65edf7602bab0bffd9"

def trace(code, lane, mode, statuses, seed_a=0x9521, seed_b=0xa512):
    if hashlib.sha256(code).hexdigest() != FIRMWARE_SHA:
        raise ValueError("unknown firmware")
    if lane not in (0,1):
        raise ValueError("unknown lane")
    regs = [0]*8
    regs[7] = lane
    ram = bytearray(256)
    xram = bytearray(65536)
    stack = []
    pc, a, carry, dptr = 0xe, 0, 0, 0
    index = 13+2*lane
    mode_reg = (0x1d11,0x1d78)[lane]
    bus = {mode_reg:mode, 0x13a1+lane:0x00fe}
    sds = {0x3f:seed_a,0x400:seed_b}
    status_iter = iter(statuses)
    log = []
    def word(hi,lo):
        return (hi<<8)|lo
    def direct_get(addr):
        return (regs[addr] if addr<8 else dptr&255 if addr==0x82 else dptr>>8 if addr==0x83 else ram[addr])
    def direct_set(addr,value):
        nonlocal dptr
        value &= 255
        if addr<8: regs[addr]=value
        elif addr==0x82: dptr=(dptr&0xff00)|value
        elif addr==0x83: dptr=(dptr&255)|(value<<8)
        else: ram[addr]=value
    def fetch():
        nonlocal pc
        b=code[pc]; pc+=1; return b
    def branch(take):
        nonlocal pc
        delta=fetch()
        if take: pc+=delta if delta<128 else delta-256
    def add(v, c=0):
        nonlocal a, carry
        s=a+v+c; a=s&255; carry=int(s>255)
    def rte():
        nonlocal pc
        pc=stack.pop() if stack else -1
    for _ in range(10000):
        if pc==-1:
            return log
        # Stock ASIC register read helper: R6:R7 address/result;
        # R4:R5 save original address. Vendor bus completion assumed.
        if pc==0x591:
            addr=word(*regs[6:8])
            if addr==0x6602 and bus[0x6600]==0x80|index:
                saddr=bus[0x6601]
                val=next(status_iter) if saddr==0x3d else sds[saddr]
                log.append(["sds-read",saddr,val])
            else:
                val=bus[addr]
                log.append(["asic-read",addr,val])
            regs[4:6]=[addr>>8,addr&255]
            regs[6:8]=[val>>8,val&255]
            carry=0
            rte(); continue
        # Stock ASIC write helper: R6:R7 address, R4:R5 data.
        if pc==0x5d5:
            addr=word(*regs[6:8]); val=word(*regs[4:6])
            bus[addr]=val
            if addr==0x6600 and val==0xc0|index:
                saddr=bus[0x6601]
                sds[saddr]=bus[0x6602]
                log.append(["sds-write",saddr,sds[saddr]])
            elif addr not in (0x6600,0x6601,0x6602):
                log.append(["asic-write",addr,val])
            regs[2:4]=[0,addr&255]
            carry=0
            rte(); continue
        if pc==0x5b5:
            log.append(["delay-argument",word(*regs[6:8])])
            regs[2:6]=[4,0x6f,regs[6],regs[7]]
            rte(); continue
        start=pc; op=fetch()
        if op in (0x02,0x12):
            target=word(fetch(),fetch())
            if op==0x12: stack.append(pc)
            pc=target
        elif op==0x22: rte()
        elif op==0x90: dptr=word(fetch(),fetch())
        elif op==0xa3: dptr=(dptr+1)&65535
        elif op==0xe0: a=xram[dptr]
        elif op==0xf0: xram[dptr]=a
        elif op==0xe4: a=0
        elif op==0x4e: a|=regs[6]
        elif op==0x44: a|=fetch()
        elif op==0x54: a&=fetch()
        elif op==0x64: a^=fetch()
        elif op==0x24: add(fetch())
        elif op==0x34: add(fetch(),carry)
        elif 0x28<=op<=0x2f: add(regs[op-0x28])
        elif 0x38<=op<=0x3f: add(regs[op-0x38],carry)
        elif op==0x60: branch(a==0)
        elif op==0x70: branch(a!=0)
        elif op==0x80: branch(True)
        elif op==0x20:
            bit=fetch()
            if not 0xe0<=bit<=0xe7: raise ValueError("unsupported bit")
            branch(bool(a & (1<<(bit-0xe0))))
        elif 0x78<=op<=0x7f: regs[op-0x78]=fetch()
        elif 0xe8<=op<=0xef: a=regs[op-0xe8]
        elif 0xf8<=op<=0xff: regs[op-0xf8]=a
        elif 0xa8<=op<=0xaf: regs[op-0xa8]=direct_get(fetch())
        elif op==0x75:
            addr=fetch(); direct_set(addr,fetch())
        elif op==0xe5: a=direct_get(fetch())
        elif op==0x15:
            addr=fetch(); direct_set(addr,direct_get(addr)-1)
        elif op==0xc5:
            addr=fetch(); old=direct_get(addr); direct_set(addr,a); a=old
        else: raise ValueError(f"unhandled opcode {op:02x} at {start:04x}")
    raise RuntimeError("instruction budget exhausted")

def checks(code):
    expected = [
        ["asic-read",0x1d11,0xe12], ["sds-read",0x3d,0],
        ["delay-argument",500], ["sds-read",0x3d,0],
        ["asic-read",0x13a1,0xfe], ["asic-write",0x13a1,0xff],
        ["sds-read",0x3f,0x9521], ["sds-write",0x3f,0x9521],
        ["sds-read",0x400,0xa512], ["sds-write",0x400,0xa516],
        ["sds-read",0x400,0xa516], ["sds-write",0x400,0xa512],
        ["sds-read",0x3f,0x9521], ["sds-write",0x3f,0x9501],
    ]
    # The initial values intentionally contain unrelated high-byte bits,
    # and the first register already has bit 5 set.
    actual=trace(code,0,0xe12,[0,0])
    assert actual==expected, (actual,expected)
    for lane in (0,1):
        assert len(trace(code,lane,0x1f,[]))==1
        assert len(trace(code,lane,0xe12,[0x10]))==2
        assert len(trace(code,lane,0xe12,[0,0x10]))==4
        normal=trace(code,lane,0xe12,[0,0],0x9501,0xa516)
        assert [x for x in normal if x[0]=="sds-write"]==[
            ["sds-write",0x3f,0x9521],["sds-write",0x400,0xa516],
            ["sds-write",0x400,0xa512],["sds-write",0x3f,0x9501]]
    return actual

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: trace-stock-recovery.py DW8051_BIN")
    print(json.dumps(checks(Path(sys.argv[1]).read_bytes()),indent=2))
    print("STOCK_RECOVERY_TRACE_PASS",file=sys.stderr)
