#!/bin/sh
# Build the pinned 64-bit macOS QM/Chordino Vamp plugins. Intended for macOS CI.
set -eu
OUT=${1:-storage/bundled-tools/macos}
VAMP_COMMIT=44c2487763eb248a933e9eff9169cfadee375009
QM_COMMIT=c918afc070f79489758bb2dab6895972bd82066b
QMDSP_COMMIT=e34a3cc188332ed7c33cd9257ef164de5b587191
NNLS_COMMIT=4c5f214a75cb354f8d8c933e161377c5b4d83713
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
fetch_source() {
  mkdir -p "$2"
  curl -fsSL "https://github.com/$1/archive/$3.tar.gz" -o "$WORK/source.tar.gz"
  tar -xzf "$WORK/source.tar.gz" -C "$2" --strip-components=1
}
fetch_source c4dm/vamp-plugin-sdk "$WORK/vamp" "$VAMP_COMMIT"
fetch_source c4dm/qm-vamp-plugins "$WORK/qm" "$QM_COMMIT"
fetch_source c4dm/qm-dsp "$WORK/qmdsp" "$QMDSP_COMMIT"
fetch_source c4dm/nnls-chroma "$WORK/nnls" "$NNLS_COMMIT"
ARCH="-mmacosx-version-min=11 -arch arm64 -stdlib=libc++"
make -C "$WORK/vamp" -f otherbuilds/Makefile.osx ARCHFLAGS="$ARCH" sdkstatic
make -C "$WORK/qmdsp" -f build/osx/Makefile.osx ARCHFLAGS="$ARCH"
mkdir -p "$WORK/qm/lib"
rm -rf "$WORK/qm/lib/vamp-plugin-sdk" "$WORK/qm/lib/qm-dsp"
cp -R "$WORK/vamp" "$WORK/qm/lib/vamp-plugin-sdk"
cp -R "$WORK/qmdsp" "$WORK/qm/lib/qm-dsp"
make -C "$WORK/qm" -f build/osx/Makefile.osx ARCHFLAGS="$ARCH"
make -C "$WORK/nnls" -f Makefile.osx ARCHFLAGS="$ARCH" VAMP_SDK_DIR="$WORK/vamp" BOOST_ROOT="$(brew --prefix)/include"
mkdir -p "$OUT/vamp-plugins" "$OUT/sources" "$OUT/licenses"
cp "$WORK/qm/qm-vamp-plugins.dylib" "$WORK/qm/qm-vamp-plugins.cat" "$WORK/qm/qm-vamp-plugins.n3" "$OUT/vamp-plugins/"
cp "$WORK/nnls/nnls-chroma.dylib" "$WORK/nnls/nnls-chroma.cat" "$WORK/nnls/nnls-chroma.n3" "$OUT/vamp-plugins/"
cp "$WORK/qm/COPYING" "$OUT/licenses/COPYING-qm-vamp-plugins.txt"
cp "$WORK/nnls/COPYING" "$OUT/licenses/COPYING-nnls-chroma.txt"
cp "$WORK/vamp/COPYING" "$OUT/licenses/COPYING-vamp-plugin-sdk.txt"
tar -czf "$OUT/sources/qm-vamp-plugins.tar.gz" -C "$WORK/qm" .
tar -czf "$OUT/sources/nnls-chroma.tar.gz" -C "$WORK/nnls" .
tar -czf "$OUT/sources/vamp-plugin-sdk.tar.gz" -C "$WORK/vamp" .
file "$OUT/vamp-plugins/"*.dylib
