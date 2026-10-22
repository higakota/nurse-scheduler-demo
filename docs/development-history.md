# 開発履歴

2026年10月16日〜22日に記録された、実際の開発67コミットを時系列で残しています。[development-historyブランチ](https://github.com/higakota/nurse-scheduler-demo/commits/development-history/)からも変更内容を確認できます。

## 履歴の扱い

- 元の非公開リポジトリに実在するコミットを、1件ずつ同じ日付・順序で再構成した。
- 公開する過去のコード全542種類を検査し、既知の氏名・施設名・PC利用者名を架空の表記へ置き換えた。
- 元のExcel・DB・バックアップ・画像・内部仕様書は履歴にも含めない。
- 氏名・非公開資料の除外により、コミットIDと一部の差分は原本とは異なる。内部文書だけを変更したコミットは公開コードの差分がない場合がある。
- 原本の履歴とデータは非公開のまま保持した。公開版mainの現在のファイルを維持して、匿名化履歴を別ブランチから統合した。
- 公開版の新しい改善は、その後のmainの通常のコミットとして記録する。

コミットの分割や日付の作り直しで開発量を演出したものではありません。元から存在した履歴を公開できる範囲で保存した記録です。公開版の初回コミットにはこの履歴がなく、後から個人情報を除外して追加しています。

## 時系列

| 日付 | 変更内容 | 匿名化した変更 |
|---|---|---|
| 2026-10-16 | Initial commit | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/5a214d33d6f51d22b87f85958b47051f7c9f42c5) |
| 2026-10-16 | Flaskアプリの開発環境を準備 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/a8c0b7f1d5ac1ec843fea2910c376237cace5ae6) |
| 2026-10-16 | 開発手順と開発方針を記載 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/0588f375964164da06a03943446c42255d378dc0) |
| 2026-10-17 | 勤務表作成の要件を整理 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/6dfa4dfca74bf85e5efedb5c8c88a3f2e07eeebc) |
| 2026-10-18 | docs: 確認済み勤務条件とExcel取込案を仕様書に反映 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/9520d1b0ba40393a9a6dd1516fc7d0e09aa1e7aa) |
| 2026-10-18 | docs: 有給と連勤および前月勤務の引継ぎ条件を確定 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/18cf1a1afaf9491967636b10f3b7904bae001c9e) |
| 2026-10-18 | feat: スタッフ設定画面とローカル保存を追加 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/c82ed4aef263c415f19dbecb6bf6cd1618f4bc09) |
| 2026-10-18 | feat: 月別入力と希望休・会議の確認表示を追加 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/9092a6e723077cdb1d5fd69d38fa7293969aeaa8) |
| 2026-10-19 | feat: 医師予定のExcel取込と確認・編集機能を追加 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/8b3305e9b39341e4757b1f3327a9b1f94619279a) |
| 2026-10-19 | feat: 診療の最低必要人数と検査室の一括設定を追加 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/efe41b89c18148f3c333b01ae84ea31365ff223a) |
| 2026-10-19 | feat: 有給カレンダーの一括保存と前月末勤務入力を追加 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/0c65cecaaf993374048541cc8c331a73191ba482) |
| 2026-10-19 | feat: 勤務表作成を中心にホームと入力画面のUIを整理 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/b67dea3ad8090c3c201cb4ed9379904c10567ee4) |
| 2026-10-20 | feat: 勤務表作成・手動編集・ヘルプ管理と画面操作を整備 | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/9e95b845b327bea0fd298265696e6cdf40330c6d) |
| 2026-10-21 | feat: clarify scheduling workflow and preserve agreed attendance edits | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/ebbca7b1e2efbf05d67d1c515f7049b58761e640) |
| 2026-10-21 | ui: simplify home status and monthly input navigation | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/d76becd686d0cfeeb1fb4cc7a3c936cd98a2bcd8) |
| 2026-10-21 | feat: edit monthly requests in a grid and infer Excel meeting dates | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/14292ada695b4955197babc2361f03b6093ccff5) |
| 2026-10-21 | ui: simplify meeting grid and collapse doctor details | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/b01e98453f87c9e3458a26a344712bebb7557cbe) |
| 2026-10-21 | feat: edit meeting attendance from staff calendar cells | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/8891b097dbf3aea4dc47cfe4f7ab751753eaefb0) |
| 2026-10-21 | ui: show full meeting titles within scrollable date columns | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/635ed442f7603fe182f3eb4c99857498dca113b3) |
| 2026-10-21 | ui: fit absence calendar with doctors and no meeting row | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/415c549aa815fb6f5eabd563b63e2151e00dc263) |
| 2026-10-21 | ui: polish calendar inputs and keyboard navigation | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/496ccc133ef3ee9b4d279ee4179e7fed73f4df3f) |
| 2026-10-21 | ui: remove distracting calendar column outlines | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/b7de47aa8328ac22f60a83860bd1e3b9f1e71410) |
| 2026-10-21 | fix: avoid preventable six-day runs after agreed work changes | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/5a89f99532fd766b3e467454447cb58e59645d40) |
| 2026-10-21 | feat: rebalance own staff with approved help across the month | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/8f21cbd28e79ddd9bc96fd048118db9fe519da80) |
| 2026-10-21 | feat: include advance-approved helpers in initial planning | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/6437ac6284a81a58f7ebc5a80ae2268b904d0879) |
| 2026-10-21 | feat: enter advance helper availability in monthly inputs | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/16baf42444f9f483a82bc5c371495f25e01fa4cb) |
| 2026-10-21 | ui: keep advance helpers in monthly inputs only | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/317a3f67720acc3cdb883524f9fb6dba113cf775) |
| 2026-10-21 | ui: use staff-by-date grid for advance helper availability | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/1e4835866555826fb1d31ae155fb2ddac658e51c) |
| 2026-10-21 | fix: expand advance availability grid to available width | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/171773c2ad6e3e48aad11597856dce122785d3d3) |
| 2026-10-21 | ui: fit advance helper calendar without horizontal scrolling | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/f45b29c2b7d916dfc49c37b41433cb2c0c81893c) |
| 2026-10-21 | ui: show one shortage planning action based on advance helpers | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/a2715cfa6df2cdaa02f7d2f4d93915418c6f88e6) |
| 2026-10-21 | fix: prioritize reducing nurse shortages in consultation drafts | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/ef1fe8859a2fa85c7a5b63618c5d06472772ca61) |
| 2026-10-21 | feat: allow helper-inclusive drafts with unresolved shortages | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/80fd2b92a5ef0d47f64ec2b025a235149a1f722f) |
| 2026-10-21 | fix: use latest shortage roster for agreed leave changes | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/303a7352d69c7ec1ed640462cbae03797c9e8c3e) |
| 2026-10-21 | fix: preserve unresolved six-day runs in fixed helper drafts | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/28d49d05afadf7fbc81d16025a36ccb41504f096) |
| 2026-10-21 | feat: preview global rebalancing for unresolved six-day runs | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/a230f9a047954f490b4675c71724980379933461) |
| 2026-10-21 | fix: preserve requested helper shifts during global rebalancing | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/d532fb1a45960583f4801421775a9b8fce888562) |
| 2026-10-21 | fix: require external technicians for each uncovered clinical half-day | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/166498af8c71967fd63e5f26085e4ccdcf66eaca) |
| 2026-10-21 | fix: show helper-inclusive draft when completion remains blocked | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/403043ee7c489216975dd0b58f0b40beccf2d6c4) |
| 2026-10-21 | fix: automatically rebalance avoidable six-day runs after agreed work | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/abbf215a7151c69c98f5d20b19f181065cae5099) |
| 2026-10-21 | ui: open updated monthly roster after agreed changes | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/b275997598b0f17958959e301b241842814c45ef) |
| 2026-10-21 | ui: remove redundant global rebalance action | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/1a3d478e06885ca6eb5afb9c67d3a155646f9010) |
| 2026-10-21 | ui: guide scheduling through planning help registration and adjustment | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/e066e1dde8aa4d80194f91eab8cdbdfc5fc28969) |
| 2026-10-21 | ui: simplify home dashboard around next action and workspace links | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/9f335f63d967dccec6846e7c4bba7ec5ce66ccfc) |
| 2026-10-21 | ui: reduce home to essential actions | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/cd977170f0d12d45e42b6e6dce158ff82e0b6328) |
| 2026-10-22 | fix: consider second technician for laboratory staffing and help demand | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/d2b967208afca5a83ac9fa5f15d349908744c0e5) |
| 2026-10-22 | fix: show technician alternatives in helper consultation calendar | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/b4b8a39951578a5100871b1cc5f9821560532503) |
| 2026-10-22 | feat: support summer leave outreach and stable roster updates | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/77b9b244e88537de741e9495c0bce17e9c50f035) |
| 2026-10-22 | ui: save meeting attendance changes in one batch | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/f39e55f36d8701eaf8bf61ae3d59098d34bf4f24) |
| 2026-10-22 | ui: replace redundant meeting list with calendar editing | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/e36b438b423929866e90ad611d07c6ff9972491b) |
| 2026-10-22 | ui: align paid leave candidates by date with compact name buttons | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/d3647cd201cfd749a185b0a46804c3fbc5b6cdba) |
| 2026-10-22 | fix: apply candidate leave to the selected roster after reviewing differences | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/4594a9663cfa545c568c7ecaca5b25f9a273ae69) |
| 2026-10-22 | fix: keep roster versions consistent across navigation and editing | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/765b91882327c73d027c992ca07d75be7b5138bd) |
| 2026-10-22 | fix: show paid leave candidates across editing and review states | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/bdd440a24450a460fbc4b7007196d64fc89b4e16) |
| 2026-10-22 | Unify helper reflection editing and printing in roster workspace | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/6513cb4a637aded55df09ad2afaeb95e90b9659f) |
| 2026-10-22 | Simplify roster updates into one reviewed action | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/b3cc5c081b6baa5c6fe78464cda7d9ec01fcf2e3) |
| 2026-10-22 | Fix helper shortage recounting and rebalance updates before returning deficits | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/d9c3c1d803b553d9de2f11250a6b1004844b3dbc) |
| 2026-10-22 | Fix half-paid leave extension and preserve stable partial rosters | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/917573e45067eccf2eacbf4075b9a4f125917f2d) |
| 2026-10-22 | Automatically preview updated roster after registering helper visits | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/23e2945e1e96ddb6957f7c110c61a9a4a313af96) |
| 2026-10-22 | Improve color roster printing and group requested helpers by day | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/01217269f502cdd62e2af208f9d1b718a800ec02) |
| 2026-10-22 | Show requested leave below actual duties and mark agreed attendance red | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/fe87ab5bb449213b2302b39433f507ec98b414e1) |
| 2026-10-22 | Group helpers in roster editor and keep on-screen leave comparison optional | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/53927bf888346dd7a3a6dd6ee890028533ffac3f) |
| 2026-10-22 | Make grouped helper names compact and hide idle add controls | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/d910a21cb62f23a5c051dad7426c769fd826f6fe) |
| 2026-10-22 | Restore individual helper rows on screen while keeping grouped printing | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/c478b76cf7cbb30a724215535f07fc4406134888) |
| 2026-10-22 | Polish shared UI and align home workflow with roster actions | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/db228d25732cf991c8e76b13744520879b197f76) |
| 2026-10-22 | Add saved-roster carryover and everyday operation safeguards | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/900c35ef5282691f97c53cb58e5c2671b37f7770) |
| 2026-10-22 | Add calendar app icon for desktop shortcut | [差分](https://github.com/higakota/nurse-scheduler-demo/commit/2434fc6185d0851fc7c2808a76147281cd6c7059) |
