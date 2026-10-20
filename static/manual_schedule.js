(() => {
const form=document.getElementById("manual-form");if(!form)return;
const data=JSON.parse(document.getElementById("manual-data").textContent);
const modal=document.getElementById("manual-dialog"),am=document.getElementById("manual-am"),pm=document.getElementById("manual-pm");
const patch={...(data.pending||{})},field=document.getElementById("manual-patch"),list=document.getElementById("manual-pending");
const buttons=[...document.querySelectorAll(".manual-cell")];
const sheet=buttons[0]?.closest(".paper-schedule");
const labels={R:"休",D:"日",C:"日",O:"日",M:"会",P:"有休",A:"日",B:"日"};
const details={R:"休み",D:"診療勤務",C:"検査室",O:"通常業務",M:"会議",P:"有給",A:"診療勤務（旧A）",B:"診療勤務（旧B）"};
const pairLabel=p=>p[0]===p[1]?labels[p[0]]:labels[p[0]]+"/"+labels[p[1]];
const cellLabel=(p,i)=>data.people[i].is_help?(p==="RR"?"":p[1]==="R"&&"ABCDMO".includes(p[0])?"午前":p[0]==="R"&&"ABCDMO".includes(p[1])?"午後":pairLabel(p)):pairLabel(p);
const originalTotals=[...(sheet?.querySelectorAll(".paper-duty-row .paper-total")||[])].map(el=>el.textContent);
let selected=null,targets=[],submitting=false;
const selectedCells=new Set(),undoStack=[],redoStack=[];
const selectMode=document.getElementById("manual-select-mode");
const keyOf=b=>b.dataset.day+"_"+b.dataset.person;
function selectionChanged(){
for(const b of buttons){b.classList.toggle("is-selected",selectedCells.has(keyOf(b)));b.setAttribute("aria-pressed",String(selectedCells.has(keyOf(b))));}
const n=selectedCells.size,bulk=document.getElementById("manual-bulk-edit");
bulk.disabled=!n;bulk.textContent="選んだマスを変更（"+n+"件）";document.getElementById("manual-clear-selection").hidden=!n;
}
function remember(){undoStack.push(JSON.stringify(patch));if(undoStack.length>50)undoStack.shift();redoStack.length=0;}
function replacePatch(text){for(const key of Object.keys(patch))delete patch[key];Object.assign(patch,JSON.parse(text));render();}
function undo(){if(!undoStack.length)return;redoStack.push(JSON.stringify(patch));replacePatch(undoStack.pop());}
function redo(){if(!redoStack.length)return;undoStack.push(JSON.stringify(patch));replacePatch(redoStack.pop());}
function current(d,i){return patch[d+"_"+i]||data.grid[d][i];}
function edit(button){selected=button;targets=[button];const d=+button.dataset.day,i=+button.dataset.person,pair=current(d,i);
document.getElementById("manual-cell-title").textContent=data.days[d]+" "+data.people[i].name;
document.getElementById("manual-cell-before").textContent="現在：午前 "+details[pair[0]]+" ／ 午後 "+details[pair[1]];
const agreedLink=document.getElementById("manual-agreed-change");
if(agreedLink){agreedLink.hidden=Boolean(data.people[i].is_help);const url=new URL(agreedLink.href);url.searchParams.set("staff",data.people[i].id);url.searchParams.set("day",data.days[d]);agreedLink.href=url.toString();}
am.value=pair[0];pm.value=pair[1];modal.showModal();am.focus();}
function render(){
field.value=JSON.stringify(patch);list.replaceChildren();
document.getElementById("manual-local-undo").disabled=!undoStack.length;document.getElementById("manual-local-redo").disabled=!redoStack.length;
for(const [key,pair] of Object.entries(patch)){const [d,i]=key.split("_").map(Number),li=document.createElement("li");
li.append(document.createTextNode(data.days[d]+" "+data.people[i].name+"："+pairLabel(data.grid[d][i])+" → "+pairLabel(pair)+" "));
const remove=document.createElement("button");remove.type="button";remove.textContent="取り消す";
remove.addEventListener("click",()=>{remember();delete patch[key];render();});li.append(remove);list.append(li);}
for(const button of buttons){const d=+button.dataset.day,i=+button.dataset.person,pair=current(d,i),cell=button.closest("td");
button.textContent=cellLabel(pair,i);button.classList.toggle("is-edited",Object.hasOwn(patch,d+"_"+i));
const hint="午前："+details[pair[0]]+"、午後："+details[pair[1]];
button.setAttribute("aria-label",data.people[i].name+" "+data.days[d]+" "+hint+"を編集");cell.title=hint;cell.setAttribute("aria-label",data.days[d]+" "+hint);
for(const kind of ["rest","paid","meeting","half","work"])cell.classList.remove("paper-"+kind);
cell.classList.add("paper-"+(pair==="RR"?"rest":pair.includes("P")?"paid":pair.includes("M")?"meeting":pair.includes("R")?"half":"work"));}
(sheet?.querySelectorAll(".paper-duty-row .paper-total")||[]).forEach((el,i)=>{
if(data.people[i].is_help||data.people[i].employment==="part")return;
let units=0;for(let d=0;d<data.days.length;d++){const pair=current(d,i);units+=pair.includes("P")?(pair.includes("R")?2:0):[...pair].filter(c=>c==="R").length;}
const old=originalTotals[i],index=old.indexOf("／");el.textContent=units/2+"日"+(index>=0?old.slice(index):"");});
const dirty=Object.keys(patch).length>0;
if(list.closest("details"))list.closest("details").hidden=!dirty;
document.getElementById("manual-status").textContent=Object.keys(patch).length+"件の変更（"+(dirty?"未保存":"変更なし")+"）";
document.getElementById("manual-recheck").hidden=!dirty;
document.querySelectorAll(".manual-print-actions [data-print-packet]").forEach(button=>{button.disabled=dirty;});
(sheet?.querySelectorAll(".paper-grid tfoot,.paper-detail-grid,.paper-deficit-note")||[]).forEach(el=>el.hidden=dirty);
}
for(const button of buttons)button.addEventListener("click",()=>{
if(selectMode.checked){const key=keyOf(button);if(selectedCells.has(key))selectedCells.delete(key);else selectedCells.add(key);selectionChanged();}
else edit(button);
});
selectMode.addEventListener("change",()=>{selectedCells.clear();selectionChanged();});
document.getElementById("manual-clear-selection").addEventListener("click",()=>{selectedCells.clear();selectionChanged();});
document.getElementById("manual-bulk-edit").addEventListener("click",()=>{
targets=buttons.filter(b=>selectedCells.has(keyOf(b)));if(!targets.length)return;selected=targets[0];
document.getElementById("manual-cell-title").textContent=targets.length+"マスをまとめて変更";
document.getElementById("manual-cell-before").textContent="選択したマスだけ変更します。「変更しない」の時間帯はそれぞれ元の勤務を残します。";
document.getElementById("manual-agreed-change")?.setAttribute("hidden","");
am.value="";pm.value="";modal.showModal();am.focus();
});
document.getElementById("manual-cell-form").addEventListener("submit",e=>{e.preventDefault();if(!targets.length)return;
const next=targets.map(b=>{const d=+b.dataset.day,i=+b.dataset.person,old=current(d,i);return {d,i,key:keyOf(b),pair:(am.value||old[0])+(pm.value||old[1])};});
if(next.some(v=>v.pair!==current(v.d,v.i))){remember();for(const v of next){if(v.pair===data.grid[v.d][v.i])delete patch[v.key];else patch[v.key]=v.pair;}render();}
selectedCells.clear();selectionChanged();modal.close();selected?.focus();});
document.getElementById("manual-local-undo").addEventListener("click",undo);
document.getElementById("manual-local-redo").addEventListener("click",redo);
document.addEventListener("keydown",e=>{
if(modal.open||e.target.closest("input,textarea,select")||!(e.ctrlKey||e.metaKey)||!["z","y"].includes(e.key.toLowerCase()))return;
e.preventDefault();if(e.shiftKey||e.key.toLowerCase()==="y")redo();else undo();
});
document.getElementById("manual-cancel").addEventListener("click",()=>modal.close());
form.addEventListener("submit",()=>{submitting=true;});
window.addEventListener("beforeunload",e=>{
const dialogDirty=modal.open&&targets.some(b=>{const old=current(+b.dataset.day,+b.dataset.person);return (am.value||old[0])+(pm.value||old[1])!==old;});
if(!submitting&&(Object.keys(patch).length||dialogDirty)){e.preventDefault();e.returnValue="";}
});
render();selectionChanged();
const params=new URLSearchParams(location.search),d=data.days.indexOf(params.get("day")),i=data.people.findIndex(p=>String(p.id)===params.get("staff"));
if(d>=0&&i>=0){const button=buttons.find(b=>+b.dataset.day===d&&+b.dataset.person===i);if(button){button.scrollIntoView({block:"center"});edit(button);}}
})();