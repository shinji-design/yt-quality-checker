/**
 * 動画クオリティ・チェッカー（静的サイト版）
 *
 * - 入力画面：ブックマークレット利用案内
 * - 結果画面：URLハッシュからブックマークレットが渡したデータを読み、
 *   180秒分の差分→5スコア→判定→アドバイスを描画する
 *
 * バックエンド不要。ユーザーのブラウザでYouTube動画を直接シークするため
 * データセンターIPのbot検出問題は発生しない。
 */

// ============================================================
// スコアリング（analyzer.py からの移植）
// ============================================================

function calcStats(diffs) {
  if (!diffs || diffs.length < 5) return null;
  const n = diffs.length;
  const bands = [
    diffs.filter(d => d < 2).length,
    diffs.filter(d => d >= 2 && d < 5).length,
    diffs.filter(d => d >= 5 && d < 10).length,
    diffs.filter(d => d >= 10 && d < 20).length,
    diffs.filter(d => d >= 20 && d < 40).length,
    diffs.filter(d => d >= 40 && d < 60).length,
    diffs.filter(d => d >= 60 && d < 100).length,
    diffs.filter(d => d >= 100).length,
  ];
  const bandThreshold = Math.max(1, Math.floor(n / 20));
  const sum = diffs.reduce((a, b) => a + b, 0);
  return {
    n,
    mean: sum / n,
    sharpCut: diffs.filter(d => d >= 60).length / n * 100,
    lowChange: diffs.filter(d => d < 20).length / n * 100,
    midRange: diffs.filter(d => d >= 20 && d < 60).length / n * 100,
    eventRate: diffs.filter(d => d >= 20).length / n * 100,
    maxBand: Math.max.apply(null, bands) / n * 100,
    usedBands: bands.filter(b => b >= bandThreshold).length,
  };
}

function calc5Scores(stats) {
  const mean = stats.mean;
  let balance;
  if (mean >= 18 && mean <= 25) balance = 90 + (1 - Math.abs(mean - 21.5) / 3.5) * 10;
  else if ((mean >= 14 && mean < 18) || (mean > 25 && mean <= 30)) balance = 70 + (1 - Math.abs(mean - 21.5) / 8.5) * 20;
  else if ((mean >= 10 && mean < 14) || (mean > 30 && mean <= 35)) balance = 50;
  else balance = Math.max(20, 50 - Math.abs(mean - 21.5) * 2);

  const lc = stats.lowChange;
  let still;
  if (lc >= 50 && lc <= 75) still = 90;
  else if (lc < 50) still = Math.max(30, 90 - (50 - lc) * 1.5);
  else if (lc <= 85) still = Math.max(50, 90 - (lc - 75) * 4);
  else still = Math.max(0, 50 - (lc - 85) * 5);

  const er = stats.eventRate;
  let scene;
  if (er >= 25 && er <= 50) scene = 90;
  else if (er < 25) scene = Math.max(40, 90 - (25 - er) * 2);
  else if (er <= 70) scene = Math.max(60, 90 - (er - 50) * 1.5);
  else scene = Math.max(0, 60 - (er - 70) * 4);

  const ub = stats.usedBands;
  const varietyMap = { 8: 95, 7: 95, 6: 80, 5: 55, 4: 30, 3: 15 };
  const variety = varietyMap[ub] !== undefined ? varietyMap[ub] : 10;

  const mb = stats.maxBand;
  let concentrate;
  if (mb < 30) concentrate = 95;
  else if (mb < 40) concentrate = 85;
  else if (mb < 45) concentrate = 70;
  else if (mb <= 50) concentrate = 55;
  else concentrate = Math.max(0, 55 - (mb - 50) * 5);

  const clamp = v => Math.max(0, Math.min(100, v));
  const b = clamp(balance), s = clamp(still), sc = clamp(scene), v = clamp(variety), c = clamp(concentrate);
  const total = (b + s + sc + v + c) / 5;

  return {
    balance: Math.round(b),
    still: Math.round(s),
    scene: Math.round(sc),
    variety: Math.round(v),
    concentrate: Math.round(c),
    total: Math.round(total),
  };
}

function makeAdvice(stats, scores) {
  const advice = [];
  if (scores.variety < 60) {
    advice.push({
      priority: 1, title: '動きの種類を増やしましょう',
      current: `今：${stats.usedBands}種類`, target: '目標：6種類以上',
      how: ['「3秒くらい完全に止まる場面」を1〜2回入れる', '章の変わり目に「フェードイン・フェードアウト」を入れる', 'テロップだけ動かす場面を作る（画面はそのまま）'],
    });
  }
  if (scores.still < 60) {
    const lc = stats.lowChange;
    if (lc > 75) {
      advice.push({
        priority: 2, title: '「ほとんど動かない時間」を減らしましょう',
        current: `今：3分のうち約${Math.round(lc * 1.8)}秒が止まったまま`, target: '目標：3分のうち90〜135秒以内',
        how: ['同じ絵がずっと続く場面を10秒短くする', '代わりに「ゆっくりズーム」や「別の絵への切替」を入れる', '1つの場面を15秒以上見せない'],
      });
    } else if (lc < 50) {
      advice.push({
        priority: 2, title: '「動きすぎ」を少し落ち着かせましょう',
        current: `今：3分のうち止まる時間が約${Math.round(lc * 1.8)}秒`, target: '目標：3分のうち90〜135秒',
        how: ['同じ絵をゆっくり見せる時間を増やす', '場面切替の頻度を下げる', '完全に静止する「間（ま）」を入れる'],
      });
    }
  }
  if (scores.concentrate < 60) {
    advice.push({
      priority: 3, title: '「同じ動き」が長く続いている場面を分散させましょう',
      current: `今：1種類の動きが3分のうち約${Math.round(stats.maxBand * 1.8)}秒を占めています`, target: '目標：1種類の動きは3分のうち80秒以内',
      how: ['ゆっくりズームを使いすぎないようにする', '別のキャラ・別の背景への切替を増やす', 'テロップ動作と組み合わせる'],
    });
  }
  if (scores.scene < 60) {
    const er = stats.eventRate;
    if (er > 50) {
      advice.push({
        priority: 4, title: '場面切替の回数を少し減らしましょう',
        current: `今：3分で約${Math.round(er * 1.8)}回の場面切替`, target: '目標：3分で45〜90回程度',
        how: ['急な場面転換を「ゆっくりズーム」に置き換える', '1つの場面を長めに見せる時間を増やす'],
      });
    } else if (er < 25) {
      advice.push({
        priority: 4, title: '場面切替の回数を増やしましょう',
        current: `今：3分で約${Math.round(er * 1.8)}回しか場面が変わらない`, target: '目標：3分で45〜90回程度',
        how: ['12秒以上同じ絵を見せない', '別の絵・別の角度を増やす'],
      });
    }
  }
  return advice.slice(0, 3);
}

function makeJudgment(total) {
  if (total >= 85) return { level: 'good', icon: '🟢', label: '合格水準', message: '動画の中身は十分な品質です。' };
  if (total >= 70) return { level: 'near', icon: '🟡', label: 'ほぼ合格', message: 'あと少しで合格水準です。軽い直しで問題ありません。' };
  if (total >= 55) return { level: 'border', icon: '🟡', label: 'もうすぐ合格', message: 'あと少しの直しで、合格の見込みが大きく上がります。' };
  if (total >= 40) return { level: 'warn', icon: '🟠', label: '要改善', message: 'いくつかの点を直す必要があります。' };
  return { level: 'ng', icon: '🔴', label: '大幅な作り直しが必要', message: '現状では合格水準に届きません。' };
}

// ============================================================
// UI 描画
// ============================================================

const SCORE_ITEMS = {
  balance: {
    label: '① 動きのバランス', icon: '🎬',
    desc: {
      good: '動画全体の動きの活発さがちょうど良いバランスです。',
      near: '動きのバランスは概ね良好です。',
      border: '動きのバランスがやや偏っています。',
      warn: '動きの量が多すぎる、または少なすぎます。',
      ng: '動きのバランスが大きく崩れています。',
    }
  },
  still: {
    label: '② 止まっている時間', icon: '📌',
    desc: {
      good: '画面が止まっている時間と動いている時間のバランスが良いです。',
      near: '止まっている時間の長さは概ね適切です。',
      border: '止まっている時間がやや多めです。',
      warn: '止まっている時間が長すぎる、または短すぎます。',
      ng: '画面がほとんど動かない、または動きすぎています。',
    }
  },
  scene: {
    label: '③ 場面切替の回数', icon: '🔄',
    desc: {
      good: '場面が変わるペースがちょうど良いです。',
      near: '場面切替のペースは適切です。',
      border: '場面切替の回数がやや多い／少なめです。',
      warn: '場面切替が多すぎる、または少なすぎます。',
      ng: '場面切替のリズムに問題があります。',
    }
  },
  variety: {
    label: '④ 動きの種類の多さ', icon: '🎨',
    desc: {
      good: '色々な種類の動きが使われていて、見飽きません。',
      near: '動きの種類は十分にあります。',
      border: '動きの種類がやや少なめです。',
      warn: '動きの種類が足りていません。',
      ng: 'いつも同じような動かし方になっています。',
    }
  },
  concentrate: {
    label: '⑤ 同じ動きの集中度', icon: '📊',
    desc: {
      good: '偏りがなく、バランスよく動きが分散されています。',
      near: '動きの分散は良好です。',
      border: '1種類の動きにやや偏っています。',
      warn: '同じ動きが長く続く部分があります。',
      ng: '1つのパターンに大きく偏っています。',
    }
  }
};

function getLevel(score) {
  if (score >= 85) return 'good';
  if (score >= 70) return 'near';
  if (score >= 55) return 'border';
  if (score >= 40) return 'warn';
  return 'ng';
}

function getIcon(level) {
  return { good: '🟢', near: '🟢', border: '🟡', warn: '🟠', ng: '🔴' }[level];
}

function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const el = document.getElementById(name + '-screen');
  if (el) el.classList.add('active');
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showResult(data) {
  const stats = calcStats(data.diffs);
  if (!stats) {
    showError('十分なフレームが取得できませんでした。動画が3分以上あることを確認してください。');
    return;
  }
  const scores = calc5Scores(stats);
  const advice = makeAdvice(stats, scores);
  const judgment = makeJudgment(scores.total);

  showScreen('result');

  const titleStr = data.title ? `分析した動画：${data.title}` : '';
  document.getElementById('video-title').textContent = titleStr;

  const judgmentBox = document.getElementById('judgment-box');
  judgmentBox.className = `judgment-box ${judgment.level}`;
  document.getElementById('judgment-icon').textContent = judgment.icon;
  document.getElementById('judgment-label').textContent = judgment.label;
  document.getElementById('total-score').textContent = scores.total;
  document.getElementById('judgment-message').textContent = judgment.message;

  setTimeout(() => {
    const fill = document.getElementById('total-bar-fill');
    fill.style.width = scores.total + '%';
    fill.style.background = {
      good: '#27ae60', near: '#16a085', border: '#f1c40f',
      warn: '#e67e22', ng: '#e74c3c'
    }[judgment.level];
  }, 100);

  const scoreList = document.getElementById('score-list');
  scoreList.innerHTML = '';
  ['balance', 'still', 'scene', 'variety', 'concentrate'].forEach(key => {
    const score = scores[key];
    const level = getLevel(score);
    const item = SCORE_ITEMS[key];
    const card = document.createElement('div');
    card.className = `score-card ${level}`;
    card.innerHTML = `
      <div class="score-card-header">
        <div><span class="score-card-icon">${item.icon}</span><span class="score-card-title">${item.label}</span></div>
        <div><span class="score-card-icon">${getIcon(level)}</span><span class="score-card-score ${level}">${score}点</span></div>
      </div>
      <p class="score-card-desc">${item.desc[level]}</p>
      <div class="score-bar"><div class="score-bar-fill ${level}" style="width: 0%;"></div></div>
    `;
    scoreList.appendChild(card);
    setTimeout(() => { card.querySelector('.score-bar-fill').style.width = score + '%'; }, 200);
  });

  const adviceList = document.getElementById('advice-list');
  const adviceTitle = document.getElementById('advice-title');
  adviceList.innerHTML = '';
  if (advice && advice.length > 0) {
    adviceTitle.style.display = 'block';
    const medals = ['🥇', '🥈', '🥉'];
    advice.forEach((adv, i) => {
      const card = document.createElement('div');
      card.className = 'advice-card';
      card.innerHTML = `
        <div class="advice-priority">${medals[i] || '・'} 優先度 ${adv.priority}</div>
        <h4 class="advice-title">${escapeHtml(adv.title)}</h4>
        <p class="advice-current">${escapeHtml(adv.current)}</p>
        <p class="advice-target">${escapeHtml(adv.target)}</p>
        <div class="advice-how">
          <p class="advice-how-label">やり方の例：</p>
          <ul>${adv.how.map(h => `<li>${escapeHtml(h)}</li>`).join('')}</ul>
        </div>
      `;
      adviceList.appendChild(card);
    });
  } else {
    adviceTitle.style.display = 'none';
  }

  const rawStats = document.getElementById('raw-stats');
  rawStats.innerHTML = `
    <div>サンプル数(n)：${stats.n}フレーム</div>
    <div>平均ピクセル差(mean)：${stats.mean.toFixed(2)}</div>
    <div>シャープカット率(≥60)：${stats.sharpCut.toFixed(1)}%</div>
    <div>低変化率(&lt;20)：${stats.lowChange.toFixed(1)}%</div>
    <div>中変化率(20-60)：${stats.midRange.toFixed(1)}%</div>
    <div>イベント率(≥20)：${stats.eventRate.toFixed(1)}%</div>
    <div>最大バンド占有率：${stats.maxBand.toFixed(1)}%</div>
    <div>使用バンド数：${stats.usedBands}/8</div>
    ${data.videoId ? `<div><a href="https://www.youtube.com/watch?v=${data.videoId}" target="_blank" rel="noopener">対象動画をYouTubeで開く</a></div>` : ''}
    ${data.capturedAt ? `<div>解析日時：${new Date(data.capturedAt).toLocaleString('ja-JP')}</div>` : ''}
  `;
}

function showError(msg) {
  showScreen('error');
  document.getElementById('error-message').textContent = msg;
}

function decodeHashData() {
  const hash = location.hash.slice(1);
  if (!hash) return null;
  try {
    return JSON.parse(decodeURIComponent(escape(atob(hash))));
  } catch (e) {
    return null;
  }
}

// ============================================================
// ブックマークレット生成
// ============================================================

function setupBookmarklet() {
  const reportUrl = new URL('', window.location.href).href;

  const bookmarkletCode = 'javascript:' + encodeURIComponent(`(function(){
  if(!location.hostname.includes('youtube.com')||!location.pathname.startsWith('/watch')){
    alert('YouTubeの動画ページで実行してください');return;
  }
  var v=document.querySelector('video');
  if(!v||!v.duration){alert('動画が読み込まれていません。少し待ってから再度クリックしてください。');return;}
  var REPORT_URL=${JSON.stringify(reportUrl)};
  var ui=document.createElement('div');
  ui.style.cssText='position:fixed;top:20px;right:20px;background:#fff;border:2px solid #3498db;border-radius:8px;padding:16px;z-index:99999;box-shadow:0 4px 20px rgba(0,0,0,0.3);font-family:sans-serif;min-width:280px;max-width:320px;';
  ui.innerHTML='<h3 style="margin:0 0 8px 0;font-size:16px;color:#2c3e50;">🎬 動画クオリティ・チェック</h3><p id="ytq_msg" style="margin:4px 0;font-size:13px;color:#555;">準備中...</p><div style="height:8px;background:#eee;border-radius:4px;overflow:hidden;margin:8px 0;"><div id="ytq_bar" style="height:100%;background:#3498db;width:0;transition:width .3s;"></div></div><div id="ytq_done" style="display:none;margin-top:12px;"><button id="ytq_view" style="display:block;width:100%;padding:10px;font-size:14px;background:#3498db;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:bold;">📊 詳細レポートを見る</button><button id="ytq_close" style="display:block;width:100%;padding:6px;margin-top:8px;font-size:12px;background:#fff;color:#888;border:1px solid #ddd;border-radius:4px;cursor:pointer;">閉じる</button></div>';
  document.body.appendChild(ui);
  var msg=function(t){ui.querySelector('#ytq_msg').textContent=t;};
  var bar=function(p){ui.querySelector('#ytq_bar').style.width=p+'%';};
  v.pause();v.muted=true;
  var diffs=[];var prev=null;
  (async function(){
    try{
      for(var t=0;t<=180;t++){
        v.currentTime=t;
        await new Promise(function(r){var d=false;var h=function(){if(!d){d=true;v.removeEventListener('seeked',h);r();}};v.addEventListener('seeked',h);setTimeout(h,1500);});
        await new Promise(function(r){setTimeout(r,200);});
        var c=document.createElement('canvas');c.width=80;c.height=45;
        var ctx=c.getContext('2d');
        try{ctx.drawImage(v,0,0,80,45);}catch(e){msg('フレーム取得失敗(CORS?): '+e.message);return;}
        var px=ctx.getImageData(0,0,80,45).data;
        if(prev){var s=0;for(var i=0;i<px.length;i+=4)s+=Math.abs(px[i]-prev[i])+Math.abs(px[i+1]-prev[i+1])+Math.abs(px[i+2]-prev[i+2]);diffs.push(s/(px.length/4*3));}
        prev=px;
        msg('解析中... '+(t+1)+'/181');
        bar(Math.round((t+1)/181*100));
      }
      msg('✅ 解析完了 ('+diffs.length+'差分)');bar(100);
      var titleEl=document.querySelector('h1.style-scope.ytd-watch-metadata, h1.title.ytd-video-primary-info-renderer, h1.ytd-watch-metadata');
      var title=titleEl?titleEl.innerText.trim():(document.title.replace(/ - YouTube$/,''));
      var vid=new URLSearchParams(location.search).get('v')||'';
      var data={title:title,videoId:vid,diffs:diffs.map(function(d){return Math.round(d*100)/100;}),capturedAt:Date.now()};
      var hash=btoa(unescape(encodeURIComponent(JSON.stringify(data))));
      var fullUrl=REPORT_URL+'#'+hash;
      ui.querySelector('#ytq_done').style.display='block';
      ui.querySelector('#ytq_view').onclick=function(){window.open(fullUrl,'_blank');};
      ui.querySelector('#ytq_close').onclick=function(){ui.remove();};
    }catch(e){msg('エラー: '+e.message);}
  })();
})();`);

  const link = document.getElementById('bookmarklet-link');
  if (link) link.href = bookmarkletCode;
}

// ============================================================
// 起動
// ============================================================

function init() {
  const data = decodeHashData();
  if (data && Array.isArray(data.diffs) && data.diffs.length >= 5) {
    showResult(data);
  } else {
    showScreen('input');
    setupBookmarklet();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
