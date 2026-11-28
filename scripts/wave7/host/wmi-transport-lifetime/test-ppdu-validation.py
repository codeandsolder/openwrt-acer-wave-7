#!/usr/bin/env python3
"""Exercise the actual HTT parser and PPDU count helper with synthetic TLVs."""
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
    source = (args.source / 'dp_htt.c').read_text()
    header = (args.source / 'dp_htt.h').read_text()
    declarations = '\n'.join(one(header, rf'^struct {name} \{{.*?^\}}[^\n]*;')
                             for name in ('htt_tlv', 'htt_ppdu_stats_common',
                                          'htt_ppdu_stats_user_rate',
                                          'htt_ppdu_stats_usr_cmpltn_cmn',
                                          'htt_ppdu_stats_usr_cmpltn_ack_ba_status',
                                          'htt_ppdu_user_stats', 'htt_ppdu_stats',
                                          'htt_ppdu_stats_info'))
    defines = '\n'.join(re.findall(r'^#define (?:HTT_TLV_\w+|HTT_PPDU_STATS_MAX_USERS)\s+[^\n]+', header, re.M))
    assert len(defines.splitlines()) == 3
    funcs = '\n'.join(one(source, pattern) for pattern in (
        r'^static int ath12k_get_ppdu_user_index\(.*?^\}',
        r'^static int ath12k_htt_tlv_ppdu_stats_parse\(.*?^\}',
        r'^int ath12k_dp_htt_tlv_iter\(.*?^\}',
        r'^static bool\nath12k_htt_ppdu_failed_mpdus\(.*?^\}'))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
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
#define ath12k_warn(...) ((void)0)
#define ath12k_err(...) ((void)0)
struct list_head { void *prev, *next; };
struct ath12k_base { int unused; };
''' + defines + '\n' + one(header, r'^enum htt_ppdu_stats_tag_type \{.*?^\};') + '\n' + declarations + '\n' + funcs + r'''
static size_t emit(u8 *buf, u16 tag, u16 len, const void *value)
{
    struct htt_tlv tlv = { .header = tag | ((u32)len << 12) };
    memcpy(buf, &tlv, sizeof(tlv));
    if (len)
        memcpy(buf + sizeof(tlv), value, len);
    return sizeof(tlv) + len;
}

static int reject(struct ath12k_base *ab, u16 tag, u16 len,
                  const void *ptr, void *data)
{
    int *calls = data;
    ++*calls;
    return -ERANGE;
}

int main(void)
{
    struct htt_ppdu_stats_info info = {};
    struct htt_ppdu_stats_user_rate rate = {};
    struct htt_ppdu_stats_usr_cmpltn_cmn cmpl = {};
    struct htt_ppdu_stats_usr_cmpltn_ack_ba_status ack = {};
    struct htt_ppdu_stats_common common = { .num_users = 8 };
    u8 buf[4096] = {};
    size_t n = emit(buf, HTT_PPDU_STATS_TAG_COMMON, sizeof(common), &common);
    for (unsigned i = 0; i < HTT_PPDU_STATS_MAX_USERS; ++i) {
        rate.sw_peer_id = i + 100;
        n += emit(buf+n, HTT_PPDU_STATS_TAG_USR_RATE, sizeof(rate), &rate);
    }
    for (int i = HTT_PPDU_STATS_MAX_USERS - 1; i >= 0; --i) {
        cmpl.sw_peer_id = i + 100;
        ack.sw_peer_id = i + 100;
        n += emit(buf+n, HTT_PPDU_STATS_TAG_USR_COMPLTN_COMMON, sizeof(cmpl), &cmpl);
        n += emit(buf+n, HTT_PPDU_STATS_TAG_USR_COMPLTN_ACK_BA_STATUS, sizeof(ack), &ack);
    }
    n += emit(buf+n, 4095, 0, NULL);
    assert(!ath12k_dp_htt_tlv_iter(NULL, buf, n, ath12k_htt_tlv_ppdu_stats_parse, &info));
    assert(info.ppdu_stats.common.num_users == 8);
    for (unsigned i=0; i<HTT_PPDU_STATS_MAX_USERS; ++i) {
        const struct htt_ppdu_user_stats *u = &info.ppdu_stats.user_stats[i];
        assert(u->is_valid_peer_id && u->peer_id == i+100);
        assert(u->tlv_flags == (BIT(HTT_PPDU_STATS_TAG_USR_RATE) |
               BIT(HTT_PPDU_STATS_TAG_USR_COMPLTN_COMMON) |
               BIT(HTT_PPDU_STATS_TAG_USR_COMPLTN_ACK_BA_STATUS)));
    }
    rate.sw_peer_id = 999;
    n = emit(buf, HTT_PPDU_STATS_TAG_USR_RATE, sizeof(rate), &rate);
    assert(ath12k_dp_htt_tlv_iter(NULL, buf, n, ath12k_htt_tlv_ppdu_stats_parse, &info) == -EINVAL);
    for (size_t i=1; i<n; ++i)
        assert(ath12k_dp_htt_tlv_iter(NULL, buf, i, ath12k_htt_tlv_ppdu_stats_parse, &info) == -EINVAL);
    const u16 tags[] = {HTT_PPDU_STATS_TAG_COMMON, HTT_PPDU_STATS_TAG_USR_RATE,
                        HTT_PPDU_STATS_TAG_USR_COMPLTN_COMMON,
                        HTT_PPDU_STATS_TAG_USR_COMPLTN_ACK_BA_STATUS};
    const size_t sizes[] = {sizeof(common), sizeof(rate), sizeof(cmpl), sizeof(ack)};
    unsigned malformed = 0;
    for (unsigned i=0; i<ARRAY_SIZE(tags); ++i)
        for (size_t len=0; len<sizes[i]; ++len) {
            u8 zero[256] = {};
            n=emit(buf, tags[i], len, zero);
            assert(ath12k_dp_htt_tlv_iter(NULL, buf, n, ath12k_htt_tlv_ppdu_stats_parse, &info) == -EINVAL);
            ++malformed;
        }
    n=emit(buf, 4095, 0, NULL);
    n+=emit(buf+n, 4095, 0, NULL);
    int calls=0;
    assert(ath12k_dp_htt_tlv_iter(NULL, buf, n, reject, &calls) == -ERANGE && calls == 1);
    const u16 boundaries[] = {0, 1, 32767, 32768, 65534, 65535};
    unsigned pairs = 0;
    for (unsigned tried=0; tried<=UINT16_MAX; ++tried)
        for (unsigned i=0; i<ARRAY_SIZE(boundaries); ++i) {
            cmpl.mpdu_tried = tried;
            cmpl.mpdu_success = boundaries[i];
            u16 failed = 0x1234;
            bool valid=ath12k_htt_ppdu_failed_mpdus(&cmpl, &failed);
            assert(valid == (tried >= boundaries[i]));
            assert(failed == (valid ? tried-boundaries[i] : 0x1234));
            ++pairs;
        }
    printf("PPDU_VALIDATION_PASS users=%u malformed=%u count_pairs=%u\n",
           HTT_PPDU_STATS_MAX_USERS, malformed, pairs);
}
'''
    c = args.output / 'ppdu-validation.c'
    obj = args.output / 'ppdu-validation.o'
    exe = args.output / 'ppdu-validation'
    c.write_text(code)
    subprocess.run(['/usr/local/bin/sccache', 'cc', '-std=gnu11', '-O2', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', '-Wno-unused-variable',
                    '-Wno-sign-compare', '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['cc', str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
