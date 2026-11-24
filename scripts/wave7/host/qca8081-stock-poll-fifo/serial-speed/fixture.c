#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((~0U>> (31-(h))) & (~0U<<(l)))
#define FIELD_PREP(mask,val) (((unsigned)(val)<<__builtin_ctz(mask))&(mask))
#define PCS_MAX_MII_NRS 5
#define IORESOURCE_MEM 0
#define PHYLINK_PCS_NEG_OUTBAND 1
#define PHYLINK_PCS_NEG_INBAND_ENABLED 2
#define PHYLINK_PCS_NEG_INBAND_DISABLED 3
#define SPEED_1000 1000
#define SPEED_100 100
#define SPEED_10 10
#define container_of(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
typedef int phy_interface_t;
enum { PHY_INTERFACE_MODE_NA, PHY_INTERFACE_MODE_SGMII, PHY_INTERFACE_MODE_2500BASEX,
       PHY_INTERFACE_MODE_QSGMII, PHY_INTERFACE_MODE_PSGMII, PHY_INTERFACE_MODE_1000BASEX,
       PHY_INTERFACE_MODE_USXGMII, PHY_INTERFACE_MODE_10G_QXGMII, PHY_INTERFACE_MODE_10GBASER };
/* DRIVER DEFINITIONS */
struct resource {unsigned long start;};
struct device {void *of_node;};
struct clk_hw {void *clk;};
struct phylink_pcs {int dummy;};
struct ipq_pcs_mii;
struct ipq_pcs {
    struct device *dev;
    void *regmap;
    bool mppe;
    phy_interface_t interface;
    unsigned diag_mode_reconfigs;
    struct clk_hw rx_hw,tx_hw;
    struct ipq_pcs_mii *qpcs_mii[PCS_MAX_MII_NRS];
    void *xpcs_rstc,*sys_rstc,*soft_rstc;
};
struct ipq_pcs_mii {
    struct ipq_pcs *qpcs;
    struct phylink_pcs pcs;
    int index;
    unsigned diag_configs,diag_link_ups;
};
#define phylink_pcs_to_qpcs_mii(p) container_of(p,struct ipq_pcs_mii,pcs)
static struct device dev;
static struct ipq_pcs q;
static struct ipq_pcs_mii m,other;
static struct resource res;
static bool board,resource_present;
static unsigned regs[0x1000/4];
static unsigned writes,fail_at,mode_writes,force_writes,speed_writes,pulses,cal_starts,cal_stops,clock_off,clock_on;
static unsigned logs,post_logs,errors,reads,fail_read_at;
static unsigned last_force_write,last_cal_start,last_cal_stop,last_pulse;
static bool require_serial;
static bool of_machine_is_compatible(const char *s){assert(!strcmp(s,"acer,wave7"));return board;}
static void *to_platform_device(void *d){return d;}
static struct resource *platform_get_resource(void *d,int type,int i){assert(d==&dev&&type==IORESOURCE_MEM&&!i);return resource_present?&res:NULL;}
static const char *phy_modes(int i){return "mode";}
static void dev_info(struct device *d,const char *fmt,...){assert(d==&dev);logs++;if(strstr(fmt,"serial-speed"))post_logs++;}
#ifdef HAS_HANDOFF
static void dev_warn(struct device *d,const char *fmt,...){assert(d==&dev);errors++;}
#endif
static void dev_err(struct device *d,const char *fmt,...){assert(d==&dev);errors++;}
static void ipq_pcs_disable_port_clks(struct ipq_pcs *qpcs,int i){assert(qpcs==&q);clock_off++;}
static int ipq_pcs_restore_port_clks(struct ipq_pcs *qpcs,int i){assert(qpcs==&q);clock_on++;return 0;}
static int reset_control_assert(void *r){return 0;}
static int reset_control_deassert(void *r){return 0;}
static void msleep(unsigned ms){}
static void fsleep(unsigned us){}
static int clk_set_rate(void *c,unsigned long rate){assert(rate==125000000||rate==312500000);return 0;}
static bool of_property_read_bool(void *node,const char *name){return false;}
static int regmap_update_bits(void *r,unsigned a,unsigned mask,unsigned val){
    assert(r==&regs&&a<sizeof(regs)&&!(a%4));
    if(++writes==fail_at)return -EIO;
    if(a==PCS_MODE_CTRL)mode_writes++;
    if(a==PCS_MII_CTRL(0)){
        if(mask&PCS_MII_FORCE_MODE){force_writes++;last_force_write=writes;}
        if(mask&PCS_MII_SPEED_MASK)speed_writes++;
        if(mask&PCS_MII_ADPT_RESET){pulses++;last_pulse=writes;}
    }
    if(a==PCS_VCO_CAL_CTRL){
        if(val&PCS_VCO_CAL_RESTART){
            cal_starts++;last_cal_start=writes;
            if(require_serial){
                assert(!(regs[PCS_MII_CTRL(0)/4]&PCS_MII_FORCE_MODE));
                assert(!(regs[PCS_MODE_CTRL/4]&PCS_MODE_AUTONEG_ATH));
                assert(last_force_write<last_cal_start);
            }
        }else{cal_stops++;last_cal_stop=writes;}
    }
    regs[a/4]=(regs[a/4]&~mask)|(val&mask);
    return 0;
}
static int regmap_set_bits(void*r,unsigned a,unsigned mask){return regmap_update_bits(r,a,mask,mask);}
static int regmap_clear_bits(void*r,unsigned a,unsigned mask){return regmap_update_bits(r,a,mask,0);}
static int regmap_write(void*r,unsigned a,unsigned val){return regmap_update_bits(r,a,~0U,val);}
static int regmap_read(void*r,unsigned a,unsigned*v){assert(r==&regs&&a<sizeof(regs)&&!(a%4));if(++reads==fail_read_at)return -EIO;*v=regs[a/4];return 0;}
#define regmap_read_poll_timeout(r,a,v,cond,interval,timeout) ((v=PCS_CALIBRATION_DONE),(cond)?0:-ETIMEDOUT)
static int ipq_pcs_config_usxgmii(struct ipq_pcs*qpcs,int idx,int interface){return 0;}
static int ipq_pcs_config_10gbaser(struct ipq_pcs*qpcs){return 0;}
static int ipq_pcs_link_up_config_usxgmii(struct ipq_pcs*qpcs,int idx,int speed){return 0;}
/* DRIVER FUNCTIONS */
static void init(int interface){
    memset(&q,0,sizeof(q));memset(&m,0,sizeof(m));memset(regs,0,sizeof(regs));
    q.dev=&dev;q.regmap=&regs;q.mppe=true;q.interface=interface;q.qpcs_mii[0]=&m;m.qpcs=&q;
    board=resource_present=true;res.start=0x7a10000;
    writes=fail_at=mode_writes=force_writes=speed_writes=pulses=cal_starts=cal_stops=clock_off=clock_on=0;
    logs=post_logs=errors=reads=fail_read_at=last_force_write=last_cal_start=last_cal_stop=last_pulse=0;
    require_serial=false;
    regs[PCS_MODE_CTRL/4]=0x421;
    regs[PCS_MII_CTRL(0)/4]=0x84e; /* deliberately distinct previous speed */
    regs[PCS_MII_STS(0)/4]=0x60; /* explicitly PCS carrier zero */
}
static void qualified(int speed){
    assert(!(regs[PCS_MODE_CTRL/4]&PCS_MODE_AUTONEG_ATH));
    assert(!(regs[PCS_MII_CTRL(0)/4]&PCS_MII_FORCE_MODE));
    assert((regs[PCS_MII_CTRL(0)/4]&PCS_MII_SPEED_MASK)==(0x84e&PCS_MII_SPEED_MASK));
    assert(regs[PCS_MII_CTRL(0)/4]&PCS_MII_ADPT_RESET);
    assert(speed_writes==0&&pulses==2&&cal_starts==1&&cal_stops==1);
    assert(last_cal_start<last_cal_stop&&last_cal_stop<last_pulse);
    assert(clock_off==1&&clock_on==1&&post_logs==1&&!errors);
    assert(regs[PCS_MII_STS(0)/4]==0x60);
}
int main(void){
    unsigned cases=0;
    /* Exhaustively exercise the exact hardware/callback scope. */
    for(int b=0;b<2;b++)for(int mppe=0;mppe<2;mppe++)for(int present=0;present<2;present++)
    for(int addr=0;addr<2;addr++)for(int multi=0;multi<2;multi++)
    for(int idx=0;idx<5;idx++)for(int neg=1;neg<=3;neg++)for(int mode=0;mode<=8;mode++){
        init(PHY_INTERFACE_MODE_NA);board=b;q.mppe=mppe;resource_present=present;
        res.start=addr?0x7a10000:0x7a00000;if(multi)q.qpcs_mii[1]=&other;
        bool expected=b&&mppe&&present&&addr&&!multi&&!idx&&neg==1&&mode==PHY_INTERFACE_MODE_SGMII;
        assert(ipq_pcs_wave7_serial_speed(&q,idx,neg,mode)==expected);cases++;
    }
    int speeds[]={10,100,1000};
    for(int i=0;i<3;i++){
        for(int initial=0;initial<3;initial++){
            init(initial);require_serial=true;
            assert(!ipq_pcs_config(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_SGMII,NULL,false));
            if(initial!=PHY_INTERFACE_MODE_SGMII)assert(!writes); /* 0479 deferral */
            writes=force_writes=last_force_write=0;
            ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_SGMII,speeds[i],1);
            qualified(speeds[i]);cases++;
        }
    }
    /* Failure propagation: calibration/setup/speed/pulse writes never log success. */
    for(unsigned fail=1;fail<=8;fail++){
        init(PHY_INTERFACE_MODE_SGMII);require_serial=true;fail_at=fail;
        ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_SGMII,1000,1);
        assert(errors&&!post_logs);cases++;
    }
    for(unsigned fail=1;fail<=3;fail++){
        init(PHY_INTERFACE_MODE_SGMII);require_serial=true;fail_read_at=fail;
        ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_SGMII,1000,1);
        assert(!errors&&!post_logs&&pulses==2);cases++;
    }
    /* No format-bit change or force-policy change for any nonopt-in PCS. */
    init(PHY_INTERFACE_MODE_SGMII);board=false;
    ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_SGMII,1000,1);
    assert(regs[PCS_MODE_CTRL/4]&PCS_MODE_AUTONEG_ATH);
    assert(regs[PCS_MII_CTRL(0)/4]&PCS_MII_FORCE_MODE);
    assert(speed_writes==1&&pulses==2&&!post_logs);cases++;
    init(PHY_INTERFACE_MODE_NA);
    assert(!ipq_pcs_config(&m.pcs,PHYLINK_PCS_NEG_INBAND_ENABLED,PHY_INTERFACE_MODE_SGMII,NULL,false));
    ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_INBAND_ENABLED,PHY_INTERFACE_MODE_SGMII,1000,1);
    assert(regs[PCS_MODE_CTRL/4]&PCS_MODE_AUTONEG_ATH);
    assert(!(regs[PCS_MII_CTRL(0)/4]&PCS_MII_FORCE_MODE));
    assert(!speed_writes&&pulses==2&&!post_logs);cases++;
    init(PHY_INTERFACE_MODE_SGMII);
    assert(!ipq_pcs_config(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_2500BASEX,NULL,false));
    ipq_pcs_link_up(&m.pcs,PHYLINK_PCS_NEG_OUTBAND,PHY_INTERFACE_MODE_2500BASEX,2500,1);
    assert(regs[PCS_MODE_CTRL/4]&PCS_MODE_AUTONEG_ATH);
    assert(regs[PCS_MII_CTRL(0)/4]&PCS_MII_FORCE_MODE);
    assert(!speed_writes&&pulses==2&&!post_logs);cases++;
#ifdef HAS_HANDOFF
    /* Exact PCS0 scope; never modify registers or clock/reset state. */
    for(int b=0;b<2;b++)for(int mppe=0;mppe<2;mppe++)
    for(int present=0;present<2;present++)for(int addr=0;addr<2;addr++){
        init(PHY_INTERFACE_MODE_NA);board=b;q.mppe=mppe;resource_present=present;
        res.start=addr?0x7a00000:0x7a10000;
        bool expected=b&&mppe&&present&&addr;
        ipq_pcs_wave7_handoff(&q,"probe");
        assert(reads==(expected?5:0)&&logs==(expected?1:0));
        assert(!errors&&!writes&&!clock_off&&!clock_on);cases++;
    }
    for(unsigned fail=1;fail<=5;fail++){
        init(PHY_INTERFACE_MODE_NA);res.start=0x7a00000;fail_read_at=fail;
        ipq_pcs_wave7_handoff(&q,"before-mode");
        assert(reads==fail&&!logs&&errors==1);
        assert(!writes&&!clock_off&&!clock_on);cases++;
    }
    init(PHY_INTERFACE_MODE_NA);res.start=0x7a00000;
    assert(!ipq_pcs_config_2500basex(&q));
    assert(reads==5&&q.interface==PHY_INTERFACE_MODE_2500BASEX&&clock_off==1&&clock_on==1);
    assert(!ipq_pcs_config_2500basex(&q)&&reads==5);cases++;
#endif
    printf("SERIAL_SPEED_POLICY_PASS: %u actual callback/scope cases\n",cases);
}
