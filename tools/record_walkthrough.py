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
        def go(path):
            page.goto(base+path,wait_until="networkidle")
            if not page.get_by_text("サンプル環境",exact=False).first.is_visible():
                raise ValueError("サンプル環境の表示を確認できません。")
        def caption(title,detail):
            page.evaluate("""([title,detail])=>{
              let box=document.getElementById("recording-caption");
              if(!box){box=document.createElement("div");box.id="recording-caption";document.body.append(box);}
              box.style.cssText="position:fixed;bottom:18px;left:232px;right:24px;z-index:2147483647;background:#153e35f5;color:white;padding:16px 22px;border-radius:14px;box-shadow:0 4px 20px #0002;pointer-events:none;font-family:Yu Gothic,Meiryo,sans-serif";
              box.replaceChildren();
              const heading=document.createElement("strong");heading.textContent=title;heading.style.cssText="display:block;font-size:24px;line-height:1.5";
              const text=document.createElement("span");text.textContent=detail;text.style.cssText="display:block;font-size:17px;line-height:1.7";
              box.append(heading,text);
            }""",[title,detail])
        def stage(number,title,detail,seconds=4,image=None):
            caption(str(number).zfill(2)+"  "+title,detail)
            page.wait_for_timeout(200 if os.environ.get("CAPTURE_QUICK") else seconds*1000)
            if image:
                path=Path(temp)/(image+".png");page.screenshot(path=str(path))
                frames.append(path)
            report["stages"].append(title)
            print("Recorded:",title,flush=True)
        def click(locator):
            locator.scroll_into_view_if_needed()
            box=locator.bounding_box()
            if box:page.mouse.move(box["x"]+box["width"]/2,box["y"]+box["height"]/2,steps=8)
            page.wait_for_timeout(450);locator.click()
            page.wait_for_load_state("networkidle")
        go("/?month=2026-11")
        stage(1,"勤務表の準備から調整まで","架空データで、入力 → 作成 → 変更確認 → 比較・印刷を試します。",5,"home")
        go("/staff?month=2026-11")
        for name in ("看護スタッフ01","検査スタッフ02","応援スタッフ02"):
            if page.get_by_text(name,exact=False).count()==0:raise ValueError("架空のスタッフ構成を確認できません。")
        stage(2,"職種・勤務条件を確認","常勤・非常勤、ベテラン、応援スタッフを区別して管理します。",5,"staff")
        go("/monthly?month=2026-11")
        stage(3,"希望休・有給・会議を入力","月単位の入力をカレンダーで確認します。実在する情報は使っていません。",5)
        go("/doctors?month=2026-11")
        page.locator("details:has(input[type=file])").evaluate_all("(items)=>items.forEach(item=>item.open=true)")
        page.locator('input[type="file"][name="workbook"]').set_input_files(str(root/"samples/sample_requests_2026-11.xlsx"))
        stage(4,"Excelから医師予定を読み取る","新規作成したサンプルExcelを選択します。",3)
        click(page.get_by_role("button",name="このExcelを読み込む",exact=True))
        page.locator('select[name="sheet"]').select_option("11月")
        stage(4,"対象シートを選ぶ","日付と対象月を照合し、読み取り対象を指定します。",3)
        click(page.get_by_role("button",name="医師・休診日・会議の候補を読み取る",exact=True))
        page.get_by_role("heading",name="3. 確認・修正して保存").scroll_into_view_if_needed()
        stage(4,"読み取り結果は保存前に確認","候補を確認する画面です。今回は保存せず、登録済みの架空予定で作成します。",6,"excel")
        go("/schedule?month=2026-11&phase=plan")
        caption("05  事前に来られる応援も含めて仮作成","希望・勤務条件から月間の配置を作成します。")
        click(page.locator('button[name="mode"][value="advance_draft"]'))
        if page.locator(".paper-schedule").count()==0:
            raise ValueError("仮作成の勤務表が表示されません。")
        stage(5,"仮作成の結果を確認","不足する日・時間帯・職種を確認してから、追加の応援を相談します。",5,"draft")
        go("/help?month=2026-11")
        stage(6,"来院が決まった応援を確認","相談はアプリ外で行い、実際に来られる予定を登録します。",5,"help")
        go("/schedule/manual?month=2026-11")
        caption("07  最新の入力・応援を勤務表に反映","同じ勤務表で、変更内容を確認してから保存します。")
        click(page.locator('button[name="action"][value="update_roster"]'))
        stage(7,"変更内容を確認して反映","保存する前に、対象の勤務表と変更箇所を確認します。",5)
        confirmation=page.locator('input[name="confirm"][value="yes"]')
        if confirmation.count()==0:raise ValueError("反映確認のチェックが見つかりません。")
        confirmation.check()
        click(page.locator('button[name="action"][value="save"]'))
        connection=sqlite3.connect((root/"instance/demo.sqlite3").resolve().as_uri()+"?mode=ro",uri=True)
        try:
            row=connection.execute("SELECT data FROM manual_schedules WHERE month='2026-11'").fetchone()
            saved=json.loads(row[0]) if row else {}
            person=next(i for i,p in enumerate(saved["people"]) if p["id"]==9)
            if saved["grid"][saved["days"].index("2026-11-09")][person]=="RR":
                raise ValueError("?????????????????????")
            report["requested_helper_applied"]=True
        finally:connection.close()
        compare=page.locator('[data-compare-schedule]').first
        compare.check()
        page.locator(".paper-schedule").first.scroll_into_view_if_needed()
        stage(8,"作成した勤務と希望を比較","同じ勤務表で希望休・有給との比較を切り替えられます。",6,"roster")
        page.locator(".paper-schedule").first.screenshot(path=str(shots/"roster.png"))
        page.evaluate("window.print=()=>window.dispatchEvent(new Event('beforeprint'))")
        click(page.locator('[data-print-packet="manual-print"]').first)
        page.emulate_media(media="print")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(shots/"print.png"))
        page.wait_for_timeout(5000)
        page.emulate_media(media="screen")
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        stage(9,"希望との比較を印刷でも確認","印刷用CSSを表示した画面です。最終的な勤務条件は利用者が確認します。",3)
        report["stages"].append("印刷用表示")
        video=page.video
        context.close()
        if report["javascript_errors"] or report["server_errors"]:
            raise ValueError("撮影中にブラウザまたはサーバーのエラーが発生しました。")
        source=video.path()
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ffmpeg,"-y","-i",str(source),"-map_metadata","-1","-vf","scale=1280:-2","-c:v","libx264","-preset","veryfast","-crf","24","-pix_fmt","yuv420p","-movflags","+faststart","-an",str(output/"walkthrough.mp4")],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        pictures=[]
        for frame in frames:
            with Image.open(frame) as img:
                img=img.convert("RGB").resize((960,667),Image.Resampling.LANCZOS)
                pictures.append(img.quantize(colors=128))
        pictures[0].save(output/"overview.gif",save_all=True,append_images=pictures[1:],duration=1800,loop=0,optimize=True,disposal=2)
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
