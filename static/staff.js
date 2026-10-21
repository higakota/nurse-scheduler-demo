const role = document.getElementById("role");
const employment = document.getElementById("employment");
function updateRole() {
  const isNurse = role.value === "nurse";
  const help = document.getElementById("is-help").checked;
  if (help) employment.value = "full";
  else if(!isNurse)employment.value="part";
  employment.disabled = help;
  const veteran = document.querySelector('input[name="veteran"]');
  veteran.disabled = !isNurse;
  if (!isNurse) veteran.checked = false;
  const noC = document.querySelector('[name="no_c"]');
  if (noC) { noC.disabled = !isNurse || help; document.getElementById("no-c-field").hidden = !isNurse || help; }
  document.getElementById("advance-help-field").hidden=!help;
  const part = !help && employment.value === "part";
  document.getElementById("weekly-fields").hidden = !part;
}
document.getElementById("is-help").addEventListener("change", updateRole);
role.addEventListener("change", updateRole);
employment.addEventListener("change", updateRole);
updateRole();
