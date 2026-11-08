// "Norns Instrument" and "Norns Effect": LV2 plug-ins that connect a Machinista
// Sound to a numbered norns instance (see bridge_shm.h).
//
// Norns Instrument (instrument slot): outputs norns' audio; its sidechain input
//   is sent to norns' input. Based on the Pi 4 add-on's Norns Bridge.
// Norns Effect (effect slot): sends the chain's audio into norns and returns
//   norns' output, mixed with the dry signal. While its norns isn't running, it
//   passes the dry signal through instead of going silent.
//
// Norns Instrument also passes the MIDI it gets (the Sound's notes: pads and
// Machinista's patterns) to its norns, which plays them as MIDI on port 1.
//
// The "Norns" control picks the instance (1-8). Only one plug-in may use an
// instance at a time; another one on the same number stays silent (instrument)
// or dry (effect).
#include "bridge_shm.h"
#include <cstdlib>
#include <cstring>

extern "C" {
typedef void* LV2_Handle;
typedef struct { const char* URI; void* data; } LV2_Feature;
typedef struct LV2_Descriptor {
    const char* URI;
    LV2_Handle (*instantiate)(const LV2_Descriptor*, double, const char*, const LV2_Feature* const*);
    void (*connect_port)(LV2_Handle, uint32_t, void*);
    void (*activate)(LV2_Handle);
    void (*run)(LV2_Handle, uint32_t);
    void (*deactivate)(LV2_Handle);
    void (*cleanup)(LV2_Handle);
    const void* (*extension_data)(const char*);
} LV2_Descriptor;
}

namespace {
constexpr const char* kInstrumentUri = "https://github.com/snassen/machinista/norns#instrument";
constexpr const char* kEffectUri = "https://github.com/snassen/machinista/norns#effect";
constexpr const char* kUridMap = "http://lv2plug.in/ns/ext/urid#map";
constexpr const char* kMidiEvent = "http://lv2plug.in/ns/ext/midi#MidiEvent";
struct UridMap { void* handle; uint32_t (*map)(void*, const char*); };
constexpr uint32_t kChunk = 1024;  // frames handled per step; larger host blocks are split

// Port indices, as declared in norns.ttl.
enum InstrumentPort { I_OUT_L, I_OUT_R, I_SIDE_L, I_SIDE_R, I_MIDI, I_GAIN, I_NORNS };
enum EffectPort { E_IN_L, E_IN_R, E_OUT_L, E_OUT_R, E_GAIN, E_MIX, E_NORNS };

struct Plugin {
    bool effect = false;
    double rate = 48000;
    nb::Shared* shared[nb::kMaxInstances + 1] = {};  // index = instance number
    int current = 0;                                 // instance in use, 0 = none yet
    nb::AdaptiveReader reader;
    float* out_l = nullptr; float* out_r = nullptr;
    const float* in_l = nullptr; const float* in_r = nullptr;  // sidechain (instrument) or chain input (effect)
    const float* gain = nullptr; const float* mix = nullptr; const float* norns = nullptr;
    const uint8_t* midi = nullptr;  // atom sequence (instrument)
    uint32_t midi_type = 0;         // URID of midi:MidiEvent, 0 = host has no URID map
    float zero[kChunk] = {};
    float dry_l[kChunk] = {}; float dry_r[kChunk] = {};
};

LV2_Handle instantiate(const LV2_Descriptor* d, double rate, const char*, const LV2_Feature* const* features) {
    auto* p = new Plugin;
    p->effect = std::strcmp(d->URI, kEffectUri) == 0;
    p->rate = rate;
    for (int i = 0; features && features[i]; ++i)
        if (std::strcmp(features[i]->URI, kUridMap) == 0 && features[i]->data) {
            auto* m = static_cast<UridMap*>(features[i]->data);
            p->midi_type = m->map(m->handle, kMidiEvent);
        }
    // Map every instance now: opening files is not allowed on the audio thread,
    // and the "Norns" control can change while playing.
    char path[256];
    for (int n = 1; n <= nb::kMaxInstances; ++n)
        if (nb::bridge_path(n, path, sizeof path)) p->shared[n] = nb::bridge_open(path);
    return p;
}

void connect_port(LV2_Handle h, uint32_t port, void* data) {
    auto* p = static_cast<Plugin*>(h);
    auto* f = static_cast<float*>(data);
    if (p->effect) {
        switch (port) {
            case E_IN_L: p->in_l = f; break;
            case E_IN_R: p->in_r = f; break;
            case E_OUT_L: p->out_l = f; break;
            case E_OUT_R: p->out_r = f; break;
            case E_GAIN: p->gain = f; break;
            case E_MIX: p->mix = f; break;
            case E_NORNS: p->norns = f; break;
            default: break;
        }
    } else {
        switch (port) {
            case I_OUT_L: p->out_l = f; break;
            case I_OUT_R: p->out_r = f; break;
            case I_SIDE_L: p->in_l = f; break;
            case I_SIDE_R: p->in_r = f; break;
            case I_MIDI: p->midi = static_cast<const uint8_t*>(data); break;
            case I_GAIN: p->gain = f; break;
            case I_NORNS: p->norns = f; break;
            default: break;
        }
    }
}

uint64_t id(const Plugin* p) { return reinterpret_cast<uintptr_t>(p); }

void release(Plugin* p) {
    if (p->current > 0 && p->shared[p->current]) {
        uint64_t self = id(p);
        p->shared[p->current]->owner.compare_exchange_strong(self, 0);
    }
}

// Which instance to use, from the "Norns" control. Instrument defaults to 1, effect to 2.
int wanted(const Plugin* p) {
    const int fallback = p->effect ? 2 : 1;
    if (!p->norns) return fallback;
    const int n = int(std::lround(*p->norns));
    return n >= 1 && n <= nb::kMaxInstances ? n : fallback;
}

void process(Plugin* p, uint32_t offset, uint32_t n) {
    float* ol = p->out_l + offset; float* orr = p->out_r + offset;
    const float* il = p->in_l ? p->in_l + offset : p->zero;
    const float* ir = p->in_r ? p->in_r + offset : p->zero;
    if (p->effect) {  // the host may process in place: keep the dry signal first
        std::copy_n(il, n, p->dry_l); std::copy_n(ir, n, p->dry_r);
        il = p->dry_l; ir = p->dry_r;
    }
    nb::Shared* s = p->shared[p->current];
    const bool owner = s && nb::claim_bridge(*s, id(p), nb::now_ns());
    if (!owner) {
        if (s) s->refused_blocks.fetch_add(1, std::memory_order_relaxed);
        if (p->effect) { std::copy_n(il, n, ol); std::copy_n(ir, n, orr); }
        else { std::fill_n(ol, n, 0.f); std::fill_n(orr, n, 0.f); }
        return;
    }
    s->to_norns.push(il, ir, n);
    const int configured = s->target_frames.load(std::memory_order_relaxed);
    p->reader.read(s->to_machinista, s->out_stats, ol, orr, n,
                   configured > 0 ? configured : nb::kDefaultTarget, n / p->rate);
    const float g = p->gain ? std::clamp(*p->gain, 0.f, 2.f) : 1.f;
    if (p->effect) {
        const bool running = p->reader.locked();  // norns answering; otherwise stay dry
        const float wet = running ? (p->mix ? std::clamp(*p->mix, 0.f, 1.f) : 1.f) : 0.f;
        for (uint32_t i = 0; i < n; ++i) {
            ol[i] = g * (il[i] * (1.f - wet) + ol[i] * wet);
            orr[i] = g * (ir[i] * (1.f - wet) + orr[i] * wet);
        }
    } else {
        for (uint32_t i = 0; i < n; ++i) { ol[i] *= g; orr[i] *= g; }
    }
    s->plugin_blocks.fetch_add(1, std::memory_order_relaxed);
}

// Passes the block's MIDI events to the norns, if this plug-in owns its bridge.
// An atom sequence: {size, type, unit, pad}, then events {frames (8 bytes),
// size, type, data}, each padded to 8 bytes. Event times are dropped: notes
// land within one block.
void forward_midi(Plugin* p) {
    nb::Shared* s = p->shared[p->current];
    if (!p->midi || !s || s->owner.load(std::memory_order_relaxed) != id(p)) return;
    uint32_t size; std::memcpy(&size, p->midi, 4);
    if (size < 8) return;
    const uint8_t* at = p->midi + 16;
    const uint8_t* end = p->midi + 8 + size;
    while (at + 16 <= end) {
        uint32_t esize, etype;
        std::memcpy(&esize, at + 8, 4); std::memcpy(&etype, at + 12, 4);
        const uint8_t* bytes = at + 16;
        if (bytes + esize > end) break;
        if ((p->midi_type == 0 || etype == p->midi_type) && esize >= 1 && esize <= 3 && bytes[0] >= 0x80 && bytes[0] < 0xf0)
            s->midi.push(bytes, esize);
        at += 16 + ((esize + 7) & ~7u);
    }
}

void run(LV2_Handle h, uint32_t n) {
    auto* p = static_cast<Plugin*>(h);
    const int want = wanted(p);
    if (want != p->current) {  // switched to another norns: start fresh there
        release(p);
        p->current = want;
        p->reader = nb::AdaptiveReader{};
    }
    for (uint32_t offset = 0; offset < n; offset += kChunk)
        process(p, offset, std::min(kChunk, n - offset));
    if (!p->effect) forward_midi(p);
}

void cleanup(LV2_Handle h) {
    auto* p = static_cast<Plugin*>(h);
    release(p);
    for (auto* s : p->shared)
        if (s) munmap(s, sizeof(nb::Shared));
    delete p;
}

const void* extension_data(const char*) { return nullptr; }
void noop(LV2_Handle) {}
const LV2_Descriptor instrument = {kInstrumentUri, instantiate, connect_port, noop, run, noop, cleanup, extension_data};
const LV2_Descriptor effect = {kEffectUri, instantiate, connect_port, noop, run, noop, cleanup, extension_data};
}  // namespace

extern "C" __attribute__((visibility("default"))) const LV2_Descriptor* lv2_descriptor(uint32_t index) {
    return index == 0 ? &instrument : index == 1 ? &effect : nullptr;
}
