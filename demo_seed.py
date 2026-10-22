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
    data=sample_data()
    rows={}
    def col(n):
        out=""
        while n:
            n,r=divmod(n-1,26);out=chr(65+r)+out
        return out
    def cell(ref,text,style=0):
        return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'
    def add(row,text):rows.setdefault(row,[]).append(text)
    add(1,cell("A1","勤務希望・医師予定サンプル｜2026年11月",1))
    add(2,cell("A2","架空データの入力見本です。勤務欄は空欄、希望は下段。会議・休診日の反映内容はアプリで確認してください。",2))
    add(4,cell("A4","日付",1));add(6,cell("A6","医師予定\n左：午前／右：午後",1));add(7,cell("A7","会議・研修",1))
    for n in range(1,31):
        day=date(2026,11,n); c=col(n+2); key=day.isoformat()
        add(4,f'<c r="{c}4" s="3"><v>{(day-date(1899,12,30)).days}</v></c>')
        add(5,cell(c+"5","月火水木金土日"[day.weekday()],1))
        plan=data["doctor_plans"][key]
        text=" / ".join(plan["am"])+"　　　"+" / ".join(plan["pm"]) if plan["am"] else ""
        add(6,cell(c+"6",text,4))
        add(7,cell(c+"7","サンプル研修会" if n==12 else "",4))
    merges=["A1:AF1","A2:AF2","A4:B5","A6:B6","A7:B7"]
    for index,person in enumerate(data["staff"]):
        r=8+index*2
        add(r,cell("A"+str(r),str(person["id"]),4))
        add(r,cell("B"+str(r),person["name"],4))
        merges.extend([f"A{r}:A{r+1}",f"B{r}:B{r+1}"])
        for n in range(1,31):
            key=str(person["id"])+f"_2026-11-{n:02}"
            wish=data["monthly_settings"]["wishes"].get(key)
            paid=data["leave_history"]["leaves"].get(key)
            text={"full":"休","am":"休／—","pm":"—／休"}.get(wish,"")
            if paid:text={"full":"有休","am":"有休／—","pm":"—／有休"}[paid]
            add(r,cell(col(n+2)+str(r),"",4))
            add(r+1,cell(col(n+2)+str(r+1),text,5 if text else 4))
    add(27,cell("A27","上段：勤務（入力例では空欄）／下段：希望休・有給。日付・職員・会議はすべて架空です。",2))
    merges.append("A27:AF27")
    worksheet='<worksheet xmlns="'+ns+'"><sheetViews><sheetView workbookViewId="0"><pane xSplit="2" ySplit="7" topLeftCell="C8" activePane="bottomRight" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="1" width="5" customWidth="1"/><col min="2" max="2" width="24" customWidth="1"/><col min="3" max="32" width="11" customWidth="1"/></cols><sheetData>'
    for r,cells in sorted(rows.items()):
        height=58 if r==6 else 34 if r in (1,2,7) else 24
        worksheet+=f'<row r="{r}" ht="{height}" customHeight="1">{"".join(cells)}</row>'
    worksheet+='</sheetData><mergeCells count="'+str(len(merges))+'">'+"".join(f'<mergeCell ref="{value}"/>' for value in merges)+'</mergeCells><pageSetup orientation="landscape" paperSize="9"/></worksheet>'
    styles='<styleSheet xmlns="'+ns+'"><numFmts count="1"><numFmt numFmtId="164" formatCode="d"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Yu Gothic"/><color rgb="FF23433C"/></font><font><b/><sz val="11"/><name val="Yu Gothic"/><color rgb="FF206C5B"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE5F1EB"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFF2B7"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFD3DFDA"/></left><right style="thin"><color rgb="FFD3DFDA"/></right><top style="thin"><color rgb="FFD3DFDA"/></top><bottom style="thin"><color rgb="FFD3DFDA"/></bottom><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="164" fontId="1" fillId="2" borderId="1" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="3" borderId="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        z.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",'<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="11月" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",worksheet)
        z.writestr("xl/styles.xml",styles)

if __name__=="__main__":
    root=Path(__file__).resolve().parent
    seed_database(root/"instance/demo.sqlite3")
    make_excel(root/"samples/sample_requests_2026-11.xlsx")
    print("架空のデモデータを準備しました。")
