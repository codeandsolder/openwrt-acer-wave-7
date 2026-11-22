/* Offline ARM instruction replay. All peripheral accesses are mocked. */
typedef unsigned int u32;
typedef unsigned char u8;
enum { CASE, POLL, BRIDGE, TX, RX, DELAY, MODE_RECORD, MODE_APPLY,
       GATE, RATE, MAC_SPEED, DUPLEX, TX_PAUSE, RX_PAUSE, REG_READ, REG_WRITE,
       NOTIFY, FDB, MODE_STATUS, END, ERROR, MII_READ, MMD_READ, MMD_WRITE,
       DEBUG_READ, DEBUG_WRITE, BUS_LOCK, WORK_LOCK, WORK_QUEUE, MAC_TYPE, MAC_PARAM_WRITE, WORK_CANCEL, MODE_WRAPPER, MODE_SYS, MODE_PORT5_CLOCK, MODE_TX, MODE_RX, MODE_UNIPHY, MODE_MUX, MODE_CACHE, MODE_RET };
struct event { u32 type, a, b, c; };
static struct event trace[131072];
static u32 count;
static void record(u32 type, u32 a, u32 b, u32 c) {
    if (count >= sizeof(trace)/sizeof(*trace)) __builtin_trap();
    trace[count++] = (struct event){type,a,b,c};
}
static long syscall3(u32 nr, u32 a, u32 b, u32 c) {
    register u32 r0 asm("r0")=a, r1 asm("r1")=b, r2 asm("r2")=c, r7 asm("r7")=nr;
    asm volatile("svc #0" : "+r"(r0) : "r"(r1),"r"(r2),"r"(r7) : "memory");
    return (long)r0;
}
__attribute__((noreturn)) static void finish(u32 status) {
    u32 len=count*sizeof(*trace);
    if (syscall3(4,1,(u32)trace,len)!=(long)len) status=99;
    syscall3(1,status,0,0);
    __builtin_unreachable();
}
__attribute__((noreturn)) void mock_unexpected(void) { record(ERROR,0,0,0); finish(91); }
#define CHECK(x) do { if (!(x)) { record(ERROR,__LINE__,0,0); finish(92); } } while (0)
#define PORT_CHECK CHECK(dev==0 && port==2)
static u32 real_mode, applying, wrappers[2], mode_fail;
u32 mock_status_global[7];
static u32 host_mode, copper_mode, phy_info[160], ctrl, status_error;
static u32 status[5], ctx[0x600/4];
static u32 bridge_ctrl, mac_enable;
static u32 mac_gate_count, param_case, mac_speed, bm_fc;
static u32 full_path, phydev[0x400/4], bus[0x100/4], phy_ops[0x120/4], adpt_ops[0x204/4];
static u32 fifo, seed, c22_status, ms_fault, bus_locked, work_locked, write_error;
u32 mock_system_wq=0x12345678;
u32 mock___stack_chk_guard=0x863510ae, mock_ssdk_log_level=0;
void mock___stack_chk_fail(void) { mock_unexpected(); }
void *mock_memset(void *dest,int val,u32 len) {
    u8 *p=dest; for (u32 i=0;i<len;i++) p[i]=(u8)val; return dest;
}
static void delay(u32 loops) { record(DELAY,loops,0,0); }
struct { void (*delay)(u32), (*constant)(u32), (*variable)(u32); u32 ticks; }
mock_arm_delay_ops={delay,delay,delay,0};
u32 mock_qca_ssdk_port_bmp_get(u32 dev) { CHECK(dev==0); return 4; }
u32 mock_hsl_port_is_sfp(u32 dev,u32 port) { PORT_CHECK; return 0; }
static u32 selector_feature;
u32 mock_hsl_port_feature_get(u32 dev,u32 port,u32 feature) {
    PORT_CHECK;
    if(feature==4) return selector_feature;
    CHECK(feature==64 || (applying && feature==128)); return 0;
}
u32 mock_hppe_mac_port_valid_check(u32 dev,u32 port) { PORT_CHECK; return 1; }
u32 mock_hsl_port_prop_check(u32 dev,u32 port,u32 prop) {
    if(applying) { CHECK(dev==0 && (port==1 || port==2) && (prop==2 || prop==3)); return prop==2; }
    PORT_CHECK; CHECK(prop==0 || prop==2); return 1;
}
static u32 synthetic_status(u32 dev,u32 phy,u32 *out) {
    CHECK(dev==0 && phy==24);
    for(u32 i=0;i<5;i++) out[i]=status[i]; return status_error;
}
u32 *mock_hsl_phy_api_ops_get(u32 dev,u32 port) {
    PORT_CHECK; record(POLL,status[0],status[1],status_error);
    phy_ops[0xf0/4]=full_path ? 0x01067640 : (u32)synthetic_status;
    return phy_ops;
}
u32 mock_hsl_port_prop_get_phyid(u32 dev,u32 port,u32 *out) {
    PORT_CHECK; *out=24; return 0;
}
u32 mock_adpt_hppe_port_interface_mode_get(u32 dev,u32 port,u32 *out) { PORT_CHECK; *out=host_mode; return 0; }
u32 mock_ssdk_dt_get_port_mode(u32 dev,u32 port) { PORT_CHECK; return host_mode; }
u32 mock_adpt_hppe_port_interface_mode_status_get(u32 dev,u32 port,u32 *out) {
    PORT_CHECK;
    u32 ret=0;
    if (full_path) ret=((u32 (*)(u32,u32,u32 *))0x010679d4)(dev,24,out);
    else *out=copper_mode;
    record(MODE_STATUS,*out,ret,0); return ret;
}
u32 *mock_hsl_phy_info_get(u32 dev) { CHECK(dev==0); return phy_info; }
u32 mock__adpt_hppe_port_interface_mode_apply(u32 dev,u32 flag) {
    CHECK(dev==0 && flag==0); host_mode=phy_info[102]; record(MODE_RECORD,host_mode,0,0);
    record(MODE_APPLY,host_mode,0,0);
    if(!real_mode) return 0;
    applying=1;
    u32 ret=((u32 (*)(u32,u32))0x01009c3c)(dev,flag);
    applying=0;
    record(MODE_CACHE,ctx[(0x208+8)/4],ctx[(0x248+8)/4],ctx[(0x288+8)/4]);
    record(MODE_RET,ret,ctx[(0x348+8)/4],ctx[(0x388+8)/4]);
    return ret;
}
u32 mock_ssdk_dt_global_get_mac_mode(u32 dev,u32 instance) {
    CHECK(dev==0);
    if(real_mode) { CHECK(instance<2); return wrappers[instance]; }
    CHECK(instance==1); return 0x0c;
}
u32 mock_ssdk_dt_global_set_mac_mode(u32 dev,u32 instance,u32 mode) {
    CHECK(applying && dev==0 && instance<2);
    wrappers[instance]=mode; record(MODE_WRAPPER,instance,mode,0); return 0;
}
void mock_ssdk_gcc_uniphy_sys_set(u32 dev,u32 instance,u32 enable) {
    CHECK(applying && dev==0 && instance<2);
    record(MODE_SYS,instance,enable,0);
}
void mock_ssdk_uniphy_port5_clock_source_set(void) {
    CHECK(applying); record(MODE_PORT5_CLOCK,0,0,0);
}
u32 mock_mode_tx_gate(u32 dev,u32 port,u32 val) {
    CHECK(applying && dev==0 && port==2 && val==0);
    record(MODE_TX,port,val,0); return 0;
}
u32 mock_mode_rx_gate(u32 dev,u32 port,u32 val) {
    CHECK(applying && dev==0 && port==2 && val==0);
    record(MODE_RX,port,val,0); return 0;
}
u32 mock_adpt_hppe_uniphy_mode_set(u32 dev,u32 instance,u32 mode) {
    CHECK(applying && dev==0 && instance==1 && (mode==12 || mode==15));
    record(MODE_UNIPHY,instance,mode,0); return mode_fail==1?0xfffffffbu:0;
}
u32 mock_adpt_hppe_port_mux_mac_type_set(u32 dev,u32 port,u32 m0,u32 m1,u32 m2) {
    CHECK(applying && dev==0 && port==2 && m0==12 && m2==255 && (m1==12 || m1==15));
    record(MODE_MUX,port,m1,0); return mode_fail==2?0xfffffffbu:0;
}
int mock_printk(const char *fmt, ...) {
    (void)fmt; CHECK(applying && mode_fail); return 0;
}
u32 mock_adpt_ppe_type_get(u32 dev) { CHECK(dev==0); return 3; }
u32 mock_hsl_port_phyid_get(u32 dev,u32 port) { PORT_CHECK; return 0x004dd101; }
u32 mock_ssdk_uniphy_valid_check(u32 dev,u32 instance,u32 mask) {
    CHECK(dev==0 && instance==1); (void)mask; return 1;
}
u32 mock_of_device_is_compatible(void *node,const char *name) {
    (void)node;
    const char expected[]="qcom,ess-switch-ipq95xx";
    for(u32 i=0;i<sizeof(expected);i++) CHECK(name[i]==expected[i]);
    return 0;
}
u32 mock_ssdk_uniphy_clock_enable(u32 dev,u32 id,u32 enable) {
    CHECK(dev==0); record(GATE,id,enable,0); return 0;
}
u32 mock_ssdk_uniphy_clock_rate_set(u32 dev,u32 id,u32 rate) {
    CHECK(dev==0); record(RATE,id,rate,0); return 0;
}
#define MOCK_PORT(name,type) u32 mock_adpt_hppe_port_##name(u32 dev,u32 port,u32 val) { PORT_CHECK; record(type,val,0,0); return 0; }
/* Replay the real bridge helper and real register-address calculation.
 * At the hardware boundary, enforce the exact port-2 offset and isolate
 * the bridge TX bit from the GMAC TX/RX enable bits. */
/* Worker fixture holds MAC type at GMAC to isolate transition policy.
 * The separately replayed selector checks the actual wrapper-dependent type. */
u32 mock_qca_hppe_port_mac_type_get(u32 dev,u32 port) {
    PORT_CHECK; CHECK(host_mode==4 || host_mode==6); return 1;
}
u32 mock_hppe_reg_get(u32 dev,u32 reg,u32 *out) {
    CHECK(dev==0);
    if(reg==0x60308) *out=bridge_ctrl;
    else if(reg==0x1200) *out=mac_enable;
    else if(param_case && reg==0x1204) *out=mac_speed;
    else mock_unexpected();
    return 0;
}
u32 mock_hppe_reg_set(u32 dev,u32 reg,u32 value) {
    CHECK(dev==0);
    if(param_case) {
        if(reg==0x1200) mac_enable=value;
        else if(reg==0x1204) mac_speed=value;
        else if(reg==0x600124) bm_fc=value;
        else mock_unexpected();
        record(MAC_PARAM_WRITE,reg,value,0);
        return 0;
    }
    if(reg==0x60308) {
        CHECK((value & ~0x10000u)==(bridge_ctrl & ~0x10000u));
        bridge_ctrl=value; record(BRIDGE,(value>>16)&1,0,0);
    } else if(reg==0x1200) {
        // The worker's first and second GMAC calls on up are TX;
        // the third is RX. A down edge has only an RX call.
        u32 link=ctx[(0x208+8)/4];
        u32 mask;
        if (full_path ? (c22_status!=0xffff && (c22_status&0x400)!=0) : status[0])
            mask=mac_gate_count<2 ? 2 : 1;
        else { CHECK(link==1 && mac_gate_count==0); mask=1; }
        CHECK((value & ~mask)==(mac_enable & ~mask));
        mac_enable=value; ++mac_gate_count;
        record(mask==2?TX:RX,!!(value&mask),0,0);
    } else mock_unexpected();
    return 0;
}
MOCK_PORT(mac_speed_set,MAC_SPEED)
MOCK_PORT(mac_duplex_set,DUPLEX)
u32 mock_tx_pause(u32 dev,u32 port,u32 val) { PORT_CHECK; record(TX_PAUSE,val,0,0); return 0; }
u32 mock_rx_pause(u32 dev,u32 port,u32 val) { PORT_CHECK; record(RX_PAUSE,val,0,0); return 0; }
u32 mock_hppe_uniphy_reg_get(u32 dev,u32 addr,u32 instance,u32 *out) {
    CHECK(dev==0); *out=ctrl; record(REG_READ,instance,addr,ctrl); return 0;
}
u32 mock_hppe_uniphy_reg_set(u32 dev,u32 addr,u32 instance,u32 val) {
    CHECK(dev==0); ctrl=val; record(REG_WRITE,instance,addr,val); return 0;
}
u32 mock_ssdk_port_link_notify(u32 port,u32 link,u32 speed,u32 duplex) {
    CHECK(port==2); record(NOTIFY,link,speed,duplex); return 0;
}
u32 mock_adpt_hppe_fdb_del_by_port(u32 dev,u32 port,u32 flag) { PORT_CHECK; record(FDB,flag,0,0); return 0; }
u32 *mock_adpt_api_ptr_get(u32 dev) {
    CHECK(dev==0 && work_locked); adpt_ops[0x200/4]=0x0100adec; return adpt_ops;
}
u32 mock_queue_delayed_work_on(u32 cpu,u32 wq,void *work,u32 delay_jiffies) {
    CHECK(!work_locked && !bus_locked && wq==mock_system_wq);
    CHECK(work==(u8*)ctx+1252); record(WORK_QUEUE,cpu,delay_jiffies,0); return 1;
}
static u32 lifecycle_has_context;
void *mock_ssdk_phy_priv_data_get(u32 dev) {
    CHECK(dev==0); return lifecycle_has_context ? ctx : (void*)0;
}
u32 mock_ssdk_is_emulation(u32 dev) { CHECK(dev==0); return 0; }
u32 mock_cancel_delayed_work_sync(void *work) {
    CHECK(work==(u8*)ctx+1252 && !work_locked && !bus_locked);
    record(WORK_CANCEL,0,0,0); return 1;
}
static void lifecycle_case(u32 id,u32 chip,u32 exists,u32 start) {
    record(CASE,id,chip,(exists<<1)|start);
    lifecycle_has_context=exists;
    ((u8*)ctx)[0xf8]=chip; ((u8*)ctx)[0x488]=0;
    u32 ret=((u32 (*)(u32))(0x01000000+(start?0x91e3c:0x91dec)))(0);
    record(END,ret,0,0);
}
void *mock_ssdk_phy_miibus_get(u32 dev,u32 phy) {
    CHECK(dev==0 && (phy==24 || phy==25)); return bus;
}
void mock_mutex_lock(void *ptr) {
    if (ptr==(u8*)bus+88) { CHECK(!bus_locked); bus_locked=1; record(BUS_LOCK,1,0,0); }
    else { CHECK(ptr==(u8*)ctx+1232 && !work_locked); work_locked=1; record(WORK_LOCK,1,0,0); }
}
void mock_mutex_unlock(void *ptr) {
    if (ptr==(u8*)bus+88) { CHECK(bus_locked); bus_locked=0; record(BUS_LOCK,0,0,0); }
    else { CHECK(ptr==(u8*)ctx+1232 && work_locked && !bus_locked); work_locked=0; record(WORK_LOCK,0,0,0); }
}
u32 mock_hsl_phy_phydev_get(u32 dev,u32 phy,u32 **out) {
    CHECK(dev==0 && phy==24); *out=phydev; return 0;
}
u32 mock___hsl_phy_mii_reg_read(u32 dev,u32 phy,u32 reg) {
    CHECK(dev==0 && phy==24 && bus_locked);
    u32 value;
    switch(reg) {
        case 2: value=0x004d; break;
        case 3: value=0xd101; break;
        case 10: value=ms_fault ? 0x8000 : 0; break;
        case 17: value=c22_status; break;
        case 31: value=copper_mode==6 ? 0xa544 : 0x8544; break;
        default: mock_unexpected();
    }
    record(MII_READ,phy,reg,value); return value;
}
u32 mock___hsl_phy_mmd_reg_read(u32 dev,u32 phy,u32 c45,u32 mmd,u32 reg) {
    CHECK(dev==0 && c45==1 && bus_locked);
    u32 value;
    if(phy==25 && mmd==1 && reg==0x9072) value=fifo;
    else if(phy==24 && mmd==1 && reg==4) value=0x2000;
    else if(phy==24 && mmd==7 && reg==0x901d) value=0;
    else mock_unexpected();
    record(MMD_READ,phy,(mmd<<16)|reg,value); return value;
}
u32 mock___hsl_phy_mmd_reg_write(u32 dev,u32 phy,u32 c45,u32 mmd,u32 reg,u32 value) {
    CHECK(dev==0 && phy==25 && c45==1 && mmd==1 && reg==0x9072 && bus_locked);
    record(MMD_WRITE,phy,(mmd<<16)|reg,value);
    if(!write_error) fifo=value;
    return write_error;
}
u32 mock___hsl_phy_debug_reg_read(u32 dev,u32 phy,u32 reg) {
    CHECK(dev==0 && phy==24 && reg==9 && bus_locked);
    record(DEBUG_READ,phy,reg,seed); return seed;
}
u32 mock___hsl_phy_debug_reg_write(u32 dev,u32 phy,u32 reg,u32 val) {
    CHECK(dev==0 && phy==24 && reg==9 && bus_locked);
    seed=val; record(DEBUG_WRITE,phy,reg,val); return 0;
}
u32 mock_prandom_u32(void) { return 149; }
unsigned long long mock___aeabi_uidivmod(u32 n,u32 d) {
    CHECK(d!=0);
    u32 q=0,r=0;
    for(u32 bit=1u<<31; bit; bit>>=1) {
        u32 carry=r>>31;
        r=(r<<1)|((n&bit)!=0);
        if(carry || r>=d) { r-=d; q|=bit; }
    }
    return ((unsigned long long)r<<32)|q;
}
static void set_old(u32 link,u32 speed,u32 duplex,u32 tx,u32 rx) {
    mock_memset(ctx,0,sizeof(ctx));
    bridge_ctrl=0xa5a45a5a | (link<<16);
    mac_enable=0xa5a45a5a | link; // TX remains enabled after stock down.
    mac_gate_count=0;
    ctx[(0x208+8)/4]=link; ctx[(0x248+8)/4]=speed; ctx[(0x288+8)/4]=duplex;
    ctx[(0x348+8)/4]=tx; ctx[(0x388+8)/4]=rx;
}
static void run_case(u32 id,u32 old_link,u32 old_speed,u32 old_duplex,u32 old_tx,u32 old_rx,
                     u32 link,u32 speed,u32 duplex,u32 tx,u32 rx,u32 hmode,u32 cmode,u32 err) {
    record(CASE,id,(old_link<<16)|(old_speed<<4)|(old_duplex<<2)|(old_tx<<1)|old_rx,
           (link<<16)|(speed<<4)|(duplex<<2)|(tx<<1)|rx);
    full_path=0;
    set_old(old_link,old_speed,old_duplex,old_tx,old_rx);
    status[0]=link; status[1]=speed; status[2]=duplex; status[3]=tx; status[4]=rx;
    host_mode=hmode; copper_mode=cmode; ctrl=0xa5a5884c; status_error=err;
    ((void (*)(void *))0x0100adec)(ctx);
    record(END,ctx[(0x208+8)/4],ctx[(0x248+8)/4],ctx[(0x288+8)/4]);
}
static void full_case(u32 id,u32 old_link,u32 old_speed,u32 spec,u32 mode,u32 initial_fifo,u32 fault,u32 err) {
    record(CASE,id,0,0);
    set_old(old_link,old_speed,1,0,0);
    full_path=1; host_mode=4; copper_mode=mode; ctrl=0xa5a5884c;
    fifo=initial_fifo; seed=0xa002; c22_status=spec; ms_fault=fault; write_error=err;
    for(u32 i=0;i<5;i++) status[i]=0;
    status_error=0; CHECK(!bus_locked && !work_locked);
    ((void (*)(void *))0x010918e8)((u8*)ctx+1252);
    CHECK(!bus_locked && !work_locked);
    record(END,ctx[(0x208+8)/4],ctx[(0x248+8)/4],ctx[(0x288+8)/4]);
}
u32 mock_qca808x_phy_get_partner_ability(u32 dev,u32 phy,u32 *adv) {
    CHECK(dev==0 && phy==24); *adv=0; return 0;
}
void *mock_qca808x_lp_adv_to_ethtool_adv(void *dev,u32 adv) {
    CHECK(dev==phydev && adv==0); return dev;
}
void mock_phy_resolve_aneg_pause(void *dev) { CHECK(dev==phydev); }
static void phylib_case(u32 id,u32 spec,u32 initial_fifo) {
    static u32 priv[2], phy_rec[4];
    record(CASE,id,0,0);
    mock_memset(phydev,0,sizeof(phydev));
    priv[1]=(u32)phy_rec; phy_rec[2]=0; phy_rec[3]=24;
    phydev[0x294/4]=(u32)priv;
    full_path=1; fifo=initial_fifo; seed=0xa002; c22_status=spec;
    ms_fault=0; write_error=0;
    CHECK(!bus_locked && !work_locked);
    CHECK(((u32 (*)(void *))0x01069cc4)(phydev)==0);
    CHECK(!bus_locked && !work_locked);
    record(END,(((u8*)phydev)[0x23d]>>2)&1,phydev[0x24c/4],phydev[0x250/4]);
}
u32 mock_qca_hppe_port_mac_type_set(u32 dev,u32 port,u32 type) {
    PORT_CHECK; record(MAC_TYPE,type,0,0); return 0;
}
/* Execute the original selector block at 0x88c4 with its required
 * live register inputs. Its common continuation is an explicit exit
 * boundary; do not execute the rest of mode application. */
__attribute__((naked)) static void selector(u32 wrapper __attribute__((unused))) {
    asm volatile("push {r4,r5,r7,lr}\nmov r7,r0\nmov r4,#2\nmov r5,#0\nldr r3,=0x010088c4\nbx r3");
}
__attribute__((naked)) void mock_selector_return(void) {
    asm volatile("pop {r4,r5,r7,pc}");
}
static void selector_case(u32 id,u32 wrapper,u32 feature) {
    record(CASE,id,wrapper,feature);
    selector_feature=feature; phy_info[102]=255;
    selector(wrapper);
    record(END,phy_info[102],0,0);
}
/* Direct low-level parameter helpers; the worker matrix retains its
 * original parameter mock boundaries. Execute actual ARM RMW and
 * register address helpers in these independent cases. */
static void parameter_case(u32 id,u32 offset,u32 value,u32 expected_reg,u32 expected) {
    record(CASE,id,offset,value);
    param_case=1;
    mac_enable=0xa5a45a5a; mac_speed=0x5a5aa5a5; bm_fc=0xf0f0f0f0;
    CHECK(((u32 (*)(u32,u32,u32))(0x01000000+offset))(0,expected_reg==0x600124?9:2,value)==0);
    u32 actual=expected_reg==0x1200?mac_enable:expected_reg==0x1204?mac_speed:bm_fc;
    CHECK(actual==expected);
    record(END,actual,0,0);
    param_case=0;
}
/* New cases execute mode apply in the actual worker, with physical
 * mode/clock/mux hardware calls as explicit boundaries. Port1 remains
 * on forced SGMII+; port2's mode is the raw PHY report. */
static void mode_apply_case(u32 id,u32 old_link,u32 speed,u32 old_speed,u32 old_mode,u32 new_mode,u32 fail) {
    real_mode=1;mode_fail=fail;
    wrappers[0]=12;wrappers[1]=old_mode==4?15:12;
    phy_info[101]=6;phy_info[102]=old_mode;
    /* Original .bss structure is relocated to writable fixture storage. */
    static u32 devices[3];
    devices[0]=(u32)ctx;
    mock_status_global[6]=(u32)devices;
    run_case(id,old_link,old_speed,1,0,0,!old_link,speed,1,0,0,old_mode,new_mode,0);
    real_mode=0;mode_fail=0;
}
/* Preserve the actual cache across subsequent worker invocations. */
static void mode_followup(u32 id,u32 link,u32 speed,u32 mode) {
    record(CASE,id,0,0);
    real_mode=1;mode_fail=0;full_path=0;status_error=0;
    mac_gate_count=0;
    status[0]=link;status[1]=speed;status[2]=1;status[3]=status[4]=0;
    copper_mode=mode;
    ((void (*)(void *))0x0100adec)(ctx);
    record(END,ctx[(0x208+8)/4],ctx[(0x248+8)/4],ctx[(0x288+8)/4]);
    real_mode=0;
}
void _start(void) {
    run_case(0,0,1000,1,0,0, 0,1000,1,0,0,4,4,0);
    run_case(1,1,1000,1,0,0, 1,1000,1,0,0,4,4,0);
    run_case(2,1,1000,1,0,0, 0,1000,1,0,0,4,4,0);
    run_case(3,0,1000,1,0,0, 1,1000,1,0,0,4,4,0);
    run_case(4,0,100,1,0,0, 1,1000,1,0,0,4,4,0);
    run_case(5,0,1000,1,0,0, 1,1000,0,0,0,4,4,0);
    run_case(6,0,1000,1,0,0, 1,1000,1,1,0,4,4,0);
    run_case(7,0,1000,1,0,0, 1,1000,1,0,0,4,4,1);
    run_case(8,0,1000,1,0,0, 1,2500,1,0,0,4,6,0);
    full_case(9,1,1000,0x2500,4,0x8844,0,0);
    full_case(10,0,1000,0x2500,4,0x8044,0,0);
    full_case(11,1,1000,0,4,0x8844,0,0);
    full_case(12,0,1000,0,4,0x8044,0,0);
    full_case(13,0,1000,0x2500,4,0x8844,0,1);
    full_case(14,0,1000,0x2500,4,0xffff,0,0);
    full_case(15,0,1000,0,4,0x8044,1,0);
    full_case(16,1,1000,0xffff,4,0x8844,0,0);
    full_case(17,0,1000,0x2600,6,0x8044,0,0);
    // Deliberately inconsistent interface report with an unchanged
    // negotiated tuple: mode apply can still run, independently of
    // the explicit host clock/reset path.
    run_case(18,0,1000,1,0,0, 1,1000,1,0,0,6,4,0);
    phylib_case(19,0x2500,0x8844);
    phylib_case(20,0,0x8844);
    phylib_case(21,0xffff,0x8844);
    selector_case(22,15,0);
    selector_case(23,12,0);
    selector_case(24,12,1);
    parameter_case(25,0x70b4,10,0x1204,0x5a5aa5a4);
    parameter_case(26,0x70b4,100,0x1204,0x5a5aa5a5);
    parameter_case(27,0x70b4,1000,0x1204,0x5a5aa5a6);
    parameter_case(28,0x70b4,2500,0x1204,0x5a5aa5a6);
    parameter_case(29,0x6210,0,0x1200,0xa5a45a1a);
    parameter_case(30,0x6210,1,0x1200,0xa5a45a5a);
    parameter_case(31,0x6298,0,0x1200,0xa5a45a5a);
    parameter_case(32,0x6298,1,0x1200,0xa5a45a7a);
    parameter_case(33,0x6320,0,0x1200,0xa5a45a4a);
    parameter_case(34,0x6320,1,0x1200,0xa5a45a5a);
    parameter_case(35,0x23f50,0,0x600124,0);
    parameter_case(36,0x23f50,1,0x600124,1);
    for(u32 i=0;i<10;i++) {
        const u32 chips[]={0x20,0xee,0x15,0x42,0x20};
        lifecycle_case(37+i,chips[i/2],i<8,!(i&1));
    }
    mode_apply_case(47,0,1000,1000,4,4,0);
    mode_apply_case(48,0,1000,1000,6,4,0);
    mode_apply_case(49,0,2500,1000,4,6,0);
    mode_apply_case(50,0,1000,2500,6,4,0);
    mode_apply_case(51,1,1000,1000,6,4,0);
    mode_apply_case(52,0,1000,1000,6,4,1);
    mode_apply_case(53,0,1000,1000,6,4,2);
    mode_apply_case(54,1,1000,1000,4,4,0);
    mode_apply_case(55,0,1000,1000,6,4,0);
    mode_followup(56,1,1000,4);
    mode_followup(57,0,1000,4);
    mode_followup(58,1,1000,4);
    mode_apply_case(59,1,1000,1000,6,4,0);
    mode_followup(60,1,1000,4);
    const u32 speeds[]={10,100,1000,2500};
    u32 id=100;
    for(u32 os=0;os<4;os++) for(u32 od=0;od<2;od++) {
        if(os>=2 && od==0) continue;
        for(u32 op=0;op<4;op++)
        for(u32 ns=0;ns<4;ns++) for(u32 nd=0;nd<2;nd++) {
            if(ns>=2 && nd==0) continue;
            for(u32 np=0;np<4;np++)
            for(u32 edges=0;edges<4;edges++)
                run_case(id++,edges>>1,speeds[os],od,op>>1,op&1,
                         edges&1,speeds[ns],nd,np>>1,np&1,os==3?6:4,ns==3?6:4,0);
        }
    }
    finish(0);
}
