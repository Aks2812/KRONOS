#!/usr/bin/env bash
# Builds tests/fixtures/leaky_test.apk from the checked-in, original source
# templates in leaky_apk_src/ — no third-party or downloaded base APK.
#
# Planted artifacts (see README.md in this directory for the full list the
# tests assert against):
#   - one exported activity (.LeakyActivity) and two non-exported components
#     (.InternalService, .InternalReceiver) in AndroidManifest.xml
#   - a plaintext hardcoded secret in res/values/strings.xml
#   - a Base64-obfuscated secret in res/values/strings.xml
#   - a hardcoded internal API endpoint URL in res/values/strings.xml
#
# Requires: aapt, zipalign, apksigner (all present on this Kali VM; see
# TOOLS_mobile.md). Re-running this script regenerates leaky_test.apk from
# the same source templates and the same committed debug-signing keystore —
# the planted content is guaranteed identical on every rebuild (signature
# bytes themselves may differ run-to-run due to timestamping in the JAR/APK
# signing schemes, which is normal and does not affect what the parser
# extracts).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/leaky_apk_src"
KEYSTORE="$HERE/kronos-fixture-debug.keystore"
FRAMEWORK="${APKTOOL_FRAMEWORK:-$HOME/.local/share/apktool/framework/1.apk}"
OUT="$HERE/leaky_test.apk"

# Test-fixture-only signing key, not used for anything beyond self-signing
# this throwaway APK so apksigner will accept it. Password is intentionally
# fixed and public, same convention as Android's own well-known debug
# keystore password.
KS_PASS="kronos-fixture-pw"
KS_ALIAS="kronos-fixture"

if [ ! -f "$FRAMEWORK" ]; then
  echo "error: apktool android framework not found at $FRAMEWORK" >&2
  echo "  run: apktool d --force-framework-only /any.apk   # or install Android platform resources" >&2
  exit 1
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

aapt package -f \
  -M "$SRC/AndroidManifest.xml" \
  -S "$SRC/res" \
  -I "$FRAMEWORK" \
  -F "$workdir/unsigned.apk"

zipalign -p -f 4 "$workdir/unsigned.apk" "$workdir/aligned.apk"

apksigner sign \
  --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" --ks-key-alias "$KS_ALIAS" \
  --out "$OUT" "$workdir/aligned.apk"

apksigner verify "$OUT"
echo "built: $OUT"
