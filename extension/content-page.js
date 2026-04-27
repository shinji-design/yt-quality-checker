/**
 * GitHub Pages（ツールサイト）に注入されるブリッジ。
 * window.postMessage 経由でページJSと通信し、
 * chrome.runtime.sendMessage で background へ中継する。
 */
(function () {
  const EXT_TAG = 'YT_QC_EXT';
  const VERSION = '1.0.0';

  // ページJSへの存在通知
  function announce() {
    window.postMessage({ source: EXT_TAG, type: 'EXT_READY', version: VERSION }, '*');
  }

  // ページJSからのメッセージ受信
  window.addEventListener('message', (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.target !== EXT_TAG) return;

    if (data.type === 'PING') {
      window.postMessage({ source: EXT_TAG, type: 'PONG', version: VERSION, requestId: data.requestId }, '*');
      return;
    }

    if (data.type === 'ANALYZE') {
      const requestId = data.requestId;
      chrome.runtime.sendMessage(
        { type: 'ANALYZE_REQUEST', payload: data.payload, requestId },
        (response) => {
          // 同期的応答（あれば）
          if (response) {
            window.postMessage({ source: EXT_TAG, type: 'ACK', requestId, response }, '*');
          }
        }
      );
    }
  });

  // background から進捗・結果を受信してページJSへ転送
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || !msg.type) return;
    if (msg.type === 'PROGRESS' || msg.type === 'RESULT' || msg.type === 'ERROR') {
      window.postMessage({ source: EXT_TAG, type: msg.type, requestId: msg.requestId, payload: msg.payload }, '*');
    }
    sendResponse({ ok: true });
    return false;
  });

  // ページロード後に存在を通知
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', announce);
  } else {
    announce();
  }
})();
