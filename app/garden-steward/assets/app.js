// Garden Steward web page: polls /api/state every 2 s and sends button presses to /api/action.

const ICONS = { ok: "✅", think: "💭", water: "💧", alert: "⚠️" };
const BUSY = { decide: "Gemma is deciding…", ask: "Gemma is answering…", photo: "Gemma is looking at the photo…", snap: "Taking a photo…", journal: "Gemma is writing the journal…" };
const JOBS = { decide: "deciding", ask: "answering", photo: "the photo check", snap: "taking the photo", journal: "the journal" };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function send(action) {
  const response = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });
  const result = await response.json();
  refresh();
  return result;
}

function timing(llm) {
  if (!llm) return "";
  const speed = llm.decode_tok_s ? `, ${llm.decode_tok_s} tok/s` : "";
  return ` <span class="small">(Gemma ${llm.seconds} s${speed})</span>`;
}

function mcuText(mcu) {
  if (!mcu) return "";
  if (!mcu.ok) return ` <span class="badge refused">MCU refused</span>${esc(mcu.note)}`;
  const note = mcu.note ? ` – ${esc(mcu.note)}` : "";
  return ` <span class="badge ok">pump ${mcu.seconds} s</span>${note}`;
}

function logLine(e) {
  const source = e.source || { manual: "manual", error: "problem" }[e.kind] || "gemma";
  const style = source.startsWith("gemma") ? "gemma" : source === "problem" ? "refused" : "fallback";
  const badge = `<span class="badge ${style}">${esc(source)}</span>`;
  let text;
  switch (e.kind) {
    case "decision":
      text = `Zone ${e.zone}: <b>${esc(e.action)}${e.action === "water" ? " " + e.seconds + " s" : ""}</b> – ${esc(e.reason)}${mcuText(e.mcu)}`;
      break;
    case "ask":
      text = `Q: ${esc(e.question)}<br>A: ${esc(e.answer)}${mcuText(e.mcu)}`;
      break;
    case "see":
      text = `Photo${e.test_photo ? ` (test drawing: ${esc(e.test_photo)})` : ""}: <b>${esc(e.status)}</b> (${esc(e.confidence)}) – ${esc(e.issue)}`;
      break;
    case "journal":
      text = `📓 ${esc(e.text)}`;
      break;
    case "manual":
      text = `Forced: water zone ${e.zone} for ${e.seconds} s${mcuText(e.mcu)}`;
      break;
    default:
      text = `Problem with ${esc(JOBS[e.job] || e.job)}: ${esc(e.error)}`;
  }
  if (e.error && e.kind === "decision") text += ` <span class="small">(${esc(e.error)})</span>`;
  return `<li><span class="small">${esc(e.time)}</span> ${badge}${text}${timing(e.llm)}</li>`;
}

let autoOn = true;
function render(s) {
  $("icon").textContent = ICONS[s.icon] || "✅";
  $("time").textContent = s.time;
  $("busy").textContent = (s.busy ? BUSY[s.busy] : s.queued ? `${s.queued} job(s) waiting` : "Gemma idle")
    + (s.auto ? "" : " · automatic decisions paused");
  autoOn = s.auto;
  $("auto-button").textContent = s.auto ? "⏸ Pause automatic decisions" : "▶ Resume automatic decisions";
  $("gemma").textContent = `Gemma: ${s.gemma}`;

  const g = s.garden;
  $("zones").innerHTML = Object.entries(s.zones).map(([zone, z]) => {
    const m = g.moisture[zone];
    const [low, high] = z.target;
    return `<div class="zone">
      <div class="small">Zone ${zone}</div>
      <div><b>${esc(z.plant)}</b></div>
      <div class="value">${m.toFixed(0)} %</div>
      <div class="bar"><div class="target" style="left:${low}%;width:${high - low}%"></div><div class="fill" style="width:${m}%"></div></div>
      <div class="small">target ${low}–${high} % · ${g.sources.soil[zone] === "sensor" ? (zone === "1" ? "knob" : "probe") + " + watering bonus" : "simulated"}</div>
    </div>`;
  }).join("");

  const tag = (source) => (source === "sensor" ? " <b>(sensor)</b>" : "");
  $("weather").innerHTML = [
    `🌡️ ${g.temp_c} °C${tag(g.sources.temp)}`, `💧 ${g.humidity} %`, `☀️ ${g.light} %${tag(g.sources.light)}`,
    `🧭 ${g.pressure_hpa} hPa`, `🔋 ${g.battery} %`, g.tank_empty ? "🚱 tank empty" : "🚰 tank ok",
    `scenario: ${g.scenario.replace("_", " ")}`, g.raining ? `🌧️ raining${tag(g.sources.rain)}` : "",
  ].filter(Boolean).map((c) => `<span class="chip">${c}</span>`).join("");
  if (s.raw_sensors && Object.keys(s.raw_sensors).length) $("raw").textContent = JSON.stringify(s.raw_sensors, null, 1);
  $("camera-status").textContent = s.camera
    ? `reCamera: ${s.camera} – press the yellow button or "Check now".`
    : "No camera: “Check now” and the yellow button show Gemma the test drawing picked here. Or take a real photo with your phone.";
  renderTestPhotos(s);
  renderBench(s.bench);
  renderWired(s);
  // "Dry zone" only works for a zone without a sensor: on a sensor zone, turn the knob or slider instead.
  document.querySelectorAll("button[data-action]").forEach((button) => {
    const action = JSON.parse(button.dataset.action);
    if (action.type === "dry") button.hidden = g.sources.soil[action.zone] === "sensor";
  });

  if (s.answer) $("answer").innerHTML = `<b>${esc(s.answer.answer)}</b>${mcuText(s.answer.mcu)}${timing(s.answer.llm)}`;
  if (s.photo) $("photo-result").innerHTML = `<b>${esc(s.photo.status)}</b> (${esc(s.photo.confidence)}): ${esc(s.photo.leaves)}${timing(s.photo.llm)}`;
  $("log").innerHTML = s.log.map(logLine).join("") || '<li class="muted">Nothing yet – Gemma looks at the garden every 2 simulated hours.</li>';
  if (s.last_prompt) $("prompt").textContent = s.last_prompt;
}

// The pretend camera: pick which built-in drawing it "sees".
function renderTestPhotos(s) {
  const box = $("test-photos");
  box.hidden = Boolean(s.camera);
  if (!box.children.length) {
    box.innerHTML = s.test_photos.map((name) => `<button class="thumb" data-photo="${esc(name)}">
      <img src="test-photos/${esc(name)}.png" alt="Test drawing: ${esc(name)} plants"><span>${esc(name)}</span></button>`).join("");
  }
  box.querySelectorAll(".thumb").forEach((b) => b.classList.toggle("selected", b.dataset.photo === s.test_photo));
}
$("test-photos").addEventListener("click", (event) => {
  const thumb = event.target.closest(".thumb");
  if (thumb) send({ type: "test_photo", value: thumb.dataset.photo });
});

// On the board: which kit sensors are really plugged in (A0 knob, A1 soil, A2 temp, A3 light, A4 steam).
const SENSOR_LABELS = { knob: "Knob (A0)", soil: "Soil probe (A1)", temp: "Temperature (A2)", light: "Light (A3)", steam: "Rain / steam (A4)" };
function renderWired(s) {
  $("wired-card").hidden = Boolean(s.bench);  // laptop mode: the test bench stands in for all of them
  const box = $("wired");
  if (!box.children.length) {
    box.innerHTML = s.all_sensors.map((name) =>
      `<label class="chip"><input type="checkbox" data-sensor="${esc(name)}"> ${esc(SENSOR_LABELS[name] || name)}</label>`).join("");
  }
  box.querySelectorAll("input").forEach((input) => { input.checked = s.wired.includes(input.dataset.sensor); });
}
$("wired").addEventListener("change", (event) => {
  const input = event.target.closest("input[data-sensor]");
  if (input) send({ type: "wired", name: input.dataset.sensor, on: input.checked });
});

// The laptop test bench: sliders start from the pretend sensors' values, then you move them.
let benchReady = false;
function renderBench(bench) {
  $("bench").hidden = !bench;
  if (!bench || benchReady) return;
  document.querySelectorAll("#bench [data-bench]").forEach((input) => {
    const value = bench[input.dataset.bench];
    if (input.type === "checkbox") input.checked = value;
    else input.value = value;
    showSlider(input);
  });
  benchReady = true;
}
function showSlider(input) {
  if (input.type === "range") input.parentElement.querySelector("output").textContent = input.value + input.dataset.unit;
}
document.querySelectorAll("#bench [data-bench]").forEach((input) => {
  input.addEventListener("input", () => showSlider(input));
  input.addEventListener("change", () => send({
    type: "bench", name: input.dataset.bench, value: input.type === "checkbox" ? input.checked : Number(input.value),
  }));
});
$("bench-button").addEventListener("click", () => send({ type: "button" }));
$("auto-button").addEventListener("click", () => send({ type: "auto", on: !autoOn }));

async function refresh() {
  try {
    render(await (await fetch("/api/state")).json());
  } catch (error) {
    $("busy").textContent = "Cannot reach the board…";
  }
}

// Buttons carry their action as JSON in data-action.
document.querySelectorAll("button[data-action]").forEach((button) => {
  button.addEventListener("click", () => send(JSON.parse(button.dataset.action)));
});

$("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  $("answer").textContent = "Asked – waiting for Gemma…";
  send({ type: "ask", question });
  $("question").value = "";
});

// Shrink the photo to 512 px before sending: smaller image = faster Gemma.
$("photo").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 512 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const imageB64 = canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
  $("photo-result").textContent = "Sent – Gemma is looking…";
  send({ type: "photo", image_b64: imageB64, mime: "image/jpeg" });
});

refresh();
setInterval(refresh, 2000);
