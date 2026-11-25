#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

typedef uint16_t u16;
#define ATH12K_MAX_MLO_PEERS 256
#define ATH12K_PEER_ML_ID_VALID (1U << 13)
#define ATH12K_MLO_PEER_ID_INVALID UINT16_MAX
#define lockdep_assert_wiphy(wiphy) assert(wiphy)
struct hw { void *wiphy; };
struct ath12k_hw {
    struct hw *hw;
    bool host_alloc_ml_id;
    bool free_ml_peer_id_map[ATH12K_MAX_MLO_PEERS];
    u16 last_ml_peer_id;
};
struct ath12k_sta { u16 ml_peer_id; };
static bool test_bit(unsigned id, bool *map)
{
    assert(id < ATH12K_MAX_MLO_PEERS);
    return map[id];
}
static void set_bit(unsigned id, bool *map)
{
    assert(id < ATH12K_MAX_MLO_PEERS);
    map[id] = true;
}
static void clear_bit(unsigned id, bool *map)
{
    assert(id < ATH12K_MAX_MLO_PEERS);
    map[id] = false;
}

/* EXTRACTED BODIES */

int main(void)
{
    struct hw hw = { .wiphy = &hw };
    struct ath12k_hw ah = { .hw = &hw, .host_alloc_ml_id = true };
    struct ath12k_sta sta;
    for (unsigned i = 1; i < ATH12K_MAX_MLO_PEERS; ++i) {
        assert(ath12k_peer_ml_alloc(&ah) == (i | ATH12K_PEER_ML_ID_VALID));
    }
    assert(!ah.free_ml_peer_id_map[0]);
    assert(ath12k_peer_ml_alloc(&ah) == ATH12K_MLO_PEER_ID_INVALID);
    assert(ah.last_ml_peer_id == ATH12K_MAX_MLO_PEERS - 1);
    sta.ml_peer_id = ATH12K_PEER_ML_ID_VALID | 17;
    ath12k_peer_ml_free(&ah, &sta);
    assert(!ah.free_ml_peer_id_map[17] && sta.ml_peer_id == ATH12K_MLO_PEER_ID_INVALID);
    assert(ath12k_peer_ml_alloc(&ah) == (ATH12K_PEER_ML_ID_VALID | 17));
    assert(ath12k_peer_ml_alloc(&ah) == ATH12K_MLO_PEER_ID_INVALID);
    sta.ml_peer_id = 17;
    ath12k_peer_ml_free(&ah, &sta);
    assert(ah.free_ml_peer_id_map[17]);
    sta.ml_peer_id = ATH12K_MLO_PEER_ID_INVALID;
    ath12k_peer_ml_free(&ah, &sta);
    sta.ml_peer_id = ATH12K_PEER_ML_ID_VALID | ATH12K_MAX_MLO_PEERS;
    ath12k_peer_ml_free(&ah, &sta);
    ah.host_alloc_ml_id = false;
    sta.ml_peer_id = ATH12K_PEER_ML_ID_VALID | 17;
    ath12k_peer_ml_free(&ah, &sta);
    assert(ah.free_ml_peer_id_map[17]);
    ah.host_alloc_ml_id = true;
    struct ath12k_hw sparse = { .hw = &hw, .host_alloc_ml_id = true };
    for (unsigned i = 1; i < 1024; ++i) {
        u16 id = ath12k_peer_ml_alloc(&sparse);
        assert(id == (ATH12K_PEER_ML_ID_VALID | (1 + (i - 1) % 255)));
        sta.ml_peer_id = id;
        ath12k_peer_ml_free(&sparse, &sta);
    }
    puts("ML_PEER_ID_ACTUAL_SOURCE_PASS");
}
