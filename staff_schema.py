"""既存スタッフのID・値を保持し、非常勤検査技師と週上限を追加する。"""
SCHEMA = """(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('nurse','technician')),
    employment TEXT NOT NULL CHECK(employment IN ('full','part','')),
    veteran INTEGER NOT NULL CHECK(veteran IN (0,1)),
    is_help INTEGER NOT NULL DEFAULT 0 CHECK(is_help IN (0,1)),
    allowed_areas TEXT NOT NULL DEFAULT 'ABC',
    weekly_limit_units INTEGER CHECK(weekly_limit_units IS NULL OR (typeof(weekly_limit_units)='integer' AND weekly_limit_units BETWEEN 0 AND 14)),
    CHECK((role='nurse' AND employment IN ('full','part')) OR (role='technician' AND employment IN ('','full','part') AND veteran=0))
)"""


def ensure_staff_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS staff " + SCHEMA)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(staff)")}
    if "weekly_limit_units" not in columns:
        db.execute("BEGIN IMMEDIATE")
        try:
            # 同時接続が移行を終えていた場合は再作成しない。
            columns = {row["name"] for row in db.execute("PRAGMA table_info(staff)")}
            if "weekly_limit_units" not in columns:
                known = {"id","name","role","employment","veteran","is_help","allowed_areas"}
                if columns - known:
                    raise RuntimeError("スタッフ表に未対応の追加項目があります。データを維持するため移行を中止しました。")
                definitions = [row["sql"] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='staff' AND type IN ('index','trigger') AND sql IS NOT NULL")]
                db.execute("CREATE TABLE staff_weekly_upgrade " + SCHEMA)
                is_help = "is_help" if "is_help" in columns else "0"
                areas = "allowed_areas" if "allowed_areas" in columns else "CASE WHEN role='technician' THEN 'C' ELSE 'ABC' END"
                db.execute("INSERT INTO staff_weekly_upgrade(id,name,role,employment,veteran,is_help,allowed_areas) SELECT id,name,role,employment,veteran," + is_help + "," + areas + " FROM staff")
                db.execute("DROP TABLE staff")
                db.execute("ALTER TABLE staff_weekly_upgrade RENAME TO staff")
                for definition in definitions:
                    db.execute(definition)
            db.commit()
        except Exception:
            db.rollback()
            raise
    if db.execute("SELECT 1 FROM staff WHERE is_help=1 AND role='nurse' AND allowed_areas!='ABC' LIMIT 1").fetchone():
        db.execute("UPDATE staff SET allowed_areas='ABC' WHERE is_help=1 AND role='nurse' AND allowed_areas!='ABC'")
        db.commit()
