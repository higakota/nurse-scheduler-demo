"""Windowsの日本語合成音声を重ね、指定した繰り返し区間を省略する。"""
import argparse
import json
import shutil
import subprocess
import wave
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import imageio_ffmpeg

def ps_quote(value):
    return "'"+str(value).replace("'","''")+"'"

def synthesize(plan,folder):
    folder.mkdir(parents=True,exist_ok=True)
    command="""Add-Type -AssemblyName System.Speech
$voice=New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.SelectVoice('Microsoft Haruka Desktop')
$voice.Rate=0
$format=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)
$items=Get-Content -LiteralPath PLAN -Raw -Encoding UTF8 | ConvertFrom-Json
try {foreach($item in $items){
 $path=Join-Path FOLDER ($item.id+'.wav')
 $voice.SetOutputToWaveFile($path,$format)
 $voice.Speak([string]$item.text)
 $voice.SetOutputToNull()
}} finally {$voice.Dispose()}
"""
    command=command.replace("PLAN",ps_quote(plan.resolve())).replace("FOLDER",ps_quote(folder.resolve()))
    subprocess.run(["powershell.exe","-NoProfile","-Command",command],check=True)

def edit(source,report_path,plan_path,voice_folder,output,start,end,make_voice=False):
    output.mkdir(parents=True,exist_ok=True)
    if source.resolve()==(output/"walkthrough.mp4").resolve():
        raise ValueError("元の動画とは別の出力先を指定してください。")
    report=json.loads(report_path.read_text(encoding="utf-8"))
    plan=json.loads(plan_path.read_text(encoding="utf-8"))
    duration=report["duration_seconds"]
    if not 0<start<end<duration:raise ValueError("省略区間を確認してください。")
    length=duration-(end-start)
    if make_voice:synthesize(plan_path,voice_folder)
    rate=22050
    track=bytearray(round(length*rate)*2)
    for i,item in enumerate(plan):
        with wave.open(str(voice_folder/(item["id"]+".wav")),"rb") as wav:
            assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,rate)
            payload=wav.readframes(wav.getnframes())
        finish=item["start"]+len(payload)/(rate*2)
        limit=plan[i+1]["start"] if i+1<len(plan) else length
        if finish>limit-.05:
            raise ValueError("ナレーションが次の説明に重なります: "+item["id"])
        offset=round(item["start"]*rate)*2
        track[offset:offset+len(payload)]=payload
    audio=output/"narration.wav"
    with wave.open(str(audio),"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(track)
    note=Image.new("RGBA",(860,58),(0,0,0,0))
    draw=ImageDraw.Draw(note)
    draw.rounded_rectangle((0,0,859,57),radius=9,fill=(255,243,205,245))
    font=ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc",23)
    draw.text((430,29),"医師の確認チェックの繰り返しを一部省略しています",font=font,fill="#604800",anchor="mm")
    note.save(output/"omission.png")
    filters=(f"[0:v]trim=end={start},setpts=PTS-STARTPTS[first];"
             f"[0:v]trim=start={end},setpts=PTS-STARTPTS[last];"
             "[first][last]concat=n=2:v=1:a=0[cut];"
             f"[cut][2:v]overlay=(W-w)/2:14:enable='between(t,{start},{start+6})'[v];"
             "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-i",str(source),"-i",str(audio),
                    "-loop","1","-i",str(output/"omission.png"),"-filter_complex",filters,
                    "-map","[v]","-map","[a]","-t",str(length),"-c:v","libx264","-preset","veryfast",
                    "-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","96k","-ar","44100",
                    "-map_metadata","-1","-movflags","+faststart",str(output/"walkthrough.mp4")],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    def edited(t):
        return t if t<start else start if t<end else t-(end-start)
    report["raw_capture_duration_seconds"]=duration
    report["duration_seconds"]=round(imageio_ffmpeg.count_frames_and_secs(str(output/"walkthrough.mp4"))[1],1)
    for chapter in report["chapters"]:chapter["seconds"]=round(edited(chapter["seconds"]),1)
    report["audio"]="日本語合成音声（Microsoft Haruka Desktop）。字幕あり。"
    report["narration_segments"]=len(plan)
    report["omitted_intervals"]=[dict(start=start,end=end,reason="医師の確認チェックの繰り返し。省略表示あり。")]
    report["player_autoplay"]=False
    (output/"capture-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    shutil.copyfile(plan_path,output/"narration.json")
    print("Narrated walkthrough:",report["duration_seconds"],"seconds; narration:",len(plan),"segments")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",required=True,type=Path)
    parser.add_argument("--report",required=True,type=Path)
    parser.add_argument("--plan",required=True,type=Path)
    parser.add_argument("--voice-folder",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--cut-start",required=True,type=float)
    parser.add_argument("--cut-end",required=True,type=float)
    parser.add_argument("--synthesize",action="store_true")
    args=parser.parse_args()
    edit(args.source,args.report,args.plan,args.voice_folder,args.output,args.cut_start,args.cut_end,args.synthesize)
