"""
動画分析ロジック
"""
import asyncio
import re
from playwright.async_api import async_playwright


CAPTURE_SCRIPT = """
async () => {
    const player = document.querySelector('#movie_player');
    const v = document.querySelector('video');
    if (!player || !v) return {error: 'プレーヤーが見つかりません', debug: {hasPlayer: !!player, hasVideo: !!v}};

    // 初期診断情報
    const initDiag = {
        videoDuration: v.duration,
        videoReadyState: v.readyState,
        videoNetworkState: v.networkState,
        videoSrc: v.src ? 'has-src' : 'no-src',
        videoWidth: v.videoWidth,
        videoHeight: v.videoHeight,
        playerExists: typeof player.playVideo === 'function',
    };

    try { player.mute(); } catch(e) {}
    try { v.muted = true; } catch(e) {}

    let playError = null;
    try {
        player.setPlaybackRate(2);
        player.playVideo();
        await new Promise(r => setTimeout(r, 3000));
    } catch(e) { playError = 'phase1:' + e.message; }

    try {
        player.seekTo(0);
        player.setPlaybackRate(4);
        const playPromise = v.play();
        if (playPromise) await playPromise.catch(e => { playError = 'phase2:' + e.message; });
    } catch(e) {
        return {error: '動画再生に失敗: ' + e.message, debug: initDiag};
    }

    await new Promise(r => setTimeout(r, 2000));
    const playDiag = {
        currentTime: v.currentTime,
        paused: v.paused,
        ended: v.ended,
        playError: playError,
        readyStateAfter: v.readyState,
    };

    if (v.currentTime === 0 && v.paused) {
        return {error: '動画が再生されません', debug: {init: initDiag, play: playDiag}};
    }

    return new Promise((resolve) => {
        const targets = [];
        for (let t = 0; t <= 180; t++) targets.push(t);
        const diffs = [];
        let idx = 0;
        let prev = null;
        const startTime = Date.now();
        const maxWait = 240000;

        const interval = setInterval(() => {
            try {
                if (Date.now() - startTime > maxWait) {
                    clearInterval(interval);
                    try { player.pauseVideo(); player.setPlaybackRate(1); } catch(e) {}
                    resolve({diffs, completed: false, reason: 'timeout'});
                    return;
                }
                if (idx >= targets.length || v.currentTime > 185) {
                    clearInterval(interval);
                    try { player.pauseVideo(); player.setPlaybackRate(1); } catch(e) {}
                    resolve({diffs, completed: true});
                    return;
                }
                const tNow = v.currentTime;
                while (idx < targets.length && targets[idx] <= tNow) {
                    const c = document.createElement('canvas');
                    c.width = 80; c.height = 45;
                    const ctx = c.getContext('2d');
                    try {
                        ctx.drawImage(v, 0, 0, 80, 45);
                        const px = ctx.getImageData(0, 0, 80, 45).data;
                        if (prev) {
                            let s = 0;
                            for (let i = 0; i < px.length; i += 4) {
                                s += Math.abs(px[i]-prev[i]) + Math.abs(px[i+1]-prev[i+1]) + Math.abs(px[i+2]-prev[i+2]);
                            }
                            diffs.push(s/(px.length/4*3));
                        }
                        prev = px;
                    } catch(e) {}
                    idx++;
                }
            } catch(e) {}
        }, 300);
    });
}
"""


def extract_video_id(url: str):
    m = re.search(r'(?:v=|youtu\.be/|/embed/|/v/|/shorts/)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None


def is_channel_url(url: str) -> bool:
    """チャンネルURLかどうかを判定"""
    if not url:
        return False
    return any(p in url for p in ['/channel/', '/@', '/c/', '/user/'])


async def get_latest_video_id(page, channel_url: str):
    """チャンネルURLから最新動画のIDを取得"""
    # /videos を末尾に追加
    url = channel_url.rstrip('/')
    if not url.endswith('/videos'):
        url = url + '/videos'

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # HTMLから最新の動画IDを抽出
    html = await page.content()
    matches = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
    if not matches:
        return None
    return matches[0]


def calc_stats(diffs):
    if not diffs or len(diffs) < 50:
        return None

    n = len(diffs)
    bands = [
        sum(1 for d in diffs if d < 2),
        sum(1 for d in diffs if 2 <= d < 5),
        sum(1 for d in diffs if 5 <= d < 10),
        sum(1 for d in diffs if 10 <= d < 20),
        sum(1 for d in diffs if 20 <= d < 40),
        sum(1 for d in diffs if 40 <= d < 60),
        sum(1 for d in diffs if 60 <= d < 100),
        sum(1 for d in diffs if d >= 100),
    ]

    return {
        'n': n,
        'mean': sum(diffs) / n,
        'sharpCut': sum(1 for d in diffs if d >= 60) / n * 100,
        'lowChange': sum(1 for d in diffs if d < 20) / n * 100,
        'midRange': sum(1 for d in diffs if 20 <= d < 60) / n * 100,
        'eventRate': sum(1 for d in diffs if d >= 20) / n * 100,
        'maxBand': max(bands) / n * 100,
        'usedBands': sum(1 for b in bands if b >= 5),
    }


def calc_5_scores(stats):
    mean = stats['mean']
    if 18 <= mean <= 25:
        balance = 90 + (1 - abs(mean - 21.5) / 3.5) * 10
    elif 14 <= mean < 18 or 25 < mean <= 30:
        balance = 70 + (1 - abs(mean - 21.5) / 8.5) * 20
    elif 10 <= mean < 14 or 30 < mean <= 35:
        balance = 50
    else:
        balance = max(20, 50 - abs(mean - 21.5) * 2)

    lc = stats['lowChange']
    if 50 <= lc <= 75:
        still = 90
    elif lc < 50:
        still = max(30, 90 - (50 - lc) * 1.5)
    elif lc <= 85:
        still = max(50, 90 - (lc - 75) * 4)
    else:
        still = max(0, 50 - (lc - 85) * 5)

    er = stats['eventRate']
    if 25 <= er <= 50:
        scene = 90
    elif er < 25:
        scene = max(40, 90 - (25 - er) * 2)
    elif er <= 70:
        scene = max(60, 90 - (er - 50) * 1.5)
    else:
        scene = max(0, 60 - (er - 70) * 4)

    ub = stats['usedBands']
    variety = {8: 95, 7: 95, 6: 80, 5: 55, 4: 30, 3: 15}.get(ub, 10)

    mb = stats['maxBand']
    if mb < 30:
        concentrate = 95
    elif mb < 40:
        concentrate = 85
    elif mb < 45:
        concentrate = 70
    elif mb <= 50:
        concentrate = 55
    else:
        concentrate = max(0, 55 - (mb - 50) * 5)

    balance = max(0, min(100, balance))
    still = max(0, min(100, still))
    scene = max(0, min(100, scene))
    variety = max(0, min(100, variety))
    concentrate = max(0, min(100, concentrate))

    total = (balance + still + scene + variety + concentrate) / 5

    return {
        'balance': round(balance),
        'still': round(still),
        'scene': round(scene),
        'variety': round(variety),
        'concentrate': round(concentrate),
        'total': round(total),
    }


def make_advice(stats, scores):
    advice = []

    if scores['variety'] < 60:
        ub = stats['usedBands']
        advice.append({
            "priority": 1,
            "title": "動きの種類を増やしましょう",
            "current": f"今：{ub}種類",
            "target": "目標：6種類以上",
            "how": [
                "「3秒くらい完全に止まる場面」を1〜2回入れる",
                "章の変わり目に「フェードイン・フェードアウト」を入れる",
                "テロップだけ動かす場面を作る（画面はそのまま）"
            ]
        })

    if scores['still'] < 60:
        lc = stats['lowChange']
        if lc > 75:
            advice.append({
                "priority": 2,
                "title": "「ほとんど動かない時間」を減らしましょう",
                "current": f"今：3分のうち約{int(lc * 1.8)}秒が止まったまま",
                "target": "目標：3分のうち90〜135秒以内",
                "how": [
                    "同じ絵がずっと続く場面を10秒短くする",
                    "代わりに「ゆっくりズーム」や「別の絵への切替」を入れる",
                    "1つの場面を15秒以上見せない"
                ]
            })
        elif lc < 50:
            advice.append({
                "priority": 2,
                "title": "「動きすぎ」を少し落ち着かせましょう",
                "current": f"今：3分のうち止まる時間が約{int(lc * 1.8)}秒",
                "target": "目標：3分のうち90〜135秒",
                "how": [
                    "同じ絵をゆっくり見せる時間を増やす",
                    "場面切替の頻度を下げる",
                    "完全に静止する「間（ま）」を入れる"
                ]
            })

    if scores['concentrate'] < 60:
        advice.append({
            "priority": 3,
            "title": "「同じ動き」が長く続いている場面を分散させましょう",
            "current": f"今：1種類の動きが3分のうち約{int(stats['maxBand'] * 1.8)}秒を占めています",
            "target": "目標：1種類の動きは3分のうち80秒以内",
            "how": [
                "ゆっくりズームを使いすぎないようにする",
                "別のキャラ・別の背景への切替を増やす",
                "テロップ動作と組み合わせる"
            ]
        })

    if scores['scene'] < 60:
        er = stats['eventRate']
        if er > 50:
            advice.append({
                "priority": 4,
                "title": "場面切替の回数を少し減らしましょう",
                "current": f"今：3分で約{int(er * 1.8)}回の場面切替",
                "target": "目標：3分で45〜90回程度",
                "how": [
                    "急な場面転換を「ゆっくりズーム」に置き換える",
                    "1つの場面を長めに見せる時間を増やす"
                ]
            })
        elif er < 25:
            advice.append({
                "priority": 4,
                "title": "場面切替の回数を増やしましょう",
                "current": f"今：3分で約{int(er * 1.8)}回しか場面が変わらない",
                "target": "目標：3分で45〜90回程度",
                "how": [
                    "12秒以上同じ絵を見せない",
                    "別の絵・別の角度を増やす"
                ]
            })

    return advice[:3]


def make_judgment(total):
    if total >= 85:
        return {
            "level": "good",
            "icon": "🟢",
            "label": "合格水準",
            "message": "動画の中身は十分な品質です。",
        }
    elif total >= 70:
        return {
            "level": "near",
            "icon": "🟡",
            "label": "ほぼ合格",
            "message": "あと少しで合格水準です。軽い直しで問題ありません。",
        }
    elif total >= 55:
        return {
            "level": "border",
            "icon": "🟡",
            "label": "もうすぐ合格",
            "message": "あと少しの直しで、合格の見込みが大きく上がります。",
        }
    elif total >= 40:
        return {
            "level": "warn",
            "icon": "🟠",
            "label": "要改善",
            "message": "いくつかの点を直す必要があります。",
        }
    else:
        return {
            "level": "ng",
            "icon": "🔴",
            "label": "大幅な作り直しが必要",
            "message": "現状では合格水準に届きません。",
        }


async def analyze_video(channel_url: str, video_url: str):
    yield {"step": "init", "progress": 5, "message": "処理を開始しています..."}

    # 入力チェック：どちらか一方は必須
    has_video = bool(video_url and video_url.strip())
    has_channel = bool(channel_url and channel_url.strip())

    if not has_video and not has_channel:
        yield {"step": "error", "message": "動画URLまたはチャンネルURLのどちらかを入力してください。"}
        return

    # 動画URLが指定されていればそれを優先
    video_id = None
    if has_video:
        video_id = extract_video_id(video_url)
        if not video_id:
            yield {"step": "error", "message": "動画URLが正しくありません。再度ご確認ください。"}
            return

    yield {"step": "browser", "progress": 10, "message": "ブラウザを起動中..."}

    async with async_playwright() as p:
        # ヘッドレスモードで動画フレームを取得するため "new" headless を使用
        browser = await p.chromium.launch(
            headless=False,  # headless=False + --headless=new で新ヘッドレスモードを有効化
            args=[
                '--headless=new',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--lang=ja-JP',
                '--autoplay-policy=no-user-gesture-required',
                '--disable-background-media-suspend',
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ja-JP'
        )
        # YouTubeのCookie同意を回避
        await context.add_cookies([
            {'name': 'CONSENT', 'value': 'YES+', 'url': 'https://www.youtube.com'},
            {'name': 'SOCS', 'value': 'CAI', 'url': 'https://www.youtube.com'},
            {'name': 'PREF', 'value': 'hl=ja&gl=JP', 'url': 'https://www.youtube.com'},
        ])
        # Bot検出回避（webdriver等を隠す）
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en']});
            window.chrome = {runtime: {}};
        """)
        page = await context.new_page()

        try:
            # 動画URLがなければ、チャンネルから最新動画を取得
            if not video_id:
                if not is_channel_url(channel_url):
                    yield {"step": "error", "message": "チャンネルURLが正しくありません。「youtube.com/@xxx」「youtube.com/channel/xxx」の形式で入力してください。"}
                    await browser.close()
                    return

                yield {"step": "find_latest", "progress": 15, "message": "チャンネルから最新動画を取得中..."}
                video_id = await get_latest_video_id(page, channel_url)
                if not video_id:
                    yield {"step": "error", "message": "チャンネルから動画が見つかりませんでした。URLをご確認ください。"}
                    await browser.close()
                    return

            yield {"step": "navigate", "progress": 20, "message": "動画ページにアクセス中..."}
            await page.goto(
                f"https://www.youtube.com/watch?v={video_id}",
                wait_until="domcontentloaded",
                timeout=30000
            )

            # #movie_player要素が出現するのを待つ（最大20秒）
            player_found = False
            try:
                await page.wait_for_selector('#movie_player', timeout=20000)
                player_found = True
            except:
                pass

            await page.wait_for_timeout(3000)

            # プレーヤーが見つからない場合は詳細情報を取得
            if not player_found:
                try:
                    current_url = page.url
                    page_title = await page.title()
                    body_snippet = await page.evaluate('document.body.innerText.substring(0, 200)')
                    yield {
                        "step": "error",
                        "message": f"動画プレーヤーを読み込めませんでした。URL={current_url[:60]} / Title={page_title[:50]} / 内容={body_snippet[:100]}"
                    }
                    await browser.close()
                    return
                except Exception as e:
                    yield {"step": "error", "message": f"動画プレーヤーが見つかりません: {str(e)[:100]}"}
                    await browser.close()
                    return

            try:
                title = await page.title()
                title = title.replace(" - YouTube", "")[:80]
            except:
                title = "（タイトル取得不可）"

            yield {"step": "capture_start", "progress": 30, "message": "動画の動きを分析しています...（5分ほどお待ちください）"}

            result = await asyncio.wait_for(
                page.evaluate(CAPTURE_SCRIPT),
                timeout=300
            )

            if result.get('error'):
                yield {"step": "error", "message": result['error']}
                await browser.close()
                return

            diffs = result.get('diffs', [])
            completed = result.get('completed', False)
            reason = result.get('reason', '')
            if len(diffs) < 50:
                yield {"step": "error", "message": f"動画の分析に十分なデータが取得できませんでした。取得フレーム数={len(diffs)} 完了={completed} 理由={reason}"}
                await browser.close()
                return

            yield {"step": "calculate", "progress": 90, "message": "結果を計算中..."}

            stats = calc_stats(diffs)
            scores = calc_5_scores(stats)
            advice = make_advice(stats, scores)
            judgment = make_judgment(scores['total'])

            await browser.close()

            yield {
                "step": "done",
                "progress": 100,
                "result": {
                    "title": title,
                    "video_id": video_id,
                    "scores": scores,
                    "judgment": judgment,
                    "advice": advice,
                    "frames_analyzed": len(diffs)
                }
            }
        except asyncio.TimeoutError:
            yield {"step": "error", "message": "分析に時間がかかりすぎました。動画が長すぎるか、再生に問題がある可能性があります。"}
            try:
                await browser.close()
            except:
                pass
        except Exception as e:
            yield {"step": "error", "message": f"エラーが発生しました: {str(e)[:200]}"}
            try:
                await browser.close()
            except:
                pass
