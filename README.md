# そーCloud

Discordの中だけで完結する、BOT起動用クラウドです。ブラウザのダッシュボードは不要で、スラッシュコマンドとボタンだけで別のDiscord BOTをデプロイ・起動・停止・ログ確認できます。各BOTのサイトも自動ホストされ、ユーザーごとに個人フォルダが自動作成されます。

**言語制限はありません。** Python / Node.js / TypeScript / Go / Rust / Java など、ソースから自動判定して起動します。ランタイムが無ければ Termux の `pkg`、Linux の `apt`、Windows の `winget` などで自動インストールします。

Windows・Linux・Android（Termux）で動作します。

## できること

- テンプレートから数秒でゲストBOT（Python）を作る
- 任意言語のソース / `.zip` をDiscordに添付して自分のコードを載せる
- 未導入の言語は作成・起動時に自動インストール
- トークンはモーダル入力（ephemeral。チャットに残りません）
- 起動・停止・再起動・ログ・環境変数・自動再起動
- `/cloud panel` のボタン操作
- 各BOTの `public/` フォルダを自動でサイト公開
- ユーザーごとに `users/<Discord ID>/` 以下へBOT・ファイルを自動保存
- サイトで **Discord ログイン** → 同じ Discord ID のフォルダ・BOT と自動同期

## セットアップ（このクラウド本体）

1. [Discord Developer Portal](https://discord.com/developers/applications) で **管理用BOT** を1つ作る
2. Bot をサーバーに入れる（`applications.commands` と `bot`）
3. **OAuth2** で Redirect URI を追加: `{PUBLIC_URL}/auth/callback`
4. Python 3.10 以上をインストール（Termux なら下の手順で自動）
5. このフォルダで:

```bash
copy .env.example .env
```

`.env` の `DISCORD_TOKEN` に **管理用BOT** のトークンを入れる。  
サイトログインを使う場合は `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` / `SESSION_SECRET` も設定する（同じアプリケーションの値でOK）。

```bash
pip install -r requirements.txt
python -m disscloud
```

Windows なら `start.cmd`、Linux / Termux なら `bash start.sh` でも起動できます。

### Termux（Android）

```bash
pkg update -y
pkg install -y python git
# このフォルダへ移動して
bash start.sh
```

初回は `.env` が作られるので `DISCORD_TOKEN` を入れてから、もう一度 `bash start.sh` してください。ゲストBOT用の言語（Node.js など）は、そのBOTを起動するときに自動で `pkg install` されます。

起動後、サーバーで `/cloud help` が使えればOKです。
サイトは `http://localhost:8080`（ローカル）で公開されます。Cloudflare 経由の場合は下記を参照してください。

### スラッシュコマンドが同期されない場合

起動時に `/cloud` 以下のコマンドをグローバル同期し、BOT が参加している全サーバーへ登録します。反映されない場合は管理者が `/cloud sync` を実行してください。Discord 側でグローバルコマンドの反映に時間がかかる場合があります。

## Cloudflare で公開する

Discord 上の `/cloud site` やサイト内リンクに表示される URL は `.env` の **`PUBLIC_URL`**（または `CLOUDFLARE_DOMAIN`）です。ローカルの待受ポート（`SITE_PORT`）とは別に設定します。

### パターン A: Cloudflare プロキシ（オレンジ雲）

```env
SITE_PORT=8080
CLOUDFLARE_ENABLED=true
PUBLIC_URL=https://cloud.example.com
TRUST_PROXY=true
```

Cloudflare DNS で `cloud.example.com` をこのサーバーに向け、プロキシを ON にします。

### パターン B: Cloudflare Tunnel（cloudflared）

```env
SITE_PORT=8080
CLOUDFLARE_TUNNEL=true
PUBLIC_URL=https://cloud.example.com
TRUST_PROXY=true
```

別ターミナルで Tunnel を起動:

```bash
cloudflared tunnel --url http://localhost:8080
```

独自ドメインを使う場合はその URL を `PUBLIC_URL` に設定してください。

設定確認は Discord で `/cloud config` を実行できます。

## サイトで Discord ログイン

1. `.env` に OAuth 設定を入れる（`.env.example` 参照）
2. ブラウザでサイトを開き **「Discord でログイン」**
3. ログイン後 `/dashboard` に、Discord の `/cloud` で作った BOT と同じ一覧が表示される
4. データは `users/<あなたのDiscord ID>/` に保存され、Discord 操作と共有される

| 変数 | 説明 |
|------|------|
| `DISCORD_CLIENT_ID` | アプリケーション ID |
| `DISCORD_CLIENT_SECRET` | OAuth2 クライアントシークレット |
| `SESSION_SECRET` | ログインセッション署名用の秘密鍵 |
| `OAUTH_REDIRECT_URI` | 省略時は `{PUBLIC_URL}/auth/callback` |

## ゲストBOTの最短手順

1. `/cloud create name:mybot`
2. `/cloud token name:mybot` → Developer Portal で作った **別BOT** のトークンを入れる
3. `/cloud start name:mybot`
4. ゲストBOTを入れたサーバーで `/ping`
5. ブラウザで `https://cloud.example.com/s/mybot/` を開く（`PUBLIC_URL` に合わせる）

自分のコードを使う場合は `/cloud create` にソースまたは zip を添付してください。言語は自動判定します（`language:` で明示も可）。`package.json` / `requirements.txt` / `go.mod` などがあれば依存関係も入れます。未導入のランタイムは自動インストールします。ゲストBOT側は環境変数 `DISCORD_TOKEN` を読んでログインしてください。

`soucloud.json` でエントリと言語を明示できます:

```json
{ "runtime": "node", "entry": "src/index.js" }
```

## 環境変数（サイト関連）

| 変数 | 説明 |
|------|------|
| `SITE_HOST` / `SITE_PORT` | そーCloud がローカルで待ち受けるアドレス |
| `PUBLIC_URL` | ユーザー向けの公開 URL（Cloudflare のドメイン） |
| `CLOUDFLARE_DOMAIN` | `PUBLIC_URL` の代替（どちらか一方で可） |
| `CLOUDFLARE_ENABLED` | Cloudflare プロキシ利用時に `true` |
| `CLOUDFLARE_TUNNEL` | cloudflared 利用時に `true` |
| `TRUST_PROXY` | `X-Forwarded-*` / `CF-Visitor` を信頼 |

## フォルダ構成

```
users/
  <DiscordユーザーID>/
    profile.json      # ユーザー情報（自動作成）
    files/            # 個人用ファイル保存先
    bots/
      <bot_id>/
        bot.py
        requirements.txt
        .env            # トークン・環境変数
        data/           # BOTの永続データ（BOT_DATA_DIR）
        public/         # 公開サイト（自動ホスト）
        cloud.log
data/
  state.json            # BOT一覧の状態
```

## 注意

- このマシン上で子プロセスとしてBOTが動きます（いわゆるセルフホストPaaS）
- 信頼できるコードだけ載せてください
- トークンをチャットに貼らないでください（必ず `/cloud token`）
- 外部公開する場合は `PUBLIC_URL` を Cloudflare の URL（`https://...`）に設定してください
