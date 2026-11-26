// SPDX-License-Identifier: GPL-2.0-only
// Bounded read-only sampling of the Wave7 direct QCA8081.
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <linux/mii.h>
#include <linux/sockios.h>
#include <net/if.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static uint64_t uptime_us(void)
{
	struct timespec t;

	if (clock_gettime(CLOCK_BOOTTIME, &t)) {
		perror("clock_gettime");
		exit(EXIT_FAILURE);
	}
	return (uint64_t)t.tv_sec * 1000000 + (uint64_t)t.tv_nsec / 1000;
}

static void sleep_interval(void)
{
	struct timespec t = { .tv_nsec = 50000000 };

	while (nanosleep(&t, &t)) {
		if (errno != EINTR) {
			perror("nanosleep");
			exit(EXIT_FAILURE);
		}
	}
}

static int read_reg(int fd, uint16_t reg)
{
	struct ifreq ifr = { .ifr_name = "lan" };
	struct mii_ioctl_data *mii = (void *)&ifr.ifr_data;

	mii->phy_id = 24;
	mii->reg_num = reg;
	if (ioctl(fd, SIOCGMIIREG, &ifr) < 0)
		return -1;
	return mii->val_out;
}

static void format_reg(char buf[static 7], int val)
{
	if (val < 0)
		memcpy(buf, "error", 6);
	else
		snprintf(buf, 7, "0x%04x", (unsigned)val & 0xffff);
}

int main(int argc, char **argv)
{
	char *end;
	unsigned long count;
	int fd;

	if (argc != 2 || !argv[1][0] || argv[1][0] < '0' ||
	    argv[1][0] > '9')
		return 2;
	errno = 0;
	count = strtoul(argv[1], &end, 10);
	if (errno || *end || count < 100 || count > 600)
		return 2;
	fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
	if (fd < 0) {
		perror("socket");
		return 1;
	}
	for (unsigned long i = 0; i < count; i++) {
		char a[7], mode[7], b[7];
		uint64_t t0 = uptime_us();

		format_reg(a, read_reg(fd, 17));
		format_reg(mode, read_reg(fd, 31));
		format_reg(b, read_reg(fd, 17));
		uint64_t t1 = uptime_us();

		if (printf("sample %" PRIu64 ".%06" PRIu64 " %s %s %s %" PRIu64 ".%06" PRIu64 "\n",
			   t0 / 1000000, t0 % 1000000, a, mode, b,
			   t1 / 1000000, t1 % 1000000) < 0 || fflush(stdout))
			return 1;
		if (i + 1 < count)
			sleep_interval();
	}
	return close(fd) ? 1 : 0;
}
