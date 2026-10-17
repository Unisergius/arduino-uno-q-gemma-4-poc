// Garden Steward web page: polls /api/state every 2 s and sends button presses to /api/action.

const ICONS = { ok: "✅", think: "💭", water: "💧", alert: "⚠️" };
const BUSY = { decide: "Gemma is deciding…", ask: "Gemma is answering…", photo: "Gemma is looking at the photo…", journal: "Gemma is writing the journal…" };
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
  const source = e.source || (e.kind === "manual" ? "manual" : "gemma");
  const badge = `<span class="badge ${source.startsWith("gemma") ? "gemma" : "fallback"}">${esc(source)}</span>`;
  let text;
  switch (e.kind) {
    case "decision":
      text = `Zone ${e.zone}: <b>${esc(e.action)}${e.action === "water" ? " " + e.seconds + " s" : ""}</b> – ${esc(e.reason)}${mcuText(e.mcu)}`;
      break;
    case "ask":
      text = `Q: ${esc(e.question)}<br>A: ${esc(e.answer)}${mcuText(e.mcu)}`;
      break;
    case "see":
      text = `Photo: <b>${esc(e.status)}</b> (${esc(e.confidence)}) – ${esc(e.issue)}`;
      break;
    case "journal":
      text = `📓 ${esc(e.text)}`;
      break;
    case "manual":
      text = `Forced: water zone ${e.zone} for ${e.seconds} s${mcuText(e.mcu)}`;
      break;
    default:
      text = `Error in ${esc(e.job)}: ${esc(e.error)}`;
  }
  if (e.error && e.kind === "decision") text += ` <span class="small">(${esc(e.error)})</span>`;
  return `<li><span class="small">${esc(e.time)}</span> ${badge}${text}${timing(e.llm)}</li>`;
}

function render(s) {
  $("icon").textContent = ICONS[s.icon] || "✅";
  $("time").textContent = s.time;
  $("busy").textContent = s.busy ? BUSY[s.busy] : s.queued ? `${s.queued} job(s) waiting` : "Gemma idle";
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
      <div class="small">target ${low}–${high} %</div>
    </div>`;
  }).join("");

  const real = s.real_sensors && (s.real_sensors.thermo || s.real_sensors.pressure) ? " (real sensor)" : "";
  $("weather").innerHTML = [
    `🌡️ ${g.temp_c} °C${real}`, `💧 ${g.humidity} %`, `☀️ ${g.light} %`, `🧭 ${g.pressure_hpa} hPa`,
    `🔋 ${g.battery} %`, g.tank_empty ? "🚱 tank empty" : "🚰 tank ok",
    `scenario: ${g.scenario.replace("_", " ")}`, g.raining ? "🌧️ raining" : "",
  ].filter(Boolean).map((c) => `<span class="chip">${c}</span>`).join("");

  if (s.answer) $("answer").innerHTML = `<b>${esc(s.answer.answer)}</b>${mcuText(s.answer.mcu)}${timing(s.answer.llm)}`;
  if (s.photo) $("photo-result").innerHTML = `<b>${esc(s.photo.status)}</b> (${esc(s.photo.confidence)}): ${esc(s.photo.issue)}${timing(s.photo.llm)}`;
  $("log").innerHTML = s.log.map(logLine).join("") || '<li class="muted">Nothing yet – Gemma looks at the garden every 2 simulated hours.</li>';
  if (s.last_prompt) $("prompt").textContent = s.last_prompt;
}

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
