#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

typedef uint64_t netdev_features_t;
/* FEATURE DEFINITIONS */

#define CONFIG_NET_DSA 1
#define IS_ENABLED(x) (x)
typedef uint32_t u32;
#define MAX_SKB_FRAGS 17
#define likely(x) (x)
#define unlikely(x) (x)
#define WARN_ON_ONCE(x) assert(!(x))
#define IS_ERR_OR_NULL(x) (!(x) || (x)==(void *)-1)
#define netdev_info(dev, ...) ((void)(dev))
struct sk_buff;
struct skb_shared_info {
	u32 gso_type;
	unsigned gso_size,nr_frags;
	struct sk_buff *frag_list;
};
struct sk_buff {
	bool stacked_vlan;
	unsigned ip_summed;
	struct skb_shared_info shinfo;
	struct sk_buff *next;
};
#define skb_shinfo(skb) (&(skb)->shinfo)
#define skb_is_gso(skb) (skb_shinfo(skb)->gso_size!=0)
#define skb_has_frag_list(skb) (skb_shinfo(skb)->frag_list!=NULL)
#define skb_is_nonlinear(skb) (skb_shinfo(skb)->nr_frags || skb_has_frag_list(skb))
#define skb_walk_frags(skb,iter) for ((iter)=skb_shinfo(skb)->frag_list;(iter);(iter)=(iter)->next)
static unsigned segment_calls,linearize_calls;
static netdev_features_t segment_features;
static bool linearize_fail;
static struct sk_buff segmented;
static netdev_features_t netif_skb_features(struct sk_buff *skb)
{
	(void)skb;
	return UINT64_MAX;
}
static struct sk_buff *skb_gso_segment(struct sk_buff *skb, netdev_features_t features)
{
	assert(skb_is_gso(skb));
	segment_calls++;
	segment_features=features;
	return &segmented;
}
static int skb_linearize(struct sk_buff *skb)
{
	linearize_calls++;
	if (linearize_fail)
		return -1;
	skb->shinfo.nr_frags=0;
	skb->shinfo.frag_list=NULL;
	return 0;
}
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
	struct net_device dev={0};
	const unsigned mss_values[]={0,1,128,255,256,257,512,10239,10240,10241,65535};
	const u32 types[]={0,SKB_GSO_TCPV4,SKB_GSO_TCPV6,
		SKB_GSO_TCPV4|SKB_GSO_TCP_ECN,SKB_GSO_TCPV4|SKB_GSO_TCP_FIXEDID,
		SKB_GSO_TCPV6|SKB_GSO_DODGY,SKB_GSO_UDP_L4,SKB_GSO_TCPV4|SKB_GSO_TCPV6};
	for(unsigned i=0;i<sizeof(mss_values)/sizeof(*mss_values);i++)
		for(unsigned j=0;j<sizeof(types)/sizeof(*types);j++)
			for(unsigned c=0;c<4;c++) {
				struct sk_buff skb={.ip_summed=c,.shinfo={.gso_size=mss_values[i],.gso_type=types[j]}};
				bool valid=c==CHECKSUM_PARTIAL && (j==1||j==2) &&
					mss_values[i]>=256 && mss_values[i]<=10240;
				assert(edma_tx_tso_supported(&skb)==valid);
				netdev_features_t expected=(mss_values[i]&&!valid)?all&~NETIF_F_GSO_MASK:all;
				assert(edma_port_feature_check(&skb,&dev,all)==expected);
				struct sk_buff *segs=NULL;
				segment_calls=linearize_calls=0;
				enum edma_tx_gso_status status=edma_tx_gso_segment(&skb,&dev,&segs);
				assert(status==((mss_values[i]&&!valid)?EDMA_TX_GSO_SUCCEED:EDMA_TX_GSO_NOT_NEEDED));
				assert(segment_calls==(mss_values[i]&&!valid) && !linearize_calls);
				if(segment_calls) assert(!(segment_features&NETIF_F_GSO_MASK));
				cases++;
			}
	for(unsigned n=0;n<=40;n++) {
		struct sk_buff children[40]={0};
		for(unsigned i=0;i+1<n;i++) children[i].next=&children[i+1];
		for(unsigned gso=0;gso<2;gso++)
			for(unsigned nested=0;nested<2;nested++)
				for(unsigned fail=0;fail<2;fail++) {
					struct sk_buff inner={0};
					if(n) children[0].shinfo.frag_list=nested?&inner:NULL;
					struct sk_buff skb={.ip_summed=CHECKSUM_PARTIAL,.shinfo={
						.gso_size=gso?512:0,.gso_type=SKB_GSO_TCPV4,
						.frag_list=n?children:NULL}};
					bool oversized=n+1>32||(n&&nested);
					struct sk_buff *segs=NULL;
					segment_calls=linearize_calls=0;linearize_fail=fail;
					enum edma_tx_gso_status status=edma_tx_gso_segment(&skb,&dev,&segs);
					assert(status==(oversized?(gso?EDMA_TX_GSO_SUCCEED:
						fail?EDMA_TX_GSO_FAIL:EDMA_TX_GSO_NOT_NEEDED):EDMA_TX_GSO_NOT_NEEDED));
					assert(segment_calls==(oversized&&gso));
					assert(linearize_calls==(oversized&&!gso));
					if(segment_calls) assert(!(segment_features&(NETIF_F_GSO_MASK|NETIF_F_SG|NETIF_F_FRAGLIST)));
					cases++;
				}
	}
	printf("EDMA_TSO_SG_POLICY_PASS: %u actual policy cases\n", cases);
}
