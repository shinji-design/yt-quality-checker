# 動画クオリティ・チェッカー

YouTubeの動画3分を分析して、収益化審査の合格水準かを5段階で判定するWebツール。

## 機能

- 動画の最初の3分を解析
- 5つの観点（動きのバランス／止まっている時間／場面切替／動きの種類／集中度）を採点
- 総合スコア（100点満点）と判定
- 改善アドバイスの自動生成

## 技術構成

- バックエンド: Python + FastAPI + Playwright
- フロントエンド: HTML + JavaScript（バニラ）
- デプロイ先: Render.com（Docker）

## ローカル起動

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

ブラウザで `http://localhost:8000` を開く。

## ライセンス

社内利用版
