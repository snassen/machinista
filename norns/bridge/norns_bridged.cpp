// JACK client on the norns side of the bridge, one per norns instance (it runs
// inside that instance's container). Sends crone's outputs to Machinista and
// Machinista's audio (instrument sidechain or effect input) to crone's inputs.
// Based on the Pi 4 add-on's daemon; the bridge file is now a path argument.
// It also passes the Norns Instrument's MIDI to matron as OSC
// /machinista/midi (status, data1, data2); the machinista_bridge mod plays it
// as MIDI from the virtual device on port 1.
//
// Usage: norns_bridged [--no-crone] [--no-midi] [path]   (path defaults to /frames/bridge)
#include "bridge_shm.h"
#include <arpa/inet.h>
#include <csignal>
#include <cstring>
#include <netinet/in.h>
#include <sys/socket.h>
#include <cstdio>
#include <jack/jack.h>
#include <string_view>

static jack_port_t* in_l; static jack_port_t* in_r; static jack_port_t* out_l; static jack_port_t* out_r;
static nb::Shared* shared; static nb::AdaptiveReader reader; static double rate = 48000;
static volatile sig_atomic_t running = 1;

static int process(jack_nframes_t n, void*) {
    auto* il = static_cast<float*>(jack_port_get_buffer(in_l, n));
    auto* ir = static_cast<float*>(jack_port_get_buffer(in_r, n));
    auto* ol = static_cast<float*>(jack_port_get_buffer(out_l, n));
    auto* or_ = static_cast<float*>(jack_port_get_buffer(out_r, n));
    shared->to_machinista.push(il, ir, n);
    const int configured = shared->target_frames.load(std::memory_order_relaxed);
    reader.read(shared->to_norns, shared->in_stats, ol, or_, n, configured > 0 ? configured : nb::kInputTarget, n / rate);
    shared->daemon_blocks.fetch_add(1, std::memory_order_relaxed);
    return 0;
}

constexpr int kMatronOscPort = 10111;

// One OSC message: /machinista/midi ,iii status data1 data2 (data2 = -1 for a
// two-byte message).
static size_t osc_midi(uint32_t word, char* out) {
    static const char head[] = "/machinista/midi\0\0\0\0,iii\0\0\0\0";  // address and tags, padded to 4
    std::memcpy(out, head, 28);  // 16 + 4 and 4 + 4 bytes
    const int n = int(word >> 24);
    const int32_t v[3] = {int32_t((word >> 16) & 0xff), int32_t((word >> 8) & 0xff), n > 2 ? int32_t(word & 0xff) : -1};
    for (int i = 0; i < 3; ++i) { const uint32_t be = htonl(uint32_t(v[i])); std::memcpy(out + 28 + 4 * i, &be, 4); }
    return 40;
}

int main(int argc, char** argv) {
    bool wire_crone = true, midi = true;
    const char* path = "/frames/bridge";
    for (int i = 1; i < argc; ++i) {
        if (std::string_view(argv[i]) == "--no-crone") wire_crone = false;
        else if (std::string_view(argv[i]) == "--no-midi") midi = false;
        else path = argv[i];
    }
    shared = nb::bridge_open(path);
    if (!shared) { perror(path); return 1; }
    jack_client_t* client = jack_client_open("machinista-bridge", JackNoStartServer, nullptr);
    if (!client) { fputs("no JACK server\n", stderr); return 1; }
    rate = jack_get_sample_rate(client);
    in_l = jack_port_register(client, "in_1", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    in_r = jack_port_register(client, "in_2", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    out_l = jack_port_register(client, "out_1", JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
    out_r = jack_port_register(client, "out_2", JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
    jack_set_process_callback(client, process, nullptr);
    jack_activate(client);
    if (wire_crone) {
        bool wired = false;
        for (int i = 0; i < 300 && !wired; ++i) {
            const int a = jack_connect(client, "crone:output_1", "machinista-bridge:in_1");
            const int b = jack_connect(client, "crone:output_2", "machinista-bridge:in_2");
            const int c = jack_connect(client, "machinista-bridge:out_1", "crone:input_1");
            const int d = jack_connect(client, "machinista-bridge:out_2", "crone:input_2");
            const auto ok = [](int r) { return r == 0 || r == 17; };  // 17 = already connected
            wired = ok(a) && ok(b) && ok(c) && ok(d);
            if (!wired) usleep(200000);
        }
        printf("%s %s\n", wired ? "BRIDGE_WIRED" : "BRIDGE_WIRE_FAILED", path);
        fflush(stdout);
    }
    std::signal(SIGINT, [](int) { running = 0; });
    std::signal(SIGTERM, [](int) { running = 0; });
    // MIDI written while no daemon ran is stale: start from now.
    shared->midi.read.store(shared->midi.write.load(std::memory_order_acquire), std::memory_order_release);
    const int sock = midi ? socket(AF_INET, SOCK_DGRAM, 0) : -1;
    sockaddr_in matron{};
    matron.sin_family = AF_INET;
    matron.sin_port = htons(kMatronOscPort);
    matron.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    while (running) {
        if (sock < 0) { pause(); continue; }
        uint32_t word; char msg[40];
        while (shared->midi.pop(word))
            sendto(sock, msg, osc_midi(word, msg), 0, reinterpret_cast<sockaddr*>(&matron), sizeof matron);
        usleep(1000);
    }
    jack_client_close(client);
    return 0;
}
