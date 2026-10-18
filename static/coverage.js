const form = document.querySelector(".monthly-form");
const bulk = document.getElementById("fill-unset");
const status = document.getElementById("coverage-status");
const progress = document.getElementById("coverage-progress");
let dirty = false;
function groups() {
  return [...form.querySelectorAll(".c-choice")].filter(group => !group.disabled);
}
function remaining() {
  return groups().filter(group => !group.querySelector("input:checked"));
}
function updateProgress() {
  const count = remaining().length;
  progress.textContent = count ? "C番の未設定：" + count + "か所" : "C番の未設定はありません。";
  bulk.disabled = count === 0;
}
form.addEventListener("change", () => {
  dirty = true;
  status.textContent = "未保存の変更があります。最後に保存してください。";
  updateProgress();
});
bulk.hidden = false;
bulk.addEventListener("click", () => {
  const targets = remaining();
  targets.forEach(group => { group.querySelector('input[value="1"]').checked = true; });
  if (targets.length) {
    dirty = true;
    status.textContent = "未設定の" + targets.length + "か所を最低1人にしました。まだ保存されていません。";
  }
  updateProgress();
});
form.addEventListener("submit", () => { dirty = false; });
window.addEventListener("beforeunload", event => {
  if (dirty) { event.preventDefault(); event.returnValue = ""; }
});
updateProgress();
