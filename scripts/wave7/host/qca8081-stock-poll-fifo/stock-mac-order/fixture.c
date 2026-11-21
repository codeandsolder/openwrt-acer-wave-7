/* Actual 0493 callbacks, explicit hardware/PCS/EDMA boundaries. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef enum {
	PHY_INTERFACE_MODE_NA, PHY_INTERFACE_MODE_SGMII,
	PHY_INTERFACE_MODE_QSGMII, PHY_INTERFACE_MODE_PSGMII,
	PHY_INTERFACE_MODE_1000BASEX, PHY_INTERFACE_MODE_2500BASEX,
	PHY_INTERFACE_MODE_USXGMII, PHY_INTERFACE_MODE_10G_QXGMII,
	PHY_INTERFACE_MODE_10GBASER
} phy_interface_t;
enum { MLO_AN_PHY, MLO_AN_INBAND, DUPLEX_FULL=1,
       SPEED_10=10, SPEED_100=100, SPEED_1000=1000 };
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
static bool board=true, pm_sleep=false;
#define IS_ENABLED(x) pm_sleep
static bool of_machine_is_compatible(const char *s) {assert(!strcmp(s,"acer,wave7"));return board;}
static const char *phy_modes(phy_interface_t p) {return p==PHY_INTERFACE_MODE_SGMII?"sgmii":"other";}
static const char *phy_speed_to_str(int speed) {return "speed";}
static void dev_info(void *d,const char *f,...) {}
static void dev_err(void *d,const char *f,...) {}
struct phylink_config {int unused;};
struct phylink_link_state {phy_interface_t interface;};
struct phylink_pcs {int unused;};
struct phylink {int unused;};
struct phy_device {u32 phy_id;struct {int addr;} mdio;};
enum ppe_mac_type { PPE_MAC_TYPE_GMAC, PPE_MAC_TYPE_XGMAC };
struct ppe_device {void *dev,*regmap;};
struct ppe_port {
	struct phylink_config phylink_config;
	struct ppe_device *ppe_dev;
	int port_id;
	enum ppe_mac_type mac_type;
	struct phylink_pcs *pcs;
	struct phylink *phylink;
	bool wave7_relink,mac_configured,wave7_gmac_active;
};
struct edma_port_priv {struct ppe_port *ppe_port;};
struct net_device {struct edma_port_priv priv;};
#define netdev_priv(n) (&(n)->priv)
#define PPE_PORT_GMAC_ADDR(x) (0x1000+((x)-1)*0x200)
#define GMAC_ENABLE_ADDR 0
#define GMAC_SPEED_ADDR 4
#define GMAC_TXFCEN (1u<<6)
#define GMAC_RXFCEN (1u<<5)
#define GMAC_DUPLEX_FULL (1u<<4)
#define GMAC_TXEN (1u<<1)
#define GMAC_RXEN (1u<<0)
#define GMAC_TRXEN (GMAC_TXEN|GMAC_RXEN)
#define GMAC_ENABLE_ALL (GMAC_TXFCEN|GMAC_RXFCEN|GMAC_DUPLEX_FULL|GMAC_TRXEN)
#define GMAC_SPEED_M 3
#define GMAC_SPEED_10 0
#define GMAC_SPEED_100 1
#define GMAC_SPEED_1000 2
#define PPE_PORT_SEL_XGMAC(p) (1u<<(p))
#define PPE_PORT_MUX_CTRL_ADDR 0x10000
#define PPE_BM_PORT_FC_MODE_ADDR 0x20000
#define PPE_BM_PORT_FC_MODE_INC 4
#define PPE_BM_PORT_MAC_START 7
#define PPE_BM_PORT_FC_MODE_EN 1
#define PPE_PORT_BRIDGE_CTRL_ADDR 0x60300
#define PPE_PORT_BRIDGE_CTRL_INC 4
#define PPE_PORT_BRIDGE_TXMAC_EN (1u<<16)
enum op { TX_OFF, PREPARE, RATE, MIB_START, SPEED, PARAMETERS, TX_ON,
	RX_ON, COMBINED_ON, FLOW, BRIDGE_ON, COMMIT, BRIDGE_OFF, DRAIN,
	MIB_STOP, RX_OFF, BOTH_OFF, INVALIDATE, MAC_RESET, MUX, X_UP, X_DOWN,
	STOP_QUEUE, CLOSE_DELAY, IRQ_OFF, NAPI_OFF, PHY_STOP,
	DISCONNECT, DESTROY, PCS_PUT };
static enum op seq[128], failure;
static unsigned count;
static unsigned failures;
static bool apply_on_failure, mib_running, committed, carrier;
static u32 gmac, bridge, speed_reg;
static unsigned tested;
static int event(enum op op)
{
	assert(count<sizeof(seq)/sizeof(*seq));
	seq[count++]=op;
	if(op==failure&&failures){failures--;return -EIO;}
	return 0;
}
static void clear(void) {count=0;failures=0;apply_on_failure=false;}
static void fail(enum op op,unsigned times,bool apply) {failure=op;failures=times;apply_on_failure=apply;}
static int write_reg(enum op op,u32 *reg,u32 mask,u32 value)
{
	int ret=event(op);
	assert(!(value&~mask));
	if(!ret||apply_on_failure)*reg=(*reg&~mask)|value;
	return ret;
}
static int regmap_update_bits(void *map,u32 reg,u32 mask,u32 value)
{
	if(reg==PPE_PORT_GMAC_ADDR(2)+GMAC_SPEED_ADDR&&mask==GMAC_SPEED_M)
		return write_reg(SPEED,&speed_reg,mask,value);
	if(reg==PPE_PORT_GMAC_ADDR(2)+GMAC_ENABLE_ADDR&&mask==GMAC_ENABLE_ALL)
		return write_reg(value&GMAC_TRXEN?COMBINED_ON:PARAMETERS,&gmac,mask,value);
	if(reg==PPE_PORT_MUX_CTRL_ADDR)return event(MUX);
	if(reg==PPE_BM_PORT_FC_MODE_ADDR+4*(2+PPE_BM_PORT_MAC_START)&&mask==PPE_BM_PORT_FC_MODE_EN)
		return event(FLOW);
	assert(0);return -EIO;
}
static int regmap_clear_bits(void *map,u32 reg,u32 mask)
{
	if(reg==PPE_PORT_BRIDGE_CTRL_ADDR+8&&mask==PPE_PORT_BRIDGE_TXMAC_EN)
		return write_reg(BRIDGE_OFF,&bridge,mask,0);
	if(reg==PPE_PORT_GMAC_ADDR(2)+GMAC_ENABLE_ADDR){
		assert(mask==GMAC_TXEN||mask==GMAC_RXEN||mask==GMAC_TRXEN);
		return write_reg(mask==GMAC_TXEN?TX_OFF:mask==GMAC_RXEN?RX_OFF:BOTH_OFF,&gmac,mask,0);
	}
	assert(0);return -EIO;
}
static int regmap_set_bits(void *map,u32 reg,u32 mask)
{
	if(reg==PPE_PORT_BRIDGE_CTRL_ADDR+8&&mask==PPE_PORT_BRIDGE_TXMAC_EN)
		return write_reg(BRIDGE_ON,&bridge,mask,mask);
	if(reg==PPE_PORT_GMAC_ADDR(2)+GMAC_ENABLE_ADDR){
		assert(mask==GMAC_TXEN||mask==GMAC_RXEN);
		if(mask==GMAC_RXEN)assert((gmac&GMAC_TRXEN)==GMAC_TXEN);
		return write_reg(mask==GMAC_TXEN?TX_ON:RX_ON,&gmac,mask,mask);
	}
	assert(0);return -EIO;
}
static int ppe_port_gmib_work_start(struct ppe_port *p) {int ret=event(MIB_START);if(!ret)mib_running=true;return ret;}
static void ppe_port_gmib_work_stop(struct ppe_port *p) {event(MIB_STOP);mib_running=false;}
static void fsleep(unsigned us) {assert(us==10000);assert(!(bridge&PPE_PORT_BRIDGE_TXMAC_EN));assert(gmac&GMAC_TXEN);event(DRAIN);}
static int ppe_port_mac_reset(struct ppe_port *p) {assert(!p->wave7_gmac_active);return event(MAC_RESET);}
static int ppe_port_mac_speed_clock_rate_set(struct ppe_port *p,phy_interface_t i,int speed) {return event(RATE);}
static int ppe_port_xgmac_link_up(struct ppe_port *p,phy_interface_t i,int speed,int duplex,bool tx,bool rx) {return event(X_UP);}
static int ppe_port_xgmac_link_down(struct ppe_port *p) {return event(X_DOWN);}
static void ipq_pcs_wave7_relink_invalidate(struct phylink_pcs *p) {event(INVALIDATE);committed=false;}
static int ipq_pcs_wave7_mac_prepare(struct phylink_pcs *p,unsigned mode,phy_interface_t i,int speed,int duplex,bool tx,bool rx,bool ready)
{
	int ret=event(PREPARE);
	return ready?ret:-EINVAL;
}
static void ipq_pcs_wave7_mac_finish(struct phylink_pcs *p,bool success)
{
	committed=success;
	if(success)event(COMMIT);
	else event(INVALIDATE);
}
static void netif_stop_queue(struct net_device *p) {event(STOP_QUEUE);}
static void msleep(unsigned ms) {assert(ms==20);event(CLOSE_DELAY);}
static void edma_cfg_tx_disable_interrupts(int p) {event(IRQ_OFF);}
static void edma_cfg_tx_napi_disable(int p) {event(NAPI_OFF);}
static void phylink_stop(struct phylink *p);
static void rtnl_lock(void) {}
static void rtnl_unlock(void) {}
static void phylink_disconnect_phy(struct phylink *p) {event(DISCONNECT);}
static void phylink_destroy(struct phylink *p) {event(DESTROY);}
static void ipq_pcs_put(struct phylink_pcs *p) {event(PCS_PUT);}
/* CALLBACKS */
static struct ppe_device dev;
static struct phylink_pcs pcs;
static struct phylink phylink;
static struct ppe_port port;
static struct net_device netdev;
static struct phy_device phy={.phy_id=0x004dd101,.mdio.addr=0x18};
static void up(phy_interface_t i,int speed,int duplex,bool tx,bool rx)
{
	ppe_port_mac_link_up(&port.phylink_config,&phy,MLO_AN_PHY,i,speed,duplex,tx,rx);
}
static void down(void)
{
	ppe_port_mac_link_down(&port.phylink_config,MLO_AN_PHY,PHY_INTERFACE_MODE_SGMII);
	carrier=false;
}
static void phylink_stop(struct phylink *p) {event(PHY_STOP);if(carrier)down();}
static void init(bool opt)
{
	port=(struct ppe_port){.ppe_dev=&dev,.port_id=2,.pcs=&pcs,.phylink=&phylink,
			       .wave7_relink=opt,.mac_configured=true};
	netdev.priv.ppe_port=&port;
	gmac=0xa5000000;bridge=0xa4000000;speed_reg=0x100;
	mib_running=committed=carrier=false;clear();
}
static void ready(void)
{
	init(true);up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
	assert(committed&&port.wave7_gmac_active&&mib_running);
	assert(gmac==(0xa5000000|GMAC_ENABLE_ALL));
	assert(bridge==(0xa4000000|PPE_PORT_BRIDGE_TXMAC_EN));
	carrier=true;clear();
}
static void closed(void)
{
	assert(!(gmac&GMAC_TRXEN)&&!(bridge&PPE_PORT_BRIDGE_TXMAC_EN)&&!mib_running);
	assert(!port.wave7_gmac_active);
	assert((gmac&~GMAC_ENABLE_ALL)==0xa5000000);
	assert((bridge&~PPE_PORT_BRIDGE_TXMAC_EN)==0xa4000000);
}
static void expect(const enum op *ops,unsigned len)
{
	assert(count==len&&!memcmp(seq,ops,len*sizeof(*ops)));
}
#define EXPECT(...) do {const enum op ops[]={__VA_ARGS__};expect(ops,sizeof(ops)/sizeof(*ops));}while(0)

int main(void)
{
	const int speeds[]={10,100,1000};
	for(unsigned i=0;i<3;i++)for(int duplex=0;duplex<2;duplex++)for(int pause=0;pause<4;pause++){
		if(i==2&&!duplex)continue;
		init(true);
		up(PHY_INTERFACE_MODE_SGMII,speeds[i],duplex,pause&2,pause&1);
		EXPECT(TX_OFF,PREPARE,RATE,MIB_START,SPEED,PARAMETERS,TX_ON,RX_ON,FLOW,BRIDGE_ON,COMMIT);
		assert(committed&&port.wave7_gmac_active&&mib_running);
		assert((gmac&GMAC_ENABLE_ALL)==(GMAC_TRXEN|(duplex?GMAC_DUPLEX_FULL:0)|(pause&2?GMAC_TXFCEN:0)|(pause&1?GMAC_RXFCEN:0)));
		assert((speed_reg&GMAC_SPEED_M)==i);
		clear();down();
		EXPECT(BRIDGE_OFF,DRAIN,MIB_STOP,RX_OFF);
		assert((gmac&GMAC_TRXEN)==GMAC_TXEN&&port.wave7_gmac_active&&!mib_running);
		clear();up(PHY_INTERFACE_MODE_SGMII,speeds[i],duplex,pause&2,pause&1);
		EXPECT(TX_OFF,PREPARE,RATE,MIB_START,SPEED,PARAMETERS,TX_ON,RX_ON,FLOW,BRIDGE_ON,COMMIT);
		tested++;
	}
	/* Non-opt-in GMAC and opted-in XGMAC are unchanged. */
	init(false);up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
	EXPECT(RATE,MIB_START,SPEED,COMBINED_ON,FLOW,BRIDGE_ON);
	clear();down();EXPECT(BRIDGE_OFF,MIB_STOP,BOTH_OFF);closed();
	init(true);port.mac_type=PPE_MAC_TYPE_XGMAC;
	up(PHY_INTERFACE_MODE_2500BASEX,2500,1,true,true);
	EXPECT(PREPARE,RATE,X_UP,FLOW,BRIDGE_ON,COMMIT);
	clear();ppe_port_mac_link_down(&port.phylink_config,MLO_AN_PHY,PHY_INTERFACE_MODE_2500BASEX);
	EXPECT(BRIDGE_OFF,X_DOWN);
	/* Actual administrative stop both with and without a down callback. */
	for(int was_up=0;was_up<2;was_up++){
		ready();if(!was_up){down();clear();}
		assert(!edma_port_close(&netdev));closed();
		if(was_up)EXPECT(STOP_QUEUE,CLOSE_DELAY,IRQ_OFF,NAPI_OFF,PHY_STOP,BRIDGE_OFF,DRAIN,MIB_STOP,RX_OFF,BRIDGE_OFF,MIB_STOP,BOTH_OFF);
		else EXPECT(STOP_QUEUE,CLOSE_DELAY,IRQ_OFF,NAPI_OFF,PHY_STOP,BRIDGE_OFF,MIB_STOP,BOTH_OFF);
	}
	ready();down();clear();ppe_port_phylink_destroy(&port);
	EXPECT(DISCONNECT,DESTROY,BRIDGE_OFF,MIB_STOP,BOTH_OFF,PCS_PUT);closed();
	ready();down();clear();
	struct phylink_link_state other={.interface=PHY_INTERFACE_MODE_2500BASEX};
	ppe_port_mac_config(&port.phylink_config,MLO_AN_PHY,&other);
	EXPECT(INVALIDATE,BRIDGE_OFF,MIB_STOP,BOTH_OFF,MAC_RESET,MUX);
	closed();assert(port.mac_type==PPE_MAC_TYPE_XGMAC&&port.mac_configured);
	/* Each link-up stage fails, including applied-before-error writes.
	 * Cleanup must close the bridge, stop MIB and disable both gates. */
	const enum op upfail[]={TX_OFF,PREPARE,RATE,MIB_START,SPEED,PARAMETERS,TX_ON,RX_ON,FLOW,BRIDGE_ON};
	for(unsigned i=0;i<sizeof(upfail)/sizeof(*upfail);i++)for(int apply=0;apply<2;apply++){
		ready();down();clear();fail(upfail[i],1,apply);
		up(PHY_INTERFACE_MODE_SGMII,1000,1,true,true);
		assert(!committed);closed();tested++;
	}
	for(int apply=0;apply<2;apply++){
		ready();fail(BRIDGE_OFF,1,apply);down();closed();assert(!committed);
		ready();fail(RX_OFF,1,apply);down();closed();assert(!committed);
	}
	/* A failed quiesce leaves ownership set and retries on next lifecycle. */
	ready();down();clear();fail(BOTH_OFF,1,false);
	assert(ppe_port_wave7_gmac_quiesce(&port)==-EIO&&port.wave7_gmac_active);
	clear();assert(!ppe_port_wave7_gmac_quiesce(&port));closed();
	ready();down();clear();fail(BRIDGE_OFF,1,false);
	assert(ppe_port_wave7_gmac_quiesce(&port)==-EIO&&port.wave7_gmac_active);
	assert(!(gmac&GMAC_TRXEN));clear();assert(!ppe_port_wave7_gmac_quiesce(&port));closed();
	ready();down();clear();fail(BOTH_OFF,1,false);
	ppe_port_mac_config(&port.phylink_config,MLO_AN_PHY,&other);
	assert(!port.mac_configured&&port.wave7_gmac_active);
	EXPECT(INVALIDATE,BRIDGE_OFF,MIB_STOP,BOTH_OFF);
	clear();assert(!ppe_port_wave7_gmac_quiesce(&port));closed();
	printf("WAVE7_STOCK_MAC_ORDER_PASS %u tuple/failure cases; exact ordering, scope, stop/teardown, failure recovery PASS\n",tested);
}
