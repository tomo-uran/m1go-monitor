# M1号 在庫監視

https://m1go.stores.jp/ を5分ごとにチェックし、**新商品**と**再入荷**（SOLD OUT → 在庫あり）を見つけたら指定のアドレスにメールします。
メール設定は後から追加できます。未設定の間は、検知結果を GitHub の Actions 画面で確認できます。

## ステップA：監視を動かす（メールなし）

1. GitHubで新しいリポジトリを作る（**Public推奨**。理由は下の「注意」を参照）
2. 「uploading an existing file」から `monitor.py` `requirements.txt` `README.md` をアップロード
3. 「Add file → Create new file」で、ファイル名に `.github/workflows/monitor.yml` と入力し、同名ファイルの中身を貼り付けて保存
4. **Actions** タブ → 「M1号 在庫監視」→ **Run workflow** で手動実行
5. 実行結果をクリックし、Summary に「取得した商品数: ○件」と出ていれば成功（30件以上が目安）

以後は5分ごとに自動で動き、変化があれば各実行の Summary に表示されます。

## ステップB：メール通知を追加する（いつでもOK）

1. 送信元にするGmailで2段階認証を有効にし、https://myaccount.google.com/apppasswords でアプリパスワード（16文字）を作る
2. リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で3つ登録

| 名前 | 値 |
|---|---|
| `SMTP_USER` | 送信元のGmailアドレス |
| `SMTP_PASS` | アプリパスワード |
| `MAIL_TO` | 通知を受け取るアドレス（複数ならカンマ区切り） |

3. 次の実行で「メール通知を開始しました」という確認メールが1通届けば完了（すぐ確かめたいときは Run workflow で手動実行）

Secretsの中身は、Publicリポジトリでも外部からは見えません。
メール未設定の間に検知した変化は、後からまとめて送られることはありません（Actions の履歴で確認できます）。

## 注意
- **Privateリポジトリだと無料枠を超えます。** GitHub Actionsの無料枠はPrivateだと月2,000分で、5分ごとに動かすと月8,000分以上かかります。Publicなら無料で使えます。Privateにしたい場合は、`monitor.yml` の `*/5` を `*/30` などに変更してください。
- GitHubの混雑時は、実行が5〜15分ほど遅れることがあります。
- Publicリポジトリで60日間コミットがないと、定期実行が自動で止まります。GitHubからメールで知らせが来るので、Actions画面で再度有効にしてください。
- 取得に失敗した場合や、サイトの構造が変わって商品を読み取れなくなった場合は、実行が失敗扱い（赤い×）になり、GitHubからリポジトリの持ち主にメールが届きます。
