#!/bin/bash
# 動画クオリティ・チェッカー起動スクリプト
cd "$(dirname "$0")/backend"
source venv/bin/activate
echo ""
echo "========================================"
echo "  動画クオリティ・チェッカー 起動中"
echo "========================================"
echo ""
echo "ブラウザで以下のURLを開いてください："
echo ""
echo "  http://localhost:8000"
echo ""
echo "停止するには Ctrl+C を押してください"
echo "========================================"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000
