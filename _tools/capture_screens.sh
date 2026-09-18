#!/bin/bash
# Re-capture the clean app screens the site shows, straight from the Luris app.
#
#   _tools/capture_screens.sh            build the app, capture every scene, frame them
#   _tools/capture_screens.sh --no-build reuse the last build in $DERIVED
#
# What it does, in order:
#   1. Uses ONE simulator it owns, named "Luris Site iPhone 17 Pro Max", and creates it
#      if it is missing. It erases that simulator (and only that one) so the profile is
#      seeded fresh in the units below; no other simulator is booted, touched or erased.
#   2. Builds ~/Developer/Luris (Debug, for that simulator) into its own derived-data
#      folder. Debug on the simulator turns on AppEnvironment.useSampleData, so every
#      screen shows the app's own sample numbers (the fictional "Alex": 7,842 steps, the
#      demo run, the sample leaderboard). A Release build never does this.
#   3. Sets the status bar Apple's marketing rules ask for: 9:41, full signal, Wi-Fi
#      and a full battery.
#   4. Launches the app once to settle first-run sheets, then once per scene. Scenes are
#      reached with the app's DEBUG launch hooks (LURIS_TAB, LURIS_PRESENT, LURIS_SHARE,
#      LURIS_DEMO_RUN) and UserDefaults launch arguments that skip onboarding and the
#      Health prompt. Nothing in the app is changed.
#   5. Saves raw 1320x2868 captures to _tools/captures/ (git-ignored) and runs
#      _tools/build_screens.py, which frames them and writes img/screens/.
#
# Units: the sample data hard-codes kilograms on Progress and kilometres on share cards,
# so the captures use English with metric units to keep every screen consistent.
# Takes about three minutes after the build.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SITE="$(dirname "$HERE")"
APP_REPO="${APP_REPO:-$HOME/Developer/Luris}"
DERIVED="${DERIVED:-${TMPDIR:-/tmp}/luris-site-derived-data}"
SIM_NAME="Luris Site iPhone 17 Pro Max"
SIM_TYPE="com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max"
SIM_RUNTIME="${SIM_RUNTIME:-com.apple.CoreSimulator.SimRuntime.iOS-26-3}"
BUNDLE_ID="iosallapps.Luris"
OUT="$HERE/captures"
SETTLE_SECONDS=9

# English, metric, onboarding done, Health prompt already shown, leaderboard joined.
LAUNCH_ARGS=(
    -hasCompletedOnboarding YES
    -luris.healthPrimingShown 1
    -luris.health.connected 1
    -luris.leaderboard.optedIn 1
    -AppleLanguages "(en)"
    -AppleLocale "en_US@measure=metric"
    -AppleMetricUnits YES
    -AppleMeasurementUnits Centimeters
)

# slot|environment for that launch (space separated KEY=VALUE, no SIMCTL_CHILD_ prefix)
SCENES=(
    "home|LURIS_TAB=home"
    "route|LURIS_PRESENT=run LURIS_DEMO_RUN=1"
    "activity|LURIS_TAB=activity"
    "plan|LURIS_TAB=plan"
    "progress|LURIS_TAB=progress"
    "leaderboard|LURIS_PRESENT=leaderboard"
    "share|LURIS_SHARE=activity"
    "share-streak|LURIS_SHARE=streak"
)

# 1. our own simulator, found by exact name
UDID="$(xcrun simctl list devices -j | python3 -c "
import json, sys
name = sys.argv[1]
for runtime, devices in json.load(sys.stdin)['devices'].items():
    for d in devices:
        if d['name'] == name and d.get('isAvailable', True):
            print(d['udid']); sys.exit()
" "$SIM_NAME")"
if [[ -z "$UDID" ]]; then
    UDID="$(xcrun simctl create "$SIM_NAME" "$SIM_TYPE" "$SIM_RUNTIME")"
    echo "created $SIM_NAME ($UDID)"
fi
echo "simulator $SIM_NAME ($UDID)"

# 2. build for that simulator (one architecture, so it is quick)
if [[ "${1:-}" != "--no-build" ]]; then
    echo "building $APP_REPO into $DERIVED"
    xcodebuild -project "$APP_REPO/Luris.xcodeproj" -scheme Luris -configuration Debug \
        -destination "platform=iOS Simulator,id=$UDID" -derivedDataPath "$DERIVED" \
        COMPILER_INDEX_STORE_ENABLE=NO build -quiet
fi
APP="$DERIVED/Build/Products/Debug-iphonesimulator/Luris.app"
[[ -d "$APP" ]] || { echo "no build at $APP"; exit 1; }

xcrun simctl shutdown "$UDID" 2>/dev/null || true
xcrun simctl erase "$UDID"
xcrun simctl boot "$UDID"
xcrun simctl bootstatus "$UDID" -b > /dev/null

# 3. appearance and status bar
xcrun simctl ui "$UDID" appearance dark
xcrun simctl status_bar "$UDID" override --time 9:41 --dataNetwork wifi --wifiMode active --wifiBars 3 \
    --cellularMode active --cellularBars 4 --batteryState discharging --batteryLevel 100 --operatorName ""
# a freshly erased simulator can refuse the first install while it settles
for attempt in 1 2 3 4 5; do
    if xcrun simctl install "$UDID" "$APP" 2>/dev/null; then break; fi
    [[ $attempt == 5 ]] && { echo "install failed"; exit 1; }
    sleep 6
done

launch() {
    local env_pairs=("$@")
    local prefixed=()
    for pair in "${env_pairs[@]}"; do prefixed+=("SIMCTL_CHILD_$pair"); done
    xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
    sleep 1
    env ${prefixed[@]+"${prefixed[@]}"} xcrun simctl launch "$UDID" "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" > /dev/null
}

# 4. warm-up: seeds the profile in these units, answers the one-time Health re-ask
#    sheet and lets the fresh simulator's first system banner come and go.
echo "warm-up launch"
launch "LURIS_TAB=home"
sleep 20

mkdir -p "$OUT"
for scene in "${SCENES[@]}"; do
    slot="${scene%%|*}"
    read -r -a env_pairs <<< "${scene#*|}"
    launch "${env_pairs[@]}"
    sleep "$SETTLE_SECONDS"
    xcrun simctl io "$UDID" screenshot "$OUT/$slot.png" > /dev/null 2>&1
    echo "captured $slot"
done
xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl status_bar "$UDID" clear
xcrun simctl shutdown "$UDID"

# 5. frame and export
python3 "$HERE/build_screens.py"
