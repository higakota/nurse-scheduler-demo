# テストと確認方法

## 現在確認していること

公開サンプルでは、Windows / Python 3.13で502件の自動テストが通っています。実在する職員・勤務表はテストに使わず、一時DBと仮名を使います。

| 分類 | 例 | テスト |
|---|---|---|
| Excel取込 | 対象月、日付、赤字、縦書き、確認前に保存しない | [test_doctor_import.py](../tests/test_doctor_import.py)、[test_doctor_colors.py](../tests/test_doctor_colors.py) |
| 勤務条件 | 希望休・有給、週上限、前月との連勤 | [test_scheduler.py](../tests/test_scheduler.py)、[test_weekly_work.py](../tests/test_weekly_work.py) |
| 応援 | 承諾済みの時間帯を維持、職種別の不足 | [test_help_commitments.py](../tests/test_help_commitments.py)、[test_help_role_preference.py](../tests/test_help_role_preference.py) |
| 表の状態 | 古い表への遷移・上書き防止、確認中は不変 | [test_roster_navigation.py](../tests/test_roster_navigation.py) |
| 入力 | 医師予定から始める入口と順序、会議の一括保存、競合時に部分保存しない | [test_meeting_attendance.py](../tests/test_meeting_attendance.py)、[test_workflow_guidance.py](../tests/test_workflow_guidance.py) |
| 運用 | バックアップ、版の切り替えと復帰 | [test_operations.py](../tests/test_operations.py) |
| サンプル | 架空DB初期化、Excel解析、作成結果、画面表示 | [test_portfolio_demo.py](../tests/test_portfolio_demo.py) |

件数は現時点の実行結果であり、過去の各コミットで502件通ったという意味ではありません。機能追加・修正に合わせてテストも追加しています。

## 再実行

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

絞って確認する例：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_roster_navigation.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_portfolio_demo.py
```

## 手動確認すること

- 作成・応援登録・変更確認・編集を往復して、同じ表を確認できるか。
- 希望休・有給を半日単位で変更し、保存前後の差分を確認できるか。
- 印刷プレビューで日付・職員名・希望欄が切れないか。
- 架空データを使ってバックアップを保存・復元できるか。

## 確認の限界

探索時間内の最適解を保証しない。認証・公開サーバーの権限管理は未実装。実運用では利用者による人数・希望・勤務条件の最終確認が必要。

業務時間の削減率、利用者数、導入効果などの数値は測定していないため掲載していません。テストの件数と業務上の効果は別の確認項目です。

## 自動実行

GitHub ActionsのWindows / Python 3.13で、依存関係のインストール、pip check、全テスト、初回サンプル初期化とホーム表示を実行する。[成功した実行記録](https://github.com/higakota/nurse-scheduler-demo/actions/runs/39758385684)と[最新の実行一覧](https://github.com/higakota/nurse-scheduler-demo/actions/workflows/tests.yml)を公開している。
