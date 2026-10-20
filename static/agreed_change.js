(() => {
const form=document.getElementById("agreed-form");if(!form)return;
const data=JSON.parse(document.getElementById("agreed-calendar-data").textContent);
const staff=document.getElementById("agreed-staff"),day=document.getElementById("agreed-day"),period=document.getElementById("agreed-period"),swap=document.getElementById("agreed-swap"),reason=document.getElementById("agreed-reason");
const editor=document.getElementById("agreed-editor"),content=document.getElementById("agreed-editor-content"),empty=document.getElementById("agreed-empty"),status=document.getElementById("agreed-calendar-status");
const pickSwap=document.getElementById("agreed-pick-swap");
let swapMode=false,dirty=Boolean(reason.value.trim()),submitting=false;
const label=value=>{const d=new Date(value+"T12:00:00");return value+"（"+"日月火水木金土"[d.getDay()]+"）";};
function entry(){return data.editable_days.includes(day.value)?(data.entries[day.value]||[]).find(item=>item.staff===staff.value&&item.wish):undefined;}
function render(){
 const selected=entry();content.hidden=!selected;empty.hidden=Boolean(selected);
 document.querySelectorAll("[data-agreed-fallback]").forEach(el=>el.hidden=true);
 document.getElementById("agreed-swap-tools").hidden=false;
 document.querySelectorAll("[data-agreed-date]").forEach(cell=>{
  cell.classList.toggle("is-selected",Boolean(selected)&&cell.dataset.agreedDate===day.value);
  cell.classList.toggle("is-replacement",Boolean(swap.value)&&cell.dataset.agreedDate===swap.value);
 });
 document.querySelectorAll("[data-agreed-staff]").forEach(chip=>{
  const active=chip.dataset.agreedStaff===staff.value&&chip.dataset.agreedDay===day.value;
  if(active)chip.setAttribute("aria-current","true");else chip.removeAttribute("aria-current");
 });
 document.querySelectorAll("[data-agreed-swap]").forEach(button=>{
  button.hidden=!swapMode;button.disabled=button.dataset.agreedSwap===day.value||!(data.replacements[staff.value]||[]).includes(button.dataset.agreedSwap);
  button.closest("td").classList.toggle("is-swap-candidate",swapMode&&!button.disabled);
 });
 document.getElementById("agreed-selection").textContent=selected?label(day.value)+" "+selected.name:"変更する希望休";
 document.getElementById("agreed-selection-note").textContent=selected?selected.wish_label+"希望休です。本人が了承した出勤時間帯を選んでください。":"";
 document.getElementById("agreed-swap-status").textContent=swap.value?"代わりの全日希望休："+label(swap.value):"指定なし：公休日数を守るための休みを自動調整します。";
 document.getElementById("agreed-clear-swap").hidden=!swap.value;
 pickSwap.textContent=swapMode?"日付選択をやめる":"カレンダーで選ぶ";
 pickSwap.setAttribute("aria-pressed",String(swapMode));
 status.textContent=swapMode?"代わりに休む日を選んでください。会議・有給のない全日勤務の日だけ選べます。":"希望休の名前を押して、変更する人と日を選んでください。";
 document.querySelector(".agreed-calendar-panel").classList.toggle("is-swap-mode",swapMode);
}
function showEditor(){if(matchMedia("(max-width:1150px)").matches)editor.scrollIntoView({block:"start"});}
document.querySelectorAll("[data-agreed-staff]").forEach(chip=>chip.addEventListener("click",event=>{
 event.preventDefault();if(swapMode)return;
 const same=staff.value===chip.dataset.agreedStaff&&day.value===chip.dataset.agreedDay;
 if(!same&&dirty&&!window.confirm("入力中の変更内容があります。別の人・日付へ切り替えますか？"))return;
 if(!same){staff.value=chip.dataset.agreedStaff;day.value=chip.dataset.agreedDay;period.value=chip.dataset.agreedPeriod;swap.value="";reason.value="";dirty=false;}
 render();showEditor();period.focus({preventScroll:true});
}));
pickSwap.addEventListener("click",()=>{
 swapMode=!swapMode;render();
 if(swapMode)document.getElementById("agreed-calendar-title").scrollIntoView({block:"start"});
});
document.querySelectorAll("[data-agreed-swap]").forEach(button=>button.addEventListener("click",()=>{
 if(button.disabled)return;swap.value=button.dataset.agreedSwap;swapMode=false;dirty=true;render();showEditor();pickSwap.focus({preventScroll:true});
}));
document.getElementById("agreed-clear-swap").addEventListener("click",()=>{swap.value="";dirty=true;render();});
form.addEventListener("input",()=>{dirty=true;});
form.addEventListener("change",()=>{dirty=true;});
form.addEventListener("submit",()=>{submitting=true;});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&swapMode){swapMode=false;render();pickSwap.focus();}});
window.addEventListener("beforeunload",event=>{if(dirty&&!submitting){event.preventDefault();event.returnValue="";}});
render();
})();