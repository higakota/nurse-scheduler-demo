
"""架空データの録画に、画面と重ならない説明欄と日本語ナレーションを付ける。"""
import argparse, asyncio, hashlib, json, subprocess, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

VOICE="ja-JP-NanamiNeural"

def run(args):
    result=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8",errors="replace")[-6000:])

def wrap(text,font,width):
    lines=[];line=""
    for char in text:
        if font.getlength(line+char)>width:
            lines.append(line);line=char
        else:line+=char
    if line:lines.append(line)
    return lines

async def voices(plan,cache):
    import edge_tts
    cache.mkdir(parents=True,exist_ok=True)
    for item in plan:
        key=hashlib.sha256(item["text"].encode()).hexdigest()[:16]
        target=cache/(key+".mp3")
        if not target.exists():
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(item["text"],VOICE).save(str(target))
                    break
                except Exception:
                    target.unlink(missing_ok=True)
                    if attempt==2:raise
                    await asyncio.sleep(2)
        item["voice_file"]=str(target.resolve())

def compose(source,report_path,script,cache,output):
    if source.resolve()==(output/"walkthrough.mp4").resolve():
        raise ValueError("元の録画とは別の出力先を使ってください。")
    output.mkdir(parents=True,exist_ok=True)
    report=json.loads(report_path.read_text(encoding="utf-8"))
    original=json.loads(script.read_text(encoding="utf-8"))
    chapters=report["chapters"]
    plan=[]
    special={"voice-month":"スタッフの次に対象月を選ぶ","voice-skip":"同じ確認操作を続けます","voice-doctor-save":"確認した医師予定を保存"}
    for item in original:
        item=dict(item)
        if item["id"] in special:
            start=next(c["start"] for c in report["captions"] if c["title"]==special[item["id"]])
        else:start=chapters[int(item["id"].split("-")[1])]["seconds"]
        item["start"]=round(start+.15,2)
        plan.append(item)
    plan.sort(key=lambda item:item["start"])
    asyncio.run(voices(plan,cache))
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    duration=report["duration_seconds"]
    track=bytearray(round(duration*22050)*2)
    for index,item in enumerate(plan):
        wavfile=output/(item["id"]+".wav")
        run([ffmpeg,"-y","-i",item["voice_file"],"-ar","22050","-ac","1","-c:a","pcm_s16le",str(wavfile)])
        with wave.open(str(wavfile),"rb") as wav:payload=wav.readframes(wav.getnframes())
        limit=plan[index+1]["start"] if index+1<len(plan) else duration
        available=limit-item["start"]-.12
        length=len(payload)/44100
        if length>available:
            # Refuse excessively rushed narration; revise the script instead.
            tempo=length/available
            if tempo>1.15:raise ValueError(f"Narration too long: {item['id']} ({length:.1f}s > {available:.1f}s)")
            run([ffmpeg,"-y","-i",item["voice_file"],"-af",f"atempo={tempo:.5f}","-ar","22050","-ac","1","-c:a","pcm_s16le",str(wavfile)])
            with wave.open(str(wavfile),"rb") as wav:payload=wav.readframes(wav.getnframes())
            item["tempo"]=round(tempo,3)
        offset=round(item["start"]*22050)*2
        track[offset:offset+len(payload)]=payload
        item.pop("voice_file")
        item["end"]=round(item["start"]+len(payload)/44100,2)
    audio=output/"narration.wav"
    with wave.open(str(audio),"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(track)
    titlefont=ImageFont.truetype("C:/Windows/Fonts/meiryob.ttc",22)
    detailfont=ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc",18)
    captions=[dict(start=0,title="",detail="")]+report["captions"]
    sequence=[]
    for index,item in enumerate(captions):
        image=Image.new("RGB",(1280,180),"#153e35")
        draw=ImageDraw.Draw(image)
        draw.text((24,10),item["title"],font=titlefont,fill="white")
        lines=wrap(item["detail"],detailfont,1232)
        if len(lines)>2:raise ValueError("説明文が長すぎます: "+item["title"])
        for n,line in enumerate(lines):draw.text((24,47+n*25),line,font=detailfont,fill="#e1eee8")
        target=output/f"caption-{index:03d}.png";image.save(target)
        end=captions[index+1]["start"] if index+1<len(captions) else duration
        sequence.extend(["file '"+target.name+"'",f"duration {max(.04,end-item['start']):.3f}"])
    sequence.append("file '"+target.name+"'")
    listing=output/"captions.txt";listing.write_text("\n".join(sequence)+"\n",encoding="utf-8")
    run([ffmpeg,"-y","-i",str(source),"-f","concat","-safe","0","-i",str(listing),"-i",str(audio),
         "-filter_complex","[0:v]fps=25,setpts=PTS-STARTPTS[s];[1:v]fps=25,setpts=PTS-STARTPTS[c];[s][c]vstack=inputs=2[v];[2:a]loudnorm=I=-18:TP=-2:LRA=9[a]",
         "-map","[v]","-map","[a]","-t",str(duration),"-c:v","libx264","-preset","veryfast","-crf","24",
         "-pix_fmt","yuv420p","-c:a","aac","-b:a","96k","-ar","44100","-map_metadata","-1","-movflags","+faststart",str(output/"walkthrough.mp4")])
    report.update(audio="日本語合成音声（Nanami）。説明文は映像の下の専用欄に表示。",
                  narration_engine=VOICE,narration_segments=len(plan),player_autoplay=False,
                  caption_layout="アプリ画面1280×764と説明専用欄1280×180を上下に配置。操作ボタンには重ねない。",
                  repeated_checks="最初の2件を操作例として表示。残りは短く操作し、説明欄で案内。")
    (output/"capture-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"narration.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Composed",duration,"seconds;",len(plan),"narration segments",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("source","report","script","cache","output"):parser.add_argument("--"+name,required=True,type=Path)
    args=parser.parse_args()
    compose(args.source,args.report,args.script,args.cache,args.output)
