# 操作デモ

**[約7分19秒の操作動画（MP4・日本語音声・字幕あり）](https://higakota.github.io/nurse-scheduler-demo/)** ／ [ダウンロード](https://raw.githubusercontent.com/higakota/nurse-scheduler-demo/main/docs/demo/walkthrough.mp4)

[![操作デモを再生](poster.png)](https://higakota.github.io/nurse-scheduler-demo/)

画像中央の再生ボタンからプレイヤーへ進み、▶を押して再生できます。READMEの画像は静止画で、自動再生しません。歯車の「設定」→「再生速度」で0.75・1・1.25・1.5・2倍を選べます。MP4はブラウザへマウス入力を送った自動操作の記録です。見えるカーソルとクリックの輪を付けています。説明文はアプリ画面の下の専用欄に表示し、保存ボタンなどには重ねません。日本語の合成音声でも説明します。

## 動画の内容

1. スタッフ設定を確認し、ホームへ戻って対象月を選ぶ。
2. ①今月の入力からExcelを読み取り、担当医を確認して保存する。
3. 希望休・有給、休日日数・週上限、休診日、会議、事前ヘルプを順に入力・確認し、それぞれ保存完了を見る。
4. 必要人数と前月末勤務を確認・保存する。
5. 画面上の手順バーの②不足を確認へ進み、仮表の勤務と表下部の不足を実際に見る。
6. 「決まったヘルプの来院予定を登録する」から③へ進み、カレンダーで人・日・時間帯を登録する。
7. 「登録したヘルプを反映する」で④勤務表・印刷へ進み、変更内容を確認して勤務表を保存する。
8. 希望との比較と印刷用表示を見る。

サンプルの11月9日は、自院の検査技師2人に希望休を設定しています。仮表では検査技師が不足し、来院予定のある「応援スタッフ02」を反映すると埋まる例です。実際の施設の勤務条件ではありません。

スタッフは初期登録済みの架空データを確認します。Excelの読取候補は確認後に保存し、希望休・会議・事前ヘルプ・依頼後の来院予定は実際に変更して保存します。休日日数・休診日・必要人数・前月末勤務は設定値を確認して保存します。空の状態から全職員を登録する動画ではありません。

GitHubの「ブラウザでアプリを試す」は、動画ページの起動ボタンへ進みます。そこで「アプリを別タブで開く」を押すと、動画ページを残したままアプリを開けます。GitHubのREADMEでは、リンクを別タブにする指定が使えないためです。

[仮表と不足](../screenshots/draft-shortage.png) ／ [ヘルプ登録カレンダー](../screenshots/help-calendar.png) ／ [比較画面](../screenshots/roster.png) ／ [印刷用表示](../screenshots/print.png)

## 撮影と確認

- すべて架空データを使い、実用版とは別のDB・ポートで撮影。
- メニュー移動・ファイル選択・ボタン・チェックのマウス操作を記録し、説明は映像の下の専用欄に配置した。
- 操作前に説明を読み、操作後に結果を確認する時間を確保した。音声は日本語のNanami音声です。
- 入力した希望休・会議・事前ヘルプが保存されたことと、来院予定が保存後の勤務表へ配置されたことをDBで確認。
- 仮作成の勤務表と不足行、ヘルプ登録のカレンダーを見える位置までスクロールして説明。
- 撮影中のJavaScript例外・サーバー500番台エラーは0件。
- 印刷部分はブラウザの印刷用CSSを表示した画面。OSの印刷ダイアログの映像ではない。
- [撮影確認記録](capture-report.json)に確認対象を記載。

## 再撮影する場合

通常のアプリ起動には撮影ライブラリは不要です。撮影用には別のvenvを作り、`tools/requirements-recording.txt` をインストールします。Microsoft Edgeを利用するWindows向けの補助スクリプトです。

```powershell
git clone https://github.com/higakota/nurse-scheduler-demo.git .runtime/recording
py -3.13 -m venv .capture-venv
.\.capture-venv\Scripts\python.exe -m pip install -r requirements.txt -r tools/requirements-recording.txt
.\.capture-venv\Scripts\python.exe -m playwright install ffmpeg
.\.capture-venv\Scripts\python.exe tools/record_walkthrough.py --root .runtime/recording --prepare-inputs
```

先に別の端末で以下を実行して、撮影用コピーを起動します。

```powershell
cd .runtime/recording
..\..\.capture-venv\Scripts\python.exe demo_run.py --no-browser
```

撮影コマンドはプロジェクトのルートから実行します。`--prepare-inputs` は `.runtime` 内のサンプルコピーだけを初期化し、希望休・事前ヘルプ・依頼後のヘルプを入力前の状態にします。撮影スクリプトはExcelの保存と入力・勤務表の変更を行うため、通常の利用データには実行しません。サンプル環境の表示と架空スタッフを確認できない場合は中止します。

## 音声と説明欄

日本語ナレーションは Nanami（ja-JP-NanamiNeural）で生成しました。生成時は公開する架空の操作説明文だけをMicrosoft Edgeのオンライン音声サービスへ送ります。実データや個人情報は使用しません。生成済みの音声を動画に収録しているため、視聴時に音声生成サービスへ接続する必要はありません。[台本](narration.md)と[時刻付き台本](narration.json)を公開しています。

医師の確認チェックは、最初の2件を操作例として示し、残りの同じ操作を短く進めています。説明欄でも案内しています。実際の利用時は、すべての候補を元のExcelと照合します。

撮影スクリプトはアプリ画面を録画し、説明文の時刻を記録します。編集用の tools/compose_walkthrough.py が、アプリの画面の下へ説明欄を追加し、音声を同期します。WindowsのMeiryoフォントを使用します。

編集コマンド例：

    .\.capture-venv\Scripts\python.exe tools/compose_walkthrough.py --source .runtime/capture/walkthrough.mp4 --report .runtime/capture/capture-report.json --script docs/demo/narration.json --cache .runtime/voice-cache --output .runtime/composed

再撮影時は record_walkthrough.py の --output .runtime/capture を指定します。録画・音声キャッシュ・編集出力は公開対象に含めません。

## 動画の目次

| 再生位置の目安 | 内容 |
|---|---|
| 0:02 | スタッフ確認から印刷まで |
| 0:13 | はじめにスタッフを確認 |
| 0:40 | 2026年11月に切り替えました |
| 0:48 | 医師予定のExcelを読み込む |
| 1:00 | 対象月とシートを確認 |
| 1:10 | 読み取り候補を元のExcelと照合 |
| 1:44 | 医師予定を保存しました |
| 1:53 | 希望休・有給を入力 |
| 2:20 | 希望休・有給を保存しました |
| 2:27 | 休日日数・週上限を確認して保存 |
| 2:37 | 休日日数・週上限を保存しました |
| 2:44 | 休診日を確認して保存 |
| 2:53 | 休診日を保存しました |
| 3:00 | 会議も変更後に保存する |
| 3:17 | 会議を保存しました |
| 3:23 | 事前に来られるヘルプを入力 |
| 3:41 | 事前ヘルプを保存しました |
| 3:49 | 必要人数を確認して保存 |
| 3:59 | 必要人数を保存しました |
| 4:07 | 前月末勤務を確認して保存 |
| 4:17 | 前月末勤務を保存しました |
| 4:41 | 不足確認で作った勤務表を見る |
| 4:50 | 表の下で不足を確認する |
| 5:16 | ヘルプ登録のカレンダーを見る |
| 5:31 | 入力した来院予定はまだ未保存 |
| 5:48 | 勤務表へ反映する変更を確認 |
| 6:16 | 更新した表を保存できました |
| 6:33 | 勤務は上段、希望は下段 |
| 7:04 | 入力から印刷まで確認できました |
