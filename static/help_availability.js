function updateHelpRefresh(){
const button=document.getElementById("refresh-shortages");
if(button)button.disabled=document.body.dataset.helpVisitDirty==="true"||document.body.dataset.helpExceptionDirty==="true";
}
(() => {
  const form = document.getElementById("help-calendar-form");
  if (!form) return;
  const people=JSON.parse(document.getElementById("help-people").textContent);
  const modal=document.getElementById("help-visit-dialog");
  let selectedDay=null;
  const included = JSON.parse(document.getElementById("help-included").textContent);
  const original = JSON.parse(document.getElementById("help-original").textContent);
  let changes = {};
  try { const patch = JSON.parse(JSON.parse(document.getElementById("help-pending").textContent)); if (patch && typeof patch === "object" && !Array.isArray(patch)) changes = patch; } catch {}
  const staff = document.getElementById("help-staff");
  const days = [...document.querySelectorAll("[data-help-day]")];
  const labels = {full: "全日来院", am: "午前来院", pm: "午後来院", "": ""};
  let dirty = false;
  let submitting = false;
  function render() {
    days.forEach(picker => {
      const key = staff.value + "_" + picker.dataset.helpDay;
      const pending = Object.hasOwn(changes, key);
      const period = pending ? changes[key] : (original[key] || "");
      picker.querySelector(".calendar-badge").textContent = "";
      const visits=picker.querySelector(".help-day-visits");visits.replaceChildren();
      for(const person of people){
        const visitKey=person.id+"_"+picker.dataset.helpDay;
        const visit=Object.hasOwn(changes,visitKey)?changes[visitKey]:(original[visitKey]||"");
        if(!visit)continue;
        const item=document.createElement("button");item.type="button";item.className="help-visit-chip";item.dataset.helpPerson=String(person.id);item.classList.toggle("is-current",String(person.id)===staff.value);
        const reflected=included[visitKey]===visit&&!Object.hasOwn(changes,visitKey);
        item.classList.toggle("is-reflected",reflected);
        const name=document.createElement("span");name.textContent=person.name+"（"+(person.role==="technician"?"検査技師":"看護師")+"）";
        const detail=document.createElement("small");detail.textContent=(labels[visit]||visit)+"・"+(Object.hasOwn(changes,visitKey)?"未保存":reflected?"反映済み":"未反映");
        item.append(name,detail);
        visits.append(item);
      }
      picker.querySelector(".calendar-pending").textContent = pending ? "未保存" : "";
      picker.classList.toggle("has-leave", Boolean(visits.childElementCount));
      picker.classList.toggle("is-dirty", pending);
      const select = picker.querySelector("select");
      select.value = period;
      const pm = select.querySelector('option[value="pm"]');
      pm.disabled = staff.selectedOptions[0].dataset.role === "technician" || select.querySelector('option[value="full"]').disabled;
    });
    const count = Object.keys(changes).length;
    dirty = count > 0;
    document.getElementById("help-status").textContent = count ? "未保存：" + count + "件" : "来院が決まった日だけ選んでください。";
    document.getElementById("help-save").disabled = !dirty;
    document.body.dataset.helpVisitDirty=String(dirty);updateHelpRefresh();
    document.getElementById("help-changes").value = JSON.stringify(changes);
  }
  function otherVisitors(day) {
    const keys=new Set([...Object.keys(original),...Object.keys(changes)]);
    return [...keys].filter(key=>{
      const split=key.indexOf("_");
      return key.slice(split+1)===day&&key.slice(0,split)!==staff.value&&
        Boolean(Object.hasOwn(changes,key)?changes[key]:original[key]);
    }).length;
  }
  function choosePeriod(period){
    if(!selectedDay)return;
    const key=staff.value+"_"+selectedDay.dataset.helpDay;
    if(period===(original[key]||""))delete changes[key];else changes[key]=period;
    render();modal.close();selectedDay.querySelector("summary").focus();
  }
  days.forEach(picker => {
    picker.querySelector("summary").addEventListener("click",event=>{
      event.preventDefault();const chip=event.target.closest("[data-help-person]");if(chip){staff.value=chip.dataset.helpPerson;render();}selectedDay=picker;
      const day=picker.dataset.helpDay,date=new Date(day+"T12:00:00");
      document.getElementById("help-visit-title").textContent=day+"（"+"日月火水木金土"[date.getDay()]+"）";
      document.getElementById("help-visit-person").textContent=staff.selectedOptions[0].textContent.trim();
      const note=document.getElementById("help-visit-note"),closed=picker.querySelector('option[value="full"]').disabled;
      note.textContent=closed?"全日休診です。登録済みの予定は取り消せます。":date.getDay()===5?"金曜午後は診療なしです。相手が承諾した範囲だけ登録してください。":"相手が承諾した来院時間帯を選んでください。";
      const abovePreferred=otherVisitors(day)>=2;
      if(abovePreferred&&!closed)note.textContent="この日は3人以上になります。できれば自院で調整して2人以内にしますが、必要な場合は登録できます。";
      const context=document.getElementById("help-visit-shortage");context.replaceChildren();
      for(const line of picker.querySelectorAll(".help-shortage-item")){const p=document.createElement("p");p.textContent="不足の目安："+line.textContent;context.append(p);}
      modal.querySelectorAll("[data-help-period]").forEach(button=>{
        const period=button.dataset.helpPeriod;
        button.disabled=Boolean(period)&& (closed||(period==="pm"&&staff.selectedOptions[0].dataset.role==="technician"));
        button.setAttribute("aria-pressed",String(period===picker.querySelector("select").value));
      });
      modal.showModal();
    });
    picker.querySelector("select").addEventListener("change",event=>{selectedDay=picker;choosePeriod(event.target.value);});
  });
  modal.querySelectorAll("[data-help-period]").forEach(button=>button.addEventListener("click",()=>choosePeriod(button.dataset.helpPeriod)));
  document.getElementById("help-visit-close").addEventListener("click",()=>modal.close());
  staff.addEventListener("change", () => { days.forEach(p => { p.open = false; }); render(); });
  form.addEventListener("submit", () => { submitting = true; });
  window.addEventListener("beforeunload", event => { if (dirty && !submitting) { event.preventDefault(); event.returnValue = ""; } });
  render();
})();

// 例外は自動選択せず、変更を保存するまで離脱時に案内する。
(() => {
  const form = document.getElementById("technician-exception-form");
  if (!form) return;
  const inputs = [...form.querySelectorAll('input[type="checkbox"]')];
  const original = inputs.map(input => input.checked);
  let submitting = false;
  if(location.hash==="#technician-exceptions")document.getElementById("technician-exceptions").open=true;
  form.addEventListener("change",()=>{document.body.dataset.helpExceptionDirty=String(inputs.some((input,index)=>input.checked!==original[index]));updateHelpRefresh();});
  form.addEventListener("submit", () => { submitting = true; });
  window.addEventListener("beforeunload", event => {
    if (!submitting && inputs.some((input,index) => input.checked !== original[index])) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
})();
