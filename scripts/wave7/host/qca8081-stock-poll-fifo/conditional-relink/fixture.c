/* Host fixture for the actual patched callbacks, not a second policy. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint8_t u8;
typedef enum {
    PHY_INTERFACE_MODE_NA, PHY_INTERFACE_MODE_SGMII, PHY_INTERFACE_MODE_QSGMII,
    PHY_INTERFACE_MODE_PSGMII, PHY_INTERFACE_MODE_1000BASEX,
    PHY_INTERFACE_MODE_2500BASEX, PHY_INTERFACE_MODE_USXGMII,
    PHY_INTERFACE_MODE_10G_QXGMII, PHY_INTERFACE_MODE_10GBASER
} phy_interface_t;
enum {PHYLINK_PCS_NEG_OUTBAND=32, PHYLINK_PCS_NEG_INBAND_ENABLED=64, MLO_AN_PHY=0, MLO_AN_INBAND=1};
enum {SPEED_10=10,SPEED_100=100,SPEED_1000=1000};
#define PCS_MAX_MII_NRS 5
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define phylink_pcs_to_qpcs_mii(p) container_of(p,struct ipq_pcs_mii,pcs)
static bool board=true, pm_sleep=false;
#define IS_ENABLED(x) pm_sleep
static bool of_machine_is_compatible(const char *s) { assert(!strcmp(s,"acer,wave7")); return board; }
static const char *phy_modes(phy_interface_t p) { return p==PHY_INTERFACE_MODE_SGMII?"sgmii":"other"; }
static void dev_info(void *d,const char *f,...) {}
static void dev_err(void *d,const char *f,...) {}
/* STRUCTS */
struct phylink_pcs {int unused;};
struct ipq_pcs;
struct ipq_pcs_mii {
    struct phylink_pcs pcs;
    struct ipq_pcs *qpcs;
    int index;
    void *rx_clk,*tx_clk;
    u8 diag_configs,diag_link_ups;
    struct ipq_pcs_relink relink;
};
struct ipq_pcs {
    void *dev,*regmap;
    bool mppe;
    phy_interface_t interface;
    struct ipq_pcs_mii *qpcs_mii[PCS_MAX_MII_NRS];
};
struct phy_device {u32 phy_id;struct {int addr;} mdio;};
struct phylink_config {int unused;};
struct phylink_link_state {phy_interface_t interface;};
enum ppe_mac_type {PPE_MAC_TYPE_GMAC,PPE_MAC_TYPE_XGMAC};
struct ppe_device {void *dev,*regmap;};
struct ppe_port {
    struct phylink_config phylink_config;
    struct ppe_device *ppe_dev;
    int port_id;
    enum ppe_mac_type mac_type;
    struct phylink_pcs *pcs;
    bool wave7_relink,mac_configured;
};
enum operation {
    MODE, FORCE, SPEED, ADAPTER_CLEAR, ADAPTER_SET, MAC_RESET, MUX,
    RATE, MAC_UP, FLOW, BRIDGE_UP, BRIDGE_DOWN, MAC_DOWN,
    CLK_ENABLE, CLK_DISABLE, OTHER_PCS, OPERATIONS
};
static int calls[OPERATIONS], sequence[128], nseq, fail=-1;
static int event(enum operation op) {
    assert(nseq<(int)(sizeof(sequence)/sizeof(sequence[0])));
    ++calls[op];sequence[nseq++]=op;
    return (int)op==fail?-EIO:0;
}
static void clear(void) { memset(calls,0,sizeof(calls));nseq=0;fail=-1; }
static int clk_prepare_enable(void *clk) {return event(CLK_ENABLE);}
static void clk_disable_unprepare(void *clk) {event(CLK_DISABLE);}
#define PCS_MII_CTRL(i) (0x480+(i)*4)
#define PCS_MII_FORCE_MODE 0x1
#define PCS_MII_SPEED_MASK 0x6
#define PCS_MII_SPEED_10 0
#define PCS_MII_SPEED_100 2
#define PCS_MII_SPEED_1000 4
#define PCS_MII_ADPT_RESET 0x800
#define PPE_PORT_SEL_XGMAC(p) (1u<<(p))
#define PPE_PORT_MUX_CTRL_ADDR 0x10000
#define PPE_BM_PORT_FC_MODE_ADDR 0x20000
#define PPE_BM_PORT_FC_MODE_INC 4
#define PPE_BM_PORT_MAC_START 7
#define PPE_BM_PORT_FC_MODE_EN 1
#define PPE_PORT_BRIDGE_CTRL_ADDR 0x60300
#define PPE_PORT_BRIDGE_CTRL_INC 4
#define PPE_PORT_BRIDGE_TXMAC_EN (1u<<16)
static int regmap_update_bits(void *map,u32 reg,u32 mask,u32 value) {
    assert((value&~mask)==0);
    if(reg==PCS_MII_CTRL(0)&&mask==PCS_MII_SPEED_MASK) return event(SPEED);
    if(reg==PPE_PORT_MUX_CTRL_ADDR) return event(MUX);
    if(reg==PPE_BM_PORT_FC_MODE_ADDR+4*(2+PPE_BM_PORT_MAC_START)) return event(FLOW);
    assert(0);return -EIO;
}
static int regmap_clear_bits(void *map,u32 reg,u32 mask) {
    if(reg==PCS_MII_CTRL(0)&&mask==PCS_MII_ADPT_RESET) return event(ADAPTER_CLEAR);
    if(reg==PCS_MII_CTRL(0)&&mask==PCS_MII_FORCE_MODE) return event(FORCE);
    if(reg==PPE_PORT_BRIDGE_CTRL_ADDR+8&&mask==PPE_PORT_BRIDGE_TXMAC_EN) return event(BRIDGE_DOWN);
    assert(0);return -EIO;
}
static int regmap_set_bits(void *map,u32 reg,u32 mask) {
    if(reg==PCS_MII_CTRL(0)&&mask==PCS_MII_ADPT_RESET) return event(ADAPTER_SET);
    if(reg==PCS_MII_CTRL(0)&&mask==PCS_MII_FORCE_MODE) return event(FORCE);
    if(reg==PPE_PORT_BRIDGE_CTRL_ADDR+8&&mask==PPE_PORT_BRIDGE_TXMAC_EN) return event(BRIDGE_UP);
    assert(0);return -EIO;
}
static int ppe_port_mac_reset(struct ppe_port *p) {return event(MAC_RESET);}
static int ppe_port_mac_speed_clock_rate_set(struct ppe_port *p,phy_interface_t i,int speed) {return event(RATE);}
static int ppe_port_gmac_link_up(struct ppe_port *p,int speed,int duplex,bool tx,bool rx) {return event(MAC_UP);}
static int ppe_port_xgmac_link_up(struct ppe_port *p,phy_interface_t i,int speed,int duplex,bool tx,bool rx) {return event(MAC_UP);}
static int ppe_port_gmac_link_down(struct ppe_port *p) {return event(MAC_DOWN);}
static int ppe_port_xgmac_link_down(struct ppe_port *p) {return event(MAC_DOWN);}
/* INVALIDATION */
static int ipq_pcs_config_mode(struct ipq_pcs *q,phy_interface_t interface) {
    for(int i=0;i<PCS_MAX_MII_NRS;i++) if(q->qpcs_mii[i]) ipq_pcs_relink_invalidate(q->qpcs_mii[i]);
    int ret=event(MODE);
    if(!ret)q->interface=interface;
    return ret;
}
static int ipq_pcs_config_2500basex(struct ipq_pcs *q) {return ipq_pcs_config_mode(q,PHY_INTERFACE_MODE_2500BASEX);}
static int ipq_pcs_config_usxgmii(struct ipq_pcs *q,int index,phy_interface_t i) {return event(OTHER_PCS);}
static int ipq_pcs_config_10gbaser(struct ipq_pcs *q) {return event(OTHER_PCS);}
static int ipq_pcs_link_up_config_2500basex(struct ipq_pcs *q,int speed) {return event(OTHER_PCS);}
static int ipq_pcs_link_up_config_usxgmii(struct ipq_pcs *q,int index,int speed) {return event(OTHER_PCS);}
/* CALLBACKS */
static struct ipq_pcs q;
static struct ipq_pcs_mii m, other;
static struct ppe_device dev;
static struct ppe_port port;
static struct phy_device phy={.phy_id=0x004dd101,.mdio.addr=0x18};
static void major(phy_interface_t i) {
    struct phylink_link_state s={.interface=i};
    ppe_port_mac_config(&port.phylink_config,MLO_AN_PHY,&s);
    assert(!ipq_pcs_config(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,i,NULL,true));
}
static void up(phy_interface_t i,int speed,int duplex,bool tx,bool rx) {
    ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,i,speed,duplex);
    ppe_port_mac_link_up(&port.phylink_config,&phy,MLO_AN_PHY,i,speed,duplex,tx,rx);
}
static void down(phy_interface_t i) {
    ppe_port_mac_link_down(&port.phylink_config,MLO_AN_PHY,i);
}
static void initialize(bool opted) {
    q=(struct ipq_pcs){.mppe=true,.qpcs_mii={&m}};
    m=(struct ipq_pcs_mii){.qpcs=&q};
    port=(struct ppe_port){.ppe_dev=&dev,.pcs=&m.pcs,.port_id=2,.wave7_relink=opted};
    assert(ppe_port_wave7_phy(&port,&phy));
    if(opted)assert(ipq_pcs_wave7_relink_enable(&m.pcs)==0);
    clear();major(PHY_INTERFACE_MODE_SGMII);
    assert(port.mac_configured);
    assert(calls[MODE]==0); /* original 0479 cold deferral */
    clear();
}
static void check_up(bool preserved,bool ready) {
    assert(calls[MODE]==!preserved);
    assert(calls[ADAPTER_CLEAR]==!preserved && calls[ADAPTER_SET]==!preserved);
    assert(calls[FORCE]==!preserved && calls[SPEED]==!preserved);
    assert(calls[RATE]==1&&calls[MAC_UP]==1&&calls[FLOW]==1&&calls[BRIDGE_UP]==1);
    assert(sequence[nseq-4]==RATE&&sequence[nseq-3]==MAC_UP&&sequence[nseq-2]==FLOW&&sequence[nseq-1]==BRIDGE_UP);
    assert(m.relink.phase==(ready?IPQ_RELINK_READY:IPQ_RELINK_INVALID));
}
static void make_ready(void) {initialize(true);up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);}
int main(void) {
    initialize(false);
    up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,false);
    clear();down(PHY_INTERFACE_MODE_SGMII);clear();
    up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,false);
    // Every valid negotiated tuple against every other tuple (including
    // independently toggled pause bits), through actual callbacks.
    int n=0;
    const int speeds[]={10,100,1000};
    for(int a=0;a<3;a++)for(int ad=0;ad<2;ad++)for(int ap=0;ap<4;ap++){
        if(a==2&&!ad)continue;
        for(int b=0;b<3;b++)for(int bd=0;bd<2;bd++)for(int bp=0;bp<4;bp++){
            if(b==2&&!bd)continue;
            initialize(true);
            up(PHY_INTERFACE_MODE_SGMII,speeds[a],ad,ap&2,ap&1);check_up(false,true);
            clear();down(PHY_INTERFACE_MODE_SGMII);
            assert(m.relink.phase==IPQ_RELINK_READY&&calls[BRIDGE_DOWN]==1&&calls[MAC_DOWN]==1);
            clear();up(PHY_INTERFACE_MODE_SGMII,speeds[b],bd,bp&2,bp&1);
            check_up(a==b&&ad==bd&&ap==bp,true);n++;
        }
    }
    // Every failed preparation or MAC commit must prevent the warm skip
    // on the following event. PCS failures must not reach MAC programming.
    const int fail_up[]={MODE,FORCE,SPEED,ADAPTER_CLEAR,ADAPTER_SET,RATE,MAC_UP,FLOW,BRIDGE_UP};
    for(unsigned i=0;i<sizeof(fail_up)/sizeof(*fail_up);i++){
        initialize(true);fail=fail_up[i];
        up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
        assert(m.relink.phase==IPQ_RELINK_INVALID);
        if(fail_up[i]<=ADAPTER_SET)assert(!calls[RATE]&&!calls[MAC_UP]&&!calls[BRIDGE_UP]);
        clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    }
    // A warm MAC-side failure invalidates the previously good tuple.
    for(int f=RATE;f<=BRIDGE_UP;f++){
        make_ready();clear();down(PHY_INTERFACE_MODE_SGMII);clear();fail=f;
        up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
        assert(m.relink.phase==IPQ_RELINK_INVALID&&calls[MODE]==0);
        clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    }
    for(int f=BRIDGE_DOWN;f<=MAC_DOWN;f++){
        make_ready();clear();fail=f;
        down(PHY_INTERFACE_MODE_SGMII);assert(m.relink.phase==IPQ_RELINK_INVALID);
        clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    }
    make_ready();clear();ipq_pcs_disable(&m.pcs);assert(m.relink.phase==IPQ_RELINK_INVALID);
    assert(!ipq_pcs_enable(&m.pcs));clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    make_ready();clear();major(PHY_INTERFACE_MODE_SGMII);
    assert(m.relink.phase==IPQ_RELINK_INVALID);clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    make_ready();clear();major(PHY_INTERFACE_MODE_2500BASEX);up(PHY_INTERFACE_MODE_2500BASEX,2500,1,true,true);
    assert(m.relink.phase==IPQ_RELINK_INVALID&&calls[OTHER_PCS]==1);
    clear();major(PHY_INTERFACE_MODE_SGMII);clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    for(int f=MAC_RESET;f<=MUX;f++){
        make_ready();clear();fail=f;major(PHY_INTERFACE_MODE_SGMII);assert(!port.mac_configured);
        clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
        assert(!calls[RATE]&&!calls[BRIDGE_UP]&&m.relink.phase==IPQ_RELINK_INVALID);
        clear();major(PHY_INTERFACE_MODE_SGMII);clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    }
    make_ready();clear();
    ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_SGMII,1000,1);
    ppe_port_mac_link_up(&port.phylink_config,&phy,MLO_AN_PHY,PHY_INTERFACE_MODE_SGMII,100,1,true,true);
    assert(m.relink.phase==IPQ_RELINK_INVALID&&!calls[RATE]);
    clear();ppe_port_mac_link_up(&port.phylink_config,&phy,MLO_AN_PHY,PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
    assert(!calls[RATE]);
    clear();up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);check_up(false,true);
    // Scope and invalidation, including unsupported system-sleep builds.
    initialize(false);board=false;assert(!ppe_port_wave7_phy(&port,&phy));assert(ipq_pcs_wave7_relink_enable(&m.pcs)==-EOPNOTSUPP);board=true;
    pm_sleep=true;assert(!ppe_port_wave7_phy(&port,&phy));assert(ipq_pcs_wave7_relink_enable(&m.pcs)==-EOPNOTSUPP);pm_sleep=false;
    q.qpcs_mii[1]=&other;assert(ipq_pcs_wave7_relink_enable(&m.pcs)==-EOPNOTSUPP);q.qpcs_mii[1]=NULL;
    port.port_id=1;assert(!ppe_port_wave7_phy(&port,&phy));port.port_id=2;phy.mdio.addr=25;assert(!ppe_port_wave7_phy(&port,&phy));
    printf("WAVE7_RELINK_POLICY_PASS %d negotiated tuple pairs; lifecycle, scope and fault injection PASS\n",n);
}
