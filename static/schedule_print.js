let selectedPacket = null;
let originalTitle = document.title;

function fitMonthlySheet() {
  if (!selectedPacket) return;
  const sheet = selectedPacket.querySelector(".print-monthly-sheet");
  if (!sheet) return;
  // beforeprintでは印刷用CSSの反映時期がブラウザで異なるため、
  // 同じ印刷ルールを計測中だけ有効にして寸法を求める。
  const measurementStyle = document.createElement("style");
  const printRules = [];
  for (const stylesheet of document.styleSheets) {
    try {
      for (const rule of stylesheet.cssRules) {
        if (rule.type === CSSRule.MEDIA_RULE && rule.conditionText === "print") {
          printRules.push(...[...rule.cssRules].map(item => item.cssText));
        }
      }
    } catch { /* このアプリの同一オリジンのCSSだけを対象にする。 */ }
  }
  measurementStyle.textContent = printRules.join("\n");
  document.head.append(measurementStyle);
  sheet.style.zoom = "1";
  // A4 landscape minus 8mm margins; leave room for print rounding.
  const ruler = document.createElement("div");
  ruler.style.cssText = "position:absolute;width:281mm;height:175mm;visibility:hidden;pointer-events:none";
  selectedPacket.append(ruler);
  const available = ruler.getBoundingClientRect();
  const content = sheet.getBoundingClientRect();
  const scale = Math.min(0.9, available.width / Math.max(content.width, sheet.scrollWidth),
                         available.height / Math.max(content.height, sheet.scrollHeight));
  sheet.style.zoom = String(scale);
  ruler.remove();
  measurementStyle.remove();
}

function preparePrint(packet) {
  document.querySelectorAll(".print-packet").forEach(item => {
    const selected = item === packet;
    item.classList.toggle("print-active", selected);
    item.setAttribute("aria-hidden", String(!selected));
  });
  if (!packet && selectedPacket) selectedPacket.querySelectorAll(".print-monthly-sheet").forEach(sheet => sheet.style.removeProperty("zoom"));
  selectedPacket = packet;
  document.body.classList.toggle("schedule-printing", Boolean(packet));
  if (packet) {
    packet.querySelectorAll(".paper-schedule").forEach(table=>table.classList.add("comparison-enabled"));
    const heading = packet.querySelector("h1");
    document.title = heading ? heading.textContent.trim() : originalTitle;
  }
}
document.querySelectorAll("[data-print-packet]").forEach(button => {
  button.addEventListener("click", () => {
    const packet = document.getElementById(button.dataset.printPacket);
    if (!packet) return;
    originalTitle = document.title;
    preparePrint(packet);
    window.print();
  });
});
window.addEventListener("beforeprint", () => {
  if (!selectedPacket) {
    originalTitle = document.title;
    preparePrint(document.getElementById("manual-print") || document.getElementById("draft-print") || document.getElementById("saved-print") || document.getElementById("working-print"));
  }
  fitMonthlySheet();
});
window.addEventListener("afterprint", () => {
  preparePrint(null);
  document.title = originalTitle;
});


document.querySelectorAll("[data-compare-schedule]").forEach(control => {
  control.addEventListener("change", () => {
    const scope = control.dataset.compareSchedule;
    const enabled = control.checked;
    document.querySelectorAll("[data-comparison-scope]").forEach(table => {
      if (table.dataset.comparisonScope === scope) table.classList.toggle("comparison-enabled", enabled);
    });
    document.querySelectorAll("[data-compare-schedule]").forEach(other => {
      if (other.dataset.compareSchedule === scope) other.checked = enabled;
    });
  });
});

let focusedSheet = null;
let sheetFocusButton = null;
function closeSheetFocus() {
  if (!focusedSheet) return;
  focusedSheet.classList.remove("sheet-focused");
  if (sheetFocusButton) {
    sheetFocusButton.textContent = "表を大きく表示";
    sheetFocusButton.setAttribute("aria-pressed", "false");
    sheetFocusButton.focus();
  }
  document.body.classList.remove("sheet-focus-open");
  focusedSheet = null;
}
document.querySelectorAll("[data-sheet-focus]").forEach(button => {
  button.addEventListener("click", () => {
    const sheet = button.closest(".paper-schedule");
    if (focusedSheet === sheet) { closeSheetFocus(); return; }
    closeSheetFocus();
    focusedSheet = sheet;
    sheetFocusButton = button;
    sheet.classList.add("sheet-focused");
    document.body.classList.add("sheet-focus-open");
    button.textContent = "元の画面に戻る（Esc）";
    button.setAttribute("aria-pressed", "true");
  });
});
document.addEventListener("keydown", event => {
  if (!focusedSheet) return;
  if (event.key === "Escape") { event.preventDefault(); closeSheetFocus(); }
  if (event.key === "Tab") {
    const controls = [...focusedSheet.querySelectorAll("button, input, summary, a[href]")].filter(el => el.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
