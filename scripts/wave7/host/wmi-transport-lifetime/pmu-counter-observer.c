/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/* Grouped, per-CPU, system-wide Cortex-A53 PMU snapshots. No multiplex scaling. */
#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

enum { CPU_COUNT = 4, EVENT_COUNT = 5, SECONDS = 335 };
static const uint64_t events[EVENT_COUNT] = {
    PERF_COUNT_HW_CPU_CYCLES, PERF_COUNT_HW_INSTRUCTIONS,
    PERF_COUNT_HW_CACHE_REFERENCES, PERF_COUNT_HW_CACHE_MISSES,
    PERF_COUNT_HW_BRANCH_MISSES,
};
struct count {
    uint64_t value, id;
};
struct group_read {
    uint64_t nr, enabled, running;
    struct count counters[EVENT_COUNT];
};
struct group {
    int fd[EVENT_COUNT];
    uint64_t ids[EVENT_COUNT];
};
static volatile sig_atomic_t stopped;

static void stop(int signum)
{
    (void)signum;
    stopped = 1;
}

static uint64_t boottime_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_BOOTTIME, &ts) < 0)
        return UINT64_MAX;
    return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

static bool online(void)
{
    char line[32];
    FILE *f = fopen("/sys/devices/system/cpu/online", "r");
    if (!f)
        return false;
    bool ok = fgets(line, sizeof(line), f) && strcmp(line, "0-3\n") == 0;
    fclose(f);
    return ok;
}

static bool same_boot(const char *boot)
{
    char line[40];
    FILE *f = fopen("/proc/sys/kernel/random/boot_id", "r");
    if (!f)
        return false;
    bool ok = fgets(line, sizeof(line), f) && strlen(boot) == 36 &&
              strlen(line) == 37 && line[36] == '\n' && memcmp(line, boot, 36) == 0;
    fclose(f);
    return ok;
}

static bool open_group(struct group *group, int cpu)
{
    for (unsigned i = 0; i < EVENT_COUNT; ++i) {
        struct perf_event_attr attr = {
            .type = PERF_TYPE_HARDWARE,
            .size = sizeof(attr),
            .config = events[i],
            .disabled = i == 0,
            .pinned = i == 0,
            .read_format = PERF_FORMAT_GROUP | PERF_FORMAT_ID |
                           PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING,
        };
        int fd = (int)syscall(SYS_perf_event_open, &attr, -1, cpu,
                              i ? group->fd[0] : -1, PERF_FLAG_FD_CLOEXEC);
        if (fd < 0) {
            fprintf(stderr, "perf_event_open cpu=%d event=%u: %s\n", cpu, i, strerror(errno));
            return false;
        }
        group->fd[i] = fd;
        if (ioctl(fd, PERF_EVENT_IOC_ID, &group->ids[i]) < 0) {
            perror("PERF_EVENT_IOC_ID");
            return false;
        }
    }
    return true;
}

static bool sample(const struct group *group, unsigned cpu, unsigned seq)
{
    struct group_read readout;
    uint64_t values[EVENT_COUNT];
    unsigned seen = 0;
    uint64_t lo = boottime_ns();
    ssize_t n = read(group->fd[0], &readout, sizeof(readout));
    uint64_t hi = boottime_ns();
    if (n != (ssize_t)sizeof(readout) || readout.nr != EVENT_COUNT ||
        lo == UINT64_MAX || hi == UINT64_MAX || hi < lo ||
        readout.running > readout.enabled)
        return false;
    for (unsigned i = 0; i < EVENT_COUNT; ++i) {
        unsigned j = 0;
        while (j < EVENT_COUNT && group->ids[j] != readout.counters[i].id)
            ++j;
        if (j == EVENT_COUNT || (seen & (1u << j)))
            return false;
        seen |= 1u << j;
        values[j] = readout.counters[i].value;
    }
    printf("PMU_SAMPLE %u %u %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64,
           seq, cpu, lo, hi, readout.enabled, readout.running);
    for (unsigned i = 0; i < EVENT_COUNT; ++i)
        printf(" %" PRIu64, values[i]);
    return putchar('\n') != EOF;
}

int main(int argc, char **argv)
{
    if (argc != 2 || !same_boot(argv[1]) || !online()) {
        fputs("expected exact Wave 7 boot and four online CPUs\n", stderr);
        return 2;
    }
    struct sigaction action = { .sa_handler = stop };
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL) ||
        sigaction(SIGHUP, &action, NULL))
        return 1;
    struct group groups[CPU_COUNT];
    for (unsigned c = 0; c < CPU_COUNT; ++c)
        for (unsigned i = 0; i < EVENT_COUNT; ++i)
            groups[c].fd[i] = -1;
    int rc = 1;
    for (unsigned c = 0; c < CPU_COUNT; ++c)
        if (!open_group(&groups[c], (int)c))
            goto done;
    for (unsigned c = 0; c < CPU_COUNT; ++c) {
        if (ioctl(groups[c].fd[0], PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP) < 0 ||
            ioctl(groups[c].fd[0], PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP) < 0) {
            perror("enable PMU group");
            goto done;
        }
    }
    uint64_t start = boottime_ns();
    if (start == UINT64_MAX)
        goto done;
    /* First validate that the entire pinned group actually runs on every CPU. */
    struct timespec warmup = { .tv_nsec = 100000000 };
    if (nanosleep(&warmup, NULL) || stopped)
        goto done;
    for (unsigned c = 0; c < CPU_COUNT; ++c) {
        struct group_read r;
        if (read(groups[c].fd[0], &r, sizeof(r)) != sizeof(r) ||
            r.nr != EVENT_COUNT || !r.enabled || !r.running) {
            fprintf(stderr, "pinned group did not run on cpu=%u\n", c);
            goto done;
        }
    }
    printf("PMU_READY boot=%s cpus=%u seconds=%u\n", argv[1], CPU_COUNT, SECONDS);
    if (fflush(stdout))
        goto done;
    start = boottime_ns();
    if (start == UINT64_MAX)
        goto done;
    for (unsigned seq = 0; seq <= SECONDS; ++seq) {
        uint64_t target = start + (uint64_t)seq * UINT64_C(1000000000);
        struct timespec when = { .tv_sec = (time_t)(target / UINT64_C(1000000000)),
                                 .tv_nsec = (long)(target % UINT64_C(1000000000)) };
        int err = clock_nanosleep(CLOCK_BOOTTIME, TIMER_ABSTIME, &when, NULL);
        if (err || stopped || !same_boot(argv[1]) || !online())
            goto done;
        for (unsigned c = 0; c < CPU_COUNT; ++c)
            if (!sample(&groups[c], c, seq))
                goto done;
        if (fflush(stdout))
            goto done;
    }
    rc = 0;
done:
    for (unsigned c = 0; c < CPU_COUNT; ++c) {
        if (groups[c].fd[0] >= 0)
            ioctl(groups[c].fd[0], PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
        for (unsigned i = 0; i < EVENT_COUNT; ++i)
            if (groups[c].fd[i] >= 0)
                close(groups[c].fd[i]);
    }
    if (!same_boot(argv[1]))
        rc = 1;
    printf("PMU_END rc=%d\n", rc);
    return rc;
}
