"""
動画分析ロジック（YouTubeストーリーボード方式）

Playwright不要・httpxとPillowのみで動作。
動画を再生せず、YouTube公式のストーリーボード画像から
動画各時点のフレームを取得してピクセル差を計算する。
"""
import asyncio
import re
import json
import httpx
from io import BytesIO
from PIL import Image


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ja-JP,ja;q=0.9',
}


def extract_video_id(url: str):
    m = re.search(r'(?:v=|youtu\.be/|/embed/|/v/|/shorts/)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None


def is_channel_url(url: str) -> bool:
    if not url:
        return False
    return any(p in url for p in ['/channel/', '/@', '/c/', '/user/'])


async def get_latest_video_id(channel_url: str):
    """チャンネルURLから最新動画IDを取得"""
    url = channel_url.rstrip('/')
    if not url.endswith('/videos'):
        url = url + '/videos'

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url, headers=HEADERS)
        html = r.text

    matches = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
    return matches[0] if matches else None


COOKIES = {"CONSENT": "YES+cb", "PREF": "hl=ja&gl=JP"}


def extract_player_response(html: str):
    """HTML中の ytInitialPlayerResponse を波括弧マッチングで抽出する。

    非貪欲regex `\\{.+?\\}` は JSON 内部の `};` 等で誤マッチするため、
    `{` の出現位置から手動で深さを追い、文字列リテラルとエスケープを
    考慮して対応する `}` まで切り出す。
    """
    markers = [
        'var ytInitialPlayerResponse = ',
        'ytInitialPlayerResponse = ',
        '"ytInitialPlayerResponse":',
    ]
    for marker in markers:
        pos = 0
        while True:
            idx = html.find(marker, pos)
            if idx == -1:
                break
            start = idx + len(marker)
            while start < len(html) and html[start] != '{':
                start += 1
            if start >= len(html):
                break
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(html)):
                c = html[i]
                if esc:
                    esc = False
                    continue
                if in_str:
                    if c == '\\':
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(html[start:i + 1])
                        except json.JSONDecodeError:
                            pos = idx + 1
                            break
            else:
                break
    return None


async def fetch_player_response(video_id: str):
    """YouTube動画ページから ytInitialPlayerResponse を取得。

    通常のwatchページでstoryboardが取れない場合（地域・consent等で
    省略されるケース）はembedページにフォールバックする。
    """
    headers = {**HEADERS, "Cookie": "; ".join(f"{k}={v}" for k, v in COOKIES.items())}
    urls = [
        f"https://www.youtube.com/watch?v={video_id}&hl=ja&gl=JP",
        f"https://www.youtube.com/embed/{video_id}?hl=ja",
    ]
    last = None
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url, headers=headers)
            except Exception:
                continue
            if r.status_code != 200:
                continue
            response = extract_player_response(r.text)
            if not response:
                continue
            last = response
            sb = response.get('storyboards', {}).get('playerStoryboardSpecRenderer', {})
            if sb.get('spec'):
                return response
    return last


def parse_storyboard_spec(spec: str):
    """spec文字列を解析"""
    parts = spec.split('|')
    base_url = parts[0]
    levels = []
    for i, level_data in enumerate(parts[1:]):
        fields = level_data.split('#')
        if len(fields) < 8:
            continue
        try:
            level = {
                'level': i,
                'width': int(fields[0]),
                'height': int(fields[1]),
                'count': int(fields[2]),
                'cols': int(fields[3]),
                'rows': int(fields[4]),
                'interval_ms': int(fields[5]),
                'name': fields[6],
                'sigh': fields[7],
            }
            level['frames_per_image'] = level['cols'] * level['rows']
            level['total_images'] = (level['count'] + level['frames_per_image'] - 1) // level['frames_per_image']
            levels.append(level)
        except (ValueError, IndexError):
            continue
    return base_url, levels


def build_image_urls(base_url: str, level: dict):
    urls = []
    for m in range(level['total_images']):
        url = base_url.replace('$L', str(level['level'])).replace('$N', level['name']).replace('$M', str(m))
        url += '&sigh=' + level['sigh']
        urls.append(url)
    return urls


async def download_image(client: httpx.AsyncClient, url: str):
    try:
        r = await client.get(url, timeout=30)
        if r.status_code != 200:
            return None
        return Image.open(BytesIO(r.content))
    except Exception:
        return None


def extract_frames_from_montage(img: Image.Image, level: dict):
    frames = []
    fw = level['width']
    fh = level['height']
    for row in range(level['rows']):
        for col in range(level['cols']):
            left = col * fw
            top = row * fh
            try:
                frame = img.crop((left, top, left + fw, top + fh))
                frames.append(frame)
            except Exception:
                pass
    return frames


def calc_pixel_diff(frame_a: Image.Image, frame_b: Image.Image, target_w=80, target_h=45):
    """既存ロジック互換のピクセル差計算"""
    a = frame_a.resize((target_w, target_h)).convert('RGB')
    b = frame_b.resize((target_w, target_h)).convert('RGB')
    a_pix = a.tobytes()
    b_pix = b.tobytes()
    total = sum(abs(a_pix[i] - b_pix[i]) for i in range(len(a_pix)))
    return total / (target_w * target_h * 3)


def calc_stats(diffs):
    if not diffs or len(diffs) < 5:
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
    # 使用バンド数の閾値はフレーム数に応じて調整（5以上が原則だが少サンプルでは1以上）
    band_threshold = max(1, n // 20)
    return {
        'n': n,
        'mean': sum(diffs) / n,
        'sharpCut': sum(1 for d in diffs if d >= 60) / n * 100,
        'lowChange': sum(1 for d in diffs if d < 20) / n * 100,
        'midRange': sum(1 for d in diffs if 20 <= d < 60) / n * 100,
        'eventRate': sum(1 for d in diffs if d >= 20) / n * 100,
        'maxBand': max(bands) / n * 100,
        'usedBands': sum(1 for b in bands if b >= band_threshold),
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
        return {"level": "good", "icon": "🟢", "label": "合格水準",
                "message": "動画の中身は十分な品質です。"}
    elif total >= 70:
        return {"level": "near", "icon": "🟡", "label": "ほぼ合格",
                "message": "あと少しで合格水準です。軽い直しで問題ありません。"}
    elif total >= 55:
        return {"level": "border", "icon": "🟡", "label": "もうすぐ合格",
                "message": "あと少しの直しで、合格の見込みが大きく上がります。"}
    elif total >= 40:
        return {"level": "warn", "icon": "🟠", "label": "要改善",
                "message": "いくつかの点を直す必要があります。"}
    else:
        return {"level": "ng", "icon": "🔴", "label": "大幅な作り直しが必要",
                "message": "現状では合格水準に届きません。"}


async def analyze_video(channel_url: str, video_url: str):
    """メイン分析関数（非同期ジェネレータ）"""
    yield {"step": "init", "progress": 5, "message": "処理を開始しています..."}

    has_video = bool(video_url and video_url.strip())
    has_channel = bool(channel_url and channel_url.strip())

    if not has_video and not has_channel:
        yield {"step": "error", "message": "動画URLまたはチャンネルURLのどちらかを入力してください。"}
        return

    video_id = None
    if has_video:
        video_id = extract_video_id(video_url)
        if not video_id:
            yield {"step": "error", "message": "動画URLが正しくありません。再度ご確認ください。"}
            return

    if not video_id:
        if not is_channel_url(channel_url):
            yield {"step": "error", "message": "チャンネルURLが正しくありません。"}
            return
        yield {"step": "find_latest", "progress": 15, "message": "チャンネルから最新動画を取得中..."}
        video_id = await get_latest_video_id(channel_url)
        if not video_id:
            yield {"step": "error", "message": "チャンネルから動画が見つかりませんでした。"}
            return

    yield {"step": "fetch_meta", "progress": 25, "message": "動画情報を取得中..."}

    try:
        player_response = await fetch_player_response(video_id)
    except Exception as e:
        yield {"step": "error", "message": f"動画情報の取得に失敗しました: {str(e)[:100]}"}
        return

    if not player_response:
        yield {"step": "error", "message": "動画情報を解析できませんでした。"}
        return

    title = player_response.get('videoDetails', {}).get('title', '（タイトル不明）')[:80]

    storyboards = player_response.get('storyboards', {})
    spec_renderer = storyboards.get('playerStoryboardSpecRenderer', {})
    spec = spec_renderer.get('spec')

    if not spec:
        yield {"step": "error", "message": "この動画はストーリーボードに対応していません。"}
        return

    yield {"step": "parse_spec", "progress": 35, "message": "フレーム情報を解析中..."}

    base_url, levels = parse_storyboard_spec(spec)
    if not levels:
        yield {"step": "error", "message": "フレーム情報の解析に失敗しました。"}
        return

    # 最高品質レベルを使用
    level = levels[-1]

    # 180秒分のフレーム数を計算
    interval_sec = max(level['interval_ms'] / 1000, 1)
    frames_for_180s = min(int(180 / interval_sec) + 1, level['count'])
    images_needed = (frames_for_180s + level['frames_per_image'] - 1) // level['frames_per_image']

    urls = build_image_urls(base_url, level)[:images_needed]

    yield {"step": "download", "progress": 50, "message": f"フレーム画像を取得中...（{len(urls)}枚）"}

    all_frames = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        # 並列ダウンロード
        results = await asyncio.gather(*[download_image(client, u) for u in urls])
        for img in results:
            if img is None:
                continue
            all_frames.extend(extract_frames_from_montage(img, level))

    all_frames = all_frames[:frames_for_180s]

    if len(all_frames) < 10:
        yield {"step": "error", "message": f"十分なフレームが取得できませんでした（{len(all_frames)}フレーム）"}
        return

    yield {"step": "calculate", "progress": 80, "message": "ピクセル差を計算中..."}

    diffs = []
    prev = None
    for f in all_frames:
        if prev is not None:
            diffs.append(calc_pixel_diff(prev, f))
        prev = f

    stats = calc_stats(diffs)
    if not stats:
        yield {"step": "error", "message": "統計計算に失敗しました。"}
        return

    yield {"step": "score", "progress": 95, "message": "スコアを計算中..."}

    scores = calc_5_scores(stats)
    advice = make_advice(stats, scores)
    judgment = make_judgment(scores['total'])

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
