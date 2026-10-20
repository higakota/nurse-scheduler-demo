(() => {
const form=document.querySelector(".schedule-form");
if(!form)return;
let submitting=false;
form.querySelectorAll('input[name="help_source"]').forEach(input=>input.addEventListener("change",()=>{const name=document.getElementById("help-source-name");if(name)name.textContent=input.dataset.label;}));
const status=document.getElementById("schedule-action-status");
const replace=form.querySelector('input[type="checkbox"][name="replace"]');
replace?.addEventListener("change",()=>{replace.removeAttribute("aria-invalid");status.hidden=true;});
form.addEventListener("submit",event=>{
if(submitting){event.preventDefault();return;}
const mode=event.submitter?.value;
if(!["draft","draft_six","self","help","six"].includes(mode)){event.preventDefault();return;}
if(["self","help","six"].includes(mode)&&replace&&!replace.checked){
event.preventDefault();status.hidden=false;status.textContent="保存済みの自動作成結果を置き換えるチェックを入れてから作成してください。手動下書きは変更しません。";replace.setAttribute("aria-invalid","true");replace.focus();return;
}
const field=document.createElement("input");field.type="hidden";field.name="mode";field.value=mode;form.append(field);
submitting=true;status.hidden=false;status.textContent="勤務表を作成しています。条件によって時間がかかります。再度押さず、そのままお待ちください。";
form.setAttribute("aria-busy","true");form.querySelectorAll('button[type="submit"],button[name="mode"]').forEach(button=>{button.disabled=true;});
});
window.addEventListener("pageshow",event=>{if(event.persisted)location.reload();});
})();