# Mobile ingestion test fixture: `leaky_test.apk`

A tiny, deliberately-leaky APK built from scratch for Brief #2's tests —
original content only, no third-party base APK (an earlier attempt reused a
GPL-licensed sample from Kali's `exploitdb-bin-sploits` package as a decode
base; dropped in favor of building clean from an original manifest +
resources to avoid any licensing ambiguity in a committed fixture).

**Secret value format note:** the planted plaintext secret deliberately
avoids any real payment-processor's live-key prefix format (an earlier
draft used one, which tripped GitHub push protection's secret scanner even
as fake test data — fixed by using an unambiguously-fixture-shaped value
instead, with no resemblance to any real vendor's key format).

**Rebuild:** `./build_leaky_apk.sh` (regenerates `leaky_test.apk` from the
source templates below and the committed debug-signing keystore;
deterministic in content — the planted artifacts are byte-identical on every
rebuild — though the signature's own bytes may vary run-to-run due to
timestamping in the APK signing schemes, which doesn't affect extraction).

**Source templates** (git-tracked, hand-written):
- `leaky_apk_src/AndroidManifest.xml`
- `leaky_apk_src/res/values/strings.xml`

## Planted artifacts (what the tests assert against)

- **Package / bundle id:** `com.kronos.testfixture.leakyapp`
- **Exported component:** `.LeakyActivity` (activity, `android:exported="true"`)
- **Non-exported components:** `.InternalService` (service),
  `.InternalReceiver` (receiver) — both `android:exported="false"`
- **Launcher activity:** `.MainActivity` — also exported (implicitly, via its
  `MAIN`/`LAUNCHER` intent-filter), included for manifest-parsing realism,
  not a planted "finding" itself.
- **Plaintext secret** (`res/values/strings.xml`, resource name
  `kronos_api_key`): `KRONOS_FIXTURE_PLAINTEXT_SECRET_abcdef1234567890`
- **Obfuscated secret** (resource name `kronos_api_key_enc`), Base64-encoded:
  `a3Jvbm9zX3Rlc3Rfb2JmdXNjYXRlZF9zZWNyZXRfOTg3NjU0MzIx` → decodes to
  `kronos_test_obfuscated_secret_987654321`
- **Internal API endpoint** (resource name `kronos_api_base_url`):
  `https://internal-api.kronos-fixture.test/v1/admin`

## Known limitation (tracked follow-up, not silently dropped)

Per Brief #2's own scope, only **Base64 obfuscation** is planted and tested
here. **Split/concatenated-string obfuscation** (a secret built at runtime
from several string-literal fragments, e.g. `"sk_" + "live_" + "abc123"` or
assembled via `StringBuilder`) is a materially harder static-extraction
problem — it needs real decompiled-code data-flow/constant-folding analysis,
not a regex pass, and is explicitly **out of scope for this brief**. Tracked
as a follow-up for whichever later brief hardens `light_extractors` against
code-level obfuscation generally.
