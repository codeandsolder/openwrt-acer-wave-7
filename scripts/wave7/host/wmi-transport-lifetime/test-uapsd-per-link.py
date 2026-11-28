#!/usr/bin/env python3
"""Check the real STA U-APSD function against vendor AC ordering."""
import argparse
from pathlib import Path
import re
import subprocess


def one(text, pattern):
    matches = re.findall(pattern, text, re.M | re.S)
    if len(matches) != 1:
        raise ValueError(f'expected one match for {pattern}, got {len(matches)}')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    mac = (args.source / 'mac.c').read_text()
    core = (args.source / 'core.h').read_text()
    wmi = (args.tree / 'drivers/net/wireless/ath/ath12k/wmi.h').read_text()
    mac80211 = (args.tree / 'include/net/mac80211.h').read_text()
    assert 'u32 uapsd;' in one(core, r'^struct ath12k_link_vif \{.*?^\};')
    assert 'uapsd' not in one(core, r'^struct ath12k_vif \{.*?^\};')
    decl = '\n'.join((
        one(mac80211, r'^enum ieee80211_ac_numbers \{.*?^\};'),
        *(one(wmi, rf'^enum {name} \{{.*?^\}};') for name in (
            'wmi_sta_ps_param_uapsd', 'wmi_sta_powersave_param',
            'wmi_sta_ps_param_rx_wake_policy', 'wmi_vdev_type')),
    ))
    func = one(mac, r'^static int ath12k_conf_tx_uapsd\(.*?^\}')
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint16_t u16;
typedef uint32_t u32;
#define ath12k_warn(ab, ...) ((void)(ab), ++warnings)
''' + decl + r'''
struct ath12k_base { int unused; };
struct ath12k { struct ath12k_base *ab; };
struct ath12k_vif { enum wmi_vdev_type vdev_type; };
struct ath12k_link_vif {
    struct ath12k *ar;
    struct ath12k_vif *ahvif;
    u32 vdev_id, uapsd;
};
static unsigned calls, warnings, fail_at;
static u32 vdevs[2], params[2], values[2];
static int ath12k_wmi_set_sta_ps_param(struct ath12k *ar, u32 vdev,
                                      u32 param, u32 value)
{
    assert(ar && calls < 2);
    vdevs[calls]=vdev;
    params[calls]=param;
    values[calls++]=value;
    return fail_at==calls ? -EIO : 0;
}
''' + func + r'''
/* WMI wire bit order is BE, BK, VI, VO, independently of mac80211 AC enum. */
static const unsigned wire_masks[] = {0xc0,0x30,0x03,0x0c};
static unsigned expand(unsigned mask)
{
    unsigned v=0;
    for(unsigned ac=0;ac<4;++ac)
        if(mask&(1u<<ac)) v|=wire_masks[ac];
    return v;
}
int main(void)
{
    struct ath12k ar={0};
    struct ath12k_vif vif={.vdev_type=WMI_VDEV_TYPE_STA};
    unsigned cases=0;
    for(unsigned a=0;a<16;++a)
    for(unsigned b=0;b<16;++b)
    for(unsigned link=0;link<2;++link)
    for(unsigned ac=0;ac<4;++ac)
    for(unsigned en=0;en<2;++en)
    for(unsigned fail=0;fail<3;++fail) {
        struct ath12k_link_vif links[2]={
            {.ar=&ar,.ahvif=&vif,.vdev_id=23,.uapsd=expand(a)},
            {.ar=&ar,.ahvif=&vif,.vdev_id=47,.uapsd=expand(b)},
        };
        unsigned unchanged=links[1-link].uapsd;
        unsigned expected=links[link].uapsd;
        if(en) expected|=wire_masks[ac];
        else expected&=~wire_masks[ac];
        calls=warnings=0;
        fail_at=fail;
        int ret=ath12k_conf_tx_uapsd(&links[link],ac,en);
        assert(ret==(fail?-EIO:0));
        assert(calls==(fail==1?1:2) && warnings==!!fail);
        assert(vdevs[0]==links[link].vdev_id);
        assert(params[0]==WMI_STA_PS_PARAM_UAPSD && values[0]==expected);
        assert(links[link].uapsd==expected && links[1-link].uapsd==unchanged);
        if(calls==2) {
            assert(vdevs[1]==links[link].vdev_id);
            assert(params[1]==WMI_STA_PS_PARAM_RX_WAKE_POLICY);
            assert(values[1]==(expected?WMI_STA_PS_RX_WAKE_POLICY_POLL_UAPSD:
                                         WMI_STA_PS_RX_WAKE_POLICY_WAKE));
        }
        calls=warnings=fail_at=0;
        unsigned other_expected=unchanged|wire_masks[ac];
        assert(!ath12k_conf_tx_uapsd(&links[1-link],ac,true));
        assert(values[0]==other_expected && links[link].uapsd==expected);
        ++cases;
    }
    struct ath12k_link_vif link={.ar=&ar,.ahvif=&vif,.vdev_id=3,.uapsd=0x30};
    for(unsigned ac=4;ac<65536;++ac) {
        calls=warnings=fail_at=0;
        assert(ath12k_conf_tx_uapsd(&link,ac,true)==-EINVAL);
        assert(!calls && !warnings && link.uapsd==0x30);
    }
    vif.vdev_type=WMI_VDEV_TYPE_AP;
    for(unsigned ac=0;ac<4;++ac) {
        calls=warnings=fail_at=0;
        assert(!ath12k_conf_tx_uapsd(&link,ac,true));
        assert(!calls && !warnings && link.uapsd==0x30);
    }
    printf("UAPSD_PER_LINK_PASS transitions=%u invalid_ac=65532\n",cases);
}
'''
    c = args.output / 'uapsd.c'
    obj = args.output / 'uapsd.o'
    exe = args.output / 'uapsd'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
