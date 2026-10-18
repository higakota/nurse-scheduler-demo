const form = document.querySelector(".monthly-form");
let dirty = false;
document.querySelectorAll(".wish-select").forEach(select => {
  select.addEventListener("change", () => { select.dataset.wish = select.value; });
});
function markDirty(event) {
  if (event?.target?.dataset.uiOnly) return;
  dirty = true;
  document.getElementById("settings-status").textContent = "変更あり・未保存です。「入力内容を保存」を押してください。";
}
form.addEventListener("input", markDirty);
form.addEventListener("change", markDirty);
form.addEventListener("submit", () => { dirty = false; });
window.addEventListener("beforeunload", event => {
  if (dirty) { event.preventDefault(); event.returnValue = ""; }
});

const monthTabs = [...document.querySelectorAll("[data-month-tab]")];
function showMonthPanel(name) {
  document.querySelectorAll("[data-month-panel]").forEach(panel => { panel.hidden = panel.dataset.monthPanel !== name; });
  monthTabs.forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.monthTab === name)));
  document.querySelectorAll("[data-month-save]").forEach(bar => { bar.hidden = name === "meetings"; });
}
monthTabs.forEach(tab => tab.addEventListener("click", event => {
  event.preventDefault();
  showMonthPanel(tab.dataset.monthTab);
  history.replaceState(null, "", "#" + tab.dataset.monthTab);
}));
if (monthTabs.length) {
  const fragment = window.location.hash.slice(1);
  showMonthPanel(monthTabs.some(tab => tab.dataset.monthTab === fragment) ? fragment : "wishes");
}

const wishesTable = document.querySelector(".wishes-table");
if (wishesTable && wishesTable.tBodies[0]) {
  const records = [...wishesTable.tBodies[0].rows].map(row => ({
    name: row.querySelector("th").textContent.trim(),
    inputs: [...row.querySelectorAll("select")].map(input => ({input, cell: input.parentElement}))
  }));
  if (records.length) {
    const wrapper = wishesTable.closest(".table-wrap");
    const host = document.createElement("div");
    host.className = "wish-calendar";
    const label = document.createElement("label");
    label.htmlFor = "wish-person-picker";
    label.textContent = "希望休を入力するスタッフ";
    const picker = document.createElement("select");
    picker.id = "wish-person-picker";
    picker.dataset.uiOnly = "true";
    records.forEach((record, index) => {
      const option = document.createElement("option");
      option.value = index;
      option.textContent = record.name;
      picker.append(option);
    });
    const calendar = document.createElement("table");
    calendar.className = "leave-calendar";
    const head = document.createElement("thead");
    const heading = document.createElement("tr");
    [..."日月火水木金土"].forEach(day => { const th = document.createElement("th"); th.scope = "col"; th.textContent = day; heading.append(th); });
    head.append(heading);
    const body = document.createElement("tbody");
    calendar.append(head, body);
    host.append(label, picker, calendar);
    wrapper.before(host);
    wrapper.hidden = true;
    function paintWishes() {
      records.forEach(record => record.inputs.forEach(({input,cell}) => cell.append(input)));
      body.replaceChildren();
      const record = records[Number(picker.value)];
      const [year, month] = document.getElementById("nav-month").value.split("-").map(Number);
      const start = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
      const count = record.inputs.length;
      const length = Math.ceil((start + count) / 7) * 7;
      for (let index = 0; index < length; index++) {
        if (index % 7 === 0) body.append(document.createElement("tr"));
        const td = document.createElement("td");
        const day = index - start + 1;
        if (day >= 1 && day <= count) {
          const number = document.createElement("span");
          number.className = "calendar-date";
          number.textContent = day;
          const input = record.inputs[day - 1].input;
          input.options[0].textContent = "—";
          input.setAttribute("aria-label", record.name + " " + month + "月" + day + "日の希望休");
          td.append(number, input);
        } else td.className = "calendar-empty";
        body.lastElementChild.append(td);
      }
    }
    picker.addEventListener("change", paintWishes);
    paintWishes();
  }
}
let invalidPanel = null;
document.querySelector(".monthly-form")?.addEventListener("invalid", event => {
  const panel = event.target.closest("[data-month-panel]");
  if (panel && !invalidPanel) {
    invalidPanel = panel;
    showMonthPanel(panel.dataset.monthPanel);
    setTimeout(() => { invalidPanel = null; }, 0);
  }
}, true);
