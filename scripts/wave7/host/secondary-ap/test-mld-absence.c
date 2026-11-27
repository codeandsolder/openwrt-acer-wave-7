/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Host test for the exact inline policy compiled into the kernel candidate. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define MT792x_MAX_INTERFACES 4
#include "mt792x_absence.h"

static int identities[MT792X_ABSENCE_SLOTS], owner, unrelated;

static void bind(struct mt792x_absence_state *s, unsigned int bss,
		 unsigned int link, const void *vif)
{
	mt792x_absence_register(s, bss, &identities[bss], vif, link);
	mt792x_absence_activate(s, bss, &identities[bss], true);
}

static void test_truth_table(void)
{
	unsigned int active, absent, target, group, qi;
	const u8 quotas[] = {0, 1, 2, 255};
	unsigned int cases = 0;

	for (active = 0; active < (1u << MT792X_ABSENCE_SLOTS); active++)
		for (absent = 0; absent < (1u << MT792X_ABSENCE_SLOTS); absent++)
			for (target = 0; target < MT792X_ABSENCE_SLOTS; target++)
				for (group = 0; group < 2; group++)
					for (qi = 0; qi < sizeof(quotas); qi++) {
						struct mt792x_absence_state s = {0};
						u64 ticket = UINT64_MAX;
						bool limited, permitted;
						u8 q = quotas[qi];

						for (unsigned int b = 0; b < MT792X_ABSENCE_SLOTS; b++) {
							mt792x_absence_register(&s, b, &identities[b],
										&owner, b);
							mt792x_absence_activate(&s, b, &identities[b],
										(active & (1u << b)) != 0);
							assert(mt792x_absence_announce(&s, b,
										(absent & (1u << b)) != 0, q));
						}
						limited = (active & absent & (1u << target)) != 0 &&
							  (!group || (active & absent) == active);
						permitted = mt792x_absence_reserve(&s, &owner, target,
										  group != 0, &ticket);
						assert(permitted == (!limited || q != 0));
						assert((ticket != 0) == (limited && q != 0));
						assert(s.slots[target].quota == q - (ticket != 0));
						if (ticket)
							assert(mt792x_absence_refund(&s, ticket));
						assert(s.slots[target].quota == q);
						cases++;
					}
	printf("EXHAUSTIVE_ABSENCE_CASES=%u\n", cases);
}

static void test_lifecycle(void)
{
	struct mt792x_absence_state s = {0};
	u64 a, b, c;

	bind(&s, 0, 1, &owner);
	bind(&s, 1, 0, &owner);
	bind(&s, 2, 0, &unrelated);
	assert(mt792x_absence_announce(&s, 0, true, 2));
	/* Unknown secondary starts present; primary-only must not charge. */
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &a) && !a);
	assert(mt792x_absence_announce(&s, 1, true, 2));
	/* Unrelated interface being present cannot unblock this MLD. */
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &a) && a);
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &b) && b);
	assert(!mt792x_absence_reserve(&s, &owner, 1, true, &c) && !c);
	assert(mt792x_absence_refund(&s, b));
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &c) && c);
	assert(mt792x_absence_announce(&s, 0, true, 2));
	/* A new announcement replaces the budget, stale refunds cannot inflate. */
	assert(!mt792x_absence_refund(&s, a));
	assert(!mt792x_absence_refund(&s, c));
	assert(s.slots[0].quota == 2);
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &a) && a);
	mt792x_absence_unregister(&s, 0, &identities[1]);
	assert(s.slots[0].identity == &identities[0]);
	bind(&s, 0, 1, &owner);
	assert(mt792x_absence_announce(&s, 0, true, 1));
	assert(!mt792x_absence_refund(&s, a));
	assert(s.slots[0].quota == 1);
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &a) && a);
	assert(!mt792x_absence_reserve(&s, &owner, 1, true, &b));
	assert(mt792x_absence_announce(&s, 1, false, 0));
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &b) && !b);
	/* Single-link traffic cannot borrow a different link's eligibility. */
	assert(!mt792x_absence_reserve(&s, &owner, 1, false, &b));
	assert(mt792x_absence_announce(&s, 1, true, 0));
	mt792x_absence_activate(&s, 0, &identities[0], false);
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &b) && !b);
	mt792x_absence_activate(&s, 0, &identities[0], true);
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &b) && !b);
	assert(mt792x_absence_announce(&s, 0, true, 1));
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &a) && a);
	mt792x_absence_reset(&s, true);
	assert(!mt792x_absence_announce(&s, 0, true, 255));
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &b) && !b);
	mt792x_absence_reset(&s, false);
	mt792x_absence_activate(&s, 0, &identities[0], true);
	mt792x_absence_activate(&s, 1, &identities[1], true);
	assert(mt792x_absence_announce(&s, 0, true, 1));
	assert(mt792x_absence_announce(&s, 1, true, 1));
	assert(!mt792x_absence_refund(&s, a));
	assert(s.slots[0].quota == 1);
	mt792x_absence_unregister(&s, 0, &identities[0]);
	assert(!mt792x_absence_announce(&s, 0, true, 255));
	assert(mt792x_absence_reserve(&s, &owner, 1, true, &b) && !b);
	assert(!mt792x_absence_announce(&s, MT792X_ABSENCE_SLOTS, true, 2));
	mt792x_absence_unregister_owner(&s, &owner);
	assert(!s.slots[0].identity && !s.slots[1].identity);
	assert(s.slots[2].identity == &identities[2]);
	assert(!mt792x_absence_announce(&s, 1, true, 255));
	mt792x_absence_activate(&s, 2, &identities[2], true);
	assert(mt792x_absence_announce(&s, 2, true, 1));
	assert(mt792x_absence_reserve(&s, &unrelated, 0, false, &a) && a);
	assert(mt792x_absence_refund(&s, a));
}

static void test_decoder(void)
{
	const u8 info[] = {1, 0, 0, 0, 0, 0, 8, 0, 1, 2, 0, 0};
	/* Unknown extension before and after the known INFO is accepted. */
	const u8 extensions[] = {1, 0, 0, 0, 1, 0, 4, 0, 0, 0, 8, 0,
				 0, 3, 0, 0, 2, 0, 4, 0};
	u8 bad[20];
	unsigned int bss;
	bool absent;
	u8 quota;

	for (unsigned int n = 0; n < sizeof(info); n++) {
		bss = 99; absent = false; quota = 99;
		assert(!mt792x_absence_decode(info, n, &bss, &absent, &quota));
		assert(bss == 99 && !absent && quota == 99);
	}
	assert(mt792x_absence_decode(info, sizeof(info), &bss, &absent, &quota));
	assert(bss == 1 && absent && quota == 2);
	assert(mt792x_absence_decode(extensions, sizeof(extensions),
				      &bss, &absent, &quota));
	assert(bss == 1 && !absent && quota == 3);

	memcpy(bad, info, sizeof(info));
	bad[0] = MT792X_ABSENCE_SLOTS;
	assert(!mt792x_absence_decode(bad, sizeof(info), &bss, &absent, &quota));
	bad[0] = 1; bad[8] = 2;
	assert(!mt792x_absence_decode(bad, sizeof(info), &bss, &absent, &quota));
	bad[8] = 1; bad[6] = 0;
	assert(!mt792x_absence_decode(bad, sizeof(info), &bss, &absent, &quota));
	bad[6] = 7;
	assert(!mt792x_absence_decode(bad, sizeof(info), &bss, &absent, &quota));
	memcpy(bad, info, sizeof(info));
	memcpy(bad + sizeof(info), info + 4, sizeof(info) - 4);
	assert(!mt792x_absence_decode(bad, sizeof(bad), &bss, &absent, &quota));
	/* Malformed trailing TLV must not partially apply an otherwise valid INFO. */
	bad[12] = 1; bad[14] = 0;
	assert(!mt792x_absence_decode(bad, sizeof(bad), &bss, &absent, &quota));
}

static void replay(void)
{
	struct mt792x_absence_state s = {0};
	unsigned int bss, value, quota, allowed = 0, charged = 0, denied = 0;
	char op;

	while (scanf(" %c %u %u %u", &op, &bss, &value, &quota) == 4) {
		u64 ticket;

		assert(bss < MT792X_ABSENCE_SLOTS);
		switch (op) {
		case 'B':
			mt792x_absence_register(&s, bss, &identities[bss], &owner, value);
			break;
		case 'S':
			assert(s.slots[bss].link == value);
			mt792x_absence_activate(&s, bss, &identities[bss], true);
			break;
		case 'A':
			assert(value <= 1 && quota <= 255);
			mt792x_absence_announce(&s, bss, value != 0, (u8)quota);
			break;
		case 'T':
			assert(s.slots[bss].active && s.slots[bss].link == value);
			if (mt792x_absence_reserve(&s, &owner, value, true, &ticket)) {
				allowed++;
				charged += ticket != 0;
			} else {
				denied++;
			}
			break;
		default:
			abort();
		}
	}
	assert(feof(stdin));
	printf("REPLAY allowed=%u charged=%u denied=%u\n", allowed, charged, denied);
}

int main(int argc, char **argv)
{
	if (argc == 2 && !strcmp(argv[1], "--replay")) {
		replay();
		return 0;
	}
	assert(argc == 1);
	test_truth_table();
	test_lifecycle();
	test_decoder();
	puts("MLD_ABSENCE_POLICY_SELFTEST_PASS");
}
