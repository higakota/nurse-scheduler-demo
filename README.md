# 看護職員の勤務表作成支援アプリ

[![Tests](https://github.com/higakota/nurse-scheduler-demo/actions/workflows/tests.yml/badge.svg)](https://github.com/higakota/nurse-scheduler-demo/actions/workflows/tests.yml)

**使用者への聞き取りと操作確認をもとに、勤務表の入力・不足確認・応援登録・修正・印刷をまとめたWebアプリです。** 自動作成だけでなく、作成後の変更を同じ勤務表に反映し、確認しながら仕上げる流れを重視しています。

**[操作動画を見る（約7分19秒・音声あり）](https://higakota.github.io/nurse-scheduler-demo/)**

[![操作デモを再生](docs/demo/poster.png)](https://higakota.github.io/nurse-scheduler-demo/)

**[ブラウザでアプリを試す ↗](https://higakota.github.io/nurse-scheduler-demo/#try-app)**　／　**[サンプルExcelをダウンロード](https://raw.githubusercontent.com/higakota/nurse-scheduler-demo/main/samples/sample_requests_2026-11.xlsx)**

動画ページの「アプリを別タブで開く」から試せます。最初の表示に1分ほどかかる場合があります。データはすべて架空で、公開体験版の操作内容はブラウザごとに分かれます。個人情報は入力しないでください。[Excelの使い方](samples/README.md)

## この開発で取り組んだこと

| 工程 | 取り組み | 確認できるもの |
|---|---|---|
| 聞き取り・要件整理 | 希望休・有給・会議・職種・応援の扱いを使用者へ確認し、作成の手順へ落とし込む | [課題と要件・受入観点](docs/project-overview.md) |
| 設計・実装 | 条件と勤務表の版を照合し、作成後の修正や画面遷移でも同じ表を扱う | [構成と設計判断](docs/portfolio.md) |
| 操作確認・改善 | 「古い表が開く」「会議を入力するたび位置が戻る」などの指摘を修正し、回帰テストへ残す | [不具合と改善の事例](docs/case-studies.md) |
| 導入・保守 | バックアップ、データを残す更新、アプリの前の版への復帰、Windows配布を整える | [Windows配布・更新の実装](docs/windows-install.md) |

**本人の担当は、使用者への聞き取り・仕様の判断・操作確認・不具合の指摘です。** コードの実装・調査・テストコード作成・文書整備には生成AIを利用しています。[担当範囲と確認状況](docs/project-overview.md#担当範囲と生成aiの利用)

## 何を解決するか

勤務表は、最初に作れれば終わりではありません。有給の追加や応援の予定変更があると、人数・連勤・公休日数を再び確認する必要があります。

そこで、入力から印刷までを次の流れに整理しました。

**スタッフ確認 → 対象月の選択 → ①今月の入力 → ②不足を確認 → ③ヘルプを依頼・登録 → ④勤務表・印刷**

依頼・相談は電話などアプリ外で行い、実際に来られる日だけ登録します。希望休・有給・依頼済み応援を保護し、不足が残る場合は日付・時間帯・職種を表示します。[画面と操作の説明](docs/demo/README.md)

## 特に工夫した点

| 課題 | 対応 | 実装・検証 |
|---|---|---|
| 編集後に古い勤務表が開く | 表の種類・版・入力条件を照合し、指定した表を表示・保存する | [修正事例1](docs/case-studies.md#1-編集後に古い勤務表が開く) |
| 検査技師が足りていても看護師不足になる | 合計人数と職種別の条件を分け、探索・結果検証・不足表示をそろえる | [修正事例2](docs/case-studies.md#2-検査室の人数と職種を正しく数える) |
| 会議参加者を追加するたびに入力位置が戻る | 複数人・複数日をまとめて入力し、版を確認して一括保存する | [修正事例4](docs/case-studies.md#4-会議をまとめて入力する) |
| 1行へ集約した応援が画面では読みにくい | 使用者の反応を受け、画面は個人別・印刷は集約へ変更する | [修正事例5](docs/case-studies.md#5-見やすさの改善案を利用者の反応で見直す) |
| 別のPCへの導入と更新でデータを失いたくない | Python不要の配布版を作り、コードとデータを分離して更新・復帰する | [修正事例7](docs/case-studies.md#7-別のpcへ配布し入力データを残して更新する) |

[コードを追って説明する3つの改善](docs/explain-the-code.md) ／ [勤務と希望の比較](docs/screenshots/roster.png) ／ [印刷用表示](docs/screenshots/print.png)

## 技術と構成

| 項目 | 内容 |
|---|---|
| アプリ | Python 3.13 / Flask / SQLite |
| 画面 | HTML / CSS / JavaScript |
| Excel取込 | XLSX内のXMLを解析し、確認画面を経て保存 |
| 検証 | unittestによる回帰テスト、ブラウザでの操作確認 |
| CI | GitHub Actions：Windowsで全テスト、Linuxで公開版の起動確認 |
| 公開 | Render：操作体験版 / GitHub Pages：動画 |
| Windows配布 | PyInstaller：インストール・更新・前の版への復帰 |

[設計と技術選定の理由](docs/portfolio.md) ／ [確認対象と限界](docs/verification.md)

## 開発の記録

| 時期 | 取り組み |
|---|---|
| 2026/10/16〜18 | 環境構築、要件整理、スタッフ・月別入力 |
| 10/19〜20 | Excel取込、必要人数、前月勤務、作成・編集・応援管理 |
| 10/21〜22 | 職種・連勤の扱い、表の版の整合性、一括入力、半日有給、印刷、バックアップ |
| 10/23 | 公開体験版・操作動画、利用者ごとのデータ分離、Windowsへの配布・更新 |

初期開発の実在する67コミットを、個人情報を除外して [development-historyブランチ](https://github.com/higakota/nurse-scheduler-demo/commits/development-history/) に収録しています。公開後の改善はmainへ通常のコミットとして記録しています。[履歴の扱いと一覧](docs/development-history.md)

## 自分のPCで動かす

<details>
<summary>Windowsでのセットアップとテスト</summary>

Python 3.13とGitを使います。

```powershell
git clone https://github.com/higakota/nurse-scheduler-demo.git
cd nurse-scheduler-demo
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe demo_run.py
```

ブラウザで http://127.0.0.1:5001/?month=2026-11 を開きます。初回は架空データを作成し、操作内容を instance/demo.sqlite3 に保存します。終了は端末でCtrl+Cです。2回目からは start_demo.bat をダブルクリックすると起動できます。

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

テストは一時DBと仮名で実行します。[新規環境での確認](docs/first-run-check.md) ／ [CIの実行一覧](https://github.com/higakota/nurse-scheduler-demo/actions/workflows/tests.yml)

</details>

## 確認状況と公開範囲

- 自動テストと操作確認は、対象の経路・条件に対する確認です。すべての入力で最適な勤務表ができることは保証しません。
- Windows配布版は、同じPCの別フォルダで新規導入・登録・更新・復帰を確認しました。使用者の別PCでの初回導入は未確認です。
- 業務時間の削減率や導入効果は未測定です。使用者による勤務条件と人数の最終確認が必要です。
- 実データ・元のExcel・実用版のセットアップ本体は公開していません。公開用サンプルは診療日を8日に絞った架空の例です。
- 公開体験版は認証・権限管理を備えた業務用サービスではありません。保存内容は一定時間後や再起動で初期化します。ライセンスは未設定です。

[テストと確認方法](docs/verification.md) ／ [公開データの検査範囲](docs/privacy-check.json) ／ [Renderでの公開方法](docs/deployment.md)
