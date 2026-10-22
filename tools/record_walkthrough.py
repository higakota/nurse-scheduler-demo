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
    report={"stages":[],"javascript_errors":[],"server_errors":[],"kind":"実際のブラウザ操作。サンプルExcelの読取結果は確認まで。保存済みの架空予定で作成。"}
    frames=[]
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as p:
        browser=p.chromium.launch(channel="msedge",headless=True)
        context=browser.new_context(viewport={"width":1440,"height":1000},locale="ja-JP",record_video_dir=temp,record_video_size={"width":1440,"height":1000})
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
        position=[320,180]
        clock_start=time.monotonic()
        report["chapters"]=[]
        report["visible_cursor"]=True
        report["click_highlight"]=True
        report["capture_method"]="Playwrightのマウス入力を記録。カーソルとクリック強調、説明字幕を重ねた自動操作。"
        def wait(seconds):
            page.wait_for_timeout(120 if os.environ.get("CAPTURE_QUICK") else int(seconds*800))
        def go(path):
            page.goto(base+path,wait_until="networkidle")
            if not page.get_by_text("サンプル環境",exact=False).first.is_visible():
                raise ValueError("サンプル環境の表示を確認できません。")
            wait(2)
        def caption(title,detail):
            page.evaluate("""([title,detail])=>{
              let box=document.getElementById("recording-caption");
              if(!box){box=document.createElement("div");box.id="recording-caption";document.body.append(box);}
              box.style.cssText="position:fixed;bottom:18px;left:232px;right:24px;z-index:2147483645;background:#153e35f5;color:white;padding:16px 22px;border-radius:14px;box-shadow:0 4px 20px #0002;pointer-events:none;font-family:Yu Gothic,Meiryo,sans-serif";
              box.replaceChildren();
              const heading=document.createElement("strong");heading.textContent=title;heading.style.cssText="display:block;font-size:24px;line-height:1.5";
              const text=document.createElement("span");text.textContent=detail;text.style.cssText="display:block;font-size:20px;line-height:1.75";
              box.append(heading,text);
            }""",[title,detail])
        def stage(number,title,detail,seconds=12,image=None):
            report["chapters"].append({"title":title,"seconds":round(time.monotonic()-clock_start,1)})
            caption(str(number).zfill(2)+"  "+title,detail)
            wait(seconds)
            if image:
                path=Path(temp)/(image+".png");page.screenshot(path=str(path))
                frames.append(path)
            report["stages"].append(title)
            print("Recorded:",title,flush=True)
        def move(locator):
            locator.wait_for(state="visible")
            box=locator.bounding_box()
            if box and (box["y"]<130 or box["y"]+box["height"]>page.viewport_size["height"]-190):
                locator.evaluate("(el)=>el.scrollIntoView({behavior:'smooth',block:'center',inline:'center'})")
                wait(1.5)
                box=locator.bounding_box()
            if not box:raise ValueError("操作対象の位置を取得できません。")
            target=(box["x"]+box["width"]/2,box["y"]+box["height"]/2)
            x,y=position
            steps=1 if abs(target[0]-x)+abs(target[1]-y)<4 else (3 if os.environ.get("CAPTURE_QUICK") else 45)
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
            navigates=locator.evaluate("(el)=>el.tagName==='A'||(el.tagName==='BUTTON'&&el.type==='submit')")
            if navigates:
                with page.expect_navigation(wait_until="networkidle"):
                    page.mouse.down();wait(.18);page.mouse.up()
            else:
                page.mouse.down();wait(.18);page.mouse.up()
                page.wait_for_load_state("networkidle")
            wait(2)
        def nav(label):
            click(page.locator(".side-nav a").filter(has_text=label).first)
            if not page.get_by_text("サンプル環境",exact=False).first.is_visible():
                raise ValueError("サンプル環境ではない画面への遷移を止めました。")
        def point(locator,title,detail,seconds=10):
            caption(title,detail);move(locator);wait(seconds)
        go("/?month=2026-11")
        stage(1,"この動画で見る流れ","希望・医師予定を確認し、仮作成します。不足を応援で埋め、保存・比較・印刷まで、マウス操作で進めます。",14,"home")
        point(page.locator(".side-nav a").filter(has_text="スタッフ").first,"まず、登録済みのスタッフを確認","左の「スタッフ」をクリックします。黄色い枠が、これから操作する場所です。",7)
        nav("スタッフ")
        for name in ("看護スタッフ01","検査スタッフ02","応援スタッフ02"):
            if page.get_by_text(name,exact=False).count()==0:raise ValueError("架空のスタッフ構成を確認できません。")
        stage(2,"職種と勤務条件を分けて管理","看護師・検査技師、常勤・非常勤、応援を区別しています。この動画で表示する情報はすべて架空です。",13,"staff")
        point(page.locator(".side-nav a").filter(has_text="今月の入力").first,"次に、今月の入力を確認","「今月の入力」をクリックします。希望休・有給・会議などを月ごとに確認する画面です。",7)
        nav("今月の入力")
        stage(3,"入力した希望を確認する","サンプルでは11月9日に自院の検査技師2人が休みを希望しています。この日を応援で補う流れを見ていきます。",14)
        caption("医師予定のExcel取込へ","上の「医師予定」をクリックします。")
        click(page.locator(".page-subnav a").filter(has_text="医師予定").first)
        stage(4,"サンプルExcelを選択する","日付は4行目、医師は6行目の形式です。ここでは架空のサンプルファイルを選びます。",11)
        page.locator("details:has(input[type=file])").evaluate_all("(items)=>items.forEach(item=>item.open=true)")
        file_input=page.locator('input[type="file"][name="workbook"]')
        move(file_input)
        with page.expect_file_chooser() as chooser:
            page.mouse.click(*position)
        chooser.value.set_files(str(root/"samples/sample_requests_2026-11.xlsx"))
        wait(3)
        point(page.locator("form[enctype] button"),"ファイル名を確認して読み込む","選択したファイル名を確認します。「このExcelを読み込む」をクリックします。",8)
        click(page.locator("form[enctype] button"))
        stage(4,"対象月とシートを確認する","対象は2026年11月です。シートも「11月」になっていることを確認し、読み取りへ進みます。",11)
        point(page.get_by_role("button",name="医師・休診日・会議の候補を読み取る",exact=True),"読み取り結果は、すぐには保存しません","このボタンで候補を読み取り、次の画面で午前・午後の担当医を確認します。",7)
        click(page.get_by_role("button",name="医師・休診日・会議の候補を読み取る",exact=True))
        page.get_by_role("heading",name="3. 確認・修正して保存").evaluate("(el)=>el.scrollIntoView({behavior:'smooth',block:'start'})")
        wait(2)
        stage(4,"読み取り候補を確認する","午前・午後を元のExcelと照合してから保存する仕組みです。今回は候補を保存せず、登録済みの架空予定で作成します。",16,"excel")
        caption("ホームから不足確認へ進む","左の「ホーム」に戻り、「不足確認・作成」を開きます。")
        nav("ホーム")
        click(page.locator('main a[href*="/schedule"]').filter(has_text="不足確認").first)
        point(page.locator('button[name="mode"][value="advance_draft"]'),"事前に来られる人も含めて仮作成","まだ追加の応援を依頼する前の表です。このボタンで、登録した条件から仮配置を作ります。",11)
        click(page.locator('button[name="mode"][value="advance_draft"]'))
        if page.locator(".paper-schedule").count()==0:raise ValueError("仮作成の表が表示されません。")
        stage(5,"仮表の不足を確認する","11月9日は検査技師が不足します。足りない職種・時間帯を見て、ほかの施設へ相談します。相談はアプリ外で行います。",15,"draft")
        point(page.locator(".side-nav a").filter(has_text="ヘルプ依頼").first,"来院予定を確認する","相談後、実際に来られることが決まった応援を登録する画面へ進みます。",7)
        nav("ヘルプ依頼")
        stage(6,"来院OKの予定を確認する","サンプルでは「応援スタッフ02」の11月9日の全日来院を登録済みです。この予定を、次に勤務表へ反映します。",15,"help")
        point(page.locator(".side-nav a").filter(has_text="勤務表").first,"同じ勤務表で更新する","左の「勤務表」へ進みます。登録した予定を反映した変更案を確認します。",7)
        nav("勤務表")
        point(page.locator('button[name="action"][value="update_roster"]'),"最新の入力・応援で更新","ボタンを押すと、保存前の変更確認が開きます。ここではまだ勤務表は保存されません。",10)
        click(page.locator('button[name="action"][value="update_roster"]'))
        stage(7,"保存する前に変更箇所を確認する","変更前と変更後を確認します。希望・有給などの確認事項も見てから、保存へ進みます。",14)
        confirmation=page.locator('input[name="confirm"][value="yes"]')
        point(confirmation,"確認してから保存する","変更内容を確認したチェックを入れます。この動画は架空データなので、内容を確認してそのまま保存します。",8)
        click(confirmation)
        point(page.locator('button[name="action"][value="save"]'),"この変更を勤務表に反映","チェックを入れた後、このボタンをクリックして保存します。",7)
        click(page.locator('button[name="action"][value="save"]'))
        connection=sqlite3.connect((root/"instance/demo.sqlite3").resolve().as_uri()+"?mode=ro",uri=True)
        try:
            saved=json.loads(connection.execute("SELECT data FROM manual_schedules WHERE month='2026-11'").fetchone()[0])
            i=next(i for i,p in enumerate(saved["people"]) if p["id"]==9)
            if saved["grid"][saved["days"].index("2026-11-09")][i]=="RR":
                raise ValueError("登録済みの応援が勤務表に反映されていません。")
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
        report["viewport"]="1440x1000"
        report["sample_month"]="2026-11"
        (output/"capture-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        browser.close()
    print("Walkthrough captured successfully.",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--base-url",default="http://127.0.0.1:5001")
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output",type=Path,default=Path(__file__).resolve().parents[1]/"docs/demo")
    args=parser.parse_args()
    capture(args.root.resolve(),args.base_url,args.output.resolve())
