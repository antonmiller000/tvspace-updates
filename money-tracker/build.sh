#!/usr/bin/env bash
# Builds Hamanets.apk without Gradle. Needs JDK 17+, Android build-tools 35 or newer and platform android-34.
#   BUILD_TOOLS=/path/to/build-tools/36.0.0 ANDROID_JAR=/path/to/platforms/android-34/android.jar ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
BT="${BUILD_TOOLS:?set BUILD_TOOLS}"; JAR="${ANDROID_JAR:?set ANDROID_JAR}"
OUT=build; rm -rf "$OUT"; mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

"$BT/aapt2" compile --dir app/res -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$JAR" --manifest app/AndroidManifest.xml \
  -A app/assets --java "$OUT/gen" "$OUT/res.zip"
javac -nowarn --release 8 -cp "$JAR" -d "$OUT/classes" $(find app/src "$OUT/gen" -name '*.java')
jar cf "$OUT/classes.jar" -C "$OUT/classes" .
"$BT/d8" --release --min-api 26 --lib "$JAR" --output "$OUT/dex" "$OUT/classes.jar"
(cd "$OUT/dex" && zip -q -j ../base.apk classes.dex)
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

# The signing key stays on this machine (it is gitignored). Keep it: updates must be signed with the same key.
[ -f signing.keystore ] || keytool -genkeypair -keystore signing.keystore -storepass hamanets -keypass hamanets \
  -alias hamanets -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Hamanets"
"$BT/apksigner" sign --ks signing.keystore --ks-pass pass:hamanets --key-pass pass:hamanets \
  --out Hamanets.apk "$OUT/aligned.apk"
"$BT/apksigner" verify --verbose Hamanets.apk | head -4
rm -f Hamanets.apk.idsig; ls -la Hamanets.apk
