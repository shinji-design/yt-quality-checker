"""
動画クオリティ・チェッカー サーバー本体
"""
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
from analyzer import analyze_video

app = FastAPI(title="動画クオリティ・チェッカー")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend"
)


@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/style.css")
async def style():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "style.css"),
        media_type="text/css"
    )


@app.get("/app.js")
async def appjs():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "app.js"),
        media_type="application/javascript"
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/analyze")
async def analyze(
    channel_url: str = Query("", description="チャンネルURL（動画URL未指定の場合に使用）"),
    video_url: str = Query("", description="動画URL（チャンネルURL未指定の場合に使用）")
):
    """動画を分析し、進捗をServer-Sent Eventsで返す。
    動画URLとチャンネルURLのどちらか一方を指定する。
    両方指定された場合は動画URLを優先する。
    チャンネルURLのみの場合は、そのチャンネルの最新動画を分析する。
    """
    async def stream():
        try:
            async for progress in analyze_video(channel_url, video_url):
                yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"step": "error", "message": f"システムエラー: {str(e)[:200]}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
