# 操作デモ

**[約5分48秒の操作動画（MP4・音声なし）](https://higakota.github.io/nurse-scheduler-demo/)** ／ [ダウンロード](https://raw.githubusercontent.com/higakota/nurse-scheduler-demo/main/docs/demo/walkthrough.mp4)

[![操作デモを再生](poster.png)](https://higakota.github.io/nurse-scheduler-demo/)

画像中央の再生ボタンからプレイヤーへ進み、▶を押して再生できます。READMEの画像は静止画で、自動再生しません。MP4はブラウザへマウス入力を送った自動操作の記録です。見えるカーソルとクリックの輪、操作前後の説明字幕を重ねています。

## 動画の内容

1. ホームから職種・勤務条件・希望を確認する。
2. サンプルExcelを選択し、対象シートと読み取り結果を確認する。
3. 事前に来られる応援を使って仮作成し、検査技師の不足を確認する。
4. 来院予定を確認し、最新の入力・応援で勤務表を更新する。
5. 変更内容を確認して保存し、希望との比較と印刷用表示を見る。

サンプルの11月9日は、自院の検査技師2人に希望休を設定しています。仮表では検査技師が不足し、来院予定のある「応援スタッフ02」を反映すると埋まる例です。実際の施設の勤務条件ではありません。

Excelは読み取り結果の確認までを撮影しています。動画内でExcelの候補は保存せず、初期登録済みの架空予定を使って勤務表を作成しています。

[比較画面](../screenshots/roster.png) ／ [印刷用表示](../screenshots/print.png)

## 撮影と確認

- すべて架空データを使い、実用版とは別のDB・ポートで撮影。
- メニュー移動・ファイル選択・ボタン・チェックのマウス操作を記録し、説明字幕を重ねた。
- 操作前に説明を読み、操作後に結果を確認する時間を確保した。音声はなし。
- 登録済みの応援が保存後の勤務表へ配置されたことを確認。
- 撮影中のJavaScript例外・サーバー500番台エラーは0件。
- 印刷部分はブラウザの印刷用CSSを表示した画面。OSの印刷ダイアログの映像ではない。
- [撮影確認記録](capture-report.json)に確認対象を記載。

## 再撮影する場合

通常のアプリ起動には撮影ライブラリは不要です。撮影用には別のvenvを作り、`tools/requirements-recording.txt` をインストールします。Microsoft Edgeを利用するWindows向けの補助スクリプトです。

```powershell
py -3.13 -m venv .capture-venv
.\.capture-venv\Scripts\python.exe -m pip install -r tools/requirements-recording.txt
.\.capture-venv\Scripts\python.exe -m playwright install ffmpeg
.\.capture-venv\Scripts\python.exe tools/record_walkthrough.py
```

先に別の端末で `python demo_run.py` を起動してください。撮影スクリプトはExcelの読取・勤務表の作成・反映・保存を行うため、変更してよい架空データのコピーで実行します。サンプル環境の表示と架空スタッフを確認できない場合は中止します。

## 動画の目次

| 再生位置の目安 | 内容 |
|---|---|
| 0:02 | この動画で見る流れ |
| 0:26 | 職種と勤務条件を分けて管理 |
| 0:49 | 入力した希望を確認する |
| 1:07 | サンプルExcelを選択する |
| 1:34 | 対象月とシートを確認する |
| 1:58 | 読み取り候補を確認する |
| 2:41 | 仮表の不足を確認する |
| 3:05 | 来院OKの予定を確認する |
| 3:47 | 保存する前に変更箇所を確認する |
| 4:24 | 更新した表を保存できました |
| 4:47 | 勤務は上段、希望は下段 |
| 5:26 | 入力から印刷まで確認できました |
