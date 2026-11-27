/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/*
 * Passive DHCPv4 and ICMPv4 echo metadata at a Linux netdev boundary. AF_PACKET/SOCK_DGRAM
 * sees the network header, without promiscuous mode or retained payload.
 * This is a host-stack witness, not a radio-air capture.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <linux/filter.h>
#include <linux/if_ether.h>
#include <linux/if_packet.h>
#include <net/if.h>
#include <poll.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

enum profile { DHCP4, ECHO4 };

static const char *profile_name(enum profile profile)
{
    return profile == DHCP4 ? "DHCP" : "ICMP4";
}

struct dhcp_meta {
    uint8_t src[4], dst[4], offered[4], client[6];
    uint16_t src_port, dst_port;
    uint32_t xid;
    uint8_t op, type;
};

static uint16_t be16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] << 8 | p[1]);
}

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}

static bool dhcp_ports(uint16_t src, uint16_t dst)
{
    return (src == 67 && (dst == 67 || dst == 68)) ||
           (src == 68 && dst == 67);
}

static bool decode_dhcp(const uint8_t *p, size_t n, struct dhcp_meta *m)
{
    if (n < 20 || p[0] >> 4 != 4 || p[9] != 17)
        return false;
    size_t ihl = (size_t)(p[0] & 15) * 4;
    size_t total = be16(p + 2);
    if (ihl < 20 || ihl > total || total > n ||
        total - ihl < 8 || (be16(p + 6) & 0x3fff))
        return false;

    const uint8_t *udp = p + ihl;
    size_t udp_len = be16(udp + 4);
    if (udp_len < 8 + 236 || udp_len != total - ihl ||
        !dhcp_ports(be16(udp), be16(udp + 2)))
        return false;
    const uint8_t *b = udp + 8;
    size_t len = udp_len - 8;
    if ((b[0] != 1 && b[0] != 2) || b[1] != 1 || b[2] != 6)
        return false;

    *m = (struct dhcp_meta){
        .src_port = be16(udp), .dst_port = be16(udp + 2),
        .op = b[0], .xid = be32(b + 4),
    };
    memcpy(m->src, p + 12, 4);
    memcpy(m->dst, p + 16, 4);
    memcpy(m->offered, b + 16, 4);
    memcpy(m->client, b + 28, 6);
    /* BOOTP without the DHCP magic cookie has no DHCP message type. */
    if (len < 240 || be32(b + 236) != UINT32_C(0x63825363))
        return true;
    bool have_type = false;
    for (size_t i = 240; i < len;) {
        uint8_t option = b[i++];
        if (option == 0)
            continue;
        if (option == 255)
            return true;
        if (i == len)
            return false;
        size_t width = b[i++];
        if (width > len - i)
            return false;
        if (option == 53) {
            if (width != 1 || !b[i] || have_type)
                return false;
            have_type = true;
            m->type = b[i];
        }
        i += width;
    }
    return false;
}

/* Linux SOCK_DGRAM packet filter offsets start at the IP header. Permit
 * first fragments so a fragmented DHCP header is visible as undecodable;
 * later fragments have no UDP port to classify. No unrelated UDP ports. */
static struct sock_filter dhcp_filter[] = {
    /* ETH_P_ALL is required for PACKET_OUTGOING; the ancillary protocol
     * check excludes non-IPv4 frames before inspecting network headers. */
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, SKF_AD_OFF + SKF_AD_PROTOCOL),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, ETH_P_IP, 0, 14),
    BPF_STMT(BPF_LD | BPF_B | BPF_ABS, 9),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 17, 0, 12),
    BPF_STMT(BPF_LD | BPF_H | BPF_ABS, 6),
    BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x1fff, 10, 0),
    BPF_STMT(BPF_LDX | BPF_B | BPF_MSH, 0),
    BPF_STMT(BPF_LD | BPF_H | BPF_IND, 0),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 67, 0, 3),
    BPF_STMT(BPF_LD | BPF_H | BPF_IND, 2),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 67, 4, 0),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 68, 3, 4),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 68, 0, 3),
    BPF_STMT(BPF_LD | BPF_H | BPF_IND, 2),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 67, 0, 1),
    BPF_STMT(BPF_RET | BPF_K, 65535),
    BPF_STMT(BPF_RET | BPF_K, 0),
};

/* Only unfragmented IPv4 echo requests/replies are decodable. First
 * fragments with an echo header reach the decoder and fail accounting. */
static struct sock_filter echo4_filter[] = {
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, SKF_AD_OFF + SKF_AD_PROTOCOL),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, ETH_P_IP, 0, 9),
    BPF_STMT(BPF_LD | BPF_B | BPF_ABS, 9),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, 7),
    BPF_STMT(BPF_LD | BPF_H | BPF_ABS, 6),
    BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x1fff, 5, 0),
    BPF_STMT(BPF_LDX | BPF_B | BPF_MSH, 0),
    BPF_STMT(BPF_LD | BPF_B | BPF_IND, 0),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 8, 0, 1),
    BPF_STMT(BPF_RET | BPF_K, 65535),
    BPF_STMT(BPF_RET | BPF_K, 0),
};

struct echo4_meta {
    uint8_t src[4], dst[4], type;
    uint16_t identifier, sequence, ip_length, ip_id;
};

static bool decode_echo4(const uint8_t *p, size_t n, struct echo4_meta *m)
{
    if (n < 20 || p[0] >> 4 != 4 || p[9] != 1)
        return false;
    size_t ihl = (size_t)(p[0] & 15) * 4;
    size_t total = be16(p + 2);
    if (ihl < 20 || ihl > total || total > n ||
        total - ihl < 8 || (be16(p + 6) & 0x3fff))
        return false;
    const uint8_t *icmp = p + ihl;
    if ((icmp[0] != 0 && icmp[0] != 8) || icmp[1])
        return false;
    *m = (struct echo4_meta){
        .type = icmp[0], .identifier = be16(icmp + 4),
        .sequence = be16(icmp + 6), .ip_length = (uint16_t)total,
        .ip_id = be16(p + 4),
    };
    memcpy(m->src, p + 12, 4);
    memcpy(m->dst, p + 16, 4);
    return true;
}

static int attach(int fd, struct sock_filter *filter, unsigned short count)
{
    struct sock_fprog program = {.len = count, .filter = filter};
    return setsockopt(fd, SOL_SOCKET, SO_ATTACH_FILTER, &program,
                      sizeof(program));
}

static int64_t monotonic_ms(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t))
        return -1;
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

/* Relate the kernel's realtime packet timestamp to this host's mono ftrace
 * clock without assuming that either remote host shares its clock offset. */
static int clock_anchor(enum profile profile)
{
    struct timespec before, realtime, after;
    if (clock_gettime(CLOCK_MONOTONIC, &before) ||
        clock_gettime(CLOCK_REALTIME, &realtime) ||
        clock_gettime(CLOCK_MONOTONIC, &after))
        return -1;
    return printf("%s_CLOCK %jd.%09ld %jd.%09ld %jd.%09ld\n",
                  profile_name(profile), (intmax_t)before.tv_sec, before.tv_nsec,
                  (intmax_t)realtime.tv_sec, realtime.tv_nsec,
                  (intmax_t)after.tv_sec, after.tv_nsec) < 0 ? -1 : 0;
}

static int emit_dhcp(const struct timespec *t, const char *iface, unsigned pkttype,
                const struct dhcp_meta *m)
{
    char src[INET_ADDRSTRLEN], dst[INET_ADDRSTRLEN], offered[INET_ADDRSTRLEN];
    if (!inet_ntop(AF_INET, m->src, src, sizeof(src)) ||
        !inet_ntop(AF_INET, m->dst, dst, sizeof(dst)) ||
        !inet_ntop(AF_INET, m->offered, offered, sizeof(offered)))
        return -1;
    return printf("DHCP_PACKET %jd.%09ld %s %s %s %s %u %u %u 0x%08" PRIx32
                  " %02x:%02x:%02x:%02x:%02x:%02x %s %u\n",
                  (intmax_t)t->tv_sec, t->tv_nsec, iface,
                  pkttype == PACKET_OUTGOING ? "tx" : "rx", src, dst,
                  (unsigned)m->src_port, (unsigned)m->dst_port,
                  (unsigned)m->op, m->xid,
                  m->client[0], m->client[1], m->client[2],
                  m->client[3], m->client[4], m->client[5],
                  offered, (unsigned)m->type) < 0 ? -1 : 0;
}

static int emit_echo4(const struct timespec *t, const char *iface,
                      unsigned pkttype, const struct echo4_meta *m)
{
    char src[INET_ADDRSTRLEN], dst[INET_ADDRSTRLEN];
    if (!inet_ntop(AF_INET, m->src, src, sizeof(src)) ||
        !inet_ntop(AF_INET, m->dst, dst, sizeof(dst)))
        return -1;
    return printf("ICMP4_PACKET %jd.%09ld %s %s %s %s %u %u %u %u %u\n",
                  (intmax_t)t->tv_sec, t->tv_nsec, iface,
                  pkttype == PACKET_OUTGOING ? "tx" : "rx", src, dst,
                  (unsigned)m->type, (unsigned)m->identifier,
                  (unsigned)m->sequence, (unsigned)m->ip_length,
                  (unsigned)m->ip_id) < 0 ? -1 : 0;
}

/* One message from a nonblocking socket. Return 0 when drained, 1 on a
 * witnessed packet, -1 on a socket/clock/output failure. An undecodable
 * packet is counted separately and makes a negative claim unavailable. */
static int receive_one(int fd, const char *iface, unsigned index,
                       enum profile profile, uint64_t *seen, uint64_t *bad)
{
    uint8_t packet[65536];
    union {
        struct cmsghdr align;
        /* Do not assume the timestamp is the only ancillary record. */
        char data[256];
    } control;
    struct sockaddr_ll address = {0};
    struct iovec iov = {.iov_base = packet, .iov_len = sizeof(packet)};
    struct msghdr msg = {
        .msg_name = &address, .msg_namelen = sizeof(address),
        .msg_iov = &iov, .msg_iovlen = 1,
        .msg_control = control.data, .msg_controllen = sizeof(control.data),
    };
    ssize_t n = recvmsg(fd, &msg, MSG_DONTWAIT);
    if (n < 0)
        return (errno == EAGAIN || errno == EWOULDBLOCK) ? 0 : -1;
    ++*seen;
    /* sockaddr_ll is variable length (sll_halen bytes after sll_addr).
     * Only the fixed fields are required for direction and device identity. */
    if ((msg.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) ||
        msg.msg_namelen < offsetof(struct sockaddr_ll, sll_addr) ||
        address.sll_family != AF_PACKET || address.sll_ifindex != (int)index) {
        fprintf(stderr, "invalid packet metadata: flags=%#x name=%u family=%u ifindex=%d expected=%u\n",
                msg.msg_flags, (unsigned)msg.msg_namelen, address.sll_family,
                address.sll_ifindex, index);
        errno = EPROTO;
        return -1;
    }
    struct timespec timestamp = {0};
    bool have_timestamp = false;
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&msg); c;
         c = CMSG_NXTHDR(&msg, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_TIMESTAMPNS &&
            c->cmsg_len == CMSG_LEN(sizeof(timestamp))) {
            memcpy(&timestamp, CMSG_DATA(c), sizeof(timestamp));
            have_timestamp = true;
        }
    }
    if (!have_timestamp || timestamp.tv_sec < 0 ||
        timestamp.tv_nsec < 0 || timestamp.tv_nsec >= 1000000000) {
        fprintf(stderr, "invalid packet timestamp: present=%d control=%zu\n",
                have_timestamp, (size_t)msg.msg_controllen);
        for (struct cmsghdr *c = CMSG_FIRSTHDR(&msg); c;
             c = CMSG_NXTHDR(&msg, c))
            fprintf(stderr, "ancillary level=%d type=%d len=%zu\n",
                    c->cmsg_level, c->cmsg_type, (size_t)c->cmsg_len);
        errno = EPROTO;
        return -1;
    }
    if (profile == DHCP4) {
        struct dhcp_meta meta;
        if (decode_dhcp(packet, (size_t)n, &meta))
            return emit_dhcp(&timestamp, iface, address.sll_pkttype, &meta) ? -1 : 1;
    } else {
        struct echo4_meta meta;
        if (decode_echo4(packet, (size_t)n, &meta))
            return emit_echo4(&timestamp, iface, address.sll_pkttype, &meta) ? -1 : 1;
    }
    ++*bad;
    return 1;
}

/* NetworkManager may administratively lower a Wi-Fi netdev to change its
 * MAC address. The packet notifier temporarily unregisters its protocol hook,
 * reports ENETDOWN and registers the same hook again on NETDEV_UP. A device
 * unregister, in contrast, clears the socket's binding. Never silently
 * continue after removal/replacement or an unrelated socket error. */
static int link_down(int fd, const char *iface, unsigned index, enum profile profile, int error)
{
    struct sockaddr_ll bound = {0};
    socklen_t len = sizeof(bound);
    if (error != ENETDOWN || if_nametoindex(iface) != index ||
        getsockname(fd, (struct sockaddr *)&bound, &len) ||
        len < offsetof(struct sockaddr_ll, sll_addr) ||
        bound.sll_ifindex != (int)index || bound.sll_protocol != htons(ETH_P_ALL)) {
        fprintf(stderr, "packet socket error=%d bound_ifindex=%d expected=%u\n",
                error, bound.sll_ifindex, index);
        errno = error ? error : EPROTO;
        return -1;
    }
    struct timespec mono;
    if (clock_gettime(CLOCK_MONOTONIC, &mono))
        return -1;
    return printf("%s_LINK_DOWN %jd.%09ld ifindex=%u\n",
                  profile_name(profile), (intmax_t)mono.tv_sec, mono.tv_nsec, index) < 0 ? -1 : 0;
}

static int observe(const char *iface, unsigned seconds, enum profile profile)
{
    unsigned index = if_nametoindex(iface);
    if (!index)
        return -1;
    /* Protocol zero at creation prevents traffic before filter installation. */
    int fd = socket(AF_PACKET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0)
        return -1;
    int one = 1, rcvbuf = 1024 * 1024, rc = -1;
    struct sockaddr_ll address = {
        .sll_family = AF_PACKET, .sll_protocol = htons(ETH_P_ALL),
        .sll_ifindex = (int)index,
    };
    if (setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf)) ||
        setsockopt(fd, SOL_SOCKET, SO_TIMESTAMPNS, &one, sizeof(one)) ||
        (profile == DHCP4 ?
         attach(fd, dhcp_filter, sizeof(dhcp_filter) / sizeof(dhcp_filter[0])) :
         attach(fd, echo4_filter, sizeof(echo4_filter) / sizeof(echo4_filter[0]))) ||
        bind(fd, (struct sockaddr *)&address, sizeof(address)))
        goto done;
    int64_t start = monotonic_ms();
    if (start < 0)
        goto done;
    int64_t deadline = start + (int64_t)seconds * 1000;
    if (printf("%s_OBSERVER_READY iface=%s ifindex=%u duration=%u\n",
               profile_name(profile), iface, index, seconds) < 0)
        goto done;
    if (clock_anchor(profile))
        goto done;
    int64_t next_anchor = start + 1000;
    uint64_t seen = 0, bad = 0;
    struct pollfd pollfd = {.fd = fd, .events = POLLIN};
    for (;;) {
        int64_t now = monotonic_ms();
        if (now < 0)
            goto done;
        if (now >= deadline)
            break;
        if (now >= next_anchor) {
            if (if_nametoindex(iface) != index) {
                fprintf(stderr, "interface identity changed: %s index=%u\n", iface, index);
                errno = ENODEV;
                goto done;
            }
            if (clock_anchor(profile))
                goto done;
            next_anchor = now + 1000;
        }
        int64_t wake = next_anchor < deadline ? next_anchor : deadline;
        int remaining = (int)(wake - now);
        int ready = poll(&pollfd, 1, remaining);
        if (ready < 0) {
            if (errno == EINTR)
                continue;
            goto done;
        }
        if (ready && (pollfd.revents & (POLLHUP | POLLNVAL))) {
            errno = EIO;
            goto done;
        }
        if (ready && (pollfd.revents & POLLERR)) {
            int error = 0;
            socklen_t len = sizeof(error);
            if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &len) ||
                len != sizeof(error) || link_down(fd, iface, index, profile, error))
                goto done;
        }
        if (ready && (pollfd.revents & POLLIN) &&
            receive_one(fd, iface, index, profile, &seen, &bad) < 0 &&
            link_down(fd, iface, index, profile, errno))
            goto done;
    }
    /* Stop admission before draining to avoid treating queued tail packets
     * as loss or extending the observation indefinitely under load. */
    struct sock_filter stop[] = {BPF_STMT(BPF_RET | BPF_K, 0)};
    if (attach(fd, stop, 1))
        goto done;
    int result;
    do {
        result = receive_one(fd, iface, index, profile, &seen, &bad);
    } while (result > 0);
    if (result < 0)
        goto done;
    if (if_nametoindex(iface) != index || clock_anchor(profile))
        goto done;
    struct tpacket_stats stats = {0};
    socklen_t stats_len = sizeof(stats);
    if (getsockopt(fd, SOL_PACKET, PACKET_STATISTICS, &stats, &stats_len) ||
        stats_len != sizeof(stats))
        goto done;
    if (printf("%s_OBSERVER_END iface=%s seen=%" PRIu64 " decoded=%" PRIu64
               " malformed=%" PRIu64 " packets=%u drops=%u\n", profile_name(profile), iface,
               seen, seen - bad, bad, stats.tp_packets, stats.tp_drops) < 0)
        goto done;
    rc = (bad || stats.tp_drops ||
          seen + stats.tp_drops != stats.tp_packets || fflush(stdout)) ? 1 : 0;
done:
    close(fd);
    return rc;
}

int main(int argc, char **argv)
{
    if (argc != 4 || strlen(argv[1]) >= IF_NAMESIZE ||
        strspn(argv[1], "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "0123456789_.:-") != strlen(argv[1])) {
        fprintf(stderr, "usage: %s IFACE SECONDS (1..1800) dhcp4|echo4\n", argv[0]);
        return 2;
    }
    enum profile profile;
    if (!strcmp(argv[3], "dhcp4"))
        profile = DHCP4;
    else if (!strcmp(argv[3], "echo4"))
        profile = ECHO4;
    else
        return 2;
    char *end;
    errno = 0;
    unsigned long duration = strtoul(argv[2], &end, 10);
    if (errno || end == argv[2] || *end || !duration || duration > 1800)
        return 2;
    if (setvbuf(stdout, NULL, _IOLBF, 0))
        return 1;
    int rc = observe(argv[1], (unsigned)duration, profile);
    if (rc < 0)
        perror("packet boundary observer");
    return rc ? 1 : 0;
}
