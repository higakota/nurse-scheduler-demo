const form = document.querySelector(".monthly-form");
let dirty = false;
document.querySelectorAll(".wish-select").forEach(select => {
  select.addEventListener("change", () => { select.dataset.wish = select.value; });
});
function markDirty() {
  dirty = true;
  document.getElementById("settings-status").textContent = "変更あり・未保存です。「入力内容を保存」を押してください。";
}
form.addEventListener("input", markDirty);
form.addEventListener("change", markDirty);
form.addEventListener("submit", () => { dirty = false; });
window.addEventListener("beforeunload", event => {
  if (dirty) { event.preventDefault(); event.returnValue = ""; }
});
