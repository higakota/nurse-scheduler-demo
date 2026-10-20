const weeklyForm = document.getElementById("weekly-form");
if (weeklyForm) {
  const fields = [...weeklyForm.querySelectorAll("select")];
  const initial = fields.map(field => field.value);
  let submitting = false;
  weeklyForm.addEventListener("submit", () => { submitting = true; });
  window.addEventListener("beforeunload", event => {
    if (!submitting && fields.some((field,index) => field.value !== initial[index])) {
      event.preventDefault(); event.returnValue = "";
    }
  });
}
