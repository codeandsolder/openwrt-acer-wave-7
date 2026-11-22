#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#define QCA8081_PHY_ID 0x004dd101
#define GENMASK(h,l) (((1U<<((h)-(l)+1))-1)<<(l))
#define IS_ENABLED(x) (x)
#define CONFIG_PM_SLEEP 0
#define IORESOURCE_MEM 0
#define PCS_MAX_MII_NRS 5
#define PHYLINK_PCS_NEG_OUTBAND 1
#define PHYLINK_PCS_NEG_INBAND_ENABLED 2
#define SPEED_1000 1000
#define SPEED_100 100
#define SPEED_10 10
#define PCS_MII_SPEED_1000 2
#define PCS_MII_SPEED_100 1
#define PCS_MII_SPEED_10 0
#define PCS_MII_SPEED_MASK 3
#define PCS_MII_FORCE_MODE 4
#define PCS_MII_ADPT_RESET 8
#define PCS_MII_CTRL(i) (i)
#define container_of(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
typedef int phy_interface_t;
enum {PHY_INTERFACE_MODE_NA,PHY_INTERFACE_MODE_SGMII,PHY_INTERFACE_MODE_2500BASEX,
      PHY_INTERFACE_MODE_QSGMII,PHY_INTERFACE_MODE_PSGMII,PHY_INTERFACE_MODE_1000BASEX,
      PHY_INTERFACE_MODE_USXGMII,PHY_INTERFACE_MODE_10G_QXGMII,PHY_INTERFACE_MODE_10GBASER};
enum { PHY_DOWN,PHY_READY,PHY_HALTED,PHY_ERROR,PHY_UP,PHY_RUNNING,PHY_NOLINK,PHY_CABLETEST };
enum { MLO_AN_FIXED,MLO_AN_PHY,MLO_AN_INBAND };
struct phy_device { unsigned phy_id,link; int state,interface,lock; struct {int addr;} mdio; };
struct phylink_link_state { bool link; int interface,speed,duplex,rate_matching,pause; };
struct work_struct { int dummy; };
struct phylink {
    struct work_struct resolve;
    int phydev_mutex,state_mutex;
    struct phy_device *phydev;
    struct phylink_link_state phy_state,link_config;
    bool carrier,phylink_disable_state,link_failed,force_major_config,major_config_failed,wave7_down_config_failed,old_link_state;
    int act_link_an_mode;
};
struct resource { unsigned long start; };
struct phylink_pcs { int dummy; };
struct ipq_pcs_mii;
struct ipq_pcs { void *dev,*regmap; bool mppe; int interface; struct ipq_pcs_mii *qpcs_mii[5]; };
struct ipq_pcs_mii {
    struct ipq_pcs *qpcs;
    struct phylink_pcs pcs;
    int index,diag_configs,diag_link_ups;
    bool warm_2500,prepared_sgmii;
    void *rx_clk,*tx_clk;
};
#define phylink_pcs_to_qpcs_mii(p) container_of(p,struct ipq_pcs_mii,pcs)
static struct phy_device phy;
static struct phylink pl;
static struct ipq_pcs q;
static struct ipq_pcs_mii m,other;
static struct resource res;
static bool board=true,resource_present=true;
static int mode_word,reads,phy_logs,queued,downs,ups,major_calls,major_error;
static int mode_calls,mode_error,reg_calls,reg_error_at,clock_calls,clock_error;
static int reg_value,system_power_efficient_wq;
static void mutex_lock(int *m){assert(!*m);*m=1;}
static void mutex_unlock(int *m){assert(*m);*m=0;}
static bool of_machine_is_compatible(const char *s){assert(!strcmp(s,"acer,wave7"));return board;}
static int phy_read(struct phy_device *p,int reg){assert(p==&phy && reg==31);reads++;return mode_word;}
static void phydev_info(struct phy_device *p,const char *fmt,...){assert(p==&phy && strstr(fmt,"down-mode PHY"));phy_logs++;}
static void phylink_info(struct phylink *p,const char *fmt,...){assert(p==&pl && strstr(fmt,"down-mode host"));}
static bool phylink_link_is_up(struct phylink *p){return p->carrier;}
static void phylink_link_down(struct phylink *p){p->carrier=false;downs++;}
static void phylink_link_up(struct phylink *p,struct phylink_link_state s){assert(s.link);p->carrier=true;ups++;}
static void phylink_get_fixed_state(struct phylink *p,struct phylink_link_state *s){*s=p->phy_state;}
static void phylink_mac_pcs_get_state(struct phylink *p,struct phylink_link_state *s){*s=p->phy_state;}
static void phylink_apply_manual_flow(struct phylink *p,struct phylink_link_state *s){}
static __attribute__((noinline)) void phylink_major_config(struct phylink *p,bool restart,const struct phylink_link_state *s){
    assert(p==&pl && !restart && !p->carrier);
    assert(s->interface==PHY_INTERFACE_MODE_SGMII || s->interface==PHY_INTERFACE_MODE_2500BASEX);
    major_calls++;p->wave7_down_config_failed=false;p->major_config_failed=major_error!=0;
}
static void queue_work(int qid,struct work_struct *w){assert(w==&pl.resolve);queued++;}
static void *to_platform_device(void *d){return d;}
static struct resource *platform_get_resource(void *d,int type,int i){assert(d==q.dev && type==0 && i==0);return resource_present?&res:NULL;}
static void ipq_pcs_clear_prepared(struct ipq_pcs_mii *mii);
static int ipq_pcs_config_mode(struct ipq_pcs *qpcs,int interface){
    assert(qpcs==&q);
    mode_calls++;
    for(int i=0;i<5;i++)if(qpcs->qpcs_mii[i])ipq_pcs_clear_prepared(qpcs->qpcs_mii[i]);
    /* Also emulate a failure after hardware mode was partially published. */
    qpcs->interface=interface;
    return mode_error;
}
static int regmap_update_bits(void *r,int addr,int mask,int val){
    assert(r==q.regmap && addr==0);
    if(++reg_calls==reg_error_at)return -EIO;
    reg_value=(reg_value&~mask)|(val&mask);return 0;
}
static int regmap_set_bits(void *r,int a,int mask){return regmap_update_bits(r,a,mask,mask);}
static int regmap_clear_bits(void *r,int a,int mask){return regmap_update_bits(r,a,mask,0);}
static int clk_prepare_enable(void *c){clock_calls++;return clock_error;}
static void clk_disable_unprepare(void *c){clock_calls++;}
static const char *phy_modes(int i){return "mode";}
#define dev_info(dev,fmt,...) do { (void)(dev); if (0) printf(fmt, ##__VA_ARGS__); } while (0)
#define dev_err(dev,fmt,...) do { (void)(dev); if (0) printf(fmt, ##__VA_ARGS__); } while (0)
static int ipq_pcs_config_usxgmii(struct ipq_pcs *q,int i,int f){return -EINVAL;}
static int ipq_pcs_config_10gbaser(struct ipq_pcs *q){return -EINVAL;}
static int ipq_pcs_link_up_config_usxgmii(struct ipq_pcs *q,int i,int speed){return -EINVAL;}

/* EXTRACTED KERNEL FUNCTIONS */

static void phy_init(void){
    phy=(struct phy_device){.phy_id=QCA8081_PHY_ID,.mdio.addr=24,.state=PHY_RUNNING,
                            .interface=PHY_INTERFACE_MODE_2500BASEX};
    board=true;reads=phy_logs=0;
}
static void pl_init(void){
    phy_init();
    pl=(struct phylink){.phydev=&phy,.carrier=true,.act_link_an_mode=MLO_AN_PHY,
       .link_config.interface=PHY_INTERFACE_MODE_2500BASEX,.phy_state.interface=PHY_INTERFACE_MODE_SGMII};
    queued=downs=ups=major_calls=major_error=0;
}
static void pcs_init(void){
    q=(struct ipq_pcs){.mppe=true,.interface=PHY_INTERFACE_MODE_2500BASEX};
    m=(struct ipq_pcs_mii){.qpcs=&q};
    q.qpcs_mii[0]=&m;
    res.start=0x7a10000;
    board=resource_present=true;
    mode_calls=mode_error=reg_calls=reg_error_at=clock_calls=clock_error=reg_value=0;
    q.dev=&q;q.regmap=&q;
}
static int configure(int md,int neg){return ipq_pcs_config(&m.pcs,neg,md,NULL,true);}
static void up(int md,int speed){ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,md,speed,1);}
static void warm(void){up(PHY_INTERFACE_MODE_2500BASEX,2500);assert(m.warm_2500 && !m.prepared_sgmii);}
static void prepared(void){assert(!configure(PHY_INTERFACE_MODE_SGMII,PHYLINK_PCS_NEG_OUTBAND));assert(m.prepared_sgmii && !m.warm_2500);}
int main(void){
    for(int x=-255;x<=65535;x++){
        phy_init();mode_word=x;qca8081_publish_down_mode(&phy,false);
        bool valid=x>=0 && x!=65535 && !(x&0x6000);
        assert(reads==1 && phy_logs==valid && !phy.link);
        assert(phy.interface==(valid?PHY_INTERFACE_MODE_SGMII:PHY_INTERFACE_MODE_2500BASEX));
    }
    for(int st=PHY_DOWN;st<=PHY_CABLETEST;st++)
    for(int l=0;l<2;l++)for(int copper=0;copper<2;copper++)
    for(int iface=PHY_INTERFACE_MODE_NA;iface<=PHY_INTERFACE_MODE_2500BASEX;iface++){
        phy_init();mode_word=0x8544;phy.state=st;phy.link=l;phy.interface=iface;
        qca8081_publish_down_mode(&phy,copper);
        assert(reads==(st==PHY_RUNNING && !l && !copper && iface==PHY_INTERFACE_MODE_2500BASEX));
        assert(phy.link==(unsigned)l);
    }
    assert(qca8081_has_independent_fifo(&phy));
    board=false;assert(!qca8081_has_independent_fifo(&phy));
    phy_init();phy.phy_id=0;assert(!qca8081_has_independent_fifo(&phy));
    phy_init();phy.mdio.addr=23;assert(!qca8081_has_independent_fifo(&phy));

    pl_init();pl.link_failed=true;pl.force_major_config=true;
    phylink_resolve(&pl.resolve);
    assert(downs==1 && queued==1 && major_calls==0 && !pl.carrier && pl.force_major_config);
    phylink_resolve(&pl.resolve);
    assert(major_calls==1 && pl.link_config.interface==PHY_INTERFACE_MODE_SGMII && !pl.carrier && !pl.force_major_config);
    phylink_resolve(&pl.resolve);assert(major_calls==1 && !ups);
    pl.phy_state.link=true;phylink_resolve(&pl.resolve);assert(major_calls==1 && ups==1 && pl.carrier);
    for(int md=PHY_INTERFACE_MODE_SGMII;md<=PHY_INTERFACE_MODE_2500BASEX;md++){
        pl_init();major_error=-EIO;phylink_resolve(&pl.resolve);
        assert(major_calls==1 && pl.major_config_failed && pl.wave7_down_config_failed && !pl.carrier);
        phylink_resolve(&pl.resolve);assert(major_calls==1);
        major_error=0;pl.phy_state.interface=md;pl.phy_state.link=true;
        phylink_resolve(&pl.resolve);assert(major_calls==2 && !pl.major_config_failed && !pl.wave7_down_config_failed && pl.carrier);
    }
    pl_init();board=false;phylink_resolve(&pl.resolve);assert(!major_calls);
    pl_init();phy.mdio.addr=23;phylink_resolve(&pl.resolve);assert(!major_calls);
    pl_init();pl.link_config.interface=PHY_INTERFACE_MODE_SGMII;phylink_resolve(&pl.resolve);assert(!major_calls);
    pl_init();pl.act_link_an_mode=MLO_AN_FIXED;phylink_resolve(&pl.resolve);assert(!major_calls);
    pl_init();pl.act_link_an_mode=MLO_AN_INBAND;phylink_resolve(&pl.resolve);assert(!major_calls);
    pl_init();pl.phylink_disable_state=true;pl.force_major_config=true;phylink_resolve(&pl.resolve);assert(!major_calls && pl.force_major_config);

    pcs_init();assert(ipq_pcs_wave7_down_mode(&m));
    for(int missing=0;missing<5;missing++){
        pcs_init();
        if(missing==0)board=false;
        if(missing==1)q.mppe=false;
        if(missing==2)resource_present=false;
        if(missing==3)res.start=0x7a00000;
        if(missing==4)q.qpcs_mii[1]=&other;
        assert(!ipq_pcs_wave7_down_mode(&m));
        up(PHY_INTERFACE_MODE_2500BASEX,2500);assert(!m.warm_2500);
    }
    pcs_init();q.interface=PHY_INTERFACE_MODE_NA;
    assert(!configure(PHY_INTERFACE_MODE_SGMII,PHYLINK_PCS_NEG_OUTBAND));assert(!mode_calls && !m.prepared_sgmii);
    up(PHY_INTERFACE_MODE_SGMII,1000);assert(mode_calls==1 && !m.prepared_sgmii);
    pcs_init();warm();prepared();assert(mode_calls==1);
    up(PHY_INTERFACE_MODE_SGMII,1000);assert(mode_calls==1 && !m.prepared_sgmii);
    assert((reg_value&(PCS_MII_FORCE_MODE|PCS_MII_SPEED_MASK|PCS_MII_ADPT_RESET))==(PCS_MII_FORCE_MODE|PCS_MII_SPEED_1000|PCS_MII_ADPT_RESET));
    up(PHY_INTERFACE_MODE_SGMII,1000);assert(mode_calls==2);
    pcs_init();warm();prepared();ipq_pcs_disable(&m.pcs);assert(!m.prepared_sgmii);
    up(PHY_INTERFACE_MODE_SGMII,1000);assert(mode_calls==2);
    pcs_init();warm();prepared();assert(!ipq_pcs_enable(&m.pcs));assert(!m.prepared_sgmii);
    pcs_init();warm();prepared();assert(!configure(PHY_INTERFACE_MODE_SGMII,PHYLINK_PCS_NEG_OUTBAND));assert(!m.prepared_sgmii);
    up(PHY_INTERFACE_MODE_SGMII,1000);assert(mode_calls==2);
    pcs_init();warm();mode_error=-EIO;assert(configure(PHY_INTERFACE_MODE_SGMII,PHYLINK_PCS_NEG_OUTBAND)==-EIO);
    assert(!m.prepared_sgmii && !m.warm_2500);mode_error=0;
    up(PHY_INTERFACE_MODE_SGMII,1000);assert(mode_calls==2);
    pcs_init();warm();reg_error_at=reg_calls+1;assert(configure(PHY_INTERFACE_MODE_SGMII,PHYLINK_PCS_NEG_OUTBAND)==-EIO);
    assert(!m.prepared_sgmii&&!m.warm_2500);
    pcs_init();reg_error_at=1;up(PHY_INTERFACE_MODE_2500BASEX,2500);assert(!m.warm_2500);
    pcs_init();warm();prepared();assert(!configure(PHY_INTERFACE_MODE_2500BASEX,PHYLINK_PCS_NEG_OUTBAND));
    assert(!m.prepared_sgmii && q.interface==PHY_INTERFACE_MODE_2500BASEX);
    up(PHY_INTERFACE_MODE_2500BASEX,2500);assert(m.warm_2500);
    puts("DOWN_MODE_POLICY_PASS: 65791 mode/error cases; PHY edge gates; phylink down/retry; PCS lifecycle/error gates");
    return 0;
}
