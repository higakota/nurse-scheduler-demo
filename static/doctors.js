function requireReview(card) {
  const checkbox = card.querySelector(".doctor-review input");
  card.querySelector(".doctor-review").hidden = false;
  checkbox.required = true;
  checkbox.checked = false;
  card.classList.add("needs-review");
  card.querySelector(".review-status").textContent = "変更あり・個別確認";
  const confirmed = document.querySelector('input[name="confirmed"]');
  if (confirmed) confirmed.checked = false;
}
document.querySelectorAll(".doctor-half input").forEach(input => {
  const count = document.createElement("small");
  input.after(count);
  function update() {
    const names = input.value.split(/[/／、,\n]+/).map(name => name.trim()).filter(Boolean);
    count.textContent = input.readOnly ? "0人（診療なし）" : names.length ? names.length + "人" : "担当医なし（0人）";
  }
  input.addEventListener("input", () => { update(); requireReview(input.closest(".doctor-day")); });
  update();
});
document.getElementById("aliases")?.addEventListener("input", () => {
  document.querySelectorAll(".doctor-day").forEach(requireReview);
});
