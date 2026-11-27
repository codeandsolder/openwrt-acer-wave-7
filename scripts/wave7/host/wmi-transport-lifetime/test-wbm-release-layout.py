#!/usr/bin/env python3
"""Compile the actual WBM map declarations and MSI lookup against host shims."""
import argparse
from pathlib import Path
import re
import subprocess


def one(text, pattern):
    m = re.search(pattern, text, re.M | re.S)
    if not m:
        raise ValueError(f'not found: {pattern}')
    return m.group(0)


def declaration(text, name):
    return one(text, rf'^const struct [^;]*?\b{name}\b[^;]*?= \{{.*?^\}};')


def function(text, name):
    return one(text, rf'^static (?:inline )?\w+(?: \w+)*\s+{name}\(.*?^\}}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    root = a.source
    a.output.mkdir(parents=True, exist_ok=True)
    hal = (root / 'hal.h').read_text()
    hw = (root / 'hw.h').read_text()
    dp = (root / 'dp.c').read_text()
    qcn = (root / 'wifi7/hal_qcn9274.c').read_text()
    wcn = (root / 'wifi7/hal_wcn7850.c').read_text()
    hal7 = (root / 'wifi7/hal.h').read_text()
    hal_init = (root / 'wifi7/hal.c').read_text()
    hw7 = (root / 'wifi7/hw.c').read_text()
    pieces = ['''#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BIT(n) (1UL << (n))
#define BITS_PER_LONG (sizeof(unsigned long) * 8)
#define DP_TCL_NUM_RING_MAX 4
#define ATH12K_EXT_IRQ_GRP_NUM_MAX 12
''']
    for tag in ('hal_ring_type','hal_rx_buf_return_buf_manager'):
        pieces.append(one(hal,rf'^enum {tag} \{{.*?^\}};'))
    for tag in ('ath12k_hw_hal_params','ath12k_hal_tcl_to_wbm_rbm_map'):
        pieces.append(one(hal,rf'^struct {tag}\s*\{{.*?^\}};'))
    pieces.append(one(hw,r'^struct ath12k_hw_ring_mask \{.*?^\};'))
    pieces.append(one(hal,r'^static inline enum hal_rx_buf_return_buf_manager\s+ath12k_hal_rx_rel_rbm\(.*?^\}'))
    pieces.extend(re.findall(r'^#define HAL_WBM_SW_COOKIE_CONV_CFG_WBM2SW\d+_EN[^\n]*',hal7,re.M))
    for text,name in ((qcn,'qcn9274'),(qcn,'ipq5332'),(wcn,'wcn7850')):
        pieces.append(declaration(text,'ath12k_hw_hal_params_'+name))
        pieces.append(declaration(text,'ath12k_hal_tcl_to_wbm_rbm_map_'+name))
    pieces.append('''struct ath12k_hw_params { const struct ath12k_hw_ring_mask *ring_mask; u8 max_tx_ring; };
struct hal_srng_config { unsigned max_rings; };
struct ath12k_base {
    const struct ath12k_hw_params *hw_params;
    struct { const struct ath12k_hw_hal_params *hal_params;
             const struct ath12k_hal_tcl_to_wbm_rbm_map *tcl_to_wbm_rbm_map;
             struct hal_srng_config srng_config[HAL_MAX_RING_TYPES]; } hal;
};''')
    for name in ('ath12k_dp_srng_find_ring_in_mask','ath12k_dp_wbm_tx_ring_index','ath12k_dp_srng_calculate_msi_group'):
        pieces.append(function(dp,name))
    validation=one(dp,r'^\tunsigned long release_rings;\n.*?(?=\n\tret = ath12k_dp_srng_setup)')
    pieces.append('''static int validate(struct ath12k_base *ab) {
    const struct ath12k_hal_tcl_to_wbm_rbm_map *map;
    unsigned i;
'''+validation+'\nreturn 0;\n}')
    pieces.append('''static unsigned checks;
static void check_layout(const struct ath12k_hal_tcl_to_wbm_rbm_map *map,
                         const struct ath12k_hw_hal_params *params,
                         unsigned n, unsigned rx, const unsigned *expected) {
    struct ath12k_hw_ring_mask mask = {};
    struct ath12k_hw_params hw = {&mask,n};
    struct ath12k_base ab = {.hw_params=&hw, .hal={.hal_params=params,.tcl_to_wbm_rbm_map=map}};
    ab.hal.srng_config[HAL_WBM2SW_RELEASE].max_rings=8;
    assert(params->rx_rel_ring_num == rx);
    assert(ath12k_hal_rx_rel_rbm(params) == HAL_RX_BUF_RBM_SW0_BM + rx);
    unsigned release = BIT(rx), cookie=BIT(rx+1);
    for (unsigned i=0;i<n;++i) {
        assert(map[i].wbm_ring_num == expected[i]);
        assert(map[i].rbm_id == HAL_RX_BUF_RBM_SW0_BM + expected[i]);
        assert(!(release & BIT(expected[i])));
        release |= BIT(expected[i]);
        cookie |= BIT(expected[i]+1);
        assert(params->rx_buf_rbm != map[i].rbm_id);
    }
    assert(params->wbm2sw_cc_enable == cookie);
    assert(validate(&ab)==0);
    /* Arbitrary IRQ group assignment: all rotations including group 11. */
    for (unsigned rotation=0;rotation<12;++rotation) {
        memset(&mask,0,sizeof(mask));
        for (unsigned i=0;i<n;++i) mask.tx[(i+rotation)%12]=BIT(i);
        mask.rx_wbm_rel[(rotation+n)%12]=1;
        for (int physical=-1;physical<=8;++physical) {
            int logical=-ENOENT;
            for (unsigned i=0;i<n;++i) if ((int)expected[i]==physical) logical=i;
            assert(ath12k_dp_wbm_tx_ring_index(&ab,physical)==logical);
            int group=physical==(int)rx?(int)((rotation+n)%12):logical<0?-ENOENT:(int)((logical+rotation)%12);
            assert(ath12k_dp_srng_calculate_msi_group(&ab,HAL_WBM2SW_RELEASE,physical)==group);
            ++checks;
        }
    }
    /* Reject invalid or overlapping physical ring allocations. */
    struct ath12k_hal_tcl_to_wbm_rbm_map bad[4];
    memcpy(bad,map,n*sizeof(*map));
    ab.hal.tcl_to_wbm_rbm_map=bad;
    for (unsigned i=0;i<n;++i) {
        bad[i].wbm_ring_num=rx; assert(validate(&ab)==-EINVAL);
        bad[i].wbm_ring_num=8; assert(validate(&ab)==-EINVAL);
        if(i) {bad[i].wbm_ring_num=bad[0].wbm_ring_num; assert(validate(&ab)==-EINVAL);}
        bad[i]=map[i];
    }
    ab.hal.srng_config[HAL_WBM2SW_RELEASE].max_rings=rx;
    assert(validate(&ab)==-EINVAL);
}
int main(void) {
    check_layout(ath12k_hal_tcl_to_wbm_rbm_map_ipq5332,&ath12k_hw_hal_params_ipq5332,4,5,(unsigned[]){0,1,2,3});
    check_layout(ath12k_hal_tcl_to_wbm_rbm_map_qcn9274,&ath12k_hw_hal_params_qcn9274,4,3,(unsigned[]){0,1,2,4});
    check_layout(ath12k_hal_tcl_to_wbm_rbm_map_wcn7850,&ath12k_hw_hal_params_wcn7850,3,3,(unsigned[]){0,2,4});
    printf("WBM_RELEASE_LAYOUT_PASS cases=%u\\n",checks);
}
''')
    # Every current revision retains its intended map and release parameters.
    expected = {
        'IPQ5332_HW10':('ipq5332','ipq5332'), 'QCN6432_HW10':('ipq5332','ipq5332'),
        'IPQ5424_HW10':('qcn9274','qcn9274'), 'QCN9274_HW10':('qcn9274','qcn9274'),
        'QCN9274_HW20':('qcn9274','qcn9274'), 'WCN7850_HW20':('wcn7850','wcn7850'),
        'QCC2072_HW10':('wcn7850','wcn7850'),
    }
    for rev,(map_name,params_name) in expected.items():
        block=one(hal_init,rf'\[ATH12K_HW_{rev}\] = \{{.*?\n\t\}},')
        assert f'.tcl_to_wbm_rbm_map = ath12k_hal_tcl_to_wbm_rbm_map_{map_name},' in block
        assert f'.hal_params = &ath12k_hw_hal_params_{params_name},' in block
    assert 'dp_srng_is_tx_comp_ring' not in dp+hw+hw7
    assert 'HAL_WBM2SW_REL_ERR_RING_NUM' not in dp+hal+hal7
    for name in ('wifi7/dp_rx.c','wifi7/hal_rx.c'):
        assert 'HAL_RX_BUF_RBM_SW3_BM' not in (root/name).read_text()
    c=a.output/'wbm-layout.c'; obj=a.output/'wbm-layout.o'; exe=a.output/'wbm-layout'
    c.write_text('\n'.join(pieces))
    subprocess.run(['/usr/local/bin/sccache','cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-c',str(c),'-o',str(obj)],check=True)
    subprocess.run(['cc',str(obj),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

if __name__ == '__main__':
    main()
