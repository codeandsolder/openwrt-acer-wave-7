#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>

typedef uint8_t u8;
#define IEEE80211_MLD_MAX_NUM_LINKS 15
#define IEEE80211_LINK_UNSPECIFIED 15
#define READ_ONCE(value) (value)
#define BIT(n) (1UL << (n))
#define for_each_set_bit(i, map, max) \
    for ((i) = 0; (i) < (max); (i)++) if (*(map) & BIT(i))
#define lockdep_assert_wiphy(wiphy) assert(wiphy)
#define wiphy_dereference(wiphy, ptr) (assert(wiphy), (ptr))
#define WRITE_ONCE(lvalue, value) ((lvalue) = (value))
#define ath12k_dbg(...) ((void)0)
struct hw_params { bool is_plink_preferable; };
struct base { const struct hw_params *hw_params; };
struct ath12k { struct base *ab; };
struct ath12k_link_vif {
    struct ath12k *ar;
    bool is_created, is_started;
    int vdev_id;
};
struct ath12k_link_sta {
    struct ath12k_link_vif *arvif;
    u8 addr[6];
};
struct ath12k_sta {
    unsigned long links_map;
    u8 assoc_link_id, primary_link_id;
    bool primary_selected, primary_setup_failed;
    struct ath12k_link_sta *link[IEEE80211_MLD_MAX_NUM_LINKS];
};
struct hw { void *wiphy; };
struct ath12k_hw { struct hw *hw; };

static int setup_count, setup_error, selected_vdev;
static int ath12k_dp_peer_setup(struct ath12k *ar, int vdev, const u8 *addr)
{
    assert(ar && addr);
    setup_count++;
    selected_vdev = vdev;
    return setup_error;
}

/* EXTRACTED BODIES */

int main(void)
{
    const struct hw_params integrated = { false }, discrete = { true };
    struct base a = { &integrated }, b = { &discrete };
    struct ath12k ar[] = { { &a }, { &b } };
    struct ath12k_link_vif av[] = {
        { &ar[0], true, true, 10 }, { &ar[1], true, true, 20 },
    };
    struct ath12k_link_sta st[] = { { &av[0], {0} }, { &av[1], {0} } };
    struct hw hw = { &hw };
    struct ath12k_hw ah = { &hw };
    struct ath12k_sta sta = { .links_map = 3, .link = { &st[0], &st[1] } };

    sta.primary_link_id = 1;
    assert(ath12k_mac_mlo_data_link(&sta, 0, false) == 1);
    assert(ath12k_mac_mlo_data_link(&sta, IEEE80211_LINK_UNSPECIFIED, false) == 1);
    assert(ath12k_mac_mlo_data_link(&sta, IEEE80211_LINK_UNSPECIFIED, true) == 0);
    assert(ath12k_mac_mlo_data_link(&sta, 0, true) == 0);
    assert(ath12k_mac_mlo_data_link(&sta, 1, true) == 1);
    assert(ath12k_mac_mlo_data_link(&sta, 2, true) == IEEE80211_LINK_UNSPECIFIED);
    sta.links_map = 1;
    assert(ath12k_mac_mlo_data_link(&sta, 1, true) == IEEE80211_LINK_UNSPECIFIED);
    assert(ath12k_mac_mlo_data_link(&sta, IEEE80211_LINK_UNSPECIFIED, true) == 0);
    sta.links_map = 3;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 1);
    sta.assoc_link_id = 1;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 1);
    sta.assoc_link_id = 0;
    sta.links_map = 1;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 0);
    sta.links_map = 3;
    av[1].is_started = false;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 0);
    av[1].is_started = true;
    av[1].is_created = false;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 0);
    av[1].is_created = true;
    sta.link[1] = NULL;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 0);
    sta.link[1] = &st[1];
    b.hw_params = &integrated;
    assert(ath12k_mac_mlo_select_primary(&ah, &sta) == 0);
    b.hw_params = &discrete;

    assert(!ath12k_mac_mlo_setup_primary(&ah, &sta));
    assert(sta.primary_selected && sta.primary_link_id == 1);
    assert(setup_count == 1 && selected_vdev == 20);
    av[1].is_started = false;
    assert(!ath12k_mac_mlo_setup_primary(&ah, &sta));
    assert(setup_count == 1 && sta.primary_link_id == 1);
    av[1].is_started = true;

    sta.primary_selected = false;
    setup_error = -ENOMEM;
    assert(ath12k_mac_mlo_setup_primary(&ah, &sta) == -ENOMEM);
    assert(sta.primary_setup_failed && setup_count == 2);
    assert(ath12k_mac_mlo_setup_primary(&ah, &sta) == -EIO);
    assert(setup_count == 2);

    sta.primary_setup_failed = false;
    sta.primary_selected = false;
    sta.link[0] = NULL;
    sta.links_map = 1;
    assert(ath12k_mac_mlo_setup_primary(&ah, &sta) == -EINVAL);
    assert(setup_count == 2);
    puts("PRIMARY_UMAC_FIXTURE_PASS (selection, setup, retry, failure)");
    return 0;
}

