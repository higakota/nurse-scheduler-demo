import json
import re
import tempfile
import unittest
from pathlib import Path
from app import app, connect_db
from manual_schedule import diagnostics, checked_patch
import test_scheduler as fixtures

class ManualScheduleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=app.config["DATABASE"]
        app.config["DATABASE"]=str(Path(self.temp.name)/"db.sqlite3")
        self.client=app.test_client()
        self.db=connect_db()
        self.db.execute("INSERT INTO staff(id,name,role,employment,veteran) VALUES (1,'仮名看護','nurse','full',1)")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.config["DATABASE"]=self.old
        self.temp.cleanup()

    def fields(self):
        page=self.client.get("/schedule/manual?month=2026-11")
        self.assertEqual(page.status_code,200)
        text=page.get_data(as_text=True)
        return {key:re.search('name="'+key+'"[^>]*value="([^"]*)"',text).group(1)
                for key in ("csrf_token","fingerprint","revision")}

    def post(self,fields,action,patch=None):
        return self.client.post("/schedule/manual?month=2026-11",data={**fields,"action":action,
            "patch":json.dumps(patch or {}),"confirm":"yes"})

    def test_preview_save_undo_preserve_original_and_inputs(self):
        fields=self.fields()
        before=list(self.db.iterdump())
        response=self.post(fields,"preview",{"1_0":"DR"})
        self.assertEqual(response.status_code,200)
        self.assertIn("まだ保存していません",response.get_data(as_text=True))
        self.assertEqual(before,list(self.db.iterdump()))
        self.assertEqual(self.post(fields,"save",{"1_0":"DR"}).status_code,303)
        saved=json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(saved["grid"][1][0],"DR")
        self.assertFalse(self.db.execute("SELECT name FROM sqlite_master WHERE name='generated_schedules'").fetchone())
        fields=self.fields()
        response=self.post(fields,"undo")
        self.assertIn("保存前の変更確認",response.get_data(as_text=True))
        patch={str(d)+"_"+str(i):pair for d,row in enumerate(saved["history"][-1]["grid"]) for i,pair in enumerate(row)}
        self.assertEqual(self.post(fields,"save",patch).status_code,303)
        restored=json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(restored["grid"][1][0],"RR")

    def test_save_requires_preview_and_rejects_tampering(self):
        fields=self.fields()
        self.post(fields,"save",{"1_0":"DD"})
        self.assertFalse(self.db.execute("SELECT name FROM sqlite_master WHERE name='manual_schedules'").fetchone())
        self.post(fields,"preview",{"1_0":"DR"})
        response=self.post(fields,"save",{"1_0":"DD"})
        self.assertIn("変更内容を確認",response.get_data(as_text=True))
        response=self.post(fields,"preview",{"999_0":"DD"})
        self.assertIn("変更内容が正しくありません",response.get_data(as_text=True))
        self.assertEqual(self.client.post("/schedule/manual?month=2026-11").status_code,400)

    def test_concurrent_input_or_draft_changes_do_not_overwrite(self):
        fields=self.fields()
        self.post(fields,"preview",{"1_0":"DD"})
        self.db.execute("UPDATE staff SET name='仮名変更'")
        self.db.commit()
        text=self.post(fields,"save",{"1_0":"DD"}).get_data(as_text=True)
        self.assertIn("別の画面で変更",text)
        fields=self.fields()
        self.post(fields,"preview",{"1_0":"DD"})
        self.assertEqual(self.post(fields,"save",{"1_0":"DD"}).status_code,303)
        text=self.post(fields,"save",{"1_0":"RR"}).get_data(as_text=True)
        self.assertIn("別の画面で変更",text)

    def test_saved_generation_is_copied_not_overwritten(self):
        fields=self.fields()
        self.db.execute("CREATE TABLE generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        from schedule import read_snapshot
        snapshot,fp,_=read_snapshot(self.db,"2026-11")
        result=dict(days=["2026-11-02"],people=snapshot["staff"],grid=[["DD"]],input_hash=fp)
        raw=json.dumps(result)
        self.db.execute("INSERT INTO generated_schedules VALUES (?,?)",("2026-11",raw))
        self.db.commit()
        fields=self.fields()
        self.post(fields,"preview",{"1_0":"DR"})
        self.post(fields,"save",{"1_0":"DR"})
        self.assertEqual(self.db.execute("SELECT data FROM generated_schedules").fetchone()[0],raw)

    def test_draft_seed_and_backup_roundtrip_keep_manual_history(self):
        from manual_schedule import seed_draft
        from data_backup import validated_backup
        from schedule import read_snapshot
        snapshot,fp,_=read_snapshot(self.db,"2026-11")
        seed_draft(self.db,"2026-11",snapshot,fp,{"problem":{"days":["2026-11-02"],"people":snapshot["staff"]},"grid":[["DO"]]})
        self.db.commit()
        fields=self.fields()
        self.post(fields,"preview",{"1_0":"DR"})
        self.post(fields,"save",{"1_0":"DR"})
        payload=self.client.get("/backup/download").data
        clean,counts=validated_backup(payload)
        self.assertEqual(counts["manual_schedules"],1)
        self.assertEqual(counts["manual_schedule_seeds"],1)
        import sqlite3
        restored=sqlite3.connect(":memory:")
        restored.deserialize(clean)
        saved=json.loads(restored.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(saved["history"][-1]["grid"][1][0],"DO")
        restored.close()

    def test_cells_are_editable_only_before_preview(self):
        fields=self.fields()
        page=self.client.get("/schedule/manual?month=2026-11").get_data(as_text=True)
        self.assertIn('class="manual-cell"',page)
        self.assertIn('data-day="0" data-person="0"',page)
        self.assertIn('id="manual-dialog"',page)
        sheet=page.split('class="paper-schedule"',1)[1].split('class="paper-schedule-title"',1)[0]
        self.assertIn('id="manual-bulk-edit"',sheet)
        self.assertNotIn('id="manual-day"',page)
        preview=self.post(fields,"preview",{"1_0":"DR"}).get_data(as_text=True)
        self.assertNotIn('class="manual-cell"',preview)
        self.assertIn("保存前の変更確認",preview)
        self.assertIn('id="manual-change-1-0"',preview)
        self.assertEqual(preview.count('manual-preview-changed'),1)
        self.assertIn('class="manual-change-before" aria-label="変更前">休／休',preview)
        self.assertIn('class="manual-change-after" aria-label="変更後">診／休',preview)

    def test_print_uses_saved_manual_draft_and_notes_remain_unconfirmed(self):
        fields=self.fields()
        text=self.client.get("/schedule/manual?month=2026-11").get_data(as_text=True)
        self.assertNotIn('id="manual-print"',text)
        preview=self.post(fields,"preview",{"13_0":"DD"}).get_data(as_text=True)
        self.assertNotIn('id="manual-print"',preview)
        self.post(fields,"save",{"13_0":"DD"})
        before=list(self.db.iterdump())
        text=self.client.get("/schedule/manual?month=2026-11").get_data(as_text=True)
        self.assertIn('data-print-packet="manual-print"',text)
        self.assertIn('data-print-packet="manual-notes-print"',text)
        packet=text.split('id="manual-print"',1)[1].split('id="manual-notes-print"',1)[0]
        notes=text.split('id="manual-notes-print"',1)[1]
        self.assertIn("下書き・未確定",packet)
        self.assertIn("午前：診療",packet)
        self.assertNotIn('class="manual-cell"',packet)
        self.assertNotIn("下書きの不足・確認事項",packet)
        self.assertIn("下書きの不足・確認事項",notes)
        self.assertIn("未完了",notes)
        self.assertEqual(before,list(self.db.iterdump()))

    def test_resume_editing_preserves_pending_changes_without_saving(self):
        fields=self.fields()
        self.post(fields,"preview",{"13_0":"DD","14_0":"DR"})
        before=list(self.db.iterdump())
        response=self.post(fields,"edit",{"13_0":"DD","14_0":"DR","0_0":"RR"})
        text=response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        match=re.search(r'<script id="manual-data" type="application/json">(.*?)</script>',text,re.S)
        payload=json.loads(match[1])
        self.assertEqual(payload["pending"],{"13_0":"DD","14_0":"DR"})
        self.assertEqual(payload["grid"][13][0],"RR")
        self.assertEqual(before,list(self.db.iterdump()))
        self.post(fields,"preview",payload["pending"])
        self.assertEqual(self.post(fields,"save",payload["pending"]).status_code,303)
        result=json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(result["grid"][13][0],"DD")
        self.assertEqual(result["grid"][14][0],"DR")

    def test_import_latest_generation_requires_preview_and_preserves_history(self):
        fields=self.fields()
        self.post(fields,"preview",{"13_0":"DR"})
        self.post(fields,"save",{"13_0":"DR"})
        from schedule import read_snapshot
        snapshot,fp,_=read_snapshot(self.db,"2026-11")
        self.db.execute("CREATE TABLE generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        result=dict(days=[f"2026-11-{d:02}" for d in range(1,31)],people=snapshot["staff"],grid=[["RR"] for _ in range(30)],input_hash=fp,created="2026-10-20T12:00:00+00:00")
        result["grid"][13][0]="DD"
        raw=json.dumps(result)
        self.db.execute("INSERT INTO generated_schedules VALUES ('2026-11',?)",(raw,))
        self.db.commit()
        fields=self.fields()
        before=list(self.db.iterdump())
        response=self.client.post("/schedule/manual?month=2026-11",data={**fields,"action":"import","source":"generated"})
        self.assertEqual(response.status_code,200)
        self.assertIn('manual-change-13-0',response.get_data(as_text=True))
        self.assertEqual(before,list(self.db.iterdump()))
        patch={f"{d}_0":row[0] for d,row in enumerate(result["grid"])}
        self.assertEqual(self.post(fields,"save",patch).status_code,303)
        saved=json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertEqual(saved["grid"][13][0],"DD")
        self.assertEqual(saved["history"][-1]["grid"][13][0],"DR")
        self.assertEqual(self.db.execute("SELECT data FROM generated_schedules").fetchone()[0],raw)

    def test_import_stale_source_is_rejected(self):
        self.db.execute("CREATE TABLE generated_schedules(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
        from schedule import read_snapshot
        snapshot,_,_=read_snapshot(self.db,"2026-11")
        self.db.execute("INSERT INTO generated_schedules VALUES ('2026-11',?)",(json.dumps(dict(days=["2026-11-01"],people=snapshot["staff"],grid=[["DD"]],input_hash="old")),))
        self.db.commit()
        fields=self.fields()
        before=list(self.db.iterdump())
        response=self.client.post("/schedule/manual?month=2026-11",data={**fields,"action":"import","source":"generated"})
        self.assertIn("以前の条件の表",response.get_data(as_text=True))
        self.assertEqual(before,list(self.db.iterdump()))

    def test_unchanged_draft_can_be_reconfirmed_for_current_inputs(self):
        fields = self.fields()
        self.post(fields, "preview", {"1_0":"DR"})
        self.post(fields, "save", {"1_0":"DR"})
        saved = json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        count = len(saved["history"])
        saved["input_hash"] = "old-inputs"
        self.db.execute("UPDATE manual_schedules SET data=?", (json.dumps(saved),))
        self.db.commit()
        fields = self.fields()
        preview = self.post(fields, "preview", {}).get_data(as_text=True)
        self.assertIn("この変更を勤務表に反映", preview)
        self.assertEqual(self.post(fields, "save", {}).status_code, 303)
        latest = json.loads(self.db.execute("SELECT data FROM manual_schedules").fetchone()[0])
        self.assertNotEqual(latest["input_hash"], "old-inputs")
        self.assertIn("conditions_hash", latest)
        self.assertEqual(latest["grid"], saved["grid"])
        self.assertEqual(len(latest["history"]), count)

    def test_empty_month_and_invalid_month(self):
        self.db.execute("DELETE FROM staff")
        self.db.commit()
        self.assertEqual(self.client.get("/schedule/manual?month=2026-11").status_code,200)
        self.assertEqual(self.client.get("/schedule/manual?month=2026-99").status_code,400)

class ManualDiagnosticsTest(unittest.TestCase):
    def test_shortage_and_wish_conflict_are_reported(self):
        snapshot=fixtures.sample()
        grid=[["RR"]*len(snapshot["staff"]) for _ in range(28)]
        base=dict(days=[f"2026-02-{d:02}" for d in range(1,29)],people=snapshot["staff"])
        warnings,shortages=diagnostics(snapshot,base,grid)
        self.assertTrue(shortages)
        self.assertTrue(any("指定休日日数" in m for m in warnings))
        snapshot["monthly_settings"]["wishes"]["1_2026-02-02"]="am"
        grid[1][0]="DD"
        warnings,_=diagnostics(snapshot,base,grid)
        self.assertTrue(any("希望休と重なって" in m for m in warnings))

    def test_bad_patch_is_rejected(self):
        base={"days":["2026-11-01"],"people":[{"name":"仮名"}],"grid":[["RR"]]}
        for patch in ('[]','{"0_0":"XX"}','{"-1_0":"DD"}'):
            with self.assertRaises(ValueError):
                checked_patch(base,patch)
