"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  token: null,
  expiryTimer: null,
  config: {},
  workspace: null,
  portfolio: null,
  instruments: [],
  instrument: null,
  cursor: null,
  account: null,
  reference: null,
  pendingOrder: null,
  pendingTrade: null,
  chartEpoch: 0,
  portfolioEpoch: 0,
  portfolioListEpoch: 0,
  referenceEpoch: 0,
};
class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}
const pretty = (value) =>
  value == null
    ? "—"
    : Math.abs(Number(value)) > 0 && Math.abs(Number(value)) < 0.0001
      ? Number(value).toPrecision(4)
      : new Intl.NumberFormat("en", { maximumFractionDigits: 4 }).format(
          Number(value),
        );
const label = (value) => (value || "unknown").replaceAll("_", " ");
const shortDate = (value) =>
  value
    ? new Date(value).toLocaleDateString("en", {
        month: "short",
        day: "numeric",
      })
    : "—";
function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}
async function api(path, options = {}) {
  const requestToken = state.token;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      },
    });
    const data = response.status === 204 ? null : await response.json();
    if (requestToken && requestToken !== state.token)
      throw new ApiError("Session changed; sign in again.", 401);
    if (!response.ok) {
      if (response.status === 401) signOut();
      throw new ApiError(
        typeof data?.detail === "string"
          ? data.detail
          : "Check the submitted values and try again.",
        response.status,
      );
    }
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "Connection interrupted. Retry the same submission to avoid duplicates.",
    );
  } finally {
    clearTimeout(timeout);
  }
}
const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body || {}) });
function bind(id, fn, event = "click") {
  $(id).addEventListener(event, async (e) => {
    e.preventDefault();
    const buttons = e.currentTarget.matches("button")
      ? [e.currentTarget]
      : [...e.currentTarget.querySelectorAll("button")];
    buttons.forEach((b) => (b.disabled = true));
    notice("");
    try {
      await fn(e);
    } catch (error) {
      notice(error.message);
    } finally {
      buttons.forEach((b) => (b.disabled = false));
    }
  });
}
function option(value, text) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = text;
  return el;
}
function textCell(row, text, small) {
  const td = document.createElement("td");
  td.textContent = text;
  if (small) {
    const s = document.createElement("small");
    s.textContent = small;
    td.append(s);
  }
  row.append(td);
  return td;
}
function emptyTable(id, message, columns = 6) {
  const tr = document.createElement("tr");
  const td = textCell(tr, message);
  td.colSpan = columns;
  $(id).replaceChildren(tr);
}
function workspaceRoot() {
  if (!state.workspace) throw new Error("Create or select a workspace first.");
  return `/v1/workspaces/${state.workspace}`;
}
function portfolioRoot() {
  if (!state.portfolio) throw new Error("Create or select a portfolio first.");
  return `${workspaceRoot()}/portfolios/${state.portfolio}`;
}
function signOut() {
  clearTimeout(state.expiryTimer);
  FinRiskLogin.clear();
  state.token = null;
  state.workspace = null;
  state.portfolio = null;
  state.account = null;
  state.pendingOrder = null;
  state.pendingTrade = null;
  state.chartEpoch++;
  state.portfolioEpoch++;
  state.referenceEpoch++;
  $("application").hidden = true;
  $("login-panel").hidden = false;
  $("logout").hidden = true;
  $("last-updated").textContent = "Not connected";
}
async function signedIn(data) {
  state.token = data.access_token;
  clearTimeout(state.expiryTimer);
  state.expiryTimer = setTimeout(
    () => {
      signOut();
      notice("Your session expired. Sign in again to continue.");
    },
    Math.min(data.expires_in * 1000, 2147483647),
  );
  $("login-panel").hidden = true;
  $("application").hidden = false;
  $("logout").hidden = false;
  await Promise.all([loadWorkspaces(), loadInstruments()]);
}
function navigationBusy(busy) {
  document
    .querySelectorAll(
      "#workspace,#sample-portfolio,#save-snapshot,#portfolio-select,#portfolio-form button,#trade-form button,#account-form button,#order-submit",
    )
    .forEach((el) => (el.disabled = busy));
}
async function loadWorkspaces() {
  navigationBusy(true);
  state.portfolioEpoch++;
  resetValuation();
  try {
    const data = await api("/v1/workspaces?limit=100");
    $("workspace").replaceChildren(
      ...data.items.map((w) => option(w.id, w.name)),
    );
    if (!data.items.length)
      $("workspace").append(option("", "Create your first workspace"));
    state.workspace = data.items.some((w) => w.id === state.workspace)
      ? state.workspace
      : data.items[0]?.id || null;
    $("workspace").value = state.workspace || "";
    await loadPortfolios();
  } finally {
    navigationBusy(false);
  }
}
async function loadPortfolios() {
  const epoch = ++state.portfolioListEpoch,
    workspace = state.workspace,
    preferred = state.portfolio;
  navigationBusy(true);
  state.portfolio = null;
  state.portfolioEpoch++;
  resetValuation();
  state.account = null;
  state.pendingOrder = null;
  $("snapshot-status").textContent = "";
  $("paper-cash").textContent = "No account selected";
  emptyTable("orders", "No simulated orders yet");
  $("portfolio-select").replaceChildren(option("", "Loading portfolios…"));
  try {
    if (!workspace) {
      $("portfolio-select").replaceChildren(option("", "No portfolio"));
      return;
    }
    const data = await api(`/v1/workspaces/${workspace}/portfolios?limit=100`);
    if (epoch !== state.portfolioListEpoch || workspace !== state.workspace)
      return;
    $("portfolio-select").replaceChildren(
      ...data.items.map((p) => option(p.id, `${p.name} · ${p.base_currency}`)),
    );
    state.portfolio = data.items.some((p) => p.id === preferred)
      ? preferred
      : data.items[0]?.id || null;
    if (!state.portfolio)
      $("portfolio-select").append(option("", "Create a portfolio"));
    $("portfolio-select").value = state.portfolio || "";
    await loadValuation();
  } finally {
    if (epoch === state.portfolioListEpoch) navigationBusy(false);
  }
}
function resetValuation() {
  $("total").textContent = "—";
  $("position-count").textContent = "—";
  $("valuation-status").textContent = "Create a portfolio to get started";
  emptyTable("positions", "No portfolio selected");
}
async function loadValuation() {
  const epoch = ++state.portfolioEpoch;
  if (!state.portfolio) {
    resetValuation();
    return;
  }
  const data = await api(`${portfolioRoot()}/valuation`);
  if (epoch !== state.portfolioEpoch) return;
  $("total").textContent =
    data.total_value === null
      ? "Incomplete"
      : `${pretty(data.total_value)} ${data.base_currency}`;
  $("position-count").textContent = data.positions.length;
  $("valuation-status").textContent =
    `${data.is_demo ? "DEMO · " : ""}${data.status === "complete" ? "Daily close valuation" : "Missing prices or FX; total withheld"}`;
  const rows = data.positions.map((p) => {
    const tr = document.createElement("tr");
    textCell(
      tr,
      p.symbol,
      `${p.market} · ${p.currency}${p.is_demo ? " · DEMO" : ""}`,
    );
    textCell(tr, pretty(p.quantity));
    textCell(
      tr,
      pretty(p.price),
      p.price_as_of ? shortDate(p.price_as_of) : null,
    );
    textCell(tr, pretty(p.base_value));
    textCell(
      tr,
      p.allocation_pct == null ? "—" : `${pretty(p.allocation_pct)}%`,
    );
    const status = textCell(tr, label(p.status));
    status.className = `status ${p.status}`;
    status.title = p.reason;
    return tr;
  });
  $("positions").replaceChildren(...rows);
  if (!rows.length)
    emptyTable(
      "positions",
      "No open positions. Record a trade or load a sample portfolio.",
    );
  $("last-updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
}
async function loadInstruments(append = false) {
  const params = new URLSearchParams({ limit: "100" });
  const q = $("search").value.trim();
  if (q) params.set("q", q);
  if (append && state.cursor) params.set("cursor", state.cursor);
  const data = await api(`/v1/instruments?${params}`);
  state.instruments = append
    ? [...state.instruments, ...data.items]
    : data.items;
  state.cursor = data.next_cursor;
  $("more-instruments").hidden = !state.cursor;
  renderInstruments();
  const selected =
    state.instruments.find((i) => i.id === state.instrument?.id) ||
    state.instruments[0];
  if (selected) await selectInstrument(selected);
  else {
    $("instrument-list").textContent =
      "No imported instruments match this search.";
  }
}
function renderInstruments() {
  const buttons = state.instruments.map((i) => {
    const b = document.createElement("button");
    b.className =
      "instrument-button" + (i.id === state.instrument?.id ? " selected" : "");
    const left = document.createElement("span");
    left.textContent = i.symbol;
    const small = document.createElement("small");
    small.textContent = i.name;
    left.append(small);
    const right = document.createElement("span");
    right.textContent = `${i.market} · ${i.currency}${i.is_demo ? " · DEMO" : ""}`;
    b.append(left, right);
    b.addEventListener("click", () =>
      selectInstrument(i).catch((e) => notice(e.message)),
    );
    return b;
  });
  $("instrument-list").replaceChildren(...buttons);
  for (const id of ["trade-instrument", "order-instrument"]) {
    const old = $(id).value;
    const list = state.instruments.filter(
      (i) => id !== "order-instrument" || i.is_demo,
    );
    $(id).replaceChildren(
      ...list.map((i) => option(i.id, `${i.symbol} · ${i.currency}`)),
    );
    if (list.some((i) => i.id === old)) $(id).value = old;
  }
}
async function selectInstrument(instrument) {
  const epoch = ++state.chartEpoch;
  state.instrument = instrument;
  renderInstruments();
  const [history, signal] = await Promise.all([
    api(`/v1/instruments/${instrument.id}/history`),
    api(`/v1/instruments/${instrument.id}/signal`),
  ]);
  if (epoch !== state.chartEpoch) return;
  $("chart-name").textContent = instrument.name;
  $("chart-market").textContent =
    `${instrument.market} / ${instrument.symbol}${instrument.is_demo ? " / SYNTHETIC DEMO" : ""}`;
  $("data-quality").textContent = label(history.quality);
  $("chart-currency").textContent = instrument.currency;
  const bars = history.bars;
  const last = bars.at(-1);
  $("last-price").textContent = pretty(last?.close);
  $("chart-start").textContent = shortDate(bars[0]?.as_of);
  $("chart-end").textContent = shortDate(last?.as_of);
  $("price-source").textContent =
    `${history.source || "No provider"} · ${history.reason}${last ? ` · As of ${new Date(last.as_of).toLocaleString()}` : ""}`;
  drawChart(bars);
  const signalText = {
    elevated: "Elevated anomaly signal",
    no_anomaly_detected: "No anomaly detected",
    insufficient_data: "Insufficient data",
  }[signal.status];
  $("signal-title").textContent = signalText;
  $("signal-summary").textContent = {
    elevated: "Elevated",
    no_anomaly_detected: "No anomaly",
    insufficient_data: "Unknown",
  }[signal.status];
  $("signal-summary").className = `status ${signal.status}`;
  $("signal-subtitle").textContent =
    `${instrument.symbol}${signal.is_demo ? " · Synthetic data" : ""}`;
  $("signal-reason").textContent = signal.reasons.length
    ? signal.reasons.join(" · ")
    : "Daily price and volume checks found no unusual pattern in this window.";
  const evidence = signal.evidence;
  $("evidence").replaceChildren(
    ...[
      ["Daily move", evidence.daily_return_pct, "%"],
      ["Price outlier score", evidence.modified_z, ""],
      ["Volume / baseline", evidence.volume_multiple, "×"],
    ].map(([name, value, suffix]) => {
      const div = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = value == null ? "—" : pretty(value) + suffix;
      const small = document.createElement("small");
      small.textContent = name;
      div.append(strong, small);
      return div;
    }),
  );
  if (last) {
    $("trade-price").value = last.close;
    $("trade-instrument").value = instrument.id;
  }
  if (instrument.is_demo) {
    $("order-instrument").value = instrument.id;
    await loadReference();
  }
}
function drawChart(bars) {
  if (!bars.length) {
    $("chart-path").setAttribute("d", "");
    return;
  }
  const values = bars.map((b) => Number(b.close));
  const lo = Math.min(...values),
    hi = Math.max(...values),
    range = hi - lo || hi * 0.01 || 1;
  const d = values
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${((i / Math.max(values.length - 1, 1)) * 680 + 10).toFixed(2)},${(175 - ((v - lo) / range) * 150).toFixed(2)}`,
    )
    .join(" ");
  $("chart-path").setAttribute("d", d);
}
async function loadReference() {
  const epoch = ++state.referenceEpoch;
  state.reference = null;
  const id = $("order-instrument").value;
  if (!id) return;
  const h = await api(`/v1/instruments/${id}/history?limit=1`);
  if (epoch !== state.referenceEpoch) return;
  state.reference = h.bars.at(-1) || null;
  $("order-reference").textContent = state.reference
    ? `Simulated reference: ${state.reference.close} · ${new Date(state.reference.as_of).toLocaleString()} · ${label(h.quality)}`
    : "No completed reference price is available.";
}
async function loadPaper() {
  if (!state.account) return;
  const selectedAccount = state.account,
    selectedWorkspace = state.workspace;
  const root = `${workspaceRoot()}/paper-accounts/${selectedAccount}`;
  const [account, orders] = await Promise.all([
    api(root),
    api(`${root}/orders?limit=100`),
  ]);
  if (
    state.account !== selectedAccount ||
    state.workspace !== selectedWorkspace
  )
    return;
  $("paper-cash").textContent =
    `${pretty(account.cash)} ${account.currency} simulated cash`;
  const rows = orders.items
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((o) => {
      const tr = document.createElement("tr");
      textCell(tr, new Date(o.created_at).toLocaleString());
      textCell(
        tr,
        state.instruments.find((i) => i.id === o.instrument_id)?.symbol ||
          o.instrument_id,
      );
      textCell(tr, o.side);
      textCell(tr, pretty(o.quantity));
      textCell(tr, pretty(o.price));
      const cell = textCell(tr, o.status);
      cell.className = `status ${o.status}`;
      cell.title = o.reason;
      return tr;
    });
  $("orders").replaceChildren(...rows);
  if (!rows.length) emptyTable("orders", "No simulated orders yet");
}
bind(
  "login-form",
  async () => {
    const data = await post("/v1/dev-login", { user: $("login-user").value });
    await signedIn(data);
  },
  "submit",
);
bind("provider-login", async () =>
  FinRiskLogin.start(state.config.browser_login),
);
bind("logout", async () => {
  signOut();
  notice("Signed out of FinRisk on this page.");
});
bind(
  "workspace-form",
  async () => {
    const w = await post("/v1/workspaces", {
      name: $("workspace-name").value.trim(),
    });
    state.workspace = w.id;
    state.portfolio = null;
    $("workspace-name").value = "";
    await loadWorkspaces();
  },
  "submit",
);
bind(
  "workspace",
  async () => {
    state.workspace = $("workspace").value;
    state.portfolio = null;
    await loadPortfolios();
  },
  "change",
);
bind(
  "portfolio-form",
  async () => {
    const p = await post(`${workspaceRoot()}/portfolios`, {
      name: $("portfolio-name").value.trim(),
      base_currency: $("base-currency").value,
    });
    state.portfolio = p.id;
    await loadPortfolios();
  },
  "submit",
);
bind(
  "portfolio-select",
  async () => {
    state.portfolio = $("portfolio-select").value;
    await loadValuation();
  },
  "change",
);
bind("search-form", async () => loadInstruments(), "submit");
bind("more-instruments", async () => loadInstruments(true));
bind("refresh", async () => {
  if (!state.token) return;
  await loadValuation();
  if (state.instrument) await selectInstrument(state.instrument);
  await loadPaper();
});
bind("sample-portfolio", async () => {
  const instruments = state.instruments.filter((i) => i.is_demo).slice(0, 3);
  if (!instruments.length)
    throw new Error("Import the demo market dataset first.");
  const root = workspaceRoot(),
    workspace = state.workspace;
  const p = await post(`${root}/portfolios`, {
    name: "Sample equity portfolio",
    base_currency: $("base-currency").value,
  });
  for (const i of instruments) {
    const h = await api(`/v1/instruments/${i.id}/history?limit=1`);
    const bar = h.bars.at(-1);
    if (!bar) continue;
    await post(`${root}/portfolios/${p.id}/transactions`, {
      client_request_id: crypto.randomUUID(),
      market: i.market,
      symbol: i.symbol,
      currency: i.currency,
      side: "buy",
      quantity: "10",
      price: bar.close,
      fees: "0",
      executed_at: bar.as_of,
    });
  }
  if (state.workspace === workspace) {
    state.portfolio = p.id;
    await loadPortfolios();
  }
});
bind("save-snapshot", async () => {
  const data = await post(`${portfolioRoot()}/valuations`);
  $("snapshot-status").textContent =
    `Saved valuation ${data.snapshot_id} · portfolio version ${data.portfolio_version} · ${data.status}`;
});
bind(
  "trade-form",
  async () => {
    const i = state.instruments.find(
      (i) => i.id === $("trade-instrument").value,
    );
    if (!i) throw new Error("Select a catalog instrument.");
    const path = `${portfolioRoot()}/transactions`;
    const fields = {
      market: i.market,
      symbol: i.symbol,
      currency: i.currency,
      side: $("trade-side").value,
      quantity: $("trade-quantity").value,
      price: $("trade-price").value,
      fees: $("trade-fees").value,
      executed_at: new Date($("trade-time").value).toISOString(),
    };
    const signature = JSON.stringify({ path, fields });
    if (state.pendingTrade && signature !== state.pendingTrade.signature)
      throw new Error(
        "A previous trade submission is unresolved. Restore its values and retry first.",
      );
    state.pendingTrade ??= {
      signature,
      body: { ...fields, client_request_id: crypto.randomUUID() },
    };
    try {
      await post(path, state.pendingTrade.body);
      state.pendingTrade = null;
    } catch (error) {
      if (error.status && error.status < 500) state.pendingTrade = null;
      throw error;
    }
    await loadValuation();
    $("snapshot-status").textContent = "Completed trade recorded.";
  },
  "submit",
);
bind(
  "account-form",
  async () => {
    const account = await post(`${workspaceRoot()}/paper-accounts`, {
      currency: $("account-currency").value,
    });
    state.account = account.id;
    await loadPaper();
  },
  "submit",
);
bind("order-instrument", async () => loadReference(), "change");
bind(
  "order-form",
  async () => {
    if (!state.account) throw new Error("Open a paper account first.");
    if (!state.reference) throw new Error("A reference price is required.");
    const path = `${workspaceRoot()}/paper-accounts/${state.account}/orders`;
    const fields = {
      instrument_id: $("order-instrument").value,
      price_bar_id: state.reference.id,
      side: $("order-side").value,
      quantity: $("order-quantity").value,
    };
    const signature = JSON.stringify({ path, fields });
    if (state.pendingOrder && signature !== state.pendingOrder.signature)
      throw new Error(
        "An earlier submission is unresolved. Restore its values and retry before changing the order.",
      );
    state.pendingOrder ??= {
      signature,
      body: { ...fields, client_request_id: crypto.randomUUID() },
    };
    try {
      const order = await post(path, state.pendingOrder.body);
      state.pendingOrder = null;
      $("order-result").textContent =
        `${order.status.toUpperCase()} · ${order.reason}`;
      await loadPaper();
    } catch (error) {
      if (error.status && error.status < 500) state.pendingOrder = null;
      throw error;
    }
  },
  "submit",
);
async function init() {
  state.config = await api("/v1/app-config");
  $("mode").textContent = state.config.demo_data
    ? "DEMO ENVIRONMENT"
    : "MARKET WORKSPACE";
  $("login-form").hidden = !state.config.development_login;
  $("provider-login").hidden = !state.config.browser_login;
  $("login-description").textContent = state.config.development_login
    ? "Choose a local demo identity. Alice and Bob have separate workspaces."
    : state.config.browser_login
      ? "Continue with your organization’s identity provider."
      : "Browser sign-in is not connected. Configure an identity provider before public deployment.";
  $("paper").hidden = !state.config.paper_trading;
  $("sample-portfolio").hidden = !state.config.demo_data;
  const local = new Date(Date.now() - 60000);
  local.setMinutes(local.getMinutes() - local.getTimezoneOffset());
  $("trade-time").value = local.toISOString().slice(0, 16);
  const exchange = FinRiskLogin.consume(state.config.browser_login);
  if (exchange) await signedIn(await post("/v1/auth/exchange", exchange));
}
init().catch((error) => notice(error.message));
