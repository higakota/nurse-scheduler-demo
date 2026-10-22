(() => {
  const form = document.getElementById("help-bulk-form");
  if (!form) return;
  const person = document.getElementById("bulk-person");
  const status = document.getElementById("bulk-status");
  const boxes = [...form.querySelectorAll('input[name="keys"]')];
  const days = [...form.querySelectorAll(".day-toggle")];
  const apply = document.getElementById("bulk-apply");
  function compatible(box) {
    const selected = person.selectedOptions[0];
    return box.dataset.applied !== "1" && (!person.value ||
      (box.dataset.role === selected.dataset.role &&
       (box.dataset.veteran !== "1" || selected.dataset.veteran === "1")));
  }
  function update() {
    boxes.forEach(box => {
      box.disabled = !compatible(box);
      if (box.disabled) box.checked = false;
    });
    const chosen = boxes.filter(b => b.checked);
    const dates = new Set(chosen.map(b => b.dataset.date));
    document.getElementById("bulk-count").textContent = chosen.length ?
      dates.size + "日・" + chosen.length + "枠を選択中" : "変更する日を選んでください。";
    form.querySelector('button[value="save"]').disabled = !chosen.length;
    apply.disabled = !chosen.length || !person.value;
    days.forEach(button => {
      const selected = boxes.some(b => b.checked && b.dataset.date === button.dataset.date);
      button.textContent = selected ? "選択中・解除" : "この日を選ぶ";
      button.setAttribute("aria-pressed", String(selected));
      button.disabled = !boxes.some(b => b.dataset.date === button.dataset.date && compatible(b));
      button.closest("td").classList.toggle("day-selected", selected);
    });
  }
  function chooseDay(text, clear = false) {
    const candidates = boxes.filter(b => b.dataset.date === text && compatible(b));
    if (clear) { candidates.forEach(b => b.checked = false); return; }
    candidates.forEach(box => box.checked = false);
    const used = new Set();
    // 同じ人を同じ午前・午後で複数人分に数えない。
    candidates.sort((a,b) => Number(b.dataset.veteran) - Number(a.dataset.veteran)).forEach(box => {
      if (!person.value || !used.has(box.dataset.half)) {
        box.checked = true;
        used.add(box.dataset.half);
      }
    });
  }
  days.forEach(button => button.addEventListener("click", () => {
    chooseDay(button.dataset.date, boxes.some(b => b.checked && b.dataset.date === button.dataset.date));
    update();
  }));
  person.addEventListener("change", () => { boxes.forEach(b => b.checked = false); update(); });
  boxes.forEach(box => box.addEventListener("change", () => {
    if (person.value && box.checked) boxes.forEach(other => {
      if (other !== box && other.dataset.date === box.dataset.date && other.dataset.half === box.dataset.half) other.checked = false;
    });
    update();
  }));
  document.getElementById("bulk-select-all").addEventListener("click", () => {
    days.forEach(button => chooseDay(button.dataset.date)); update();
  });
  document.getElementById("bulk-clear").addEventListener("click", () => {
    boxes.forEach(box => box.checked = false); update();
  });
  apply.addEventListener("click", () => { status.value = "ok"; });
  update();
})();