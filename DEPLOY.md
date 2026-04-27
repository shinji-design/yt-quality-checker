# デプロイ手順書（Render.com）

ローカル動作確認後、外部公開するための手順です。

---

## 前提

ローカルでの動作確認が完了していること。

```bash
~/yt-quality-checker/start.sh
```

これで `http://localhost:8000` が開けばOK。

---

## ステップ1: GitHubアカウント作成・リポジトリ作成

### 1-1. GitHubアカウント作成
1. https://github.com/ にアクセス
2. 「Sign up」をクリック
3. メールアドレス・パスワード・ユーザー名を入力
4. メール認証

### 1-2. 新規リポジトリ作成
1. 右上の「+」→「New repository」
2. Repository name: `yt-quality-checker`
3. Privacy: **Private**（推奨）
4. 「Create repository」をクリック

### 1-3. 表示される手順を控える
GitHub上に表示される `git remote add origin ...` の URL をコピー。

---

## ステップ2: ローカルからGitHubへアップロード

ターミナルで以下を実行：

```bash
cd ~/yt-quality-checker

# Gitの初期設定（初回のみ）
git config --global user.name "あなたの名前"
git config --global user.email "あなたのメール"

# Gitリポジトリ初期化
git init
git add .
git commit -m "Initial commit"

# GitHubにアップロード（URLは1-3でコピーしたものに置換）
git remote add origin https://github.com/yourname/yt-quality-checker.git
git branch -M main
git push -u origin main
```

初回pushでGitHubのユーザー名・パスワード（または Personal Access Token）を聞かれます。

---

## ステップ3: Render.comでデプロイ

### 3-1. Render.comに登録
1. https://render.com/ にアクセス
2. 「Get Started」→ GitHub認証で登録
3. クレジットカード登録（後の有料プラン用）

### 3-2. 新規Webサービス作成
1. ダッシュボードで「New +」→「Web Service」
2. 「Build and deploy from a Git repository」
3. リポジトリ `yt-quality-checker` を選択

### 3-3. 設定入力
| 項目 | 値 |
|---|---|
| Name | `yt-quality-checker` |
| Region | Singapore |
| Branch | main |
| Runtime | **Docker** |
| Dockerfile Path | `./backend/Dockerfile` |
| Docker Build Context Directory | `.` |
| Plan | **Starter ($7/month)** |

### 3-4. デプロイ実行
1. 「Create Web Service」をクリック
2. 10〜15分待つ（Docker buildが走る）
3. 完了すると `https://yt-quality-checker.onrender.com` のようなURLが発行される

---

## ステップ4: 動作確認

発行されたURLにブラウザでアクセス。
ローカルと同じ画面が出ればデプロイ成功。

---

## メモリ不足エラーが出る場合

Render Starter（512MB）でPlaywrightは綱渡りです。
頻繁にエラーが出る場合：

1. Render ダッシュボード → Settings
2. Plan を **Standard ($25/month)** にアップグレード
3. メモリが2GBに増加し、安定動作

---

## 独自ドメイン設定（任意）

### 4-1. ドメイン取得
- お名前.com、ムームードメインなどで取得（年1,500円程度）
- 例: `video-checker.example.com`

### 4-2. Renderに追加
1. Render ダッシュボード → Settings → Custom Domains
2. ドメインを入力
3. 表示されるDNSレコード（CNAME）をドメイン管理画面で設定
4. 数十分〜数時間で反映

---

## 月額コスト見込み

| 項目 | 金額 |
|---|---|
| Render Web Service (Starter) | $7/月（約1,100円） |
| ドメイン（任意） | 年1,500円程度 |
| **合計** | **月約1,100円〜1,200円** |

利用回数が増えてきたら、Standard プラン（$25/月）への昇格を検討。

---

## 更新時の操作

コードを変更したら：

```bash
cd ~/yt-quality-checker
git add .
git commit -m "変更内容のメモ"
git push
```

Renderが自動で再デプロイします（5〜10分）。

---

## トラブル時の確認場所

### Renderのログ
1. Render ダッシュボード → サービス選択
2. 「Logs」タブ
3. エラーメッセージを確認

### よくあるエラー
- `Out of memory` → プランをStandardへ昇格
- `Build failed` → Dockerfileのパス設定を確認
- `Connection timeout` → 動画長すぎ・YouTube側変更
