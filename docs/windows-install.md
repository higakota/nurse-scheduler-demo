# 別のWindows PCへの配布と更新

使用者には Python・Git・開発者のGitHubアカウントを要求しません。勤務データはPC内に保存します。公開体験版のRenderとは別の、実用版の配布方法です。

このリポジトリでは、配布・更新処理のソースと一時データによるテストを公開しています。実用版に渡すセットアップ本体や勤務データは公開していません。ブラウザで試す場合は [README](../README.md) のリンクを使用してください。

## 利用者の手順

1. 配布用ZIPを使用者のWindows PCへコピーし、展開する。
2. セットアップ実行ファイルをダブルクリックし、「インストールする」を押す。
3. 次回からデスクトップの「看護師勤務表」から開く。
4. 更新時は、入力を保存してから新しいセットアップを実行し、「更新する」を押す。

Windows 10 / 11の64ビット版向けです。管理者権限は不要で、利用者ごとのLocalAppDataへインストールします。実データは配布ファイルに含めません。既存データを移す場合は、元のPCでバックアップし、移行先のバックアップ画面で内容を確認して復元します。復元前の移行先データも保護します。

更新ファイルをこちらから渡す方式です。開発者がソースを変更・Gitへpushしただけで、使用者のPCが自動更新される仕組みではありません。私用GitHubの認証情報は渡しません。

## 保存先と更新

保存先は %LOCALAPPDATA%\\NurseScheduler です。

- versions/版番号：Pythonを内包したアプリ本体。以前の版も残す。
- installation.json：現在と直前の版の番号。
- data/staff.sqlite3：全月の勤務データ。アプリ本体のフォルダと分離する。
- data/backups/automatic：既存の自動バックアップ。
- data/backups/before_update_*.sqlite3：更新・復帰前のデータ。
- .runtime：起動中のアプリの識別情報と操作ロック。

更新ファイルの構成とハッシュを確認し、別フォルダへ展開して起動確認を行います。その後、所有を確認したアプリを停止し、SQLiteのbackup APIでバックアップしてから切り替えます。新しい版が起動できなければ、使用する版の設定を戻して旧版の起動を試みます。勤務データの内容を自動で巻き戻すことはしません。

スタートメニューの「看護師勤務表 → 更新・保存場所の確認」から、保存先の確認と前の版への復帰ができます。依存ライブラリも配布版ごとに内包するため、利用者側でpipを実行する必要はありません。更新時に未保存の入力は引き継がれないため、先に保存します。

## 開発者による作成

専用のビルド環境に requirements.txt と tools/requirements-build.txt をインストールします。通常のPython環境にはPyInstallerは不要です。

    py -3.13 -m venv .build-venv
    .\\.build-venv\\Scripts\\python.exe -m pip install -r requirements.txt -r tools/requirements-build.txt
    .\\.build-venv\\Scripts\\python.exe -B -m unittest discover -s tests
    .\\.build-venv\\Scripts\\python.exe tools/build_windows.py --version 2026.10.23.3

版番号は毎回変えます。同じ版番号で異なるファイルを配布しません。出力先は dist です。セットアップと利用案内をまとめてUSBなどで渡します。実用DB・Excel・Gitの認証情報・開発用venvを同梱しません。

ビルドはWindows上で行います。アプリとセットアップの両方をPyInstallerで作成し、画面テンプレート・静的ファイルだけを明示的に含めます。配布版にソースのテストや実データを含めません。Gitを使う既存の開発者用 update.vbs とは別の仕組みです。

## 確認

データ保持・起動失敗時の復帰・破損ファイル・パス逸脱・重複ファイルなどを tests/test_desktop_distribution.py で検証します。配布バイナリは別の保存先とポートを使って新規インストール・登録・更新・復帰を確認します。使用者の実機での最終確認は別途必要です。
