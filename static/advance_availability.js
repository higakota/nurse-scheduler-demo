(() => {
const form=document.getElementById("advance-availability-form");
if(!form)return;
const inputs=[...form.querySelectorAll("[data-advance-key]")];
const original=new Map(inputs.map(input=>[input,input.value]));
const cells=[...form.querySelectorAll("[data-advance-cell]")];
const byKey=new Map(inputs.map(input=>[input.dataset.advanceKey,input]));
const dialog=document.getElementById("advance-period-dialog");
let active=null;
function render(){
const changes={};
for(const input of inputs)if(input.value!==original.get(input))changes[input.dataset.advanceKey]=input.value;
for(const cell of cells){
const input=byKey.get(cell.dataset.advanceCell);
cell.textContent={full:"全日",am:"午前",pm:"午後"}[input.value]||"";
cell.classList.toggle("has-availability",Boolean(input.value));
cell.classList.toggle("is-pending",Object.hasOwn(changes,cell.dataset.advanceCell));
cell.setAttribute("aria-label",cell.dataset.personName+" "+cell.dataset.date+"："+(input.selectedOptions[0]?.textContent||"未登録")+"を編集");
}
document.getElementById("advance-availability-changes").value=JSON.stringify(changes);
document.getElementById("advance-availability-save").disabled=!Object.keys(changes).length;
}
for(const cell of cells)cell.addEventListener("click",()=>{
active=cell;
const input=byKey.get(cell.dataset.advanceCell);
document.getElementById("advance-period-title").textContent=cell.dataset.date+"の勤務可能時間";
document.getElementById("advance-period-person").textContent=cell.dataset.personName;
dialog.querySelectorAll("[data-advance-period]").forEach(button=>{
button.hidden=button.dataset.advancePeriod==="pm"&&cell.dataset.role==="technician";
button.setAttribute("aria-pressed",String(button.dataset.advancePeriod===input.value));
});
dialog.showModal();
});
dialog.querySelectorAll("[data-advance-period]").forEach(button=>button.addEventListener("click",()=>{
if(!active)return;
byKey.get(active.dataset.advanceCell).value=button.dataset.advancePeriod;
render();
byKey.get(active.dataset.advanceCell).dispatchEvent(new Event("change",{bubbles:true}));
dialog.close();active.focus();
}));
document.getElementById("advance-period-close").addEventListener("click",()=>dialog.close());
dialog.addEventListener("close",()=>active?.focus());
form.addEventListener("change",render);
render();
})();
