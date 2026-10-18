const dirtyForms = new Set();
const entry = document.querySelector(".leave-entry");
const history = document.querySelector(".history-form");
if (history) {
  history.addEventListener("change", () => dirtyForms.add(history));
  history.addEventListener("submit", () => dirtyForms.delete(history));
}
if (entry) {
  const staff = document.getElementById("staff");
  const original = JSON.parse(document.getElementById("calendar-leaves").textContent);
  const changes = {};
  const labels = {"": "", full: "全日有給", am: "午前有給", pm: "午後有給"};
  const pickers = [...document.querySelectorAll(".calendar-picker")];
  function render() {
    pickers.forEach(picker => {
      const key = staff.value + "_" + picker.dataset.day;
      const changed = Object.hasOwn(changes, key);
      const value = changed ? changes[key] : (original[key] || "");
      picker.querySelector(".calendar-badge").textContent = labels[value];
      picker.querySelector(".calendar-pending").textContent = changed ? "未保存" : "";
      picker.classList.toggle("has-leave", Boolean(value));
      picker.classList.toggle("is-dirty", changed);
      picker.querySelector(".clear-leave").hidden = !value;
      picker.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.period === value)));
    });
    const count = Object.keys(changes).length;
    document.getElementById("calendar-save-status").textContent = count ? "未保存：" + count + "件。最後にまとめて保存してください。" : "有給を取る日だけ選んでください。";
    document.getElementById("save-all-leaves").disabled = count === 0;
    document.getElementById("leave-changes").value = JSON.stringify(changes);
    if (count) dirtyForms.add(entry); else dirtyForms.delete(entry);
  }
  pickers.forEach(picker => {
    picker.addEventListener("toggle", () => {
      if (picker.open) pickers.forEach(other => { if (other !== picker) other.open = false; });
    });
    picker.querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
      const key = staff.value + "_" + picker.dataset.day;
      const value = button.dataset.period;
      if (value === (original[key] || "")) delete changes[key];
      else changes[key] = value;
      picker.open = false;
      render();
    }));
  });
  staff.addEventListener("change", () => { pickers.forEach(picker => { picker.open = false; }); render(); });
  entry.addEventListener("submit", () => { document.getElementById("leave-changes").value = JSON.stringify(changes); dirtyForms.delete(entry); });
  render();
}
window.addEventListener("beforeunload", event => { if (dirtyForms.size) { event.preventDefault(); event.returnValue = ""; } });
