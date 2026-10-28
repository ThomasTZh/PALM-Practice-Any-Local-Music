# Local Vamp native host

The default analysis path uses a small C++ host built against the Vamp Host
SDK. It reads interleaved float32 PCM and emits only the `beats` and `bars`
features, avoiding the per-block JSON overhead of the Piper host.

This is local personal-use tooling. The QM plugin pack is AGPL; the host and
plugins are not part of the application's distributable code.

## Build (Linux, local SDK checkout)

The Vamp SDK is available at <https://github.com/c4dm/vamp-plugin-sdk>. The
host source is [scripts/vamp_host.cpp](../scripts/vamp_host.cpp).

```sh
cd <vamp-sdk>
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DVAMPSDK_BUILD_EXAMPLE_PLUGINS=ON
cmake --build build --target vamp-hostsdk vamp-sdk -j2

g++ -O2 -std=c++11 -I . -I src \
  <repo>/scripts/vamp_host.cpp \
  build/libvamp-hostsdk.a build/libvamp-sdk.a \
  -ldl -lpthread -o <repo>/storage/tools/vamp-host
```

Extract the QM plugin library from the Vamp Plugin Pack installer into
`storage/tools/vamp-plugins` (for example `qm-vamp-plugins.so`).

## Configure

```sh
export BASSEPARATE_VAMP_PLUGIN_PATH="$PWD/storage/tools/vamp-plugins"
export BASSEPARATE_VAMP_NATIVE_HOST_PATH="$PWD/storage/tools/vamp-host"
```

The fallback Piper host uses `BASSEPARATE_VAMP_SERVER`,
`BASSEPARATE_VAMP_LIBRARY_PATH`, and the same plugin path.

## Verify

```sh
BASSEPARATE_VAMP_NATIVE_HOST_PATH=$PWD/storage/tools/vamp-host \
BASSEPARATE_VAMP_PLUGIN_PATH=$PWD/storage/tools/vamp-plugins \
  .venv/bin/python -m pytest tests/integration/test_vamp_native_real.py -q
```

The native host is a performance path, not a quality change: both hosts run
the same QM plugin and produce the same beats/bars.
