#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>

typedef uint8_t u8;
typedef uint32_t u32;
#define IEEE80211_NUM_TIDS 16
#define HAL_PN_TYPE_NONE 0
#define WMI_PEER_SET_DEFAULT_ROUTING 42
#define DP_RX_HASH_ENABLE 1
#define min(a,b) ((a)<(b)?(a):(b))
#define ath12k_warn(ab,...) ((void)(ab))
struct ath12k_sta { bool defer_mlo_dp, primary_selected; u8 primary_link_id; };
struct ath12k_dp_peer { bool dp_setup_done; };
struct ath12k_dp_link_peer {
    struct ath12k_dp_peer *dp_peer;
    struct ath12k_sta *sta;
    bool mlo, primary_link;
    u8 link_id;
};
struct ath12k_dp { int dp_lock; struct ath12k_dp_link_peer *peer; };
struct ath12k_base { struct ath12k_dp *dp; };
struct ath12k { struct ath12k_base *ab; struct { unsigned mac_id; } dp; };
#define ath12k_ab_to_dp(ab) ((ab)->dp)
#define ath12k_sta_to_ahsta(sta) (sta)
static int setup_calls, frag_calls, cleanup_calls, fail_tid, fail_frag, route_rc;
static unsigned active, deleted, route_value;
static void spin_lock_bh(int *lock) { assert(!*lock); *lock=1; }
static void spin_unlock_bh(int *lock) { assert(*lock); *lock=0; }
static struct ath12k_dp_link_peer *ath12k_dp_link_peer_find_by_vdev_and_addr(
    struct ath12k_dp *dp, int vdev, const u8 *addr)
{
    assert(dp->dp_lock && vdev==10 && addr);
    return dp->peer;
}
static int ath12k_wmi_set_peer_param(struct ath12k *ar,const u8 *addr,
                                    int vdev,int param,u32 val)
{
    assert(ar && addr && vdev==10 && param==WMI_PEER_SET_DEFAULT_ROUTING);
    route_value=val;
    return route_rc;
}
static int ath12k_dp_rx_peer_tid_setup(struct ath12k *ar,const u8 *addr,
    int vdev,int tid,int win,int ssn,int pn)
{
    assert(ar && addr && vdev==10 && win==1 && ssn==0 && pn==0);
    assert(!ar->ab->dp->dp_lock);
    assert(ar->ab->dp->peer->primary_link);
    setup_calls++;
    active|=1u<<tid; /* model a failed request after allocation/publication */
    return tid==fail_tid ? -ENOMEM : 0;
}
static int ath12k_dp_rx_peer_frag_setup(struct ath12k *ar,const u8 *addr,int vdev)
{
    assert(ar && addr && vdev==10);
    frag_calls++;
    if (fail_frag) return -EIO;
    ar->ab->dp->peer->dp_peer->dp_setup_done=true;
    return 0;
}
static void ath12k_dp_arch_rx_peer_tid_delete(struct ath12k_dp *dp,
    struct ath12k_dp_link_peer *peer,int tid)
{
    assert(dp->dp_lock && peer==dp->peer);
    if (active & (1u<<tid)) {
        deleted|=1u<<tid;
        active&=~(1u<<tid);
    }
}
static void ath12k_dp_rx_peer_tid_cleanup(struct ath12k *ar,
    struct ath12k_dp_link_peer *peer)
{
    assert(ar->ab->dp->dp_lock && peer->primary_link && peer->dp_peer->dp_setup_done);
    cleanup_calls++;
    for (int i=0;i<=IEEE80211_NUM_TIDS;i++)
        ath12k_dp_arch_rx_peer_tid_delete(ar->ab->dp,peer,i);
}

/* EXTRACTED BODIES */

int main(void)
{
    const u8 addr[6]={0};
    const unsigned all=(1u<<(IEEE80211_NUM_TIDS+1))-1;
    struct ath12k_sta sta={.defer_mlo_dp=true};
    struct ath12k_dp_peer shared={0};
    struct ath12k_dp_link_peer peer={.dp_peer=&shared,.sta=&sta,.mlo=true,.link_id=1};
    struct ath12k_dp dp={.peer=&peer};
    struct ath12k_base ab={.dp=&dp};
    struct ath12k ar={.ab=&ab,.dp={.mac_id=3}};
    fail_tid=-1;
    assert(!ath12k_dp_peer_set_default_routing(&ar,10,addr));
    assert(route_value==9 && setup_calls==0);
    route_rc=-EIO;
    assert(ath12k_dp_peer_set_default_routing(&ar,10,addr)==-EIO);
    assert(ath12k_dp_peer_setup(&ar,10,addr)==-EINVAL); /* unselected */
    sta.primary_selected=true;
    assert(ath12k_dp_peer_setup(&ar,10,addr)==-EINVAL); /* wrong link */
    assert(setup_calls==0 && !peer.primary_link && !dp.dp_lock);
    sta.primary_link_id=1;
    assert(!ath12k_dp_peer_setup(&ar,10,addr));
    assert(peer.primary_link && shared.dp_setup_done && active==all);
    assert(setup_calls==17 && frag_calls==1);
    assert(!ath12k_dp_peer_setup(&ar,10,addr));
    assert(setup_calls==17 && frag_calls==1);
    peer.primary_link=false;
    ath12k_dp_peer_cleanup(&ar,10,addr); /* secondary must not free shared queues */
    assert(active==all && !cleanup_calls);
    peer.primary_link=true;
    ath12k_dp_peer_cleanup(&ar,10,addr);
    assert(!active && deleted==all && !shared.dp_setup_done && cleanup_calls==1);
    ath12k_dp_peer_cleanup(&ar,10,addr);
    assert(cleanup_calls==1);
    deleted=0; fail_tid=5;
    assert(ath12k_dp_peer_setup(&ar,10,addr)==-ENOMEM);
    assert(!active && deleted==63 && !shared.dp_setup_done);
    ath12k_dp_peer_cleanup(&ar,10,addr); /* no uninitialized frag cleanup */
    assert(cleanup_calls==1);
    deleted=0; fail_tid=-1; fail_frag=1;
    assert(ath12k_dp_peer_setup(&ar,10,addr)==-EIO);
    assert(!active && deleted==all && !shared.dp_setup_done);
    dp.peer=NULL;
    assert(ath12k_dp_peer_setup(&ar,10,addr)==-ENOENT && !dp.dp_lock);
    puts("PRIMARY_UMAC_DP_FIXTURE_PASS (routing, ownership, retry, partial failure, cleanup)");
}
