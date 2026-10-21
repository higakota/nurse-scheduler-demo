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
  document.querySelector('[data-month-tab="meetings"]')?.click();
  dayField.value=button.dataset.attendanceDay;
  if(button.dataset.attendancePerson)staff.value=button.dataset.attendancePerson;
  renderAttendance();attendanceDialog.showModal();
 }));
 staff.addEventListener("change",()=>renderAttendance());
 document.getElementById("attendance-close").addEventListener("click",()=>attendanceDialog.close());
 if(attendanceDialog.hasAttribute("data-reopen")){
  dayField.value=pending.day;staff.value=pending.staff;renderAttendance(pending.selected);attendanceDialog.showModal();
 }
}

})();