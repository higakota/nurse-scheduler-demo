"""架空データ環境の実操作を撮影する。アプリの通常起動には不要。"""
import argparse,json,shutil,subprocess,tempfile,time,os,sqlite3
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from PIL import Image
import imageio_ffmpeg

def capture(root,base,output):
    parsed=urlparse(base)
    if parsed.hostname not in ("127.0.0.1","localhost"):
        raise ValueError("ローカルのサンプル環境だけを撮影できます。")
    output.mkdir(parents=True,exist_ok=True)
    shots=output.parent/"screenshots";shots.mkdir(exist_ok=True)
    report={"stages":[],"javascript_errors":[],"server_errors":[],"kind":"実際のブラウザ操作。対象月切替・Excel確認保存・各入力保存・仮表確認・ヘルプ入力反映を実操作。"}
    frames=[]
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as p:
        browser=p.chromium.launch(channel="msedge",headless=True)
        context=browser.new_context(viewport={"width":1440,"height":860},locale="ja-JP",record_video_dir=temp,record_video_size={"width":1440,"height":860})
        page=context.new_page();page.set_default_timeout(30000)
        page.on("pageerror",lambda error:report["javascript_errors"].append(str(error)))
        page.on("response",lambda response:report["server_errors"].append(response.status) if response.status>=500 else None)
        page.add_init_script("""(()=>{
          let cursor;
          const mount=()=>{
            if(document.getElementById("demo-mouse"))return;
            cursor=document.createElement("div");cursor.id="demo-mouse";
            cursor.style.cssText="position:fixed;left:320px;top:180px;width:32px;height:40px;pointer-events:none;z-index:2147483647;filter:drop-shadow(1px 2px 2px #0008)";
            cursor.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 40"><path d="M3 2V31L11 23L18 37L24 34L17 21H29Z" fill="white" stroke="#173d34" stroke-width="2"/></svg>';
            document.documentElement.append(cursor);
            try{const saved=JSON.parse(sessionStorage.getItem("demo-mouse-position"));if(saved){cursor.style.left=(saved.x-3)+"px";cursor.style.top=(saved.y-2)+"px";}}catch{}
            const style=document.createElement("style");style.textContent='[data-demo-target]{outline:3px solid #e5ae35!important;outline-offset:5px!important}';
            document.head.append(style);
          };
          document.addEventListener("DOMContentLoaded",mount);
          document.addEventListener("pointermove",e=>{
            if(!cursor)mount();cursor.style.left=(e.clientX-3)+"px";cursor.style.top=(e.clientY-2)+"px";
            try{sessionStorage.setItem("demo-mouse-position",JSON.stringify({x:e.clientX,y:e.clientY}));}catch{}
          },true);
          document.addEventListener("pointerdown",e=>{
            const ring=document.createElement("div");
            ring.style.cssText="position:fixed;width:54px;height:54px;border:4px solid #edab28;border-radius:50%;background:#ffcc4422;pointer-events:none;z-index:2147483646;left:"+(e.clientX-27)+"px;top:"+(e.clientY-27)+"px";
            document.documentElement.append(ring);
            ring.animate([{transform:"scale(.5)",opacity:1},{transform:"scale(1.5)",opacity:0}],{duration:1000,fill:"forwards"});
            setTimeout(()=>ring.remove(),1100);
          },true);
        })()""")
        report["saved_steps"]=[]
        position=[320,180]
        clock_start=time.monotonic()
        report["chapters"]=[]
        report["visible_cursor"]=True
        report["click_highlight"]=True
        report["capture_method"]="Playwrightのマウス入力を記録。カーソルとクリックを強調。説明時刻を記録し、編集時に画面下の専用欄へ配置する自動操作。"
        def wait(seconds):
            page.wait_for_timeout(120 if os.environ.get("CAPTURE_QUICK") else int(seconds*600))
        def go(path):
            page.goto(base+path,wait_until="networkidle")
            if not page.get_by_text("サンプル環境",exact=False).first.is_visible():
                raise ValueError("サンプル環境の表示を確認できません。")
            wait(2)
        def caption(title,detail):
            report.setdefault("captions",[]).append(dict(start=round(time.monotonic()-clock_start,2),title=title,detail=detail))
        def stage(number,title,detail,seconds=12,image=None):
            report["chapters"].append({"title":title,"seconds":round(time.monotonic()-clock_start,1)})
            caption(title,detail)
            wait(seconds)
            if image:
                path=Path(temp)/(image+".png");page.screenshot(path=str(path))
                frames.append(path)
            report["stages"].append(title)
            print("Recorded:",title,flush=True)
        def move(locator):
            locator.wait_for(state="visible")
            box=locator.bounding_box()
            if box and (box["y"]<130 or box["y"]+box["height"]>page.viewport_size["height"]-40):
                locator.evaluate("(el)=>el.scrollIntoView({behavior:'instant',block:'center',inline:'center'})")
                wait(1.5)
                box=locator.bounding_box()
            if not box:raise ValueError("操作対象の位置を取得できません。")
            target=(box["x"]+box["width"]/2,box["y"]+box["height"]/2)
            x,y=position
            steps=1 if abs(target[0]-x)+abs(target[1]-y)<4 else (3 if os.environ.get("CAPTURE_QUICK") else 32)
            for n in range(1,steps+1):
                t=n/steps;ease=t*t*(3-2*t)
                page.mouse.move(x+(target[0]-x)*ease,y+(target[1]-y)*ease)
                page.wait_for_timeout(1 if os.environ.get("CAPTURE_QUICK") else 25)
            position[:]=target
            page.locator("[data-demo-target]").evaluate_all("(items)=>items.forEach(el=>el.removeAttribute('data-demo-target'))")
            locator.evaluate("(el)=>el.setAttribute('data-demo-target','true')")
            wait(1)
        def click(locator):
            move(locator)
            navigates=locator.evaluate("(el)=>(el.tagName==='A'&&!el.getAttribute('href').startsWith('#'))||(el.tagName==='BUTTON'&&el.type==='submit')")
            if navigates:
                with page.expect_navigation(wait_until="networkidle"):
                    locator.click(delay=20 if os.environ.get("CAPTURE_QUICK") else 120)
            else:
                locator.click(delay=20 if os.environ.get("CAPTURE_QUICK") else 120)
                page.wait_for_load_state("networkidle")
            wait(2)
        def nav(label):
            click(page.locator(".side-nav a").filter(has_text=label).first)
            if not page.get_by_text("サンプル環境",exact=False).first.is_visible():
                raise ValueError("サンプル環境ではない画面への遷移を止めました。")
        def saved(label):
            marker=page.locator(".success").first
            marker.wait_for(state="visible")
            marker.evaluate("(el)=>el.scrollIntoView({block:'center'})")
            stage(5,label+"を保存しました","保存完了の表示を確認してから、次の入力へ進みます。",5)
            report["saved_steps"].append(label)
        def point(locator,title,detail,seconds=10):
            caption(title,detail);move(locator);wait(seconds)
        go("/?month=2026-10")
        stage(1,"スタッフ確認から印刷まで","対象月を選び、Excelと入力内容を保存。仮表と不足を確認し、来院OKのヘルプを登録して勤務表へ反映します。",10,"home")
        nav("スタッフ")
        for name in ("看護スタッフ01","検査スタッフ02","応援スタッフ02"):
            if page.get_by_text(name,exact=False).count()==0:raise ValueError("架空スタッフを確認できません。")
        stage(2,"はじめにスタッフを確認","サンプルは登録済みです。看護師・検査技師、常勤・非常勤、事前に来られるヘルプを分けて登録します。",10,"staff")
        nav("ホーム")
        point(page.locator("#nav-month"),"スタッフの次に対象月を選ぶ","今回は2026年11月を作ります。上の対象月を変更し、「切替」でその月を開きます。",8)
        click(page.locator("#nav-month"))
        page.locator("#nav-month").fill("2026-11");page.keyboard.press("Escape")
        click(page.locator(".topbar-month button"))
        if "month=2026-11" not in page.url:raise ValueError("対象月を切り替えられません。")
        stage(3,"2026年11月に切り替えました","ホームの「今月の入力」から、医師予定へ進みます。",6)
        click(page.locator('main a').filter(has_text="今月の入力").first)
        stage(4,"医師予定のExcelを読み込む","対象月を確認してからファイルを選びます。読んだだけでは保存されないので、最後まで進めます。",8)
        page.locator("details:has(input[type=file])").evaluate_all("(items)=>items.forEach(item=>item.open=true)")
        file_input=page.locator('input[type="file"][name="workbook"]')
        move(file_input)
        with page.expect_file_chooser() as chooser:page.mouse.click(*position)
        chooser.value.set_files(str(root/"samples/sample_requests_2026-11.xlsx"))
        click(page.locator("form[enctype] button"))
        stage(4,"対象月とシートを確認","2026年11月・11月シートを確認し、医師・休診日・会議の候補を読み取ります。",7)
        click(page.get_by_role("button",name="医師・休診日・会議の候補を読み取る",exact=True))
        page.get_by_role("heading",name="3. 確認・修正して保存").evaluate("(el)=>el.scrollIntoView({block:'start'})")
        stage(4,"読み取り候補を元のExcelと照合","午前・午後の担当医を確認します。「個別確認」の日は、その日の確認チェックも入れます。",10,"excel")
        for index,field in enumerate(page.locator('input[name^="review_"]:visible').all()):
            if not field.is_checked():
                if index<2:click(field)
                else:
                    if index==2:caption("同じ確認操作を続けます","最初の2件を操作例として示し、残りの確認チェックは短く進めています。実際の利用時は、すべての候補を照合してください。")
                    field.check()
                    page.wait_for_timeout(120)

        for key in ("replace","confirmed"):
            field=page.locator('input[name="'+key+'"]')
            if field.count():click(field)
        point(page.get_by_role("button",name="確認した医師予定を保存",exact=True),"確認した医師予定を保存","最後の保存ボタンまで押します。これで読み取り結果が、この月の医師予定として登録されます。",8)
        click(page.get_by_role("button",name="確認した医師予定を保存",exact=True))
        saved("医師予定")
        click(page.locator(".page-subnav a").filter(has_text="希望休・会議・事前ヘルプ").first)
        stage(5,"希望休・有給を入力","希望のあるスタッフと日付のマスを押します。今回は検査スタッフ02の11月9日に全日希望休を入力します。",9,"wishes")
        click(page.locator('[data-input-person="7"][data-input-day="2026-11-09"]'))
        click(page.locator('[data-grid-kind="wishes"][data-grid-period="full"]'))
        click(page.locator("#input-absence-close"))
        point(page.locator("#absence-save"),"希望休・有給をまとめて保存","マスを選んだ段階では未保存です。このボタンを押して、保存完了を確認します。",7)
        click(page.locator("#absence-save"));saved("希望休・有給")
        click(page.locator('[data-month-tab="targets"]'))
        stage(5,"休日日数・週上限を確認して保存","常勤の休日日数と、非常勤の週上限を確認します。入力後は下の保存ボタンを押します。",7,"targets")
        click(page.locator('[data-month-save] button'));saved("休日日数・週上限")
        click(page.locator('[data-month-tab="closures"]'))
        stage(5,"休診日を確認して保存","日曜・祝日などを確認し、保存します。サンプルは操作例を見やすくするため診療日を絞っています。",7,"closures")
        click(page.locator('[data-month-save] button'));saved("休診日")
        click(page.locator('[data-month-tab="meetings"]'))
        stage(5,"会議も変更後に保存する","登録済みの会議名を開き、名称を変更して保存する例です。参加者を変更した場合も、最後にまとめて保存します。",8,"meetings")
        click(page.locator('[data-meeting-edit]').first)
        title=page.locator('.meeting-editor-dialog[open] input[name="title"]')
        move(title);title.fill("サンプル研修会（確認済み）");wait(3)
        click(page.locator('.meeting-editor-dialog[open] form').first.locator('button'))
        saved("会議")
        click(page.locator('[data-month-tab="availability"]'))
        stage(5,"事前に来られるヘルプを入力","依頼前から来られる日が決まっている人を入力します。今回は応援スタッフ01の11月12日を全日で登録します。",8,"availability")
        click(page.locator('[data-advance-cell="8_2026-11-12"]'))
        click(page.locator('[data-advance-period="full"]'))
        click(page.locator("#advance-availability-save"));saved("事前ヘルプ")
        click(page.locator(".page-subnav a").filter(has_text="必要人数").first)
        stage(6,"必要人数を確認して保存","医師予定と検査室に必要な人数を確認します。入力値を確認したら、下のボタンで保存します。",8,"coverage")
        click(page.get_by_role("button",name="検査室の必要人数を保存",exact=True));saved("必要人数")
        click(page.locator(".page-subnav a").filter(has_text="前月末勤務").first)
        stage(6,"前月末勤務を確認して保存","月をまたぐ連勤の確認に使います。初回は直前6日分を入力し、前月末の勤務を保存します。",8,"history")
        click(page.get_by_role("button",name="前月末の勤務を保存",exact=True));saved("前月末勤務")
        point(page.locator(".journey-nav a").filter(has_text="不足を確認"),"手順②「不足を確認」へ進む","入力の保存が終わったら、画面上の手順バーから不足確認へ進みます。ホームへ戻る必要はありません。",7)
        click(page.locator(".journey-nav a").filter(has_text="不足を確認"))
        point(page.locator('button[name="mode"][value="advance_draft"]'),"事前ヘルプも使って仮作成","保存した入力をもとに、追加で相談する人数を確認するための仮表を作ります。",8)
        click(page.locator('button[name="mode"][value="advance_draft"]'))
        grid=page.locator(".paper-schedule").first
        if not grid.count():raise ValueError("仮表がありません。")
        grid.evaluate("(el)=>el.scrollIntoView({block:'start'})")
        stage(7,"不足確認で作った勤務表を見る","まず仮の勤務表を見ます。上段の医師予定と、自院・事前ヘルプの勤務が表示されています。",12,"draft")
        page.mouse.wheel(0,440);wait(2)
        stage(7,"表の下で不足を確認する","11月9日は検査技師が不足します。職種と午前・午後の人数を確認して、アプリ外でヘルプを相談します。",12,"draft-shortage")
        report["draft_grid_shown"]=True
        point(page.get_by_role("link",name="決まったヘルプの来院予定を登録する",exact=True),"来院が決まったら、このボタンへ","相談・依頼は電話などで行います。来られる人と日が決まったら、このボタンから登録へ進みます。",8)
        click(page.get_by_role("link",name="決まったヘルプの来院予定を登録する",exact=True))
        point(page.locator("#help-staff"),"来院OKの人を選ぶ","検査技師の応援スタッフ02を選びます。不足と予定を同じカレンダーで見ながら登録できます。",7)
        click(page.locator("#help-staff"));page.locator("#help-staff").select_option("9");page.keyboard.press("Escape")
        page.locator('[data-help-day="2026-11-09"]').evaluate("(el)=>el.scrollIntoView({block:'center'})")
        stage(8,"ヘルプ登録のカレンダーを見る","日付ごとに不足と来院予定が表示されます。11月9日に来院OKの予定を入力します。",12,"help")
        report["help_calendar_shown"]=True
        click(page.locator('[data-help-day="2026-11-09"] > summary'))
        click(page.locator('[data-help-period="full"]'))
        stage(8,"入力した来院予定はまだ未保存","11月9日の全日来院が未保存として表示されます。「登録したヘルプを反映する」で登録し、勤務表の変更確認へ進みます。",8)
        point(page.locator('button[form="help-calendar-form"][name="continue"]'),"登録したヘルプを反映する","このボタンで予定を保存し、勤務表・印刷の画面へ進みます。左メニューから探し直す必要はありません。",8)
        click(page.locator('button[form="help-calendar-form"][name="continue"]'))
        if "/schedule/manual" not in page.url:raise ValueError("勤務表の変更確認へ遷移できません。")
        report["saved_steps"].append("依頼後のヘルプ来院予定")
        stage(9,"勤務表へ反映する変更を確認","ヘルプを登録すると、保存前の変更確認が開きます。希望休・有給・配置の変更を見てから、この勤務表を保存します。",12)
        confirmation=page.locator('input[name="confirm"][value="yes"]')
        point(confirmation,"確認してから保存する","変更内容を確認したチェックを入れます。この動画は架空データなので、内容を確認してそのまま保存します。",8)
        click(confirmation)
        point(page.locator('button[name="action"][value="save"]'),"この変更を勤務表に反映","チェックを入れた後、このボタンをクリックして保存します。",7)
        click(page.locator('button[name="action"][value="save"]'))
        report["saved_steps"].append("勤務表")
        connection=sqlite3.connect((root/"instance/demo.sqlite3").resolve().as_uri()+"?mode=ro",uri=True)
        try:
            saved=json.loads(connection.execute("SELECT data FROM manual_schedules WHERE month='2026-11'").fetchone()[0])
            i=next(i for i,p in enumerate(saved["people"]) if p["id"]==9)
            if saved["grid"][saved["days"].index("2026-11-09")][i]=="RR":
                raise ValueError("登録済みの応援が勤務表に反映されていません。")
            monthly=json.loads(connection.execute("SELECT data FROM monthly_settings WHERE month='2026-11'").fetchone()[0])
            visits=json.loads(connection.execute("SELECT data FROM help_availability WHERE month='2026-11'").fetchone()[0])
            assert monthly["wishes"]["7_2026-11-09"]=="full"
            assert any(m["title"]=="サンプル研修会（確認済み）" for m in monthly["meetings"])
            assert visits["8_2026-11-12"]=="full" and visits["9_2026-11-09"]=="full"
            report["input_saves_verified"]=True
            report["requested_helper_applied"]=True
        finally:connection.close()
        stage(7,"更新した表を保存できました","登録済みの応援が配置されたことも確認しています。次は、勤務表と希望休・有給を比較します。",10)
        compare=page.locator('[data-compare-schedule]').first
        point(compare,"希望休・有給との比較を表示","このチェックをクリックすると、実際の勤務と入力した希望を上下で比較できます。",9)
        click(compare)
        page.locator(".paper-schedule").first.evaluate("(el)=>el.scrollIntoView({behavior:'smooth',block:'start'})")
        wait(2)
        stage(8,"勤務は上段、希望は下段","黄色の希望欄と勤務を見比べます。ここで変更漏れがないかを確認してから、印刷へ進めます。",15,"roster")
        page.locator(".paper-schedule").first.screenshot(path=str(shots/"roster.png"))
        page.evaluate("window.print=()=>window.dispatchEvent(new Event('beforeprint'))")
        point(page.locator('[data-print-packet="manual-print"]').first,"印刷用の表示を確認する","「勤務表だけ印刷／PDF保存」をクリックします。この動画では印刷用CSSの画面を表示します。",9)
        click(page.locator('[data-print-packet="manual-print"]').first)
        page.emulate_media(media="print");wait(2)
        page.screenshot(path=str(shots/"print.png"));wait(14)
        page.emulate_media(media="screen")
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        stage(9,"入力から印刷まで確認できました","希望と勤務を確認しながら、同じ表を更新して印刷できます。操作はすべて架空データで行っています。",14)
        report["stages"].append("印刷用表示")
        video=page.video
        context.close()
        if report["javascript_errors"] or report["server_errors"]:
            raise ValueError("撮影中にブラウザまたはサーバーのエラーが発生しました。")
        source=video.path()
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ffmpeg,"-y","-i",str(source),"-map_metadata","-1","-vf","scale=1280:-2","-c:v","libx264","-preset","veryfast","-crf","24","-pix_fmt","yuv420p","-movflags","+faststart","-an",str(output/"walkthrough.mp4")],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        report["duration_seconds"]=round(imageio_ffmpeg.count_frames_and_secs(str(output/"walkthrough.mp4"))[1],1)
        report["snapshot_count"]=len(frames)
        report["viewport"]="1440x860"
        report["caption_layout"]="映像の外の専用説明欄。アプリのボタンには重ねない。"
        report["sample_month"]="2026-11"
        (output/"capture-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        browser.close()
    print("Walkthrough captured successfully.",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--base-url",default="http://127.0.0.1:5001")
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output",type=Path,default=Path(__file__).resolve().parents[1]/"docs/demo")
    parser.add_argument("--prepare-inputs",action="store_true",help=".runtime内の撮影用コピーを架空の入力例へ初期化します")
    args=parser.parse_args()
    if args.prepare_inputs:
        from prepare_walkthrough import prepare
        prepare(args.root)
    capture(args.root.resolve(),args.base_url,args.output.resolve())
