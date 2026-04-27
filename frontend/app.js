/**
 * 動画クオリティ・チェッカー フロントエンド
 */

const screens = {
  input: document.getElementById('input-screen'),
  loading: document.getElementById('loading-screen'),
  result: document.getElementById('result-screen'),
  error: document.getElementById('error-screen'),
};

function showScreen(name) {
  Object.values(screens).forEach(s => s.classList.remove('active'));
  screens[name].classList.add('active');
}

const SCORE_ITEMS = {
  balance: {
    label: '① 動きのバランス',
    icon: '🎬',
    desc: {
      good: '動画全体の動きの活発さがちょうど良いバランスです。',
      near: '動きのバランスは概ね良好です。',
      border: '動きのバランスがやや偏っています。',
      warn: '動きの量が多すぎる、または少なすぎます。',
      ng: '動きのバランスが大きく崩れています。',
    }
  },
  still: {
    label: '② 止まっている時間',
    icon: '📌',
    desc: {
      good: '画面が止まっている時間と動いている時間のバランスが良いです。',
      near: '止まっている時間の長さは概ね適切です。',
      border: '止まっている時間がやや多めです。',
      warn: '止まっている時間が長すぎる、または短すぎます。',
      ng: '画面がほとんど動かない、または動きすぎています。',
    }
  },
  scene: {
    label: '③ 場面切替の回数',
    icon: '🔄',
    desc: {
      good: '場面が変わるペースがちょうど良いです。',
      near: '場面切替のペースは適切です。',
      border: '場面切替の回数がやや多い／少なめです。',
      warn: '場面切替が多すぎる、または少なすぎます。',
      ng: '場面切替のリズムに問題があります。',
    }
  },
  variety: {
    label: '④ 動きの種類の多さ',
    icon: '🎨',
    desc: {
      good: '色々な種類の動きが使われていて、見飽きません。',
      near: '動きの種類は十分にあります。',
      border: '動きの種類がやや少なめです。',
      warn: '動きの種類が足りていません。',
      ng: 'いつも同じような動かし方になっています。',
    }
  },
  concentrate: {
    label: '⑤ 同じ動きの集中度',
    icon: '📊',
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
  return {good: '🟢', near: '🟢', border: '🟡', warn: '🟠', ng: '🔴'}[level];
}

document.getElementById('check-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const channelUrl = document.getElementById('channel-url').value.trim();
  const videoUrl = document.getElementById('video-url').value.trim();

  if (!channelUrl && !videoUrl) {
    alert('チャンネルURLか動画URLのどちらか一方を入力してください');
    return;
  }

  startAnalysis(channelUrl, videoUrl);
});

function startAnalysis(channelUrl, videoUrl) {
  showScreen('loading');
  updateProgress(0, '処理を開始しています...');

  const url = `/analyze?channel_url=${encodeURIComponent(channelUrl)}&video_url=${encodeURIComponent(videoUrl)}`;
  const eventSource = new EventSource(url);

  let timeoutId = setTimeout(() => {
    eventSource.close();
    showError('処理がタイムアウトしました。もう一度お試しください。');
  }, 360000);

  eventSource.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }

    if (data.step === 'error') {
      clearTimeout(timeoutId);
      eventSource.close();
      showError(data.message);
      return;
    }

    if (data.progress !== undefined) {
      updateProgress(data.progress, data.message || '');
    }

    if (data.step === 'done' && data.result) {
      clearTimeout(timeoutId);
      eventSource.close();
      setTimeout(() => showResult(data.result), 500);
    }
  };

  eventSource.onerror = () => {
    clearTimeout(timeoutId);
    eventSource.close();
    showError('サーバーとの通信中にエラーが発生しました。');
  };
}

function updateProgress(percent, message) {
  document.getElementById('progress-fill').style.width = `${percent}%`;
  document.getElementById('progress-percent').textContent = percent;
  if (message) {
    document.getElementById('loading-message').textContent = message;
  }
}

function showResult(result) {
  showScreen('result');

  document.getElementById('video-title').textContent = `分析した動画：${result.title}`;

  const judgment = result.judgment;
  const total = result.scores.total;

  const judgmentBox = document.getElementById('judgment-box');
  judgmentBox.className = `judgment-box ${judgment.level}`;
  document.getElementById('judgment-icon').textContent = judgment.icon;
  document.getElementById('judgment-label').textContent = judgment.label;
  document.getElementById('total-score').textContent = total;
  document.getElementById('judgment-message').textContent = judgment.message;

  setTimeout(() => {
    document.getElementById('total-bar-fill').style.width = `${total}%`;
    document.getElementById('total-bar-fill').style.background = {
      good: '#27ae60',
      near: '#16a085',
      border: '#f1c40f',
      warn: '#e67e22',
      ng: '#e74c3c'
    }[judgment.level];
  }, 100);

  const scoreList = document.getElementById('score-list');
  scoreList.innerHTML = '';
  ['balance', 'still', 'scene', 'variety', 'concentrate'].forEach(key => {
    const score = result.scores[key];
    const level = getLevel(score);
    const item = SCORE_ITEMS[key];

    const card = document.createElement('div');
    card.className = `score-card ${level}`;
    card.innerHTML = `
      <div class="score-card-header">
        <div>
          <span class="score-card-icon">${item.icon}</span>
          <span class="score-card-title">${item.label}</span>
        </div>
        <div>
          <span class="score-card-icon">${getIcon(level)}</span>
          <span class="score-card-score ${level}">${score}点</span>
        </div>
      </div>
      <p class="score-card-desc">${item.desc[level]}</p>
      <div class="score-bar">
        <div class="score-bar-fill ${level}" style="width: 0%;"></div>
      </div>
    `;
    scoreList.appendChild(card);

    setTimeout(() => {
      card.querySelector('.score-bar-fill').style.width = `${score}%`;
    }, 200);
  });

  const adviceList = document.getElementById('advice-list');
  const adviceTitle = document.getElementById('advice-title');
  adviceList.innerHTML = '';

  if (result.advice && result.advice.length > 0) {
    adviceTitle.style.display = 'block';
    const medals = ['🥇', '🥈', '🥉'];
    result.advice.forEach((adv, i) => {
      const card = document.createElement('div');
      card.className = 'advice-card';
      card.innerHTML = `
        <div class="advice-priority">${medals[i] || '・'} 優先度 ${adv.priority}</div>
        <h4 class="advice-title">${adv.title}</h4>
        <p class="advice-current">${adv.current}</p>
        <p class="advice-target">${adv.target}</p>
        <div class="advice-how">
          <p class="advice-how-label">やり方の例：</p>
          <ul>
            ${adv.how.map(h => `<li>${h}</li>`).join('')}
          </ul>
        </div>
      `;
      adviceList.appendChild(card);
    });
  } else {
    adviceTitle.style.display = 'none';
  }
}

function showError(message) {
  showScreen('error');
  document.getElementById('error-message').textContent = message;
}
