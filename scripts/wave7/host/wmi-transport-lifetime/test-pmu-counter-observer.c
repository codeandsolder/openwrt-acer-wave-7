/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#define main pmu_observer_main
#include "pmu-counter-observer.c"
#undef main
#include <assert.h>

static bool check_read(struct group_read *data, size_t size)
{
    int fds[2];
    assert(pipe(fds) == 0);
    struct group g = { .fd = { fds[0] }, .ids = { 11, 12, 13, 14, 15 } };
    assert(write(fds[1], data, size) == (ssize_t)size);
    close(fds[1]);
    bool ok = sample(&g, 2, 1);
    close(fds[0]);
    return ok;
}

int main(void)
{
    struct group_read data = {
        .nr = EVENT_COUNT, .enabled = 1000000000, .running = 1000000000,
        .counters = { {50,15}, {30,13}, {10,11}, {40,14}, {20,12} },
    };
    assert(check_read(&data, sizeof(data)));
    assert(!check_read(&data, sizeof(data) - 1));
    data.nr = EVENT_COUNT - 1;
    assert(!check_read(&data, sizeof(data)));
    data.nr = EVENT_COUNT;
    data.running++;
    assert(!check_read(&data, sizeof(data)));
    data.running--;
    data.counters[0].id = 12;
    assert(!check_read(&data, sizeof(data)));
    data.counters[0].id = 17;
    assert(!check_read(&data, sizeof(data)));
    puts("PMU_GROUP_READ_PASS valid=1 rejected=5");
    return 0;
}
