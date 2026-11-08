// Ownership and routing rules of the numbered plug-ins, without JACK or norns.
// Built with its own NB_DIR, so it is safe to run while real norns are playing.
#include "bridge_shm.h"
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <dlfcn.h>
#include <string>

typedef void* Handle;
struct Descriptor {
    const char* uri;
    Handle (*instantiate)(const Descriptor*, double, const char*, const void* const*);
    void (*connect_port)(Handle, uint32_t, void*);
    void (*activate)(Handle);
    void (*run)(Handle, uint32_t);
    void (*deactivate)(Handle);
    void (*cleanup)(Handle);
    const void* (*extension_data)(const char*);
};
constexpr uint32_t N = 256;
struct Instance {
    const Descriptor* d; Handle h; bool effect;
    float l[N], r[N], in_l[N], in_r[N], gain = 1, mix = 1, norns;
    void attach(const Descriptor* desc, bool fx, int number) {
        d = desc; effect = fx; norns = number;
        h = d->instantiate(d, 48000, "", nullptr);
        if (effect) { d->connect_port(h, 0, in_l); d->connect_port(h, 1, in_r); d->connect_port(h, 2, l); d->connect_port(h, 3, r); d->connect_port(h, 4, &gain); d->connect_port(h, 5, &mix); d->connect_port(h, 6, &norns); }
        else { d->connect_port(h, 0, l); d->connect_port(h, 1, r); d->connect_port(h, 2, in_l); d->connect_port(h, 3, in_r); d->connect_port(h, 5, &gain); d->connect_port(h, 6, &norns); }
        std::fill_n(in_l, N, 0.25f); std::fill_n(in_r, N, 0.25f);  // a constant "dry" signal
    }
    void run() { d->run(h, N); }
    float peak() const { float m = 0; for (float v : l) m = std::max(m, std::fabs(v)); return m; }
    bool is_dry() const { for (uint32_t i = 0; i < N; ++i) if (l[i] != in_l[i]) return false; return true; }
};
static int failures = 0;
static void check(const char* what, bool ok) { printf("%s %s\n", ok ? "PASS" : "FAIL", what); if (!ok) ++failures; }
static double phase = 0;
static void feed(nb::Shared* s, uint32_t blocks) {  // stands in for a running norns
    float l[N];
    for (uint32_t b = 0; b < blocks; ++b) {
        for (auto& v : l) { v = 0.5f * std::sin(phase); phase += 0.05; }
        s->to_machinista.push(l, l, N);
    }
}
static void wait_ms(long ms) { timespec t{ms / 1000, (ms % 1000) * 1000000}; nanosleep(&t, nullptr); }
static nb::Shared* open_instance(int n) {
    char path[256]; nb::bridge_path(n, path, sizeof path); unlink(path); return nb::bridge_open(path);
}

int main() {
    nb::Shared* one = open_instance(1);
    nb::Shared* two = open_instance(2);
    void* lib = dlopen("./guard_test_plugin.so", RTLD_NOW);
    if (!one || !two || !lib) { puts(lib ? "shared memory failed" : dlerror()); return 2; }
    auto* get = reinterpret_cast<const Descriptor* (*)(uint32_t)>(dlsym(lib, "lv2_descriptor"));
    const Descriptor* instrument = get(0);
    const Descriptor* effect = get(1);
    check("two plug-ins in the bundle", instrument && effect && !get(2));

    static Instance a, b, fx;
    a.attach(instrument, false, 1);
    b.attach(instrument, false, 1);
    fx.attach(effect, true, 1);

    // Two instruments on norns 1: only the first plays.
    float peak_a = 0, peak_b = 0;
    feed(one, 4);
    uint64_t written = one->to_norns.write.load();
    for (int i = 0; i < 100; ++i) {
        feed(one, 1);
        a.run(); peak_a = std::max(peak_a, a.peak());
        b.run(); peak_b = std::max(peak_b, b.peak());
        wait_ms(5);
    }
    check("first instrument plays", peak_a > 0.3f);
    check("second instrument on the same norns stays silent", peak_b == 0.f);
    check("only one writer into norns", one->to_norns.write.load() - written == 100 * N);

    // norns stops: the instrument goes quiet and stays quiet, with no replayed
    // bursts of old audio.
    int noisy_late = 0;
    for (int i = 0; i < 60; ++i) { a.run(); if (i >= 20 && a.peak() > 0.f) ++noisy_late; wait_ms(5); }
    check("a stopped norns goes quiet without replaying old audio", noisy_late == 0);
    for (int i = 0; i < 100; ++i) { feed(one, 1); a.run(); wait_ms(5); }
    check("it plays again once norns resumes", a.peak() > 0.3f);

    // An effect pointed at a norns that is already taken passes the dry signal.
    fx.run();
    check("effect on a taken norns stays dry", fx.is_dry());

    // Effect on norns 2 while nothing runs there: dry, not silent.
    fx.norns = 2;
    fx.run();
    check("effect with no norns running stays dry", fx.is_dry());

    // norns 2 starts answering: the effect returns norns' audio (mix 1 = fully wet).
    float peak_fx = 0; bool wet = false;
    for (int i = 0; i < 100; ++i) { feed(two, 1); fx.run(); peak_fx = std::max(peak_fx, fx.peak()); wet = wet || !fx.is_dry(); wait_ms(5); }
    check("effect returns norns' audio once it answers", wet && peak_fx > 0.3f);
    check("effect sends its input into norns 2", two->to_norns.write.load() >= 100 * N);

    // Switching the instrument's number releases norns 1 at once.
    a.norns = 3;
    a.run();
    check("switching number releases the old norns", one->owner.load() == 0);
    b.run();
    check("the other instrument can claim norns 1 now", one->owner.load() != 0);

    // The owning instrument passes its MIDI to its norns: a note-on and a
    // program change pass, system messages (here SysEx) do not.
    alignas(8) uint8_t seq[128] = {};
    const auto event = [&](int at, std::initializer_list<uint8_t> bytes) {
        const uint32_t size = uint32_t(bytes.size());
        std::memcpy(seq + at + 8, &size, 4);
        std::copy(bytes.begin(), bytes.end(), seq + at + 16);
    };
    event(16, {0x90, 60, 100}); event(40, {0xf0}); event(64, {0xc0, 5});
    const uint32_t seq_size = 8 + 3 * 24; std::memcpy(seq, &seq_size, 4);
    b.d->connect_port(b.h, 4, seq);
    a.d->connect_port(a.h, 4, seq);
    const uint64_t before = one->midi.write.load();
    b.run();
    a.run();  // on norns 3: nothing reaches norns 1
    uint32_t w1 = 0, w2 = 0, extra = 0;
    const bool got = one->midi.pop(w1) && one->midi.pop(w2) && !one->midi.pop(extra);
    check("instrument passes its notes to its norns", got && one->midi.write.load() - before == 2);
    check("note-on packed whole", w1 == (3u << 24 | 0x90u << 16 | 60u << 8 | 100u));
    check("two-byte message keeps its length", w2 == (2u << 24 | 0xc0u << 16 | 5u << 8));

    instrument->cleanup(a.h); instrument->cleanup(b.h); effect->cleanup(fx.h);
    check("removing the plug-ins frees their norns", one->owner.load() == 0 && two->owner.load() == 0);
    puts(failures ? "GUARD_TEST_FAILED" : "GUARD_TEST_PASSED");
    return failures ? 1 : 0;
}
