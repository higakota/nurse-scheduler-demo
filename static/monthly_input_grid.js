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
})();