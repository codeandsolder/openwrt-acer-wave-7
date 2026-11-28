#!/usr/bin/env python3
"""Exercise the actual HTT rate decoder against both RU wire encodings."""
import argparse
from pathlib import Path
import re
import subprocess


def one(text, pattern):
    matches = re.findall(pattern, text, re.M | re.S)
    if len(matches) != 1:
        raise ValueError(f'expected one match for {pattern}, got {len(matches)}')
    return matches[0]


def enums(text, *names):
    return '\n'.join(one(text, rf'^enum {name} \{{.*?^\}};') for name in names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='patched ath12k C and HTT header')
    parser.add_argument('tree', type=Path, help='complete source tree for unchanged headers')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.tree / 'drivers/net/wireless/ath/ath12k'
    src = (args.source / 'dp_htt.c').read_text()
    htt = (args.source / 'dp_htt.h').read_text()
    hal = (root / 'hal.h').read_text()
    mac = (root / 'mac.c').read_text()
    hw = (root / 'hw.h').read_text()
    cfg = (args.tree / 'include/net/cfg80211.h').read_text()
    nl = (args.tree / 'include/uapi/linux/nl80211.h').read_text()
    # Extract full macro lines including continuation lines.
    def macro_block(text, pattern):
        lines = text.splitlines()
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r'^#define (?:' + pattern + r')(?=[\s(])', line):
                result.append(line)
                while lines[i].endswith('\\'):
                    i += 1
                    result.append(lines[i])
            i += 1
        return '\n'.join(result)

    decl = '\n'.join((
        enums(htt, 'HTT_PPDU_STATS_BW', 'htt_ppdu_stats_gi',
              'HTT_PPDU_STATS_PPDU_TYPE', 'htt_ppdu_stats_ru_format',
              'htt_ppdu_stats_ru_size'),
        enums((root / 'wmi.h').read_text(), 'wmi_rate_preamble'),
        enums(hal, 'rx_msdu_start_sgi'),
        enums(hw, 'ath12k_hw_rate_cck', 'ath12k_hw_rate_ofdm'),
        enums(cfg, 'rate_info_bw', 'rate_info_flags'),
        enums(nl, 'nl80211_he_ru_alloc', 'nl80211_eht_ru_alloc',
              'nl80211_he_gi', 'nl80211_eht_gi'),
        macro_block(htt, r'HTT_PPDU_STATS_USER_RATE_\w+|HTT_USR_RATE_\w+'),
        macro_block(hal, r'RU_\w+'),
        macro_block((root / 'core.h').read_text(), r'ATH12K_(?:HT|VHT|HE|EHT)_MCS_MAX'),
        macro_block(hw, 'ATH12K_HW_RATECODE_CCK_SHORT_PREAM_MASK'),
        macro_block(mac, r'ATH12K_MAC_RATE_\w+|ATH12K_MAC_FIRST_OFDM_RATE_IDX|ath12k_g_rates_size'),
        one(htt, r'^struct htt_ppdu_stats_user_rate \{.*?^\} __packed;'),
        one(cfg, r'^struct rate_info \{.*?^\};'),
        one(mac, r'^static struct ieee80211_rate ath12k_legacy_rates\[\] = \{.*?^\};'),
        one(mac, r'^int ath12k_mac_hw_ratecode_to_legacy_rate\(.*?^\}'),
        one((root / 'dp_rx.h').read_text(), r'^static inline u32 ath12k_he_gi_to_nl80211_he_gi\(.*?^\}'),
        one(mac, r'^enum nl80211_eht_gi ath12k_mac_eht_gi_to_nl80211_eht_gi\(.*?^\}'),
        one(src, r'^static const struct \{\n\tu16 span;.*?^\};'),
        one(src, r'^static bool\nath12k_htt_ppdu_decode_ru\(.*?^\}'),
        one(src, r'^static bool ath12k_htt_ppdu_decode_bw\(.*?^\}'),
        one(src, r'^static bool\nath12k_htt_ppdu_decode_rate\(.*?^\}'),
    ))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8;
typedef int8_t s8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint16_t __le16;
typedef uint32_t __le32;
#define __packed __attribute__((packed))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define BIT(n) (UINT32_C(1) << (n))
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
#define le32_get_bits(v,m) (((v)&(m)) >> __builtin_ctz(m))
#define le16_to_cpu(v) (v)
#define IEEE80211_RATE_MANDATORY_A 1
#define IEEE80211_RATE_SHORT_PREAMBLE 2
struct ieee80211_rate { int bitrate, hw_value, hw_value_short, flags; };
''' + decl + r'''
static struct htt_ppdu_stats_user_rate make_rate(unsigned preamble, unsigned bw,
    unsigned nss, unsigned mcs, unsigned gi, unsigned ppdu, unsigned format,
    unsigned low, unsigned high)
{
    return (struct htt_ppdu_stats_user_rate){
        .rate_flags=(preamble<<20)|(bw<<8)|(nss<<12)|(mcs<<16)|(gi<<24),
        .info0=format<<12, .info1=ppdu<<1, .ru_end=low, .ru_start=high,
    };
}

/* Independent wire-format oracle, from the vendor ABI and nl80211 enums. */
static const unsigned spans[] = {1,2,3,4,5,9,18,27,37,55,64,74,92,111,129,148};
static const int he[] = {0,1,-1,2,-1,3,4,-1,5,-1,-1,6,-1,-1,-1,-1};
static const int width[] = {-1,-1,RATE_INFO_BW_20,RATE_INFO_BW_40,
    RATE_INFO_BW_80,RATE_INFO_BW_160,-1,-1,RATE_INFO_BW_320,
    -1,-1,-1,-1,-1,-1,-1};

int main(void)
{
    unsigned cases=0, rus=0;
    for(unsigned pre=0;pre<16;++pre)
    for(unsigned bw=0;bw<16;++bw)
    for(unsigned nss=0;nss<16;++nss)
    for(unsigned mcs=0;mcs<16;++mcs)
    for(unsigned gi=0;gi<16;++gi) {
        struct htt_ppdu_stats_user_rate u=make_rate(pre,bw,nss,mcs,gi,0,0,0,0);
        struct rate_info r={};
        bool valid=false;
        if(width[bw]>=0) {
            switch(pre) {
            case 0: valid=mcs<=7; break;
            case 1: valid=mcs<=7; break;
            case 2: valid=(bw==2 || bw==3) && nss<4 && mcs<=7 && gi<=1; break;
            case 3: valid=bw!=8 && nss<8 && mcs<=9 && gi<=1; break;
            case 4: valid=bw!=8 && nss<8 && mcs<=11 && (gi==0 || gi==2 || gi==3); break;
            case 5: valid=nss<8 && (gi==0 || gi==2 || gi==3); break;
            }
        }
        assert(ath12k_htt_ppdu_decode_rate(&u,&r)==valid);
        if(valid) {
            assert(r.bw==width[bw]);
            if(pre>=2) {
                assert(r.nss==nss+1);
                assert(r.mcs==mcs+(pre==2?8*nss:0));
            }
            if(pre==2 || pre==3)
                assert(!!(r.flags&RATE_INFO_FLAGS_SHORT_GI)==(gi==1));
            if(pre==4) assert(r.he_gi==(gi?gi-1:0));
            if(pre==5) assert(r.eht_gi==(gi?gi-1:0));
        }
        ++cases;
    }
    for(unsigned pre=0;pre<16;++pre)
    for(unsigned bw=0;bw<16;++bw)
    for(unsigned fmt=0;fmt<16;++fmt)
    for(unsigned x=0;x<170;++x) {
        /* fmt0: RU index span, fmt1: index and size. */
        unsigned low=fmt==0?100+x:17;
        unsigned high=fmt==0?100:x;
        int idx=-1;
        if(fmt==0) {
            for(unsigned k=0;k<ARRAY_SIZE(spans);++k)
                if(spans[k]==x+1) idx=k;
        } else if(fmt==1 && x<ARRAY_SIZE(spans)) idx=x;
        bool valid=idx>=0 && (pre==5 || (pre==4 && he[idx]>=0));
        struct htt_ppdu_stats_user_rate u=make_rate(pre,bw,1,7,0,2,fmt,low,high);
        struct rate_info r={};
        assert(ath12k_htt_ppdu_decode_rate(&u,&r)==valid);
        if(valid) {
            assert(r.bw==(pre==5?RATE_INFO_BW_EHT_RU:RATE_INFO_BW_HE_RU));
            assert(pre==5?r.eht_ru_alloc==idx:r.he_ru_alloc==he[idx]);
        }
        ++rus;
    }
    for(unsigned pre=4;pre<=5;++pre) {
        struct rate_info r={};
        struct htt_ppdu_stats_user_rate u=make_rate(pre,4,1,7,0,2,0,0,1);
        assert(!ath12k_htt_ppdu_decode_rate(&u,&r));
        u=make_rate(pre,4,1,7,0,2,0,65535,0);
        assert(!ath12k_htt_ppdu_decode_rate(&u,&r));
        u=make_rate(pre,4,1,7,0,3,1,0,65535);
        assert(!ath12k_htt_ppdu_decode_rate(&u,&r));
    }
    printf("PPDU_RATE_ABI_PASS fixed_rate=%u ru=%u\n",cases,rus);
}
'''
    c = args.output / 'ppdu-rate-abi.c'
    obj = args.output / 'ppdu-rate-abi.o'
    exe = args.output / 'ppdu-rate-abi'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall', '-Wextra',
                    '-Werror', '-Wno-sign-compare', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
