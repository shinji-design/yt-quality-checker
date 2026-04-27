"""
ストーリーボード方式の技術検証スクリプト
"""
import asyncio
import re
import json
import httpx
from io import BytesIO
from PIL import Image


async def fetch_storyboard_spec(video_id: str):
    """YouTube動画ページからストーリーボード仕様を取得"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ja-JP,ja;q=0.9',
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        html = r.text

    # ytInitialPlayerResponse を抽出
    m = re.search(r'var ytInitialPlayerResponse\s*=\s*(\{.+?\});', html)
    if not m:
        m = re.search(r'ytInitialPlayerResponse\s*=\s*(\{.+?\});\s*var', html)
    if not m:
        return None

    try:
        player_response = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"JSONパース失敗: {e}")
        return None

    # storyboard情報を取得
    storyboards = player_response.get('storyboards', {})
    spec_renderer = storyboards.get('playerStoryboardSpecRenderer', {})
    spec = spec_renderer.get('spec')

    if not spec:
        return None

    # 動画タイトル
    title = player_response.get('videoDetails', {}).get('title', '')
    length = player_response.get('videoDetails', {}).get('lengthSeconds', '0')

    return {
        'spec': spec,
        'title': title,
        'length': int(length),
    }


def parse_storyboard_spec(spec: str, video_id: str):
    """spec文字列を解析してダウンロードURLリストを生成

    spec形式: "URL_TEMPLATE|L0_DATA|L1_DATA|L2_DATA|L3_DATA"
    各レベル: "WIDTH#HEIGHT#COUNT#COLS#ROWS#INTERVAL_MS#NAME#SIGH"
    """
    parts = spec.split('|')
    base_url = parts[0]  # https://i.ytimg.com/sb/$N/storyboard3_$L/$M.jpg?... のテンプレート

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
                'count': int(fields[2]),  # 全フレーム数
                'cols': int(fields[3]),
                'rows': int(fields[4]),
                'interval_ms': int(fields[5]),
                'name': fields[6],
                'sigh': fields[7],
            }
            level['frames_per_image'] = level['cols'] * level['rows']
            level['total_images'] = (level['count'] + level['frames_per_image'] - 1) // level['frames_per_image']
            levels.append(level)
        except (ValueError, IndexError) as e:
            print(f"レベル{i}のパースエラー: {e}")
            continue

    return base_url, levels


def build_image_urls(base_url: str, level: dict, video_id: str):
    """指定レベルの全画像URLを生成"""
    urls = []
    for m in range(level['total_images']):
        url = base_url.replace('$L', str(level['level'])).replace('$N', level['name']).replace('$M', str(m))
        url += '&sigh=' + level['sigh']
        urls.append(url)
    return urls


async def download_and_extract_frames(image_url: str, level: dict):
    """1枚のモンタージュ画像を取得して個別フレームに分割"""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(image_url)
        if r.status_code != 200:
            return []
        img = Image.open(BytesIO(r.content))

    frames = []
    fw = level['width']
    fh = level['height']
    for row in range(level['rows']):
        for col in range(level['cols']):
            left = col * fw
            top = row * fh
            frame = img.crop((left, top, left + fw, top + fh))
            frames.append(frame)
    return frames


def calc_pixel_diff(frame_a: Image.Image, frame_b: Image.Image, target_w=80, target_h=45):
    """2フレーム間のピクセル差を計算（既存ロジック互換）"""
    a = frame_a.resize((target_w, target_h)).convert('RGB')
    b = frame_b.resize((target_w, target_h)).convert('RGB')
    a_pix = a.tobytes()
    b_pix = b.tobytes()
    total = sum(abs(a_pix[i] - b_pix[i]) for i in range(len(a_pix)))
    return total / (target_w * target_h * 3)


async def main(video_id: str):
    print(f"\n=== 検証開始: {video_id} ===\n")

    # 1. spec取得
    print("[1] ストーリーボード仕様取得中...")
    info = await fetch_storyboard_spec(video_id)
    if not info:
        print("失敗: spec取得不可")
        return

    print(f"   タイトル: {info['title'][:50]}")
    print(f"   長さ: {info['length']}秒")
    print(f"   spec先頭: {info['spec'][:100]}")

    # 2. spec解析
    print("\n[2] spec解析中...")
    base_url, levels = parse_storyboard_spec(info['spec'], video_id)
    print(f"   base_url: {base_url[:80]}...")
    for lv in levels:
        print(f"   L{lv['level']}: {lv['width']}x{lv['height']}, {lv['cols']}x{lv['rows']}フレーム/画像, "
              f"全{lv['count']}フレーム, {lv['interval_ms']}ms間隔, 画像数={lv['total_images']}")

    # 3. 最高品質レベルを使用
    if not levels:
        print("失敗: レベル情報なし")
        return

    level = levels[-1]  # 最高品質
    print(f"\n[3] レベル{level['level']}使用、URLを生成...")

    # 180秒分のフレームに必要な画像数
    interval_sec = level['interval_ms'] / 1000
    frames_for_180s = min(int(180 / interval_sec) + 1, level['count'])
    images_needed = (frames_for_180s + level['frames_per_image'] - 1) // level['frames_per_image']
    print(f"   180秒で必要なフレーム: {frames_for_180s}個 ({interval_sec:.2f}秒間隔)")
    print(f"   必要な画像数: {images_needed}枚")

    urls = build_image_urls(base_url, level, video_id)[:images_needed]
    print(f"   最初のURL: {urls[0][:120]}...")

    # 4. 画像取得
    print(f"\n[4] {len(urls)}枚の画像をダウンロード中...")
    all_frames = []
    for i, url in enumerate(urls):
        frames = await download_and_extract_frames(url, level)
        all_frames.extend(frames)
        print(f"   [{i+1}/{len(urls)}] 取得: {len(frames)}フレーム")

    # 180秒分にトリム
    all_frames = all_frames[:frames_for_180s]
    print(f"\n   合計: {len(all_frames)}フレーム取得")

    # 5. ピクセル差計算
    print(f"\n[5] ピクセル差計算中...")
    diffs = []
    prev = None
    for f in all_frames:
        if prev is not None:
            diffs.append(calc_pixel_diff(prev, f))
        prev = f

    if not diffs:
        print("失敗: 差分データなし")
        return

    print(f"   diff数: {len(diffs)}")
    print(f"   mean: {sum(diffs)/len(diffs):.2f}")
    print(f"   max: {max(diffs):.2f}")
    print(f"   min: {min(diffs):.2f}")
    print(f"   先頭5件: {[round(d, 2) for d in diffs[:5]]}")

    print("\n✅ 検証成功")


if __name__ == '__main__':
    import sys
    video_id = sys.argv[1] if len(sys.argv) > 1 else 'qgS9vKS5Fh4'
    asyncio.run(main(video_id))
