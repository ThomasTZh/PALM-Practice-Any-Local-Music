#include <vamp-hostsdk/PluginLoader.h>
#include <vamp-sdk/Plugin.h>
#include <vamp-sdk/RealTime.h>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <cmath>

using namespace Vamp;
using namespace Vamp::HostExt;

static std::string esc(const std::string &s) {
    std::ostringstream o;
    for (char c : s) {
        if (c == '"' || c == '\\') o << '\\' << c;
        else if (c == '\n') o << "\\n";
        else o << c;
    }
    return o.str();
}

static std::string event_json(const Plugin::Feature &f) {
    std::ostringstream o;
    double t = f.timestamp.sec + f.timestamp.nsec / 1e9;
    o << "{\"time_seconds\":" << t << ",\"label\":";
    if (f.hasTimestamp && !f.label.empty()) o << "\"" << esc(f.label) << "\"";
    else o << "null";
    o << ",\"values\":[";
    for (size_t i = 0; i < f.values.size(); ++i) {
        if (i) o << ",";
        o << f.values[i];
    }
    o << "]}";
    return o.str();
}

int main(int argc, char **argv) {
    if (argc != 7) {
        std::cerr << "usage: vamp-host plugin_key pcm_f32 sample_rate channels bpb output_json\n";
        return 2;
    }
    std::string key = argv[1];
    std::string pcmPath = argv[2];
    int rate = std::stoi(argv[3]);
    int channels = std::stoi(argv[4]);
    int bpb = std::stoi(argv[5]);
    std::string outputPath = argv[6];
    if (channels < 1) return 2;

    std::ifstream in(pcmPath, std::ios::binary);
    if (!in) { std::cerr << "cannot open PCM\n"; return 1; }
    in.seekg(0, std::ios::end);
    std::streamoff bytes = in.tellg();
    in.seekg(0, std::ios::beg);
    if (bytes <= 0 || bytes % (4 * channels) != 0) { std::cerr << "PCM is not aligned\n"; return 1; }
    size_t totalFrames = static_cast<size_t>(bytes / (4 * channels));
    std::vector<float> raw(totalFrames * channels);
    in.read(reinterpret_cast<char *>(raw.data()), bytes);
    if (!in) { std::cerr << "cannot read PCM\n"; return 1; }

    PluginLoader *loader = PluginLoader::getInstance();
    Plugin *plugin = loader->loadPlugin(key, rate, 0);
    if (!plugin) { std::cerr << "cannot load plugin " << key << "\n"; return 1; }
    plugin->setParameter("bpb", static_cast<float>(bpb));
    size_t step = plugin->getPreferredStepSize();
    size_t block = plugin->getPreferredBlockSize();
    if (step == 0) step = block;
    if (block == 0 || step == 0) { std::cerr << "invalid plugin framing\n"; return 1; }
    if (!plugin->initialise(1, step, block)) { std::cerr << "plugin initialise failed\n"; return 1; }

    Plugin::FeatureSet all;
    std::vector<float> mono(block);
    for (size_t start = 0; start < totalFrames; start += step) {
        std::fill(mono.begin(), mono.end(), 0.0f);
        size_t count = std::min(block, totalFrames - start);
        for (size_t i = 0; i < count; ++i) {
            float sum = 0.0f;
            for (int c = 0; c < channels; ++c) sum += raw[(start + i) * channels + c];
            mono[i] = sum / channels;
        }
        const float *input[1] = {mono.data()};
        RealTime timestamp;
        timestamp = RealTime::frame2RealTime(static_cast<long>(start), rate);
        Plugin::FeatureSet fs = plugin->process(input, timestamp);
        for (const auto &entry : fs)
            all[entry.first].insert(all[entry.first].end(), entry.second.begin(), entry.second.end());
    }
    Plugin::FeatureSet fs = plugin->getRemainingFeatures();
    for (const auto &entry : fs)
        all[entry.first].insert(all[entry.first].end(), entry.second.begin(), entry.second.end());

    auto descriptors = plugin->getOutputDescriptors();
    std::ostringstream o;
    o << "{\"plugin\":\"" << esc(key) << "\",\"plugin_version\":\""
      << esc(std::to_string(plugin->getPluginVersion())) << "\",\"sample_rate\":" << rate
      << ",\"bpb\":" << bpb << ",\"features\":{";
    bool firstOutput = true;
    for (size_t oi = 0; oi < descriptors.size(); ++oi) {
        const std::string &id = descriptors[oi].identifier;
        if (id != "beats" && id != "bars") continue;
        if (!firstOutput) o << ",";
        firstOutput = false;
        o << "\"" << esc(id) << "\":[";
        for (size_t i = 0; i < all[oi].size(); ++i) {
            if (i) o << ",";
            o << event_json(all[oi][i]);
        }
        o << "]";
    }
    o << "}}";
    std::ofstream out(outputPath);
    out << o.str() << "\n";
    delete plugin;
    return 0;
}
