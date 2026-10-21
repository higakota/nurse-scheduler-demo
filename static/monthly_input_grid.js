(() => {
const dialog=document.getElementById("input-absence-dialog");
document.querySelectorAll("[data-open-meeting]").forEach(link=>link.addEventListener("click",event=>{
 event.preventDefault();const target=document.querySelector(link.getAttribute("href"));if(!target)return;
 document.querySelector('[data-month-tab="meetings"]')?.click();
 if(target.matches("details"))target.open=true;else target.querySelector("details")?.setAttribute("open","");
 target.scrollIntoView({block:"center",behavior:"smooth"});
}));
document.querySelectorAll("[data-meeting-day]").forEach(button=>button.addEventListener("click",()=>{
 const date=document.getElementById("meeting_date");date.value=button.dataset.meetingDay;
 document.getElementById("meeting-add-dialog").showModal();document.getElementById("title").focus();
}));
const meetingDialog=document.getElementById("meeting-add-dialog");
document.getElementById("meeting-open-add")?.addEventListener("click",()=>meetingDialog.showModal());
document.getElementById("meeting-add-close")?.addEventListener("click",()=>meetingDialog.close());
if(meetingDialog?.hasAttribute("data-reopen"))meetingDialog.showModal();
document.querySelectorAll("[data-absence-view]").forEach(button=>button.addEventListener("click",()=>{
 const list=button.dataset.absenceView==="sheet";
 document.getElementById("absence-sheet-view").hidden=!list;document.getElementById("absence-person-view").hidden=list;
 document.querySelectorAll("[data-absence-view]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));
 if(dialog?.open)dialog.close();
}));

const attendanceDialog=document.getElementById("meeting-attendance-dialog");
if(attendanceDialog){
 const days=JSON.parse(document.getElementById("attendance-data").textContent);
 const pending=JSON.parse(document.getElementById("attendance-pending").textContent);
 const staff=document.getElementById("attendance-staff"),dayField=document.getElementById("attendance-day");
 let attendanceTrigger=null;
 function renderAttendance(selected){
  const choices=days[dayField.value]||[],list=document.getElementById("attendance-choices");list.replaceChildren();
  for(const item of choices){
   const label=document.createElement("label");label.className="checkbox";
   const input=document.createElement("input");input.type="checkbox";input.name="attendance";input.value=item.key;input.dataset.uiOnly="true";
   input.checked=selected?selected.includes(item.key):item.participants.map(String).includes(staff.value);
   label.append(input,document.createTextNode(item.title+(item.candidate?"（Excelから登録）":"")));list.append(label);
  }
  document.getElementById("attendance-empty").hidden=Boolean(choices.length);
  document.getElementById("attendance-save").disabled=!choices.length;
  document.getElementById("meeting-attendance-title").textContent=dayField.value+" の会議参加";
 }
 document.querySelectorAll("[data-attendance-day]").forEach(button=>button.addEventListener("click",()=>{
  attendanceTrigger=button;
  document.querySelector('[data-month-tab="meetings"]')?.click();
  dayField.value=button.dataset.attendanceDay;
  if(button.dataset.attendancePerson)staff.value=button.dataset.attendancePerson;
  renderAttendance();attendanceDialog.showModal();
 }));
 staff.addEventListener("change",()=>renderAttendance());
 document.getElementById("attendance-close").addEventListener("click",()=>attendanceDialog.close());
 attendanceDialog.addEventListener("close",()=>attendanceTrigger?.focus());
 if(attendanceDialog.hasAttribute("data-reopen")){
  dayField.value=pending.day;staff.value=pending.staff;renderAttendance(pending.selected);attendanceDialog.showModal();
 }
}


/* Keep the selected staff and date easy to follow, including keyboard editing. */
document.querySelectorAll(".input-sheet").forEach((table,index)=>{
 const wrapper=table.parentElement,key="meeting-scroll:"+location.pathname+":"+(new URLSearchParams(location.search).get("month")||"")+":"+index;
 try{const saved=JSON.parse(sessionStorage.getItem(key)||"null");if(saved)requestAnimationFrame(()=>{wrapper.scrollLeft=saved.left;});}catch{}
 wrapper.addEventListener("scroll",()=>{try{sessionStorage.setItem(key,JSON.stringify({left:wrapper.scrollLeft}));}catch{}},{passive:true});

 let highlighted=[];
 function clear(){for(const el of highlighted)el.classList.remove("input-active-date","input-active-row");highlighted=[];}
 function highlight(cell){
  clear();if(!cell)return;
  for(const row of table.rows){const col=row.cells[cell.cellIndex];if(col){col.classList.add("input-active-date");highlighted.push(col);}}
  cell.parentElement.classList.add("input-active-row");highlighted.push(cell.parentElement);
 }
 table.addEventListener("pointerover",e=>highlight(e.target.closest("td,th")));
 table.addEventListener("focusin",e=>highlight(e.target.closest("td,th")));
 table.addEventListener("pointerleave",()=>highlight(table.contains(document.activeElement)?document.activeElement.closest("td,th"):null));
 table.addEventListener("keydown",e=>{
  if(!e.target.matches(".input-absence-cell,.input-attendance-cell"))return;
  const rows=[...table.querySelectorAll("tbody tr")].map(row=>[...row.querySelectorAll(".input-absence-cell,.input-attendance-cell")]).filter(row=>row.length);
  const r=rows.findIndex(row=>row.includes(e.target)),c=rows[r]?.indexOf(e.target);
  let next;
  if(e.key==="ArrowLeft")next=rows[r]?.slice(0,c).reverse().find(cell=>!cell.disabled);
  if(e.key==="ArrowRight")next=rows[r]?.slice(c+1).find(cell=>!cell.disabled);
  if(e.key==="ArrowUp")next=rows[r-1]?.[c];
  if(e.key==="ArrowDown")next=rows[r+1]?.[c];
  if(e.key==="Home")next=rows[r]?.find(cell=>!cell.disabled);
  if(e.key==="End")next=rows[r]?.slice().reverse().find(cell=>!cell.disabled);
  if(next&&!next.disabled){e.preventDefault();next.focus();}
 });
});

})();