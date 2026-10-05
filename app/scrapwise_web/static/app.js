"use strict";

const ui = Object.fromEntries([
  "workbench", "reset-button", "shape-count", "copy-count", "copy-label",
  "stock-list", "part-gap", "edge-margin", "command-form", "command",
  "create-button", "create-label", "response", "response-message", "retry-button",
  "last-request", "last-request-message", "download-button", "drawing-status",
  "zoom-out", "zoom-fit", "zoom-in", "drawing-viewport", "drawing-empty",
  "drawing-image-wrap", "layout-image", "result-strip", "result-pieces",
  "result-sheets", "result-purchased", "file-check-title", "file-check-detail",
  "layout-note"
].map(id => [id, document.getElementById(id)]));
const examples = [...document.querySelectorAll(".example-button")];
let sessionId = null;
let busy = false;
let imageUrl = null;
let hasLayout = false;
let imageAspectRatio = 1;
let zoom = 1;

function number(value, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US", {maximumFractionDigits: digits}) : "—";
}

function setBusy(value) {
  busy = value;
  ui.workbench.classList.toggle("is-busy", value);
  ui["command-form"].setAttribute("aria-busy", String(value));
  ui.command.disabled = value || !sessionId;
  ui["create-button"].disabled = value || !sessionId;
  ui["reset-button"].disabled = value || !sessionId;
  examples.forEach(button => { button.disabled = value || !sessionId; });
  ui["retry-button"].disabled = value;
  ui["create-label"].textContent = value ? "Creating layout…" : "Create layout";
}

function tell(message, kind = "ready") {
  ui.response.dataset.kind = kind;
  ui["response-message"].textContent = message;
}

async function api(path, data) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data)
  });
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error("The workshop could not complete this request. Try again."); }
  if (!response.ok) {
    throw new Error(payload.assistantMessage || payload.message || "The workshop could not complete this request. Try again.");
  }
  return payload;
}

function isPurchase(stock) {
  return ["purchase", "purchased", "new"].includes(stock.kind);
}

function stockName(stock) {
  const match = String(stock.id).match(/^scrap[-_ ]?(\d+)$/i);
  if (match) return `Scrap ${match[1]}`;
  if (isPurchase(stock)) return "New sheet option";
  return String(stock.id).replace(/[-_]/g, " ");
}

function updateState(state) {
  if (!state) return;
  ui["shape-count"].textContent = number(state.shapeCount, 0);
  if (state.copyCount !== null && state.copyCount !== undefined) {
    ui["copy-count"].textContent = number(state.copyCount, 0);
    ui["copy-label"].textContent = state.copyCount === 1 ? "copy of each" : "copies of each";
  } else {
    ui["copy-count"].textContent = "Mixed";
    ui["copy-label"].textContent = "part quantities";
  }
  ui["part-gap"].textContent = number(state.spacing);
  ui["edge-margin"].textContent = number(state.margin);
  ui["stock-list"].replaceChildren();
  for (const stock of state.stock || []) {
    const row = document.createElement("li");
    if (stock.quantity === 0) row.classList.add("stock-unavailable");
    const name = document.createElement("span");
    name.className = "stock-name";
    const swatch = document.createElement("span");
    swatch.className = "stock-swatch";
    swatch.setAttribute("aria-hidden", "true");
    if (isPurchase(stock)) swatch.classList.add("new");
    name.append(swatch, document.createTextNode(stockName(stock)));
    const quantity = document.createElement("span");
    quantity.className = "stock-quantity";
    quantity.textContent = `${isPurchase(stock) ? "≤" : "×"}${number(stock.quantity, 0)}`;
    const size = document.createElement("span");
    size.className = "stock-size";
    size.textContent = `${number(stock.width)} × ${number(stock.height)}`;
    row.append(name, quantity, size);
    ui["stock-list"].append(row);
  }
}

function fitImage() {
  if (!hasLayout) return;
  const viewport = ui["drawing-viewport"];
  const width = Math.max(100, viewport.clientWidth - 50);
  const height = Math.max(100, viewport.clientHeight - 60);
  const fitWidth = Math.min(width, height * imageAspectRatio);
  ui["layout-image"].style.width = `${Math.max(100, fitWidth * zoom)}px`;
}

function enableDownload(url) {
  const link = ui["download-button"];
  if (url) {
    link.href = url;
    link.setAttribute("download", "scrapwise-layout.svg");
    link.setAttribute("aria-disabled", "false");
    link.tabIndex = 0;
  } else {
    link.removeAttribute("href");
    link.removeAttribute("download");
    link.setAttribute("aria-disabled", "true");
    link.tabIndex = -1;
  }
}

function clearLayout() {
  hasLayout = false;
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = null;
  ui["layout-image"].removeAttribute("src");
  ui["drawing-image-wrap"].hidden = true;
  ui["drawing-empty"].hidden = false;
  ui["result-strip"].hidden = true;
  ui["drawing-status"].textContent = "Awaiting a request";
  ui["layout-note"].textContent = "Each request creates a new layout from the current job. Unchanged dimensions stay as they are.";
  ["zoom-out", "zoom-fit", "zoom-in"].forEach(id => { ui[id].disabled = true; });
  enableDownload(null);
}

function showLayout(result) {
  if (typeof result.svg !== "string" || !result.svg.trim() || !result.downloadUrl || result.fileCheckSummary?.valid !== true) {
    throw new Error("The cutting file is not ready. Try the request again.");
  }
  const parsed = new DOMParser().parseFromString(result.svg, "image/svg+xml");
  const svg = parsed.documentElement;
  if (svg.localName !== "svg" || parsed.querySelector("parsererror")) {
    throw new Error("The cutting file could not be displayed. Try the request again.");
  }
  const viewBox = svg.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
  const width = viewBox?.length === 4 ? viewBox[2] : parseFloat(svg.getAttribute("width"));
  const height = viewBox?.length === 4 ? viewBox[3] : parseFloat(svg.getAttribute("height"));
  imageAspectRatio = width > 0 && height > 0 ? width / height : 1;
  const nextUrl = URL.createObjectURL(new Blob([result.svg], {type: "image/svg+xml"}));
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = nextUrl;
  hasLayout = true;
  zoom = 1;
  ui["layout-image"].src = imageUrl;
  ui["layout-image"].alt = `Actual cutting layout containing ${number(result.requiredPieces, 0)} pieces on ${number(result.usedSheets, 0)} sheets`;
  ui["drawing-empty"].hidden = true;
  ui["drawing-image-wrap"].hidden = false;
  ui["result-strip"].hidden = false;
  ui["result-pieces"].textContent = number(result.requiredPieces, 0);
  ui["result-sheets"].textContent = number(result.usedSheets, 0);
  ui["result-purchased"].textContent = `${number(result.purchasedArea)} units²`;
  ui["file-check-title"].textContent = "File checked";
  ui["file-check-detail"].textContent = `${number(result.fileCheckSummary.actualSVGCopies, 0)} parts included · spacing checked`;
  ui["drawing-status"].textContent = `${number(result.requiredPieces, 0)} pieces / ${number(result.usedSheets, 0)} ${result.usedSheets === 1 ? "sheet" : "sheets"}`;
  ui["layout-note"].textContent = "This preview shows the actual SVG file. Download it to use the layout outside this workbench.";
  ["zoom-out", "zoom-fit", "zoom-in"].forEach(id => { ui[id].disabled = false; });
  enableDownload(result.downloadUrl);
  fitImage();
  ui["drawing-viewport"].scrollTo({left: 0, top: 0});
}

async function startSession() {
  if (busy) return;
  setBusy(true);
  ui["retry-button"].hidden = true;
  tell("Opening your workshop…");
  try {
    const result = await api("/api/session", {});
    if (!result.sessionId || !result.state) throw new Error("The workshop could not open. Try again.");
    sessionId = result.sessionId;
    updateState(result.state);
    tell("Your original parts and stock are ready. Write a request to create a cutting file.");
  } catch (error) {
    tell(error.message || "The workshop could not open. Try again.", "error");
    ui["retry-button"].hidden = false;
  } finally {
    setBusy(false);
  }
}

ui["command-form"].addEventListener("submit", async event => {
  event.preventDefault();
  if (busy || !sessionId) return;
  const message = ui.command.value.trim();
  if (!message) { ui.command.focus(); return; }
  setBusy(true);
  tell("Creating your cutting layout from the current job…");
  ui["last-request"].hidden = false;
  ui["last-request-message"].textContent = message;
  try {
    const result = await api("/api/command", {sessionId, message});
    if (result.status === "complete") {
      showLayout(result);
      updateState(result.state);
      tell(result.assistantMessage || "Your cutting layout is ready. Download the checked SVG file.", "complete");
    } else if (result.status === "clarify") {
      updateState(result.state);
      tell(result.assistantMessage || "Use a whole-number copy count or name the stock you want to change.", "clarify");
    } else {
      updateState(result.state);
      tell(result.assistantMessage || "This request could not create a cutting file. Try another request.", "error");
    }
  } catch (error) {
    tell(error.message || "The workshop could not complete this request. Try again.", "error");
  } finally {
    setBusy(false);
  }
});

examples.forEach(button => button.addEventListener("click", () => {
  if (busy) return;
  ui.command.value = button.dataset.message;
  ui.command.focus();
}));

ui["reset-button"].addEventListener("click", async () => {
  if (busy || !sessionId) return;
  setBusy(true);
  tell("Restoring the original parts and stock…");
  try {
    const result = await api("/api/reset", {sessionId});
    if (!result.state || result.status !== "reset") throw new Error("The workshop could not reset. Try again.");
    updateState(result.state);
    clearLayout();
    ui.command.value = "";
    ui["last-request"].hidden = true;
    tell(result.assistantMessage || "Original parts and stock restored. Create a new layout.");
  } catch (error) {
    tell(error.message || "The workshop could not reset. Try again.", "error");
  } finally {
    setBusy(false);
  }
});

ui["retry-button"].addEventListener("click", startSession);
ui["download-button"].addEventListener("click", event => {
  if (ui["download-button"].getAttribute("aria-disabled") === "true") event.preventDefault();
});
ui["zoom-in"].addEventListener("click", () => { zoom = Math.min(4, zoom + .25); fitImage(); });
ui["zoom-out"].addEventListener("click", () => { zoom = Math.max(.5, zoom - .25); fitImage(); });
ui["zoom-fit"].addEventListener("click", () => { zoom = 1; fitImage(); ui["drawing-viewport"].scrollTo({left: 0, top: 0}); });
window.addEventListener("resize", fitImage);
window.addEventListener("beforeunload", () => { if (imageUrl) URL.revokeObjectURL(imageUrl); });
startSession();
