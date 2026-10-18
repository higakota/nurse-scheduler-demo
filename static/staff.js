const role = document.getElementById("role");
const nurseFields = document.getElementById("nurse-fields");
function updateRole() {
  const isNurse = role.value === "nurse";
  nurseFields.hidden = !isNurse;
  nurseFields.querySelectorAll("input, select").forEach(field => {
    field.disabled = !isNurse;
  });
}
role.addEventListener("change", updateRole);
updateRole();
