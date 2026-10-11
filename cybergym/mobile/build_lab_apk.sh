#!/usr/bin/env bash
# Builds cybergym/mobile/cybergym_lab.apk from the checked-in source
# templates in apk_src/ — original content only, same from-scratch
# approach as Brief #2's tests/fixtures/build_leaky_apk.sh (reused
# deliberately, see DECISIONS.md). No third-party base APK.
#
# Planted artifacts (see ground_truth.yaml for the full grading key):
#   - Chain 1: plaintext secret + undocumented endpoint reference
#     (res/values/strings.xml)
#   - Chain 2: Base64-obfuscated AWS-shaped credential pair
#     (res/values/strings.xml)
#   - Chain 3: a secret split across assets/cfg.dat (first half) and
#     res/values/strings.xml (second half) — neither file alone is the
#     real credential
#
# Requires: aapt, zipalign, apksigner.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/apk_src"
KEYSTORE="$HERE/cybergym-debug.keystore"
FRAMEWORK="${APKTOOL_FRAMEWORK:-$HOME/.local/share/apktool/framework/1.apk}"
OUT="$HERE/cybergym_lab.apk"

KS_PASS="cybergym-fixture-pw"
KS_ALIAS="cybergym-lab"

if [ ! -f "$FRAMEWORK" ]; then
  echo "error: apktool android framework not found at $FRAMEWORK" >&2
  exit 1
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

aapt package -f \
  -M "$SRC/AndroidManifest.xml" \
  -S "$SRC/res" \
  -A "$SRC/assets" \
  -I "$FRAMEWORK" \
  -F "$workdir/unsigned.apk"

zipalign -p -f 4 "$workdir/unsigned.apk" "$workdir/aligned.apk"

apksigner sign \
  --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" --ks-key-alias "$KS_ALIAS" \
  --out "$OUT" "$workdir/aligned.apk"

apksigner verify "$OUT"
echo "built: $OUT"
