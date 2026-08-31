#!/usr/bin/env bash
# Build a real Android app around the web app, and print what to do with it.
#
#   bash scripts/build_android.sh https://sudo-kun.tail696f09.ts.net
#
# This makes a Trusted Web Activity: a genuine APK that installs to the app
# drawer and runs full screen, with the web app inside it. That matters for
# updates -- the shell almost never changes, so publishing a new version of the
# site updates the app for everyone with nothing to reinstall.
#
# Needs Node, a JDK and the Android SDK, all of which the machine already has.

set -euo pipefail
cd "$(dirname "$0")/.."

URL="${1:-}"
if [ -z "$URL" ]; then
    echo "Usage: bash scripts/build_android.sh https://your-app-address"
    exit 1
fi
case "$URL" in
    https://*) ;;
    *) echo "It has to be https. Android refuses to build a TWA over plain http,"
       echo "because the app would have no way to prove the site is yours."
       exit 1 ;;
esac

OUT="android"
mkdir -p "$OUT"

echo
echo "  Checking the site is reachable and installable"
if ! curl -fsS "$URL/manifest.webmanifest" >/dev/null 2>&1; then
    echo "  Could not read $URL/manifest.webmanifest"
    echo "  The app has to be running and reachable at that address first."
    exit 1
fi
echo "  Manifest found."

if ! command -v bubblewrap >/dev/null 2>&1; then
    echo
    echo "  Installing Bubblewrap (Google's TWA builder)"
    npm install -g @bubblewrap/cli
fi

cd "$OUT"
if [ ! -f twa-manifest.json ]; then
    echo
    echo "  Setting the project up. Accept the defaults; it reads the rest from"
    echo "  the site's own manifest."
    bubblewrap init --manifest "$URL/manifest.webmanifest"
fi

echo
echo "  Building"
bubblewrap build

echo
echo "  Done."
echo
echo "  The signing fingerprint below has to go into the server, or the app"
echo "  opens with a browser bar across the top:"
echo
bubblewrap fingerprint list 2>/dev/null || \
    keytool -list -v -keystore android.keystore -alias android 2>/dev/null \
      | grep "SHA256:" | head -1
echo
echo "  1. Put it in .env as TWA_FINGERPRINT=<the SHA256 value>"
echo "  2. Restart the server so it publishes /.well-known/assetlinks.json"
echo "  3. Install on a phone plugged in over USB:"
echo "         adb install -r android/app-release-signed.apk"
echo
echo "  Keep android.keystore and its password safe. Losing it means the next"
echo "  build cannot update this app, only replace it."
