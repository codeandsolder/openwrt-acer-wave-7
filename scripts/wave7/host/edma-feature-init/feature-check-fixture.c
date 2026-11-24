#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

typedef uint64_t netdev_features_t;
/* FEATURE DEFINITIONS */

#define CONFIG_NET_DSA 1
#define IS_ENABLED(x) (x)
struct sk_buff { bool stacked_vlan; };
struct dsa_port { void *rcv; };
struct net_device { struct dsa_port *dsa_ptr; };
static bool skb_vlan_tagged_multi(const struct sk_buff *skb)
{
	return skb->stacked_vlan;
}
/* ACTUAL FUNCTIONS */

int main(void)
{
	const netdev_features_t all = NETIF_F_SG | NETIF_F_HIGHDMA |
		NETIF_F_HW_CSUM | NETIF_F_IP_CSUM | NETIF_F_IPV6_CSUM |
		NETIF_F_FRAGLIST | NETIF_F_HW_VLAN_CTAG_TX |
		NETIF_F_HW_VLAN_STAG_TX | NETIF_F_RXCSUM | NETIF_F_GSO_MASK;
	const netdev_features_t multi_vlan = NETIF_F_SG | NETIF_F_HIGHDMA |
		NETIF_F_HW_CSUM | NETIF_F_FRAGLIST | NETIF_F_HW_VLAN_CTAG_TX |
		NETIF_F_HW_VLAN_STAG_TX;
	const netdev_features_t selected[] = {
		NETIF_F_SG, NETIF_F_HIGHDMA, NETIF_F_HW_CSUM,
		NETIF_F_IP_CSUM, NETIF_F_IPV6_CSUM, NETIF_F_FRAGLIST,
		NETIF_F_HW_VLAN_CTAG_TX, NETIF_F_HW_VLAN_STAG_TX,
		NETIF_F_RXCSUM, NETIF_F_TSO, NETIF_F_TSO6,
		NETIF_F_GSO_UDP_L4, NETIF_F_GSO_PARTIAL, NETIF_F_GSO_FRAGLIST
	};
	unsigned cases = 0;
	int receiver;
	struct dsa_port dp = { .rcv = &receiver };
	for (unsigned mode = 0; mode < 3; mode++) {
		struct dsa_port no_tag = { .rcv = NULL };
		struct net_device dev = { .dsa_ptr = mode == 0 ? NULL :
					 mode == 1 ? &no_tag : &dp };
		for (unsigned vlan = 0; vlan < 2; vlan++) {
			struct sk_buff skb = { .stacked_vlan = vlan };
			netdev_features_t allowed = mode == 2 ?
				~(NETIF_F_CSUM_MASK | NETIF_F_GSO_MASK) : ~UINT64_C(0);
			if (vlan)
				allowed &= multi_vlan;
			for (unsigned bits = 0; bits < (1U << (sizeof(selected)/sizeof(*selected))); bits++) {
				netdev_features_t offered = 0;
				for (unsigned i = 0; i < sizeof(selected)/sizeof(*selected); i++)
					if (bits & (1U << i))
						offered |= selected[i];
				assert(edma_port_feature_check(&skb, &dev, offered) ==
				       (offered & allowed));
				cases++;
			}
			assert(edma_port_feature_check(&skb, &dev, all) == (all & allowed));
			cases++;
		}
	}
	printf("EDMA_DSA_FEATURE_CHECK_PASS: %u actual policy cases\n", cases);
}
