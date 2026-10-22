"""実在のデータを参照せず、架空のサンプルを新規作成する。"""
import calendar,json,sqlite3,zipfile
from datetime import date,timedelta
from pathlib import Path
from xml.sax.saxutils import escape

MONTH="2026-11"
def sample_data():
    people=[]
    for i in range(1,6):
        people.append(dict(id=i,name=f"看護スタッフ{i:02}",role="nurse",employment="full" if i<=4 else "part",veteran=int(i in (1,2,5)),is_help=0,allowed_areas="ABC",weekly_limit_units=None if i<=4 else 8,advance_help=0))
    for i in (6,7):
        people.append(dict(id=i,name=f"検査スタッフ{i-5:02}",role="technician",employment="part",veteran=0,is_help=0,allowed_areas="C",weekly_limit_units=8,advance_help=0))
    for i in (8,9):
        people.append(dict(id=i,name=f"応援スタッフ{i-7:02}",role="nurse" if i==8 else "technician",employment="part",veteran=int(i==8),is_help=1,allowed_areas="ABC" if i==8 else "C",weekly_limit_units=8,advance_help=int(i==8)))
    doctors={}; coverage={}
    closures={f"2026-11-{n:02}":"holiday" for n in range(1,31) if n not in (2,5,9,12,16,19,26,30) and date(2026,11,n).weekday()!=6}
    for n in range(1,31):
        day=date(2026,11,n); key=day.isoformat()
        closed=day.weekday()==6 or key in closures
        doctors[key]={"am":[] if closed else ["サンプル医師A"],"pm":[] if closed or day.weekday()==4 else ["サンプル医師B"]}
        for half in ("am","pm"):
            coverage[key+"_"+half]={"c":0 if closed or (half=="pm" and day.weekday()==4) else 1,"doctors":doctors[key][half]}
    return dict(month=MONTH,staff=people,doctor_plans=doctors,coverage_settings=coverage,
        monthly_settings={"targets":{"1":"23","2":"22","3":"22","4":"22.5"},"closures":closures,"wishes":{"1_2026-11-09":"full","4_2026-11-19":"pm"},"meetings":[{"date":"2026-11-12","period":"pm","title":"サンプル研修会","participants":["2"]}],"summer_leaves":{}},
        leave_history={"leaves":{"3_2026-11-16":"full"},"history":{str(i)+"_"+(date(2026,11,1)-timedelta(days=k)).isoformat():"rest" for i in range(1,8) for k in range(1,7)}},
        help_availability={"8_2026-11-09":"full","8_2026-11-12":"full","9_2026-11-09":"full"},
        previous_closures={},weekly_work_boundaries={str(i)+"_2026-12-0"+str(n):"0" for i in range(5,8) for n in range(1,7)})
def seed_database(path):
    path=Path(path)
    if path.exists():
        return False
    from doctor_import import IMPORT_VERSION
    from staff_schema import ensure_staff_schema
    path.parent.mkdir(parents=True,exist_ok=True)
    data=sample_data()
    db=sqlite3.connect(path); db.row_factory=sqlite3.Row
    try:
        ensure_staff_schema(db)
        for person in data["staff"]:
            columns=list(person)
            db.execute("INSERT INTO staff("+",".join(columns)+") VALUES ("+",".join("?" for _ in columns)+")",[person[k] for k in columns])
        for table in ("monthly_settings","doctor_plans","coverage_settings","leave_history","help_availability","weekly_work_boundaries"):
            db.execute("CREATE TABLE "+table+"(month TEXT PRIMARY KEY,data TEXT NOT NULL)")
            db.execute("INSERT INTO "+table+" VALUES (?,?)",(MONTH,json.dumps(data[table],ensure_ascii=False)))
        raw=json.dumps(data["doctor_plans"],ensure_ascii=False)
        db.execute("CREATE TABLE doctor_plan_reviews(month TEXT PRIMARY KEY,data TEXT NOT NULL,version INTEGER NOT NULL)")
        db.execute("INSERT INTO doctor_plan_reviews VALUES (?,?,?)",(MONTH,raw,IMPORT_VERSION))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return True

def make_excel(path):
    ns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rows={1:[],4:[],6:[],7:[],8:[],9:[]}
    def column(n):
        result=""
        while n:
            n,r=divmod(n-1,26);result=chr(65+r)+result
        return result
    def cell(ref,text):
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'
    rows[1].append(cell("A1","架空のサンプル：実在の施設・職員とは関係ありません"))
    data=sample_data()
    for n in range(1,31):
        day=date(2026,11,n); col=column(n+2); key=day.isoformat()
        rows[4].append(f'<c r="{col}4"><v>{(day-date(1899,12,30)).days}</v></c>')
        plan=data["doctor_plans"][key]
        text=" / ".join(plan["am"])+"　　　"+" / ".join(plan["pm"]) if plan["am"] else ""
        rows[6].append(cell(col+"6",text))
        if n==12: rows[7].append(cell(col+"7","サンプル研修会"))
    for row,i in ((8,1),(9,2)):
        rows[row].append(cell("A"+str(row),f"看護スタッフ{i:02}"))
    worksheet='<worksheet xmlns="'+ns+'"><sheetData>'+"".join(f'<row r="{r}">{"".join(cells)}</row>' for r,cells in rows.items())+'</sheetData></worksheet>'
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",'<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="11月" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",worksheet)
if __name__=="__main__":
    root=Path(__file__).resolve().parent
    seed_database(root/"instance/demo.sqlite3")
    make_excel(root/"samples/sample_requests_2026-11.xlsx")
    print("架空のデモデータを準備しました。")
