
// ==============================================================================
// ПІДСУМОК ТА АРХІТЕКТУРНІ ЗАМІТКИ: app/static/app.js
// ==============================================================================

// Роль коду в системі:
// "Оновлює та візуалізує дані" (Frontend Interactivity & Dashboard Controller).

// Призначення:
// Клієнтський JavaScript-скрипт (Vanilla SPA) для відображення метричних даних 
// дашборду, управління пошуковими кампаніями, інвентарем та перегляду бухгалтерського балансу.

// Ключові паттерни та рішення розробника:
// 1. Zero-Dependency SPA Architecture:
//    Побудова інтерактивного дашборду на чистому JavaScript (ES6) без використання 
//    важких фронтенд-фреймворків чи етапів збірки.
// 2. Централізований HTTP Wrapper (`api`):
//    Єдина обгортка для `fetch`, яка автоматично додає JSON-заголовки, обробляє 
//    статуси відповідей та витягує деталі помилок у тоасти.
// 3. Оптимізація пам'яті через Event Delegation:
//    Використання `e.target.closest("button")` на рівні всієї таблиці замість 
//    вішання обробників подій на кожен окремий рядок.
// 4. Локалізація та регулярне опитування (Polling):
//    Використання `Intl.NumberFormat("uk-UA")` для форматування гривень та 
//    `setInterval(loadDashboard, 5000)` для автооновлення KPI.

// Оцінка коду та покращення:
// - Плюси: Легковажний, миттєво завантажується, чиста асинхронна логіка через async/await.
// - Мінуси: Вставка динамічних даних через `innerHTML` створює ризик DOM-XSS 
//   (доцільно замінити вставку тексту на безпечний `textContent`).
// ==============================================================================





const UAH = (v) =>
  v == null ? "—" : new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 }).format(v) + " UAH";
const PCT = (v) => (v == null ? "—" : `${v}%`);

let selectedCampaign = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail || JSON.stringify(body);
    } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg, isErr = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (el.className = "toast"), 3000);
}

async function loadDashboard() {
  const d = await api("/api/dashboard");
  document.getElementById("kpi-capital").textContent = UAH(d.total_capital);
  const profitEl = document.getElementById("kpi-profit");
  profitEl.textContent = (d.net_profit_month >= 0 ? "+" : "") + UAH(d.net_profit_month);
  profitEl.className = "kpi-value " + (d.net_profit_month >= 0 ? "pos" : "neg");
  document.getElementById("kpi-stock").textContent = d.items_in_stock + " од.";
  document.getElementById("kpi-roi").textContent = PCT(d.avg_deal_roi);

  const m = d.metrics;
  document.getElementById("m-turnover").textContent = m.turnover_ratio ?? "—";
  document.getElementById("m-realization").textContent =
    m.avg_realization_days != null ? m.avg_realization_days + " дн." : "—";
  document.getElementById("m-roc").textContent = PCT(m.return_on_capital_pct);
  document.getElementById("m-rejected").textContent = PCT(m.rejected_ratio_pct);
}

async function loadCampaigns() {
  const rows = await api("/api/campaigns");
  const tbody = document.querySelector("#campaigns-table tbody");
  tbody.innerHTML = "";
  for (const c of rows) {
    const tr = document.createElement("tr");
    const toggle = c.status === "active" ? "paused" : "active";
    tr.innerHTML = `
      <td>${c.id}</td>
      <td>${c.query}</td>
      <td>${UAH(c.market_price)}</td>
      <td><span class="pill ${c.status}">${c.status}</span></td>
      <td>${c.scanned_count}/${c.rejected_count}</td>
      <td class="actions">
        <button class="ghost" data-scan="${c.id}">Сканувати</button>
        <button class="ghost" data-status="${c.id}" data-to="${toggle}">${toggle === "active" ? "Активувати" : "Пауза"}</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function loadDeals(campaignId) {
  const offers = await api(`/api/campaigns/${campaignId}/offers?deals_only=true`);
  const tbody = document.querySelector("#deals-table tbody");
  const hint = document.getElementById("deals-hint");
  tbody.innerHTML = "";
  if (!offers.length) {
    hint.textContent = "Для цієї кампанії ще немає вигідних лотів.";
    return;
  }
  hint.textContent = `Кампанія #${campaignId}: знайдено ${offers.length} лотів.`;
  for (const o of offers) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><a href="${o.url}" target="_blank" rel="noopener">${o.title}</a></td>
      <td>${UAH(o.price)}</td>
      <td>${PCT(o.discount)}</td>
      <td>${o.score}</td>
      <td class="${o.net_profit >= 0 ? "pos" : "neg"}">${UAH(o.net_profit)}</td>
      <td class="risks">${o.risks || "—"}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadInventory() {
  const rows = await api("/api/inventory");
  const tbody = document.querySelector("#inventory-table tbody");
  tbody.innerHTML = "";
  for (const i of rows) {
    const tr = document.createElement("tr");
    const sellBtn =
      i.status === "sold"
        ? ""
        : `<button class="ghost" data-sell="${i.id}" data-price="${i.estimated_market_price}">Продати</button>`;
    tr.innerHTML = `
      <td>${i.id}</td>
      <td>${i.title}</td>
      <td>${UAH(i.capitalised_cost)}</td>
      <td><span class="pill ${i.status === "sold" ? "sold" : "active"}">${i.status}</span></td>
      <td class="actions">${sellBtn}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadLedger() {
  const rows = await api("/api/ledger/trial-balance");
  const tbody = document.querySelector("#ledger-table tbody");
  tbody.innerHTML = "";
  for (const a of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${a.code}</td><td>${a.name}</td><td>${a.class}</td><td>${UAH(a.balance)}</td>`;
    tbody.appendChild(tr);
  }
}

async function refreshAll() {
  await Promise.all([loadDashboard(), loadCampaigns(), loadInventory(), loadLedger()]);
  if (selectedCampaign) await loadDeals(selectedCampaign);
}

// ---- events ----
document.getElementById("campaign-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const c = await api("/api/campaigns", {
      method: "POST",
      body: JSON.stringify({
        query: f.get("query"),
        min_discount: parseFloat(f.get("min_discount")),
        weight_kg: parseFloat(f.get("weight_kg")),
      }),
    });
    toast(`Кампанію «${c.query}» навчено. Ринкова: ${UAH(c.market_price)}`);
    e.target.reset();
    await refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("buy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/inventory/buy", {
      method: "POST",
      body: JSON.stringify({
        title: f.get("title"),
        purchase_price: parseFloat(f.get("purchase_price")),
        estimated_market_price: parseFloat(f.get("estimated_market_price")),
        delivery_cost: parseFloat(f.get("delivery_cost") || "0"),
      }),
    });
    toast("Товар придбано та проведено в обліку.");
    e.target.reset();
    await refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("capital-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("/api/ledger/capital", {
      method: "POST",
      body: JSON.stringify({ amount: parseFloat(f.get("amount")) }),
    });
    toast("Капітал внесено.");
    e.target.reset();
    await refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
});

document.querySelector("#campaigns-table").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  try {
    if (btn.dataset.scan) {
      selectedCampaign = parseInt(btn.dataset.scan, 10);
      const r = await api(`/api/campaigns/${selectedCampaign}/scan`, { method: "POST" });
      toast(`Сканування завершено: ${r.deals_found} вигідних лотів.`);
      await refreshAll();
    } else if (btn.dataset.status) {
      await api(`/api/campaigns/${btn.dataset.status}/status?status=${btn.dataset.to}`, {
        method: "POST",
      });
      await refreshAll();
    }
  } catch (err) {
    toast(err.message, true);
  }
});

document.querySelector("#inventory-table").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn || !btn.dataset.sell) return;
  const price = prompt("Ціна продажу (UAH):", btn.dataset.price);
  if (!price) return;
  try {
    await api(`/api/inventory/${btn.dataset.sell}/sell`, {
      method: "POST",
      body: JSON.stringify({ sale_price: parseFloat(price) }),
    });
    toast("Продаж проведено (виручка + списання собівартості).");
    await refreshAll();
  } catch (err) {
    toast(err.message, true);
  }
});

async function init() {
  try {
    const h = await api("/api/health");
    const badge = document.getElementById("mode-badge");
    badge.textContent = h.simulation_mode ? "SIMULATION MODE" : "LIVE MODE";
    badge.className = "badge " + (h.simulation_mode ? "sim" : "live");
  } catch (_) {}
  await refreshAll();
  setInterval(loadDashboard, 5000);
}

init();
