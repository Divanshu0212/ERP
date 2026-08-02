#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/3: generating narration audio (Piper TTS) =="
node 01-generate-audio.js

echo "== 2/3: recording scenes (Playwright against http://localhost:3001) =="
node 02-record.js

echo "== 3/3: assembling final video (ffmpeg) =="
node 03-assemble.js

echo "Done: final/su-erp-demo.mp4"
