#!/bin/zsh
# build.sh — 빌드 카운트 자동 증가, 빌드+설치, 로그 기록

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
COUNT_FILE="$PROJECT_DIR/build_number.txt"
LOG_FILE="$PROJECT_DIR/build_log.txt"
DEVICE_ID="ABF59436-7009-59CC-ABBB-569036DA18F3"
SCHEME="OLiveCam"
DERIVED_DATA="$HOME/Library/Developer/Xcode/DerivedData"

# 빌드 번호 읽기 / 초기화
if [[ -f "$COUNT_FILE" ]]; then
    BUILD_NUM=$(cat "$COUNT_FILE")
else
    BUILD_NUM=3
fi
BUILD_NUM=$((BUILD_NUM + 1))

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  빌드 #$BUILD_NUM  $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 빌드
xcodebuild \
    -project "$PROJECT_DIR/LiveCatCam.xcodeproj" \
    -scheme "$SCHEME" \
    -configuration Debug \
    -destination 'generic/platform=iOS' \
    CODE_SIGN_ENTITLEMENTS="" \
    CURRENT_PROJECT_VERSION="$BUILD_NUM" \
    build \
    2>&1 | tee /tmp/xcodebuild_last.log | grep -E "error:|BUILD SUCCEEDED|BUILD FAILED" | grep -v "^$"

# 빌드 결과 확인
if grep -q "BUILD SUCCEEDED" /tmp/xcodebuild_last.log; then
    STATUS="SUCCESS"
else
    echo "✗ 빌드 실패 — build_number.txt 유지"
    exit 1
fi

# 빌드 번호 저장 (성공 시만)
echo "$BUILD_NUM" > "$COUNT_FILE"

# 설치
echo "\n▶ iPhone에 설치 중..."
APP=$(find "$DERIVED_DATA"/LiveCatCam-*/Build/Products/Debug-iphoneos/ -name "*.app" 2>/dev/null | head -1)
xcrun devicectl device install app --device "$DEVICE_ID" "$APP" 2>&1

# 로그 기록
echo "$(date '+%Y-%m-%d %H:%M:%S')  #$BUILD_NUM  $STATUS" >> "$LOG_FILE"

echo "\n✓ 완료  빌드 #$BUILD_NUM"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "최근 빌드 이력:"
tail -10 "$LOG_FILE"
