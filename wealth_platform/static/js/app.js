const $ = (id) => document.getElementById(id);
let mode = "login";
let charts = {};
let currentUser = null;

const today = new Date().toISOString().slice(0, 10);
$("txDate").value = today;
$("recDue").value = today;

function money(v) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currentUser?.base_currency || "USD",
    maximumFractionDigits: 2
  }).format(Number(v || 0));
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    credentials: "include",
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options
  });
  if (!res.ok) {
    let msg = "Request failed";
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function setMode(next) {
  mode = next;
  $("loginTab").className = `btn flex-1 ${mode === "login" ? "bg-indigo-500" : "bg-slate-800"}`;
  $("signupTab").className = `btn flex-1 ${mode === "signup" ? "bg-indigo-500" : "bg-slate-800"}`;
  $("nameWrap").classList.toggle("hidden", mode !== "signup");
}

$("loginTab").onclick = () => setMode("login");
$("signupTab").onclick = () => setMode("signup");

$("authForm").onsubmit = async (e) => {
  e.preventDefault();
  $("authError").textContent = "";
  try {
    const body = {
      email: $("email").value,
      password: $("password").value
    };
    if (mode === "signup") {
      body.full_name = $("name").value;
      body.base_currency = $("authCurrency").value;
    }
    currentUser = await api(`/api/auth/${mode === "signup" ? "signup" : "login"}`, {
      method: "POST", body: JSON.stringify(body)
    });
    await startApp();
  } catch (err) {
    $("authError").textContent = err.message;
  }
};

$("logout").onclick = async () => {
  await api("/api/auth/logout", {method:"POST"});
  location.reload();
};

$("baseCurrency").onchange = async () => {
  currentUser = await api(`/api/profile/currency?currency=${$("baseCurrency").value}`, {method:"PATCH"});
  await refresh();
};

async function startApp() {
  $("auth").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("baseCurrency").value = currentUser.base_currency;
  lucide.createIcons();
  await refresh();
}

async function refresh() {
  const [analytics, txs] = await Promise.all([
    api("/api/analytics"),
    loadTransactions()
  ]);
  renderMetrics(analytics);
  renderCharts(analytics);
  renderLedger(txs);
  lucide.createIcons();
}

function renderMetrics(a) {
  $("totalIncome").textContent = money(a.total_income);
  $("totalExpenses").textContent = money(a.total_expenses);
  $("projected").textContent = money(a.projected_month_end_spend);
  $("burn").textContent = `${Number(a.budget_burn_percent).toFixed(1)}%`;
}

function renderCharts(a) {
  const timeline = a.timeline || [];
  const categories = a.category_breakdown || [];

  if (charts.timeline) charts.timeline.destroy();
  charts.timeline = new ApexCharts($("timelineChart"), {
    chart: {type:"area", height:330, toolbar:{show:false}, animations:{enabled:true}},
    series: [
      {name:"Income", data:timeline.map(x=>[new Date(x.date).getTime(), x.income])},
      {name:"Expenses", data:timeline.map(x=>[new Date(x.date).getTime(), x.expense])}
    ],
    xaxis:{type:"datetime", labels:{style:{colors:"#94a3b8"}}},
    yaxis:{labels:{formatter:v=>money(v), style:{colors:"#94a3b8"}}},
    stroke:{curve:"smooth", width:2},
    fill:{type:"gradient", gradient:{opacityFrom:.35, opacityTo:.03}},
    legend:{labels:{colors:"#cbd5e1"}},
    grid:{borderColor:"#1e293b"},
    theme:{mode:"dark"},
    tooltip:{shared:true, x:{format:"dd MMM"}}
  });
  charts.timeline.render();

  if (charts.donut) charts.donut.destroy();
  charts.donut = new ApexCharts($("donutChart"), {
    chart:{type:"donut", height:330, events:{
      dataPointSelection:(event, chartContext, config)=>{
        const c = categories[config.dataPointIndex]?.category;
        if (c) { $("search").value = c; loadTransactions().then(renderLedger); }
      }
    }},
    labels:categories.map(x=>x.category),
    series:categories.map(x=>Number(x.amount)),
    legend:{position:"bottom", labels:{colors:"#cbd5e1"}},
    theme:{mode:"dark"},
    dataLabels:{enabled:false},
    tooltip:{y:{formatter:v=>money(v)}}
  });
  charts.donut.render();
}

async function loadTransactions() {
  const p = new URLSearchParams();
  if ($("search").value) p.set("q", $("search").value);
  if ($("kindFilter").value) p.set("kind", $("kindFilter").value);
  if ($("minAmount").value) p.set("min_amount", $("minAmount").value);
  if ($("maxAmount").value) p.set("max_amount", $("maxAmount").value);
  return api(`/api/transactions?${p}`);
}

function renderLedger(txs) {
  $("ledger").innerHTML = txs.map(t => `
    <tr class="border-b border-slate-900 hover:bg-slate-800/40 transition">
      <td class="p-3 text-slate-400">${t.transaction_date}</td>
      <td class="p-3"><div class="font-medium">${escapeHtml(t.merchant || "—")}</div><div class="text-xs text-slate-500">${escapeHtml(t.note || "")}</div></td>
      <td class="p-3"><span class="rounded-full bg-slate-800 px-2 py-1 text-xs">${escapeHtml(t.category)}</span></td>
      <td class="p-3 text-right ${t.kind === "income" ? "text-emerald-400" : "text-rose-400"}">${t.kind === "income" ? "+" : "-"}${money(t.amount_base)}</td>
      <td class="p-3 text-right"><button onclick="removeTx(${t.id})" class="text-slate-500 hover:text-rose-400"><i data-lucide="trash-2" class="w-4"></i></button></td>
    </tr>
  `).join("");
  lucide.createIcons();
}

window.removeTx = async (id) => {
  await api(`/api/transactions/${id}`, {method:"DELETE"});
  await refresh();
};

$("txForm").onsubmit = async e => {
  e.preventDefault();
  await api("/api/transactions", {
    method:"POST",
    body:JSON.stringify({
      transaction_date:$("txDate").value,
      kind:$("txKind").value,
      amount:Number($("txAmount").value),
      currency:$("txCurrency").value,
      category:$("txCategory").value,
      merchant:$("txMerchant").value,
      note:$("txNote").value,
      tags:$("txTags").value.split(",").map(x=>x.trim()).filter(Boolean)
    })
  });
  e.target.reset();
  $("txDate").value=today;
  await refresh();
};

$("recForm").onsubmit = async e => {
  e.preventDefault();
  await api("/api/recurring", {
    method:"POST",
    body:JSON.stringify({
      name:$("recName").value,
      kind:"expense",
      amount:Number($("recAmount").value),
      currency:currentUser.base_currency,
      category:$("recCategory").value,
      frequency:$("recFrequency").value,
      next_due:$("recDue").value,
      active:true
    })
  });
  e.target.reset();
  $("recDue").value=today;
  alert("Recurring transaction scheduled.");
};

["search","kindFilter","minAmount","maxAmount"].forEach(id => {
  $(id).addEventListener("input", async () => renderLedger(await loadTransactions()));
  $(id).addEventListener("change", async () => renderLedger(await loadTransactions()));
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}

(async () => {
  try {
    currentUser = await api("/api/auth/me");
    await startApp();
  } catch {
    $("auth").classList.remove("hidden");
    $("app").classList.add("hidden");
    lucide.createIcons();
  }
})();
