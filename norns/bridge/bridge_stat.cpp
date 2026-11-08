// Prints the health of one norns instance's bridge. Read-only apart from opening the file.
// Usage: bridge_stat [n]   (default 1; reads <NB_DIR>/<n>/bridge)
#include "bridge_shm.h"
#include <cstdio>
#include <cstdlib>
int main(int argc, char** argv) {
    char path[256];
    const int n = argc > 1 ? atoi(argv[1]) : 1;
    if (!nb::bridge_path(n, path, sizeof path)) return 2;
    auto* s = nb::bridge_open(path); if (!s) return 1;
    printf("norns %d (%s)\n", n, path);
    printf("plugin_blocks=%llu daemon_blocks=%llu refused_blocks=%llu\n", (unsigned long long)s->plugin_blocks.load(), (unsigned long long)s->daemon_blocks.load(), (unsigned long long)s->refused_blocks.load());
    printf("norns>machinista fill=%ld ppm=%+.0f locks=%llu underruns=%llu resyncs=%llu\n", long(s->out_stats.fill.load()), s->out_stats.ppm.load(), (unsigned long long)s->out_stats.locks.load(), (unsigned long long)s->out_stats.underruns.load(), (unsigned long long)s->out_stats.resyncs.load());
    printf("machinista>norns fill=%ld ppm=%+.0f locks=%llu underruns=%llu resyncs=%llu\n", long(s->in_stats.fill.load()), s->in_stats.ppm.load(), (unsigned long long)s->in_stats.locks.load(), (unsigned long long)s->in_stats.underruns.load(), (unsigned long long)s->in_stats.resyncs.load());
}
