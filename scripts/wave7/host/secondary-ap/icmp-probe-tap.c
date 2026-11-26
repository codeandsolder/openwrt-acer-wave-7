/* Bounded lab ICMP probe metadata capture, no payload saved.
 * Only the pinned Wave7 lab test IDs and peer addresses are accepted.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <pcap/pcap.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static const char filter[] =
    "(icmp and host 192.168.76.2 and host 192.168.76.145 "
    "and (icmp[0] = 8 or icmp[0] = 0) "
    "and (icmp[4:2] = 47601 or icmp[4:2] = 47603)) or "
    "(ip6 and host fd76:7::2 and ip6[6] = 58 "
    "and (ip6[40] = 128 or ip6[40] = 129) "
    "and (ip6[44:2] = 47602 or ip6[44:2] = 47604))";
static volatile sig_atomic_t stop;
static void on_signal(int sig) { (void)sig; stop = 1; }

static unsigned be16(const uint8_t *p) { return ((unsigned)p[0] << 8) | p[1]; }
struct echo {
    unsigned family, request, id, seq;
    char src[INET6_ADDRSTRLEN], dst[INET6_ADDRSTRLEN];
};
static int decode(const uint8_t *p, size_t n, struct echo *out)
{
    unsigned proto, off, family, request, id;
    const uint8_t *src, *dst, *icmp;
    if (n < 14) return 0;
    proto = be16(p+12);
    p += 14; n -= 14;
    if (proto == 0x0800) {
        if (n < 20 || (p[0] >> 4) != 4 || p[9] != 1 ||
            (be16(p+6) & 0x3fff)) return 0;
        off = (p[0] & 15u) * 4u;
        if (off < 20 || off+8 > n) return 0;
        src=p+12; dst=p+16; family=4;
    } else if (proto == 0x86dd) {
        if (n < 48 || (p[0] >> 4) != 6 || p[6] != 58) return 0;
        off=40; src=p+8; dst=p+24; family=6;
    } else return 0;
    icmp=p+off;
    if (icmp[1] != 0) return 0;
    if (family == 4) {
        if (icmp[0] != 8 && icmp[0] != 0) return 0;
        request=icmp[0] == 8;
    } else {
        if (icmp[0] != 128 && icmp[0] != 129) return 0;
        request=icmp[0] == 128;
    }
    id=be16(icmp+4);
    if (family==4 ? (id!=47601 && id!=47603) :
                    (id!=47602 && id!=47604)) return 0;
    if (!inet_ntop(family==4 ? AF_INET : AF_INET6,src,out->src,sizeof(out->src)) ||
        !inet_ntop(family==4 ? AF_INET : AF_INET6,dst,out->dst,sizeof(out->dst))) return 0;
    const char *peer=request ? out->dst : out->src;
    const char *client=request ? out->src : out->dst;
    if (family==4) {
        if (strcmp(peer,"192.168.76.2") ||
            strcmp(client,"192.168.76.145")) return 0;
    } else if (strcmp(peer,"fd76:7::2") ||
               strncmp(client,"fd76:7:",7) || !strcmp(client,peer)) return 0;
    out->family=family; out->request=request; out->id=id; out->seq=be16(icmp+6);
    return 1;
}

static int selftest(void)
{
    pcap_t *dead=pcap_open_dead(DLT_EN10MB,96);
    struct bpf_program bpf;
    uint8_t frame[96]={0};
    struct pcap_pkthdr hdr={.caplen=sizeof(frame),.len=sizeof(frame)};
    struct echo e;
    if (!dead || pcap_compile(dead,&bpf,filter,1,PCAP_NETMASK_UNKNOWN)) return 1;
    frame[12]=8; frame[14]=0x45; frame[23]=1;
    if (inet_pton(AF_INET,"192.168.76.145",frame+26)!=1 ||
        inet_pton(AF_INET,"192.168.76.2",frame+30)!=1) return 1;
    frame[34]=8; frame[38]=47601>>8; frame[39]=47601&255; frame[41]=1;
    if (!pcap_offline_filter(&bpf,&hdr,frame) ||
        !decode(frame,sizeof(frame),&e) || e.id!=47601 || e.seq!=1 || !e.request) return 1;
    frame[39]^=0x80;
    if (pcap_offline_filter(&bpf,&hdr,frame) || decode(frame,sizeof(frame),&e)) return 1;
    memset(frame,0,sizeof(frame)); frame[12]=0x86; frame[13]=0xdd;
    frame[14]=0x60; frame[20]=58;
    if (inet_pton(AF_INET6,"fd76:7::1234",frame+22)!=1 ||
        inet_pton(AF_INET6,"fd76:7::2",frame+38)!=1) return 1;
    frame[54]=128; frame[58]=47602>>8; frame[59]=47602&255; frame[61]=2;
    if (!pcap_offline_filter(&bpf,&hdr,frame) ||
        !decode(frame,sizeof(frame),&e) || e.id!=47602 || e.seq!=2 || e.family!=6) return 1;
    frame[20]=17;
    if (pcap_offline_filter(&bpf,&hdr,frame) || decode(frame,sizeof(frame),&e)) return 1;
    pcap_freecode(&bpf); pcap_close(dead);
    puts("ICMP_TAP_SELFTEST_PASS");
    return 0;
}

static double monotonic(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC,&ts)) { perror("clock_gettime"); exit(1); }
    return (double)ts.tv_sec + (double)ts.tv_nsec/1e9;
}

int main(int argc,char **argv)
{
    if (argc==2 && !strcmp(argv[1],"--selftest")) return selftest();
    if (argc!=3 || (strcmp(argv[1],"wlp2s0") && strcmp(argv[1],"enp4s0f4u2u4"))) {
        fprintf(stderr,"usage: icmp-probe-tap wlp2s0|enp4s0f4u2u4 SECONDS\n");
        return 2;
    }
    char *end;
    long duration=strtol(argv[2],&end,10);
    if (*end || duration<5 || duration>180) return 2;
    char err[PCAP_ERRBUF_SIZE]={0};
    pcap_t *p=pcap_create(argv[1],err);
    if (!p) { fprintf(stderr,"%s\n",err); return 1; }
    int rc=1;
    if (pcap_set_snaplen(p,96) || pcap_set_promisc(p,0) ||
        pcap_set_timeout(p,100) || pcap_set_immediate_mode(p,1) ||
        pcap_set_buffer_size(p,1024*1024) ||
        pcap_set_tstamp_precision(p,PCAP_TSTAMP_PRECISION_NANO)) goto done;
    if (pcap_activate(p)!=0 || pcap_datalink(p)!=DLT_EN10MB) goto done;
    struct bpf_program bpf;
    if (pcap_compile(p,&bpf,filter,1,PCAP_NETMASK_UNKNOWN)) goto done;
    int filter_rc=pcap_setfilter(p,&bpf);
    pcap_freecode(&bpf);
    if (filter_rc || pcap_setnonblock(p,1,err)) goto done;
    int fd=pcap_get_selectable_fd(p);
    if (fd<0) goto done;
    struct pollfd pollfd={.fd=fd,.events=POLLIN};
    signal(SIGINT,on_signal); signal(SIGTERM,on_signal);
    setvbuf(stdout,NULL,_IOLBF,0);
    puts("READY timestamp=epoch_ns direction=echo_type");
    double deadline=monotonic()+(double)duration;
    unsigned parsed=0,rejected=0;
    while (!stop && monotonic()<deadline) {
        int pr=poll(&pollfd,1,100);
        if (pr<0 && errno!=EINTR) goto done;
        if (pr<=0) continue;
        if (pollfd.revents&(POLLERR|POLLHUP|POLLNVAL)) goto done;
        for (;;) {
            struct pcap_pkthdr *h;
            const u_char *data;
            int n=pcap_next_ex(p,&h,&data);
            if (n==0) break;
            if (n<0) goto done;
            struct echo echo;
            if (!decode(data,h->caplen,&echo)) { ++rejected; continue; }
            printf("%lld.%09ld,%u,%s,%u,%u,%s,%s\n",
                (long long)h->ts.tv_sec,(long)h->ts.tv_usec,
                echo.family,echo.request?"request":"reply",echo.id,echo.seq,echo.src,echo.dst);
            ++parsed;
        }
    }
    struct pcap_stat stats;
    if (pcap_stats(p,&stats)) goto done;
    printf("END parsed=%u rejected=%u recv=%u dropped=%u ifdrop=%u\n",parsed,rejected,
        stats.ps_recv,stats.ps_drop,stats.ps_ifdrop);
    rc=stats.ps_drop || stats.ps_ifdrop || rejected ? 1 : 0;
done:
    if (rc) fprintf(stderr,"capture failed: %s %s\n",pcap_geterr(p),err);
    pcap_close(p);
    return rc;
}
