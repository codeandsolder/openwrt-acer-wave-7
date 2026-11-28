#!/usr/bin/env python3
"""Exercise the actual ath12k extended service decoder and MLO capability rule."""
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
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    hdr = (args.source / 'wmi.h').read_text()
    wmi = (args.source / 'wmi.c').read_text()
    mac = (args.source / 'mac.c').read_text()
    enum = one(hdr, r'^enum wmi_tlv_service \{.*?^\};')
    dims = '\n'.join(re.findall(
        r'^#define WMI_(?:SERVICE_SEGMENT_BM_SIZE32|AVAIL_SERVICE_BITS_IN_SIZE32) [^\n]+',
        hdr, re.M))
    assert len(dims.splitlines()) == 2
    event = one(hdr, r'^struct wmi_service_available_event \{.*?^\} __packed;')
    helpers = '\n'.join(one(wmi, rf'^static (?:void|int) {name}\(.*?^\}}')
                        for name in ('ath12k_wmi_decode_service_bitmap',
                                     'ath12k_wmi_tlv_services_parser'))
    rule = one(mac, r'^\s*eth_offload &= test_bit\(WMI_TLV_SERVICE_ETH_OFFLOAD,\s*ar->ab->wmi_ab.svc_map\);')
    register = one(mac, r'^static int ath12k_mac_hw_register\(.*?^\}')
    assert register.index('bool eth_offload = true;') < register.index('for_each_ar(ah, ar, i)')
    assert register.index(rule) < register.index('if (eth_offload) {')
    assert register.index('if (eth_offload) {') < register.index('ieee80211_hw_set(hw, SUPPORTS_RX_DECAP_OFFLOAD);')
    c = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint32_t __le32;
#define __packed __attribute__((packed))
#define BIT(n) (1UL << (n))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define WMI_TAG_SERVICE_AVAILABLE_EVENT 1
#define WMI_TAG_ARRAY_UINT32 2
#define ATH12K_DBG_WMI 0
#define ath12k_dbg(...) ((void)0)
static u32 get_unaligned_le32(const void *p)
{
    const u8 *b = p;
    return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
#define le32_to_cpu(x) get_unaligned_le32(&(x))
''' + enum + '\n' + dims + '\n' + event + r'''
#define ULONG_BITS (sizeof(unsigned long)*8)
#define NWORDS ((WMI_MAX_EXT2_SERVICE+ULONG_BITS-1)/ULONG_BITS)
struct ath12k_base {
    struct { unsigned long svc_map[NWORDS]; } wmi_ab;
};
struct ath12k { struct ath12k_base *ab; };
static void set_bit(u32 bit, unsigned long *map)
{
    assert(bit < WMI_MAX_EXT2_SERVICE);
    map[bit/ULONG_BITS] |= BIT(bit%ULONG_BITS);
}
static bool test_bit(u32 bit, const unsigned long *map)
{
    return !!(map[bit/ULONG_BITS] & BIT(bit%ULONG_BITS));
}
''' + helpers + r'''
static bool group_support(struct ath12k *radios, unsigned count)
{
    bool eth_offload = true;
    for (unsigned i=0;i<count;i++) {
        struct ath12k *ar = &radios[i];
''' + rule + r'''
    }
    return eth_offload;
}
static void put32(u8 *p, u32 x)
{
    for(unsigned i=0;i<4;i++) p[i]=(u8)(x>>(8*i));
}
static void check(const struct ath12k_base *ab, const u8 *data,
                  u32 offset, unsigned nbytes)
{
    for (u32 bit=0;bit<WMI_MAX_EXT2_SERVICE;bit++) {
        bool expected = bit == 7;
        if (bit>=offset && bit-offset<nbytes*8)
            expected |= !!(data[(bit-offset)/8] & BIT((bit-offset)%8));
        assert(test_bit(bit,ab->wmi_ab.svc_map)==expected);
    }
}
int main(void)
{
    unsigned cases=0, groups=0;
    for (u32 offset=0;offset<700;offset++) {
        u8 raw[sizeof(struct wmi_service_available_event)+1]={0};
        put32(raw+1,offset);
        for(unsigned i=5;i<sizeof(raw);i++)
            raw[i]=(u8)(i*29+offset*7);
        struct ath12k_base ab={0};
        set_bit(7,ab.wmi_ab.svc_map);
        int rc=ath12k_wmi_tlv_services_parser(&ab,1,sizeof(raw)-1,raw+1,NULL);
        assert(rc==(offset<128?-EINVAL:0));
        check(&ab,raw+5,offset,offset<128?0:sizeof(raw)-5);
        cases++;
    }
    for(unsigned len=0;len<=256;len++) {
        u8 raw[257];
        for(unsigned i=0;i<sizeof(raw);i++)raw[i]=(u8)(i*17+len*31);
        struct ath12k_base ab={0};
        set_bit(7,ab.wmi_ab.svc_map);
        int rc=ath12k_wmi_tlv_services_parser(&ab,2,len,raw+1,NULL);
        assert(rc==(len%4?-EINVAL:0));
        check(&ab,raw+1,256,len%4?0:len);
        cases++;
    }
    for(unsigned len=0;len<sizeof(struct wmi_service_available_event);len++) {
        struct ath12k_base ab={0};
        assert(ath12k_wmi_tlv_services_parser(&ab,1,len,NULL,NULL)==-EINVAL);
        assert(ath12k_wmi_tlv_services_parser(&ab,3,len,NULL,NULL)==0);
        cases+=2;
    }
    struct ath12k_base ab={0};
    u8 raw[sizeof(struct wmi_service_available_event)]={0};
    put32(raw,UINT32_MAX);
    assert(ath12k_wmi_tlv_services_parser(&ab,1,sizeof(raw),raw,NULL)==0);
    for(u32 bit=0;bit<WMI_MAX_EXT2_SERVICE;bit++)assert(!test_bit(bit,ab.wmi_ab.svc_map));
    assert(!ath12k_wmi_tlv_services_parser(&ab,2,0,NULL,NULL));
    /* Explicit segment and extension array must accumulate, including bit 461. */
    put32(raw,384);
    raw[4+(461-384)/8]=BIT((461-384)%8);
    assert(!ath12k_wmi_tlv_services_parser(&ab,1,sizeof(raw),raw,NULL));
    assert(test_bit(461,ab.wmi_ab.svc_map));
    u8 ext[32]={0};
    ext[(289-256)/8]=BIT((289-256)%8);
    assert(!ath12k_wmi_tlv_services_parser(&ab,2,sizeof(ext),ext,NULL));
    assert(test_bit(289,ab.wmi_ab.svc_map)&&test_bit(461,ab.wmi_ab.svc_map));
    for(unsigned n=1;n<=6;n++)
    for(unsigned mask=0;mask<(1U<<n);mask++){
        struct ath12k_base bases[6]={0};
        struct ath12k radios[6]={0};
        for(unsigned i=0;i<n;i++){
            radios[i].ab=&bases[i];
            if(mask&BIT(i))set_bit(461,bases[i].wmi_ab.svc_map);
        }
        assert(group_support(radios,n)==(mask==((1U<<n)-1)));
        groups++;
    }
    printf("WMI_SERVICE_CAPABILITIES_PASS parser=%u groups=%u\n",cases+4,groups);
}
'''
    path = args.output / 'wmi-service-capabilities.c'
    obj = path.with_suffix('.o')
    exe = path.with_suffix('')
    path.write_text(c)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=c11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-Wno-unused-parameter', '-c', str(path),
                    '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
