(() => {
  const form = document.getElementById("absence-form");
  if (!form) return;
  const expand=document.getElementById("absence-expand"),panel=document.getElementById("wishes");
  function focusCalendar(enabled){
    panel.classList.toggle("absence-focused",enabled);
    document.body.classList.toggle("absence-focus-open",enabled);
    expand.setAttribute("aria-pressed",String(enabled));
    expand.textContent=enabled?"元の画面に戻る（Esc）":"カレンダーを大きく表示";
    if(!enabled)expand.focus();
  }
  expand?.addEventListener("click",()=>focusCalendar(!panel.classList.contains("absence-focused")));
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape"&&panel.classList.contains("absence-focused")){e.preventDefault();focusCalendar(false);}
    if(e.key==="Tab"&&panel.classList.contains("absence-focused")){
      const controls=[...panel.querySelectorAll("button,select,input,summary,a[href]")].filter(el=>!el.disabled&&el.getClientRects().length);
      const first=controls[0],last=controls[controls.length-1];
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
    }
  });
  const original = JSON.parse(document.getElementById("absence-original").textContent);
  let changes = {wishes: {}, leaves: {}};
  try {
    const pending = JSON.parse(JSON.parse(document.getElementById("absence-pending").textContent));
    if (pending && typeof pending.wishes === "object" && pending.wishes && typeof pending.leaves === "object" && pending.leaves) changes = pending;
  } catch {}
  const staff = document.getElementById("absence-staff");
  const days = [...document.querySelectorAll("[data-absence-day]")];
  const labels = {full: "全日", am: "午前", pm: "午後"};
  let dirty = false;
  let submitting = false;
  function value(kind, key) {
    return Object.hasOwn(changes[kind], key) ? changes[kind][key] : (original[kind][key] || "");
  }
  function render() {
    days.forEach(picker => {
      const key = staff.value + "_" + picker.dataset.absenceDay;
      const wish = value("wishes", key);
      const paid = value("leaves", key);
      const pending = ["wishes", "leaves"].some(kind => Object.hasOwn(changes[kind], key));
      picker.querySelector(".calendar-badge").textContent = [
        wish ? labels[wish] + "希望休" : "", paid ? labels[paid] + "有給" : ""
      ].filter(Boolean).join("／");
      const halfRest = (wish === "am" && paid === "pm") || (wish === "pm" && paid === "am");
      picker.querySelector(".calendar-pending").textContent = [halfRest ? "休日日数：1日" : "", pending ? "未保存" : ""].filter(Boolean).join("・");
      picker.classList.toggle("has-leave", Boolean(wish || paid));
      picker.classList.toggle("is-dirty", pending);
      picker.querySelectorAll("button").forEach(button => {
        const current = value(button.dataset.kind, key);
        button.setAttribute("aria-pressed", String(Boolean(current) && current === button.dataset.period));
        if (!button.dataset.period) button.hidden = !current;
      });
    });
    const count = Object.values(changes).reduce((sum, patch) => sum + Object.keys(patch).length, 0);
    dirty = count > 0;
    document.getElementById("absence-status").textContent = count ? "未保存：" + count + "件。最後にまとめて保存してください。" : "休む日だけ選んでください。";
    document.getElementById("absence-save").disabled = !dirty;
    document.getElementById("absence-changes").value = JSON.stringify(changes);
    document.dispatchEvent(new Event("monthly-input-state"));
  }
  days.forEach(picker => {
    picker.addEventListener("toggle", () => { if (picker.open) days.forEach(other => { if (other !== picker) other.open = false; }); });
    picker.querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
      const key = staff.value + "_" + picker.dataset.absenceDay;
      const kind = button.dataset.kind;
      const period = button.dataset.period;
      if (period === (original[kind][key] || "")) delete changes[kind][key];
      else changes[kind][key] = period;
      picker.open = false;
      render();
    }));
  });
  staff.addEventListener("change", () => { days.forEach(p => { p.open = false; }); render(); });
  form.addEventListener("submit", () => { submitting = true; });
  window.addEventListener("beforeunload", event => {
    if (dirty && !submitting && !window.monthlySubmitting) { event.preventDefault(); event.returnValue = ""; }
  });
  render();
})();
