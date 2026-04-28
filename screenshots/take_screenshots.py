"""
Chrome Web Store 用スクリーンショット生成スクリプト
1280x800 のサイズで各画面を撮影する
"""
import asyncio
import os
import random
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8765/?v=screenshot"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_diffs_pass():
    """合格水準スコア(85+) 相当のdiffsを生成"""
    # 目標: lowChange ~55%, eventRate ~45%, maxBand ~30%, bands 7-8
    # 各帯にサンプルを配置
    bands = []
    bands += [random.uniform(0.1, 1.9) for _ in range(15)]   # b0_2: 15
    bands += [random.uniform(2.0, 4.9) for _ in range(15)]   # b2_5: 15
    bands += [random.uniform(5.0, 9.9) for _ in range(25)]   # b5_10: 25
    bands += [random.uniform(10.0, 19.9) for _ in range(45)] # b10_20: 45
    bands += [random.uniform(20.0, 39.9) for _ in range(50)] # b20_40: 50
    bands += [random.uniform(40.0, 59.9) for _ in range(20)] # b40_60: 20
    bands += [random.uniform(60.0, 99.9) for _ in range(8)]  # b60_100: 8
    bands += [random.uniform(100.0, 150.0) for _ in range(2)] # b100plus: 2
    random.shuffle(bands)
    return bands


def generate_diffs_warn():
    """要改善スコア(50前後) 相当のdiffsを生成 - 静止過多"""
    # 目標: lowChange ~85%, eventRate ~15%, maxBand ~45%, bands 4
    bands = []
    bands += [random.uniform(0.1, 1.9) for _ in range(35)]   # b0_2: 35
    bands += [random.uniform(2.0, 4.9) for _ in range(40)]   # b2_5: 40
    bands += [random.uniform(5.0, 9.9) for _ in range(30)]   # b5_10: 30
    bands += [random.uniform(10.0, 19.9) for _ in range(48)] # b10_20: 48
    bands += [random.uniform(20.0, 39.9) for _ in range(20)] # b20_40: 20
    bands += [random.uniform(40.0, 59.9) for _ in range(5)]  # b40_60: 5
    bands += [random.uniform(60.0, 99.9) for _ in range(2)]  # b60_100: 2
    random.shuffle(bands)
    return bands


def js_show_input():
    return """
        showScreen('input');
        document.getElementById('ext-version').textContent = '1.0.0';
        document.getElementById('channel-url').value = 'https://www.youtube.com/@example-channel';
    """


def js_show_install():
    return """
        showScreen('install');
        const btn = document.getElementById('install-btn');
        if (btn) btn.href = 'https://chromewebstore.google.com/';
    """


def js_show_result(title, diffs):
    diffs_str = "[" + ",".join(f"{d:.2f}" for d in diffs) + "]"
    return f"""
        showResult({{
            title: {title!r},
            videoId: 'sample',
            diffs: {diffs_str},
            capturedAt: Date.now()
        }});
    """


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # 1280x800 viewport, deviceScaleFactor=1（Retina影響なし）
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            device_scale_factor=1,
        )
        page = await context.new_page()

        # ===== 1. 入力画面 =====
        await page.goto(BASE_URL, wait_until='networkidle')
        await page.wait_for_timeout(1500)
        await page.evaluate(js_show_input())
        await page.wait_for_timeout(300)
        path1 = os.path.join(OUTPUT_DIR, '01_input_screen.png')
        await page.screenshot(path=path1, full_page=False)
        print(f"saved: {path1}")

        # ===== 2. インストール案内 =====
        await page.evaluate(js_show_install())
        await page.wait_for_timeout(300)
        path2 = os.path.join(OUTPUT_DIR, '02_install_guide.png')
        await page.screenshot(path=path2, full_page=False)
        print(f"saved: {path2}")

        # ===== 3. 結果画面（合格水準） =====
        random.seed(42)
        await page.evaluate(js_show_result('【サンプル動画】テスト動画タイトル', generate_diffs_pass()))
        await page.wait_for_timeout(1500)
        # スクロールトップ位置で撮影
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)
        path3 = os.path.join(OUTPUT_DIR, '03_result_pass.png')
        await page.screenshot(path=path3, full_page=False)
        print(f"saved: {path3}")

        # ===== 4. 結果画面（改善アドバイス部分） =====
        # 同じ画面でスコア下部までスクロール
        await page.evaluate("""
            const advTitle = document.getElementById('advice-title');
            const target = advTitle && advTitle.style.display !== 'none' ? advTitle : document.querySelector('.score-list');
            if (target) target.scrollIntoView({block: 'start'});
        """)
        await page.wait_for_timeout(500)
        path4 = os.path.join(OUTPUT_DIR, '04_result_pass_scroll.png')
        await page.screenshot(path=path4, full_page=False)
        print(f"saved: {path4}")

        # ===== 5. 結果画面（要改善・アドバイス付き） =====
        random.seed(123)
        await page.evaluate(js_show_result('【サンプル動画】静止画多めの動画', generate_diffs_warn()))
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)
        path5 = os.path.join(OUTPUT_DIR, '05_result_warn.png')
        await page.screenshot(path=path5, full_page=False)
        print(f"saved: {path5}")

        # ===== 6. 結果画面（改善アドバイス表示部分） =====
        await page.evaluate("""
            const advTitle = document.getElementById('advice-title');
            if (advTitle && advTitle.style.display !== 'none') advTitle.scrollIntoView({block: 'start'});
        """)
        await page.wait_for_timeout(500)
        path6 = os.path.join(OUTPUT_DIR, '06_result_warn_advice.png')
        await page.screenshot(path=path6, full_page=False)
        print(f"saved: {path6}")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
