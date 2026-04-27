/**
 * バックグラウンドサービスワーカー。
 * - ツールページからの分析依頼を受け取る
 * - YouTube動画ページを新タブで開く
 * - そこに analyzer スクリプトを scripting.executeScript で注入
 * - 結果を tabs.sendMessage 経由でツールページに返す
 */

const TARGET_PAGE_PATTERNS = [
  /^https:\/\/shinji-design\.github\.io\/yt-quality-checker\//,
  /^http:\/\/localhost(:\d+)?\//,
  /^http:\/\/127\.0\.0\.1(:\d+)?\//,
];

function extractVideoId(url) {
  if (!url) return null;
  const m = String(url).match(/(?:v=|youtu\.be\/|\/embed\/|\/v\/|\/shorts\/)([a-zA-Z0-9_-]{11})/);
  return m ? m[1] : null;
}

function isChannelUrl(url) {
  if (!url) return false;
  return /\/channel\/|\/@|\/c\/|\/user\//.test(url);
}

async function findRequesterTab(senderTabId) {
  if (senderTabId) {
    try {
      const t = await chrome.tabs.get(senderTabId);
      if (t) return t;
    } catch (e) {}
  }
  const tabs = await chrome.tabs.query({});
  return tabs.find(t => t.url && TARGET_PAGE_PATTERNS.some(p => p.test(t.url))) || null;
}

async function sendToRequester(tabId, type, requestId, payload) {
  try {
    await chrome.tabs.sendMessage(tabId, { type, requestId, payload });
  } catch (e) {
    // 無視
  }
}

async function getLatestVideoIdFromChannel(channelUrl) {
  // チャンネルの /videos ページを fetch して最新動画IDを取得
  const url = channelUrl.replace(/\/+$/, '') + (channelUrl.endsWith('/videos') ? '' : '/videos');
  try {
    const res = await fetch(url, { credentials: 'omit' });
    const html = await res.text();
    const matches = html.match(/"videoId":"([a-zA-Z0-9_-]{11})"/g) || [];
    if (matches.length === 0) return null;
    const m = matches[0].match(/([a-zA-Z0-9_-]{11})/);
    return m ? m[1] : null;
  } catch (e) {
    return null;
  }
}

async function runAnalysis(payload, requesterTabId, requestId) {
  const { channelUrl, videoUrl } = payload || {};

  // 1) 入力解決：videoUrl 優先、なければ channelUrl から最新を取得
  let videoId = extractVideoId(videoUrl);
  if (!videoId) {
    if (!isChannelUrl(channelUrl)) {
      await sendToRequester(requesterTabId, 'ERROR', requestId, { message: 'チャンネルURLか動画URLのどちらかを入力してください。' });
      return;
    }
    await sendToRequester(requesterTabId, 'PROGRESS', requestId, { progress: 5, message: 'チャンネルから最新動画を取得中...' });
    videoId = await getLatestVideoIdFromChannel(channelUrl);
    if (!videoId) {
      await sendToRequester(requesterTabId, 'ERROR', requestId, { message: 'チャンネルから動画が見つかりませんでした。URLをご確認ください。' });
      return;
    }
  }

  // 2) YouTube動画ページを新タブで開く（最前面にして再生を許可させる）
  await sendToRequester(requesterTabId, 'PROGRESS', requestId, { progress: 10, message: '動画ページを開いています...' });
  let analyzerTab;
  try {
    analyzerTab = await chrome.tabs.create({
      url: `https://www.youtube.com/watch?v=${videoId}`,
      active: true,
    });
  } catch (e) {
    await sendToRequester(requesterTabId, 'ERROR', requestId, { message: 'YouTube動画ページを開けませんでした: ' + e.message });
    return;
  }

  // 3) ロード完了を待つ
  await sendToRequester(requesterTabId, 'PROGRESS', requestId, { progress: 15, message: '動画の読み込みを待機中...' });
  await new Promise(r => setTimeout(r, 6000));

  // 4) analyzer を scripting.executeScript で注入
  await sendToRequester(requesterTabId, 'PROGRESS', requestId, { progress: 25, message: '動画の分析を開始します（約45秒）...' });

  let injectionResult;
  try {
    injectionResult = await chrome.scripting.executeScript({
      target: { tabId: analyzerTab.id },
      world: 'MAIN',
      func: analyzeInPage,
    });
  } catch (e) {
    try { await chrome.tabs.remove(analyzerTab.id); } catch (_) {}
    await sendToRequester(requesterTabId, 'ERROR', requestId, { message: '動画ページへの注入に失敗しました: ' + e.message });
    return;
  }

  const result = injectionResult && injectionResult[0] && injectionResult[0].result;

  // 5) 進捗ポーリング
  let lastProgress = 25;
  const startTime = Date.now();
  let analysisData = null;
  while (Date.now() - startTime < 240000) { // 最大4分
    await new Promise(r => setTimeout(r, 1500));
    let pollRes;
    try {
      pollRes = await chrome.scripting.executeScript({
        target: { tabId: analyzerTab.id },
        world: 'MAIN',
        func: () => window.__YTQC_STATE__ || null,
      });
    } catch (e) { break; }
    const state = pollRes && pollRes[0] && pollRes[0].result;
    if (!state) continue;

    if (state.error) {
      try { await chrome.tabs.remove(analyzerTab.id); } catch (_) {}
      await sendToRequester(requesterTabId, 'ERROR', requestId, { message: state.error });
      return;
    }

    const pct = Math.min(95, 25 + Math.floor((state.done || 0) / 181 * 70));
    if (pct > lastProgress) {
      lastProgress = pct;
      await sendToRequester(requesterTabId, 'PROGRESS', requestId, { progress: pct, message: `分析中... ${state.done || 0}/181フレーム` });
    }

    if (state.finished) {
      analysisData = state;
      break;
    }
  }

  // 6) タブを閉じる
  try { await chrome.tabs.remove(analyzerTab.id); } catch (_) {}

  // 7) 元タブを最前面に戻す
  try { await chrome.tabs.update(requesterTabId, { active: true }); } catch (_) {}

  if (!analysisData || !analysisData.diffs) {
    await sendToRequester(requesterTabId, 'ERROR', requestId, { message: '分析がタイムアウトしました。' });
    return;
  }

  // 8) 結果送信
  await sendToRequester(requesterTabId, 'RESULT', requestId, {
    title: analysisData.title || '',
    videoId,
    diffs: analysisData.diffs,
    capturedAt: Date.now(),
  });
}

// ページコンテキストで実行される分析関数
function analyzeInPage() {
  if (window.__YTQC_RUNNING__) return { already: true };
  window.__YTQC_RUNNING__ = true;
  window.__YTQC_STATE__ = { done: 0, finished: false, diffs: [], error: null };

  (async function () {
    try {
      const v = document.querySelector('video');
      const player = document.querySelector('#movie_player');
      if (!v) { window.__YTQC_STATE__.error = '動画要素が見つかりません'; window.__YTQC_STATE__.finished = true; return; }

      const setRate = (r) => { try { player && player.setPlaybackRate && player.setPlaybackRate(r); } catch (e) {} try { v.playbackRate = r; } catch (e) {} };
      const play = () => { try { player && player.playVideo ? player.playVideo() : v.play(); } catch (e) {} };
      const pause = () => { try { player && player.pauseVideo ? player.pauseVideo() : v.pause(); } catch (e) {} };
      const seek = (t) => { try { player && player.seekTo ? player.seekTo(t, true) : (v.currentTime = t); } catch (e) { v.currentTime = t; } };

      v.muted = true;
      seek(0);
      setRate(4);
      play();

      // 動画がロードされるのを待つ
      let waited = 0;
      while ((!v.duration || v.readyState < 3) && waited < 15000) {
        await new Promise(r => setTimeout(r, 500));
        waited += 500;
      }
      if (!v.duration) { window.__YTQC_STATE__.error = '動画が読み込まれませんでした'; window.__YTQC_STATE__.finished = true; return; }

      // タイトル取得
      const titleEl = document.querySelector('h1.style-scope.ytd-watch-metadata, h1.ytd-watch-metadata, h1.title');
      window.__YTQC_STATE__.title = titleEl ? titleEl.innerText.trim() : (document.title.replace(/ - YouTube$/, ''));

      const targets = [];
      for (let t = 0; t <= 180; t++) targets.push(t);
      let idx = 0;
      let prev = null;
      let lastDoneTime = Date.now();

      const interval = setInterval(() => {
        try {
          if (idx >= targets.length || v.currentTime > 185) {
            clearInterval(interval);
            pause();
            setRate(1);
            window.__YTQC_STATE__.finished = true;
            return;
          }
          // 停滞検出
          if (Date.now() - lastDoneTime > 20000) {
            clearInterval(interval);
            pause(); setRate(1);
            if (window.__YTQC_STATE__.diffs.length < 5) {
              window.__YTQC_STATE__.error = '動画再生が進みませんでした。';
            }
            window.__YTQC_STATE__.finished = true;
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
                  s += Math.abs(px[i] - prev[i]) + Math.abs(px[i + 1] - prev[i + 1]) + Math.abs(px[i + 2] - prev[i + 2]);
                }
                window.__YTQC_STATE__.diffs.push(Math.round((s / (px.length / 4 * 3)) * 100) / 100);
              }
              prev = px;
            } catch (e) {}
            idx++;
            window.__YTQC_STATE__.done = idx;
            lastDoneTime = Date.now();
          }
        } catch (e) {
          clearInterval(interval);
          window.__YTQC_STATE__.error = 'ループエラー: ' + e.message;
          window.__YTQC_STATE__.finished = true;
        }
      }, 300);
    } catch (e) {
      window.__YTQC_STATE__.error = '初期化エラー: ' + e.message;
      window.__YTQC_STATE__.finished = true;
    }
  })();

  return { started: true };
}

// メッセージリスナー
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== 'ANALYZE_REQUEST') return;
  const requestId = msg.requestId;
  const requesterTabId = sender.tab && sender.tab.id;
  // 非同期で実行
  runAnalysis(msg.payload, requesterTabId, requestId);
  sendResponse({ accepted: true });
  return false;
});
