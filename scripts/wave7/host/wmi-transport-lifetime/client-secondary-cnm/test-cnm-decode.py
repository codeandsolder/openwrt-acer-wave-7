#!/usr/bin/env python3
"""Compile the actual CNM parser against a bounded host-side wire fixture."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def extract(text, start, end):
    a = text.index(start)
    return text[a:text.index(end, a)]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("scratch", type=Path)
    args = parser.parse_args()
    h = (args.source / "mt7925/mcu.h").read_text()
    c = (args.source / "mt7925/mcu.c").read_text()
    structs = extract(h, "struct mt7925_lab_cnm_bss {", "int mt7925_lab_cnm_get_info")
    helper = extract(h, "static inline bool\nmt7925_mcu_tlv_valid(", "#define mt7925_for_each_tlv")
    decode = extract(c, "static int\nmt7925_lab_cnm_decode(", "int mt7925_lab_cnm_get_info")
    fixture = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define U8_MAX UINT8_MAX
#define U32_MAX UINT32_MAX
#define __packed __attribute__((packed))
#define le16_to_cpu(x) (x)
struct tlv { u16 tag, len; } __packed;
"""
    tests = r"""
static void check(void)
{
    struct mt7925_lab_cnm_info info = {};
    u8 data[4 + 8 + 12 * 2 + 8] = {};
    struct tlv *b = (void *)(data + 4);
    b->tag = 2; b->len = 8 + 12 * 2;
    data[8] = 2;
    data[12 + 4] = 40;
    data[12 + 5] = 1;
    data[12 + 7] = 2;
    data[24 + 4] = 1;
    data[24 + 5] = 0;
    struct tlv *other = (void *)(data + 4 + b->len);
    other->tag = 1; other->len = 8;
    assert(!mt7925_lab_cnm_decode(data, sizeof(data), &info));
    assert(info.count == 2 && info.bss[0].channel == 40 &&
           info.bss[0].band == 1 && info.bss[0].omac_band == 2 &&
           info.bss[1].channel == 1 && info.bss[1].band == 0);
    for (size_t i = 0; i < sizeof(data); i++)
        if (i != 4 + b->len)
            assert(mt7925_lab_cnm_decode(data, i, &info) != 0);
    data[8] = 3;
    assert(mt7925_lab_cnm_decode(data, sizeof(data), &info) == -EPROTO);
    data[8] = 2;
    other->tag = 2;
    assert(mt7925_lab_cnm_decode(data, sizeof(data), &info) == -EPROTO);
    other->tag = 1; other->len = 0;
    assert(mt7925_lab_cnm_decode(data, sizeof(data), &info) == -EPROTO);
    other->len = 3;
    assert(mt7925_lab_cnm_decode(data, sizeof(data), &info) == -EPROTO);
    other->len = 9;
    assert(mt7925_lab_cnm_decode(data, sizeof(data), &info) == -EPROTO);
    b->tag = 1; other->len = 8;
    assert(mt7925_lab_cnm_decode(data, sizeof(data), &info) == -ENODATA);
    b->tag = 2; b->len = 8; data[8] = 0;
    assert(!mt7925_lab_cnm_decode(data, 12, &info) && info.count == 0);
    /* Full count range; output allocation must accept every u8 count. */
    u8 big[4 + 8 + 12 * 255] = {};
    struct tlv *full = (void *)(big + 4);
    full->tag = 2; full->len = sizeof(big) - 4; big[8] = 255;
    big[sizeof(big) - 6] = 17;
    assert(!mt7925_lab_cnm_decode(big, sizeof(big), &info));
    assert(info.count == 255 && info.bss[254].omac == 17);
}
int main(void) { check(); puts("CNM_ACTUAL_SOURCE_FIXTURE_PASS"); }
"""
    with tempfile.TemporaryDirectory(prefix="cnm-parser-", dir=args.scratch) as d:
        path = Path(d)
        src = path / "fixture.c"
        exe = path / "fixture"
        src.write_text(fixture + structs + helper + decode + tests)
        subprocess.run(["clang", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        "-O2", str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

if __name__ == "__main__":
    main()
