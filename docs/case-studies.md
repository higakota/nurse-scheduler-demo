# 不具合と改善の事例

利用者から報告された課題と、変更した処理・回帰テストを対応させています。氏名・施設名・実際の勤務表は掲載していません。ここに書いた結果は該当経路での確認内容で、あらゆる操作で不具合が起きないことの保証ではありません。

## 1. 編集後に古い勤務表が開く

**課題**：作成結果・仮表・編集表が別に保存され、画面を往復すると、利用者が直前に確認したものと別の勤務表が表示される場合があった。

**変更**：遷移先に元の表の種類と版を渡し、入力条件も照合する。確認画面を開くだけでは保存表を更新しない。古いリンクの先に別の最新表を黙って表示しない。編集保存後に戻る場合は、その保存済み編集表を表示する。

**検証**：編集表と生成表を意図的に別の内容にした一時DBで、表示対象・保存前の不変・古いリンクの拒否を確認する。

- [版を扱う処理](../roster_navigation.py)、[編集・保存](../manual_schedule.py)
- [回帰テスト](../tests/test_roster_navigation.py)：`test_return_to_creation_shows_saved_edits_instead_of_old_generated_grid`、`test_creation_step_five_opens_exact_result_as_read_only_review`
- 実際の開発記録：[4ac2651の変更](https://github.com/higakota/nurse-scheduler-demo/commit/765b91882327c73d027c992ca07d75be7b5138bd)、[8ec01f7の変更](https://github.com/higakota/nurse-scheduler-demo/commit/6513cb4a637aded55df09ad2afaeb95e90b9659f)

**学んだこと**：画面を統一するだけでなく、「どの表を確認し、どの表へ保存するか」を状態として扱う必要があった。

## 2. 検査室の人数と職種を正しく数える

**課題**：検査室に2人必要な場合、検査技師＋看護師だけを想定すると、検査技師が2人いても看護師の不足が残る。また、検査技師が必要な時間帯を看護師の不足として表示すると、依頼先の判断を誤る。

**変更**：検査技師2人の組み合わせを探索・結果検証・不足表示に反映する。診療担当医の人数、検査室の人数、担当可能な職種を区別する。看護師のみの検査対応は、明示された例外として扱う。

**検証**：検査技師2人が検査室2人分を満たすこと、不足表示も0になること、看護師2人の応援が必要な条件は拒否しないことを確認する。

- [配置と結果検証](../scheduler_engine.py)、[応援の職種](../help_limits.py)
- [回帰テスト](../tests/test_help_role_preference.py)：`test_mixed_pair_is_preferred_and_two_technicians_count_as_two_c_staff`
- 実際の開発記録：[65744f4の変更](https://github.com/higakota/nurse-scheduler-demo/commit/d2b967208afca5a83ac9fa5f15d349908744c0e5)、[8cddfb5の変更](https://github.com/higakota/nurse-scheduler-demo/commit/b4b8a39951578a5100871b1cc5f9821560532503)

**学んだこと**：合計人数が一致しても、職種や担当可能範囲が一致するとは限らない。画面の不足表示まで同じ判定を使う必要があった。

## 3. 了承出勤後の連勤を調整する

**課題**：休み希望の日を本人了承で出勤へ変えると、その日の不足が埋まっても、連勤や別の日の人数に影響する。すでに依頼済みの応援を勝手に動かすと運用できない。

**変更**：本人了承の出勤を保持し、公休日数・希望休・有給・会議・連勤を再検証する。局所的な休みの調整で解けなければ、依頼済み応援を固定した全体調整を検討し、差分を確認してから反映する。

**検証**：仮名の勤務表で、避けられる6連勤の解消、公休日数の維持、依頼済み応援の固定、変更の取り消しによる復元を確認する。

- [了承変更](../negotiated_leave.py)、[全体調整](../agreed_rebalance.py)
- [回帰テスト](../tests/test_agreed_consecutive_rest.py)：`test_full_time_rest_is_selected_to_break_run_and_keep_target`、`test_joint_adjustment_runs_during_agreement_and_can_be_fully_cancelled`
- 実際の開発記録：[02267e7の変更](https://github.com/higakota/nurse-scheduler-demo/commit/5a89f99532fd766b3e467454447cb58e59645d40)、[b6fa73cの変更](https://github.com/higakota/nurse-scheduler-demo/commit/d532fb1a45960583f4801421775a9b8fce888562)、[5a2c2beの変更](https://github.com/higakota/nurse-scheduler-demo/commit/abbf215a7151c69c98f5d20b19f181065cae5099)

**限界**：どの入力でも5連勤以内にできるという意味ではない。条件上避けられない連勤や、不足が残る場合の確認は必要。

## 4. 会議をまとめて入力する

**課題**：参加者を1人登録するたびに再表示され、カレンダーの位置が戻るため、複数人の入力を続けにくかった。

**変更**：複数人・複数日の変更をブラウザ内で保持し、最後に一括保存する。登録の版を照合し、不正なセルや重複があれば全件を保存しない。

**検証**：複数人の追加・削除の同時反映、1セルが不正な場合の保存前状態の維持、別画面から更新された後の古い一括保存の拒否を確認する。

- [一括保存](../meeting_attendance.py)、[入力画面](../static/monthly.js)
- [回帰テスト](../tests/test_meeting_attendance.py)：`MeetingBatchTest.test_multiple_people_and_removals_are_saved_together`、`test_one_invalid_cell_does_not_save_any_changes`
- 実際の開発記録：[325da74の変更](https://github.com/higakota/nurse-scheduler-demo/commit/f39e55f36d8701eaf8bf61ae3d59098d34bf4f24)、[9872accの変更](https://github.com/higakota/nurse-scheduler-demo/commit/e36b438b423929866e90ad611d07c6ff9972491b)

**学んだこと**：入力を速くする改善と、複数変更を安全に保存する仕組みを一緒に考える必要があった。

## 5. 見やすさの改善案を利用者の反応で見直す

**課題**：応援スタッフを1行へ集約する案を画面にも適用したところ、狭い日付列で氏名が読みにくくなった。

**変更**：画面では個人別表示に戻し、印刷では依頼後に決まった応援だけを集約する。事前に来られる人は別行にする。希望との比較も画面では必要なときに表示し、印刷では上下に並べる。

**検証**：画面では個人別、印刷では対象の応援だけを集約し、氏名・時間帯・職種が保持されることを確認する。

- [表示データ](../schedule_display.py)、[印刷](../templates/_manual_print.html)
- [回帰テスト](../tests/test_print_help_summary.py)：`test_groups_only_requested_helpers_and_keeps_time_and_role`、`test_editor_shows_helpers_individually_and_comparison_is_optional`
- 試行と見直しの開発記録：[3a93184の変更](https://github.com/higakota/nurse-scheduler-demo/commit/53927bf888346dd7a3a6dd6ee890028533ffac3f)、[e85757bの変更](https://github.com/higakota/nurse-scheduler-demo/commit/d910a21cb62f23a5c051dad7426c769fd826f6fe)、[2243813の変更](https://github.com/higakota/nurse-scheduler-demo/commit/c478b76cf7cbb30a724215535f07fc4406134888)

**学んだこと**：情報をまとめるだけでは読みやすくならない。画面と紙で見方が異なるため、利用者の反応から用途別に表示を変えた。

## 6. 普段使うときの保存・更新を守る

**課題**：起動の手間、入力データの消失、アプリ更新後の不具合にも対応が必要だった。

**変更**：デスクトップ起動、日ごとの開始時点・最新保存の自動バックアップ、更新版のテスト後の切り替え、勤務データを巻き戻さないアプリの版の復帰を追加した。

**検証**：バックアップ失敗時に保存を止めること、更新版テスト失敗時に切り替えないこと、版の復帰でDB内容を変えないことを一時フォルダで確認する。

- [バックアップ](../automatic_backup.py)、[更新](../runtime_tools.py)
- [回帰テスト](../tests/test_operations.py)：`test_post_is_backed_up_and_failed_backup_prevents_write`、`test_update_failed_tests_keeps_current_release`、`test_rollback_preserves_database`
- 実際の開発記録：[002524fの変更](https://github.com/higakota/nurse-scheduler-demo/commit/900c35ef5282691f97c53cb58e5c2671b37f7770)

**限界**：同じPC内のバックアップだけではPC故障に備えられない。更新用スクリプトの配布・権限・ライブラリ変更は環境に合わせた扱いが必要。公開サンプルの起動方法はREADMEの手順を使う。
