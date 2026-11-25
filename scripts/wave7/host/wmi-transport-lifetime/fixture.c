/* Deterministic source-body fixture. This is not a kernel lockdep test. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int spinlock_t;
typedef u64 atomic64_t;
#define atomic64_read(p) (*(p))
#define atomic64_set(p,v) (*(p)=(v))
#define REG_ALPHA2_LEN 2
#define ALPHA_IS_SET 1
#define ATH12K_FLAG_CRASH_FLUSH 0
#define WMI_SEND_TIMEOUT_HZ 10
#define test_bit(i,p) (!!(*(p)&(1UL<<(i))))
#define might_sleep() ((void)0)
#define lockdep_assert_held(p) assert(*(p))
#define lockdep_assert_wiphy(p) assert(*(p))

struct task_struct { int id; };
static struct task_struct caller={1}, boot={2};
static struct task_struct *current=&caller;
static void (*wait_hook)(void);
static void (*unlock_hook)(void);
static unsigned int wake_count, sends, cases;
static int transport_result;
static bool reject_country;
static bool wiphy_locked=true;
static void spin_lock_bh(int *p) { assert(!*p); *p=1; }
static void spin_unlock_bh(int *p) {
    assert(*p); *p=0;
    if (unlock_hook) {
        void (*hook)(void)=unlock_hook;
        unlock_hook=NULL;
        hook();
    }
}
#define wake_up(q) ((void)(q), ++wake_count)
#define wait_event_timeout(q, condition, timeout) ({ \
    (void)(q); (void)(timeout); \
    for (int tries=0; tries<3; ++tries) { \
        if (condition) break; \
        if (wait_hook) { void (*hook)(void)=wait_hook; wait_hook=NULL; hook(); } \
    } \
    1; \
})
#define ath12k_warn(ab,...) ((void)(ab))
static void mutex_unlock_guard(int **p) { assert(**p); **p=0; }
static int *mutex_lock_guard(int *p) { assert(!*p); *p=1; return p; }
#define guard(kind) __attribute__((cleanup(mutex_unlock_guard))) int *guard_lock=mutex_lock_guard
#define ath12k_ar_to_hw(ar) (&(ar)->hw)
static void complete_all(int *p) { *p=1; }
static void reinit_completion(int *p) { *p=0; }
struct sk_buff { int dummy; };
struct ath12k_base;
struct ath12k_wmi_base {
    struct ath12k_base *ab;
    int tx_credits_wq;
    spinlock_t tx_lock;
    u64 tx_generation;
    struct task_struct *tx_bootstrap;
    bool tx_ready;
};
struct ath12k_hw_params { bool current_cc_support; };
struct ath12k_base {
    struct ath12k_wmi_base wmi_ab;
    unsigned long dev_flags;
    int core_lock;
    struct ath12k_hw_params *hw_params;
};
struct ath12k_wmi_pdev { struct ath12k_wmi_base *wmi_ab; };
struct ath12k_hw { bool regd_updated; };
struct ath12k {
    struct ath12k_base *ab;
    struct ath12k_hw *ah;
    struct { bool *wiphy; } hw;
    int reg_country_lock;
    u8 alpha2[2];
    bool regdom_set_by_user;
    atomic64_t reg_country_generation;
    int regd_update_completed;
};
struct wmi_set_current_country_arg { u8 alpha2[2]; };
struct ath12k_wmi_init_country_arg { union { u8 alpha2[3]; } cc_info; int flags; };
static struct ath12k_hw_params params;
static struct ath12k_base base;
static struct ath12k_wmi_pdev wmi={&base.wmi_ab};
static struct sk_buff skb;
static struct ath12k_hw hw;
static struct ath12k ar;
static u8 last_country[2];
static int last_cmd;
int ath12k_wmi_cmd_send(struct ath12k_wmi_pdev *,struct sk_buff *,u32);
static int ath12k_wmi_cmd_send_nowait(struct ath12k_wmi_pdev *p,struct sk_buff *b,u32 cmd) {
    (void)b; (void)cmd;
    assert(p->wmi_ab->tx_lock);
    assert(p->wmi_ab->tx_ready || p->wmi_ab->tx_bootstrap==current);
    assert(!p->wmi_ab->ab->dev_flags);
    ++sends;
    if (reject_country) atomic64_set(&ar.reg_country_generation,0);
    return transport_result;
}
static int ath12k_wmi_send_set_current_country_cmd(struct ath12k *radio, struct wmi_set_current_country_arg *arg) {
    assert(radio==&ar);
    last_cmd=1; memcpy(last_country,arg->alpha2,2);
    return ath12k_wmi_cmd_send(&wmi,&skb,1);
}
static int ath12k_wmi_send_init_country_cmd(struct ath12k *radio, struct ath12k_wmi_init_country_arg *arg) {
    assert(radio==&ar);
    assert(arg->flags==ALPHA_IS_SET && arg->cc_info.alpha2[2]==0);
    last_cmd=2; memcpy(last_country,arg->cc_info.alpha2,2);
    return ath12k_wmi_cmd_send(&wmi,&skb,2);
}
/* EXTRACTED BODIES */

static void reset_fixture(bool current_cc) {
    assert(!base.wmi_ab.tx_lock && !ar.reg_country_lock);
    base=(struct ath12k_base){0};
    base.wmi_ab.ab=&base;
    base.core_lock=1;
    params.current_cc_support=current_cc;
    base.hw_params=&params;
    hw=(struct ath12k_hw){.regd_updated=true};
    ar=(struct ath12k){.ab=&base,.ah=&hw,.hw={&wiphy_locked}};
    current=&caller;
    sends=0; wake_count=0; last_cmd=0;
    transport_result=0; reject_country=false;
    wait_hook=NULL; unlock_hook=NULL;
}
static void start(void) {
    struct task_struct *saved=current;
    current=&boot;
    assert(ath12k_wmi_tx_start(&base)==0);
    assert(ath12k_wmi_tx_publish(&base)==0);
    current=saved;
}
static void reopen(void) {
    ath12k_wmi_tx_close(&base);
    base.dev_flags=0;
    start();
}
static void crash(void) {
    base.dev_flags=1;
    ath12k_wmi_tx_close(&base);
}
static void test_gate(void) {
    reset_fixture(true);
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==-ESHUTDOWN && !sends);
    current=&boot;
    assert(ath12k_wmi_tx_start(&base)==0);
    assert(ath12k_wmi_tx_start(&base)==-EBUSY);
    current=&caller;
    assert(ath12k_wmi_tx_publish(&base)==-ESHUTDOWN);
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==-ESHUTDOWN && !sends);
    current=&boot;
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==0 && sends==1);
    assert(ath12k_wmi_tx_publish(&base)==0);
    current=&caller;
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==0 && sends==2);
    transport_result=-EAGAIN;
    wait_hook=reopen;
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==-ESHUTDOWN && sends==3);
    transport_result=0;
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==0 && sends==4);
    unlock_hook=reopen;
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==-ESHUTDOWN && sends==4);
    crash();
    assert(ath12k_wmi_tx_start(&base)==-ESHUTDOWN);
    assert(ath12k_wmi_cmd_send(&wmi,&skb,7)==-ESHUTDOWN && sends==4);
    base.dev_flags=0;
    assert(ath12k_wmi_tx_start(&base)==0);
    crash();
    assert(ath12k_wmi_tx_publish(&base)==-ESHUTDOWN);
    assert(wake_count>=4);
    ++cases;
}
static void test_country(bool current_cc, bool initially_ready, int error, bool reset_after_request) {
    const u8 pl[]={'P','L'}, de[]={'D','E'}, us[]={'U','S'};
    reset_fixture(current_cc);
    if (initially_ready) start();
    transport_result=error;
    int ret=ath12k_reg_request_country(&ar,pl,true);
    assert(ret==(initially_ready?error:-ESHUTDOWN));
    assert(ar.regdom_set_by_user && !memcmp(ar.alpha2,pl,2));
    unsigned before=sends;
    assert(ath12k_reg_request_country(&ar,us,false)==0);
    assert(!memcmp(ar.alpha2,pl,2) && sends==before);
    if (reset_after_request || !initially_ready) reopen();
    transport_result=0;
    assert(ath12k_reg_replay_country(&ar)==0);
    assert(last_cmd==(current_cc?1:2) && !memcmp(last_country,pl,2));
    assert(ar.reg_country_generation==base.wmi_ab.tx_generation);
    before=sends;
    assert(ath12k_reg_replay_country(&ar)==0 && sends==before);
    assert(ath12k_reg_request_country(&ar,pl,true)==0 && sends==before);
    crash();
    assert(ath12k_reg_request_country(&ar,de,true)==-ESHUTDOWN && sends==before);
    reopen();
    assert(ath12k_reg_replay_country(&ar)==0 && sends==before+1);
    assert(!memcmp(last_country,de,2));
    ++cases;
}
static void test_automatic(bool current_cc) {
    const u8 us[]={'U','S'}, pl[]={'P','L'};
    reset_fixture(current_cc); start();
    assert(ath12k_reg_request_country(&ar,us,false)==0);
    assert(sends==(unsigned)current_cc);
    assert(ath12k_reg_request_country(&ar,pl,true)==0);
    unsigned before=sends;
    assert(ath12k_reg_request_country(&ar,us,false)==0 && sends==before);
    assert(!memcmp(ar.alpha2,pl,2));
    ++cases;
}
static void test_rejection(bool current_cc) {
    const u8 pl[]={'P','L'};
    reset_fixture(current_cc); start();
    reject_country=true;
    assert(ath12k_reg_request_country(&ar,pl,true)==0);
    assert(ar.reg_country_generation==0 && sends==1);
    reject_country=false;
    assert(ath12k_reg_request_country(&ar,pl,true)==0 && sends==2);
    assert(ar.reg_country_generation==base.wmi_ab.tx_generation);
    ++cases;
}
int main(void) {
    test_gate();
    for (int cc=0;cc<2;cc++) {
        test_automatic(cc);
        test_rejection(cc);
        for (int ready=0;ready<2;ready++)
            for (int err=0;err<2;err++)
                for (int reset=0;reset<2;reset++)
                    test_country(cc,ready,err?-EIO:0,reset);
    }
    printf("PASS: %u deterministic actual-source cases\n",cases);
    return 0;
}
