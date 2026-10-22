(() => {
const main=document.getElementById("main-content");
if(!main)return;
const settings=document.querySelector(".monthly-form");
const tabs=[...document.querySelectorAll("[data-month-tab]")];
const labels={wishes:"希望休・有給",targets:"休日日数・週上限",closures:"休診日",meetings:"会議",availability:"みどりに出勤できる日"};
const forms=[...main.querySelectorAll("form")];
const controls=form=>[...form.querySelectorAll("input,select,textarea")].filter(input=>
input.type!=="hidden"&&input.type!=="submit"&&input.type!=="button"&&!input.dataset.uiOnly&&input.id!=="absence-staff");
const value=input=>input.type==="checkbox"||input.type==="radio"?String(input.checked):input.value;
const initial=new Map(forms.map(form=>[form,new Map(controls(form).map(input=>[input,value(input)]))]));
window.monthlySubmitting=false;
function isDirty(form){
if(form.id==="attendance-batch-form")return !document.getElementById("attendance-batch-save").disabled;
if(form.id==="absence-form")return !document.getElementById("absence-save").disabled;
return controls(form).some(input=>value(input)!==initial.get(form)?.get(input));
}
function dirtyPanels(){
const names=new Set();
for(const form of forms){
if(form.id==="attendance-batch-form"){if(isDirty(form))names.add("meetings");continue;}
if(form.id==="absence-form"){if(isDirty(form))names.add("wishes");continue;}
for(const input of controls(form))if(value(input)!==initial.get(form)?.get(input)){
const panel=input.closest("[data-month-panel]");if(panel)names.add(panel.dataset.monthPanel);
}}
return names;
}
function showPanel(name){
document.getElementById("settings-tab").value=name;
document.querySelectorAll("[data-month-panel]").forEach(panel=>panel.hidden=panel.dataset.monthPanel!==name);
tabs.forEach(tab=>tab.setAttribute("aria-selected",String(tab.dataset.monthTab===name)));
document.querySelectorAll("[data-month-save]").forEach(bar=>bar.hidden=name==="meetings"||name==="wishes"||name==="availability");
}
const banner=document.createElement("p");banner.id="monthly-unsaved";banner.className="month-unsaved";banner.setAttribute("role","status");banner.hidden=true;
document.querySelector(".month-tabs")?.before(banner);
function updateStatus(){
const pending=dirtyPanels();
banner.hidden=!pending.size;
banner.textContent="未保存："+[...pending].map(name=>labels[name]).join("・")+"。タブを切り替えても入力は残ります。各項目で保存してください。";
tabs.forEach(tab=>{tab.classList.toggle("has-unsaved",pending.has(tab.dataset.monthTab));});
const status=document.getElementById("settings-status");
if(status)status.textContent=settings&&isDirty(settings)?"変更あり・未保存です。「入力内容を保存」を押してください。":"変更はありません。";
}
main.addEventListener("input",updateStatus);
main.addEventListener("change",updateStatus);
document.addEventListener("monthly-input-state",updateStatus);
main.addEventListener("submit",event=>{
if(event.target.closest("#meeting-attendance-dialog"))return;
const other=forms.filter(form=>form!==event.target&&isDirty(form));
if(other.length&&!window.confirm("別の項目に未保存の変更があります。この内容だけ保存して移動すると、ほかの未保存の変更は失われます。続けますか？")){
event.preventDefault();event.stopImmediatePropagation();return;
}
window.monthlySubmitting=true;
},true);
window.addEventListener("beforeunload",event=>{
if(!window.monthlySubmitting&&forms.some(isDirty)){event.preventDefault();event.returnValue="";}
});
tabs.forEach(tab=>tab.addEventListener("click",event=>{
event.preventDefault();showPanel(tab.dataset.monthTab);history.replaceState(null,"","#"+tab.dataset.monthTab);
}));
if(tabs.length){const fragment=location.hash.slice(1);showPanel(tabs.some(tab=>tab.dataset.monthTab===fragment)?fragment:"wishes");}
let invalidPanel=null;
settings?.addEventListener("invalid",event=>{
const panel=event.target.closest("[data-month-panel]");
if(panel&&!invalidPanel){invalidPanel=panel;showPanel(panel.dataset.monthPanel);setTimeout(()=>{invalidPanel=null;},0);}
},true);
const meetingError=document.querySelector('#meetings .error[role="alert"]');
if(meetingError){showPanel("meetings");meetingError.scrollIntoView({block:"center"});}
document.querySelectorAll("[data-excel-meeting]").forEach(candidate=>{
const pick=candidate.querySelector('input[name^="meeting_pick_"]'),status=candidate.querySelector("[data-excel-meeting-status]");
const selectCandidate=event=>{
if(event.target===pick||!event.target.matches("input,select,textarea"))return;
pick.checked=true;
if(status)status.textContent="取り込み対象に選択しました。まだ未保存です。日付・参加者を確認して、下の「選んだ会議を反映・保存」を押してください。";
updateStatus();
};
candidate.addEventListener("input",selectCandidate);candidate.addEventListener("change",selectCandidate);
});
const excelError=document.querySelector(".excel-event-error");
if(excelError){const panel=excelError.closest("[data-month-panel]");if(panel)showPanel(panel.dataset.monthPanel);excelError.scrollIntoView({block:"center"});}
updateStatus();
})();
