"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  token: null,
  expiryTimer: null,
  config: {},
  workspace: null,
  workspaceRole: null,
  portfolio: null,
  instruments: [],
  instrument: null,
  watchlist: [],
  alerts: [],
  cursor: null,
  account: null,
  reference: null,
  pendingOrder: null,
  pendingTrade: null,
  pendingImport: null,
  importPreview: null,
  chartEpoch: 0,
  chartBars: [],
  chartRange: 61,
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
  if (message && !state.token && !$("landing").hidden) {
    $("login-description").textContent = `Sign-in failed: ${message}`;
    $("login-panel").classList.add("login-error");
    $("login-panel").scrollIntoView({ behavior: "smooth", block: "center" });
  }
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
const patch = (path, body) =>
  api(path, { method: "PATCH", body: JSON.stringify(body || {}) });
const remove = (path) => api(path, { method: "DELETE" });
function staysDisabled(element) {
  if (element.id === "watch-instrument")
    return (
      !state.instrument ||
      !state.workspace ||
      !canWriteWorkspace() ||
      state.watchlist.some((item) => item.instrument_id === state.instrument.id)
    );
  if (element.id === "run-risk-scan")
    return (
      !state.workspace || !canWriteWorkspace() || !state.watchlist.length
    );
  if (element.id === "risk-lab-run") return !state.portfolio;
  if (element.id === "save-risk-snapshot")
    return !state.portfolio || !canWriteWorkspace();
  return (
    element.id === "commit-import" &&
    (!state.importPreview ||
      state.importPreview.status !== "previewed" ||
      state.importPreview.error_count > 0)
  );
}
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
      buttons.forEach((b) => (b.disabled = staysDisabled(b)));
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
  state.workspaceRole = null;
  state.portfolio = null;
  state.account = null;
  state.pendingOrder = null;
  state.pendingTrade = null;
  state.pendingImport = null;
  state.importPreview = null;
  state.watchlist = [];
  state.alerts = [];
  state.chartEpoch++;
  state.portfolioEpoch++;
  state.referenceEpoch++;
  $("application").hidden = true;
  document.body.classList.remove("app-active");
  $("command-search").hidden = true;
  $("landing").hidden = false;
  $("login-panel").hidden = false;
  $("app-sidebar").hidden = true;
  $("app-shell").hidden = true;
  $("logout").hidden = true;
  $("last-updated").textContent = "Not connected";
}
const views = {
  overview: {
    name: "Overview",
    kicker: "PORTFOLIO COMMAND CENTER",
    title: "Portfolio overview",
    description:
      "Monitor exposure, market evidence, and simulated execution from one workspace.",
    sections: ["metrics", "portfolio", "markets", "signal", "riskLab"],
  },
  portfolio: {
    name: "Portfolio",
    kicker: "POSITIONS & EXPOSURE",
    title: "Portfolio management",
    description:
      "Review holdings, valuation quality, completed trades, and allocation in base currency.",
    sections: ["metrics", "portfolio"],
  },
  markets: {
    name: "Markets",
    kicker: "MARKET INTELLIGENCE",
    title: "Price and anomaly monitor",
    description:
      "Inspect sourced daily history and the evidence behind each statistical signal.",
    sections: ["markets", "signal"],
  },
  alerts: {
    name: "Risk alerts",
    kicker: "RISK OPERATIONS",
    title: "Watchlist and alerts",
    description:
      "Scan monitored instruments, review durable evidence, and acknowledge findings.",
    sections: ["riskLab", "alerts"],
  },
  paper: {
    name: "Paper trading",
    kicker: "SIMULATED EXECUTION",
    title: "Paper trading desk",
    description:
      "Test decisions against explicit reference prices without connecting real funds.",
    sections: ["paper"],
  },
  team: {
    name: "Team access",
    kicker: "WORKSPACE ADMINISTRATION",
    title: "Team and permissions",
    description:
      "Manage invitations, roles, and access to this financial workspace.",
    sections: ["team"],
  },
};
function setView(name) {
  const effectiveName = views[name] ? name : "overview";
  const selected = views[effectiveName];
  const sectionMap = {
    metrics: document.querySelector(".metrics"),
    portfolio: $("portfolio"),
    markets: $("markets"),
    signal: document.querySelector(".signal-panel"),
    riskLab: $("risk-lab"),
    alerts: $("alerts"),
    paper: $("paper"),
    team: $("team"),
  };
  for (const [key, element] of Object.entries(sectionMap))
    element.hidden = !selected.sections.includes(key);
  document.querySelectorAll(".nav[data-view]").forEach((item) => {
    const active = item.dataset.view === effectiveName;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  $("view-name").textContent = selected.name;
  $("page-kicker").textContent = selected.kicker;
  $("page-title").textContent = selected.title;
  $("page-description").textContent = selected.description;
}
function openMarketSearch() {
  history.replaceState(null, "", "#markets");
  setView("markets");
  requestAnimationFrame(() => $("search").focus());
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
  $("landing").hidden = true;
  $("app-sidebar").hidden = false;
  $("app-shell").hidden = false;
  $("application").hidden = false;
  document.body.classList.add("app-active");
  $("command-search").hidden = false;
  $("logout").hidden = false;
  setView(location.hash.slice(1));
  await Promise.all([loadWorkspaces(), loadInstruments()]);
}
function navigationBusy(busy) {
  document
    .querySelectorAll(
      "#workspace,#sample-portfolio,#save-snapshot,#portfolio-select,#portfolio-form button,#trade-form button,#import-form button,#commit-import,#account-form button,#order-submit,#watch-instrument,#run-risk-scan,#risk-lab-run,#save-risk-snapshot",
    )
    .forEach((el) => (el.disabled = busy || staysDisabled(el)));
}
async function loadWorkspaces() {
  navigationBusy(true);
  state.portfolioEpoch++;
  resetValuation();
  resetRiskLab();
  try {
    const data = await api("/v1/workspaces?limit=100");
    const firstRun = data.items.length === 0;
    $("onboarding").hidden = !firstRun;
    $("workspace-content").hidden = firstRun;
    $("workspace").replaceChildren(
      ...data.items.map((w) => option(w.id, w.name)),
    );
    if (!data.items.length)
      $("workspace").append(option("", "Create your first workspace"));
    state.workspace = data.items.some((w) => w.id === state.workspace)
      ? state.workspace
      : data.items[0]?.id || null;
    state.workspaceRole =
      data.items.find((w) => w.id === state.workspace)?.role || null;
    $("workspace").value = state.workspace || "";
    await Promise.all([loadPortfolios(), loadTeam(), loadRisk(), loadSubscription()]);
  } finally {
    navigationBusy(false);
  }
}

function memberIdentity(userId) {
  return `User ${userId.slice(0, 8)}`;
}
function usageLabel(subscription, key) {
  const used = subscription.usage[key] ?? 0;
  const limit = subscription.plan.entitlements[key];
  return typeof limit === "number" ? `${used} / ${limit}` : String(used);
}
async function loadSubscription() {
  if (!state.workspace) {
    $("plan-name").textContent = "No workspace";
    $("plan-status").textContent = "Create or join a workspace";
    for (const id of ["usage-seats", "usage-portfolios", "usage-watchlist", "usage-risk-scans"])
      $(id).textContent = "—";
    return;
  }
  const subscription = await api(`${workspaceRoot()}/subscription`);
  $("plan-name").textContent = subscription.plan.name;
  $("plan-status").textContent = label(subscription.status);
  $("usage-seats").textContent = usageLabel(subscription, "seats");
  $("usage-portfolios").textContent = usageLabel(subscription, "portfolios");
  $("usage-watchlist").textContent = usageLabel(subscription, "watchlist_instruments");
  $("usage-risk-scans").textContent = usageLabel(subscription, "risk_scans_monthly");
}
function teamActions(row, canManage) {
  const cell = document.createElement("td");
  if (!canManage || row.role === "owner") {
    cell.textContent = row.role === "owner" ? "Protected owner" : "Managed by an admin";
    cell.className = "muted";
    return cell;
  }
  const role = document.createElement("select");
  for (const value of ["viewer", "member", "admin"])
    role.append(option(value, label(value)));
  role.value = row.role;
  role.setAttribute("aria-label", `Role for ${memberIdentity(row.user_id)}`);
  role.addEventListener("change", async () => {
    role.disabled = true;
    try {
      await patch(`${workspaceRoot()}/members/${row.user_id}`, { role: role.value });
      await loadTeam();
    } catch (error) {
      notice(error.message);
      role.value = row.role;
    } finally {
      role.disabled = false;
    }
  });
  const button = document.createElement("button");
  button.type = "button";
  button.className = "danger-quiet";
  button.textContent = "Remove";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await remove(`${workspaceRoot()}/members/${row.user_id}`);
      await loadTeam();
    } catch (error) {
      notice(error.message);
      button.disabled = false;
    }
  });
  cell.append(role, button);
  cell.className = "row-actions";
  return cell;
}
async function loadTeam() {
  $("team-role").textContent = label(state.workspaceRole || "No workspace");
  $("invite-secret").hidden = true;
  if (!state.workspace) {
    emptyTable("members", "Create a workspace to manage access", 3);
    emptyTable("invitations", "No workspace selected", 4);
    return;
  }
  const canManage = ["owner", "admin"].includes(state.workspaceRole);
  $("invite-manager").hidden = !canManage;
  $("invitation-list-panel").hidden = !canManage;
  const members = await api(`${workspaceRoot()}/members`);
  const memberRows = members.map((member) => {
    const row = document.createElement("tr");
    textCell(row, memberIdentity(member.user_id), member.user_id);
    textCell(row, label(member.role));
    row.append(teamActions(member, canManage));
    return row;
  });
  $("members").replaceChildren(...memberRows);
  if (!memberRows.length) emptyTable("members", "No members found", 3);
  if (!canManage) return;
  const invitations = await api(`${workspaceRoot()}/invitations?limit=100`);
  const inviteRows = invitations.map((invitation) => {
    const row = document.createElement("tr");
    textCell(row, label(invitation.role));
    textCell(row, new Date(invitation.expires_at).toLocaleString());
    const status = textCell(row, label(invitation.status));
    status.className = `status ${invitation.status}`;
    const action = document.createElement("td");
    if (invitation.status === "pending") {
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "danger-quiet";
      revoke.textContent = "Revoke";
      revoke.addEventListener("click", async () => {
        revoke.disabled = true;
        try {
          await remove(`${workspaceRoot()}/invitations/${invitation.id}`);
          await loadTeam();
        } catch (error) {
          notice(error.message);
          revoke.disabled = false;
        }
      });
      action.append(revoke);
    }
    row.append(action);
    return row;
  });
  $("invitations").replaceChildren(...inviteRows);
  if (!inviteRows.length) emptyTable("invitations", "No invitations yet", 4);
}

function canWriteWorkspace() {
  return ["owner", "admin", "member"].includes(state.workspaceRole);
}
function updateWatchButton() {
  const watched = state.watchlist.some(
    (item) => item.instrument_id === state.instrument?.id,
  );
  $("watch-instrument").textContent = watched
    ? "Added to watchlist"
    : "+ Add to watchlist";
  $("watch-instrument").disabled =
    !state.instrument || !state.workspace || watched || !canWriteWorkspace();
}
function renderWatchlist() {
  const canWrite = canWriteWorkspace();
  const rows = state.watchlist.map((item) => {
    const row = document.createElement("tr");
    textCell(
      row,
      item.symbol,
      `${item.market} · ${item.currency}${item.is_demo ? " · DEMO" : ""}`,
    );
    const ruleCell = document.createElement("td");
    const rule = document.createElement("select");
    rule.append(option("true", "Daily alerts on"), option("false", "Alerts paused"));
    rule.value = String(item.alerts_enabled);
    rule.disabled = !canWrite;
    rule.setAttribute("aria-label", `Alert rule for ${item.symbol}`);
    rule.addEventListener("change", async () => {
      rule.disabled = true;
      try {
        await patch(`${workspaceRoot()}/watchlist/${item.instrument_id}`, {
          alerts_enabled: rule.value === "true",
        });
        await Promise.all([loadRisk(), loadSubscription()]);
      } catch (error) {
        notice(error.message);
        rule.value = String(item.alerts_enabled);
        rule.disabled = !canWrite;
      }
    });
    ruleCell.append(rule);
    row.append(ruleCell);
    const action = document.createElement("td");
    if (canWrite) {
      const removeButton = document.createElement("button");
      removeButton.className = "danger-quiet";
      removeButton.type = "button";
      removeButton.textContent = "Remove";
      removeButton.addEventListener("click", async () => {
        removeButton.disabled = true;
        try {
          await remove(`${workspaceRoot()}/watchlist/${item.instrument_id}`);
          await Promise.all([loadRisk(), loadSubscription()]);
        } catch (error) {
          notice(error.message);
          removeButton.disabled = false;
        }
      });
      action.append(removeButton);
    } else action.textContent = "Read only";
    row.append(action);
    return row;
  });
  $("watchlist").replaceChildren(...rows);
  if (!rows.length) emptyTable("watchlist", "No saved instruments", 3);
  updateWatchButton();
}
function renderAlerts() {
  const canWrite = canWriteWorkspace();
  const rows = state.alerts.map((alert) => {
    const row = document.createElement("tr");
    textCell(row, new Date(alert.triggered_at).toLocaleString());
    textCell(row, alert.symbol, `${alert.market} · ${alert.currency}`);
    const evidence = alert.evidence;
    textCell(
      row,
      evidence.reasons?.join(" · ") || alert.title,
      `Price z ${pretty(evidence.price_return_z)} · Volume z ${pretty(evidence.volume_z)} · ${evidence.model_version}`,
    );
    const action = document.createElement("td");
    if (alert.status === "open" && canWrite) {
      const acknowledge = document.createElement("button");
      acknowledge.type = "button";
      acknowledge.className = "quiet";
      acknowledge.textContent = "Acknowledge";
      acknowledge.addEventListener("click", async () => {
        acknowledge.disabled = true;
        try {
          await post(`${workspaceRoot()}/alerts/${alert.id}/acknowledge`);
          await Promise.all([loadRisk(), loadSubscription()]);
        } catch (error) {
          notice(error.message);
          acknowledge.disabled = false;
        }
      });
      action.append(acknowledge);
    } else {
      action.textContent = label(alert.status);
      action.className = `status ${alert.status}`;
    }
    row.append(action);
    return row;
  });
  $("risk-alerts").replaceChildren(...rows);
  if (!rows.length) emptyTable("risk-alerts", "No alerts have been triggered", 4);
  const open = state.alerts.filter((item) => item.status === "open").length;
  $("open-alert-count").textContent = `${open} open`;
}
async function loadRisk() {
  state.watchlist = [];
  state.alerts = [];
  if (!state.workspace) {
    renderWatchlist();
    renderAlerts();
    $("run-risk-scan").disabled = true;
    return;
  }
  const workspace = state.workspace;
  const [watchlist, alerts] = await Promise.all([
    api(`${workspaceRoot()}/watchlist`),
    api(`${workspaceRoot()}/alerts?limit=100`),
  ]);
  if (workspace !== state.workspace) return;
  state.watchlist = watchlist;
  state.alerts = alerts;
  renderWatchlist();
  renderAlerts();
  $("run-risk-scan").disabled = !canWriteWorkspace() || !watchlist.length;
  $("risk-status").textContent = watchlist.length
    ? `${watchlist.filter((item) => item.alerts_enabled).length} active daily rules · results are deduplicated against the latest market bar.`
    : "Add an instrument to begin monitoring.";
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
  state.pendingImport = null;
  state.importPreview = null;
  $("snapshot-status").textContent = "";
  $("paper-cash").textContent = "No account selected";
  $("import-status").textContent = "Select a CSV file to begin.";
  $("commit-import").disabled = true;
  emptyTable("import-rows", "No import preview", 6);
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
    await Promise.all([loadValuation(), loadImports(), loadRiskLab()]);
  } finally {
    if (epoch === state.portfolioListEpoch) navigationBusy(false);
  }
}

function renderImportPreview(preview) {
  state.importPreview = preview;
  const rows = preview.rows.map((item) => {
    const row = document.createElement("tr");
    textCell(row, item.row_number);
    textCell(
      row,
      `${item.data.market || "?"}:${item.data.symbol || "?"}`,
      item.data.currency,
    );
    textCell(row, item.data.side);
    textCell(row, item.data.quantity);
    textCell(row, item.data.executed_at);
    const result = textCell(
      row,
      item.errors.length ? item.errors.join("; ") : "Ready",
    );
    result.className = item.errors.length ? "status rejected" : "status";
    return row;
  });
  $("import-rows").replaceChildren(...rows);
  $("import-status").textContent =
    `${preview.valid_count} ready · ${preview.error_count} with errors · ${preview.row_count} total`;
  $("commit-import").disabled =
    preview.status !== "previewed" || preview.error_count > 0;
}
async function loadImports() {
  if (!state.portfolio) {
    $("import-history").textContent = "";
    return;
  }
  const history = await api(`${portfolioRoot()}/transaction-imports?limit=5`);
  $("import-history").textContent = history.length
    ? `Recent imports: ${history
        .map((item) => `${item.filename || "CSV"} (${label(item.status)}, ${item.row_count} rows)`)
        .join(" · ")}`
    : "No previous CSV imports.";
}
function resetValuation() {
  $("total").textContent = "—";
  $("position-count").textContent = "—";
  $("valuation-status").textContent = "Create a portfolio to get started";
  emptyTable("positions", "No portfolio selected");
  renderAllocation([]);
}
function renderAllocation(positions) {
  const colors = ["#43d7a2", "#72a8ff", "#c18cff", "#f4c96b", "#ff8c69", "#7ed6df"];
  const allocated = positions.filter(
    (position) => position.allocation_pct != null && Number(position.allocation_pct) > 0,
  );
  const segments = allocated.map((position, index) => {
    const segment = document.createElement("span");
    segment.style.width = `${Number(position.allocation_pct)}%`;
    segment.style.backgroundColor = colors[index % colors.length];
    segment.title = `${position.symbol}: ${pretty(position.allocation_pct)}%`;
    return segment;
  });
  $("allocation-strip").replaceChildren(...segments);
  const items = allocated.map((position, index) => {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.backgroundColor = colors[index % colors.length];
    const name = document.createElement("b");
    name.textContent = position.symbol;
    const value = document.createElement("small");
    value.textContent = `${pretty(position.allocation_pct)}%`;
    item.append(swatch, name, value);
    return item;
  });
  $("allocation-legend").replaceChildren(...items);
  $("allocation-caption").textContent = allocated.length
    ? `${allocated.length} valued positions · based on current base-currency value`
    : "Add fully valued positions to calculate allocation.";
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
  renderAllocation(data.positions);
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
function resetRiskLab() {
  for (const id of [
    "risk-es",
    "risk-var",
    "risk-volatility",
    "risk-drawdown",
    "risk-diversification",
    "risk-effective-holdings",
    "risk-largest",
    "risk-hhi",
    "risk-days",
    "risk-downside",
    "risk-coverage",
  ])
    $(id).textContent = "â€”";
  $("risk-lab-status").textContent = "WAITING";
  $("risk-lab-status").className = "tag";
  $("risk-lab-window").textContent = "Select a valued portfolio to calculate risk.";
  $("risk-limitations").textContent =
    "Results will state their assumptions and data limits here.";
  $("risk-snapshot-status").textContent = "";
  emptyTable("risk-scenarios", "No risk analysis yet", 3);
  emptyTable("risk-attribution", "No position attribution yet", 5);
}
function renderRiskLab(data) {
  const status = $("risk-lab-status");
  status.textContent = label(data.status).toUpperCase();
  status.className = `tag ${data.status === "complete" ? "success-tag" : "alert-tag"}`;
  const metrics = data.metrics;
  if (!metrics) {
    for (const id of [
      "risk-es",
      "risk-var",
      "risk-volatility",
      "risk-drawdown",
      "risk-diversification",
      "risk-effective-holdings",
      "risk-largest",
      "risk-hhi",
      "risk-days",
      "risk-downside",
    ])
      $(id).textContent = "â€”";
    $("risk-lab-window").textContent = "The selected evidence is not sufficient for a portfolio result.";
    emptyTable("risk-scenarios", "Risk scenarios need a complete analysis", 3);
    emptyTable(
      "risk-attribution",
      "Position attribution needs a complete analysis",
      5,
    );
  } else {
    $("risk-es").textContent = `${pretty(metrics.expected_shortfall_pct)}%`;
    $("risk-var").textContent = `${pretty(metrics.value_at_risk_pct)}%`;
    $("risk-volatility").textContent = `${pretty(metrics.annualized_volatility_pct)}%`;
    $("risk-drawdown").textContent = `${pretty(metrics.max_drawdown_pct)}%`;
    $("risk-diversification").textContent = pretty(metrics.diversification_ratio);
    $("risk-effective-holdings").textContent = pretty(
      data.concentration.effective_holdings,
    );
    $("risk-largest").textContent =
      `${data.concentration.largest_position} Â· ${pretty(data.concentration.largest_position_pct)}%`;
    $("risk-hhi").textContent = pretty(data.concentration.herfindahl_index);
    $("risk-days").textContent =
      `${pretty(metrics.worst_day_pct)}% / +${pretty(metrics.best_day_pct)}%`;
    $("risk-downside").textContent = `${pretty(metrics.downside_frequency_pct)}%`;
    $("risk-lab-window").textContent =
      `${metrics.observation_count} aligned sessions Â· ${shortDate(metrics.from_date)} to ${shortDate(metrics.through_date)} Â· ${(Number(data.parameters.confidence) * 100).toFixed(0)}% confidence`;
    const rows = data.scenarios.map((scenario) => {
      const row = document.createElement("tr");
      textCell(row, scenario.name, scenario.description);
      textCell(
        row,
        `${pretty(scenario.estimated_impact)} ${data.base_currency}`,
      );
      const impact = textCell(row, `${pretty(scenario.estimated_impact_pct)}%`);
      impact.className = Number(scenario.estimated_impact_pct) < 0 ? "status elevated" : "status";
      return row;
    });
    $("risk-scenarios").replaceChildren(...rows);
    const attributionRows = data.attribution.map((position) => {
      const row = document.createElement("tr");
      textCell(row, position.symbol, position.market);
      textCell(row, `${pretty(position.weight_pct)}%`);
      textCell(row, `${pretty(position.annualized_volatility_pct)}%`);
      textCell(row, pretty(position.correlation_to_portfolio));
      textCell(row, `${pretty(position.volatility_contribution_pct)}%`);
      return row;
    });
    $("risk-attribution").replaceChildren(...attributionRows);
  }
  const ready = data.coverage.filter((item) =>
    ["demo", "end_of_day"].includes(item.quality),
  ).length;
  $("risk-coverage").textContent = `${ready}/${data.coverage.length} instruments usable`;
  $("risk-limitations").textContent = data.limitations.length
    ? data.limitations.join(" Â· ")
    : "No material data limitations were reported.";
}
async function loadRiskLab() {
  const portfolio = state.portfolio;
  if (!portfolio) {
    resetRiskLab();
    return;
  }
  const params = new URLSearchParams({
    confidence: $("risk-confidence").value,
    lookback: $("risk-lookback").value,
  });
  const data = await api(`${portfolioRoot()}/risk-lab?${params}`);
  if (portfolio !== state.portfolio) return;
  renderRiskLab(data);
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
  updateWatchButton();
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
  state.chartBars = bars;
  $("last-price").textContent = pretty(last?.close);
  $("price-source").textContent =
    `${history.source || "No provider"} · ${history.reason}${last ? ` · As of ${new Date(last.as_of).toLocaleString()}` : ""}`;
  renderChartRange();
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
    $("chart-area").setAttribute("d", "");
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
  $("chart-area").setAttribute("d", `${d} L690,185 L10,185 Z`);
}
function renderChartRange() {
  const bars = state.chartRange
    ? state.chartBars.slice(-state.chartRange)
    : state.chartBars;
  $("chart-start").textContent = shortDate(bars[0]?.as_of);
  $("chart-end").textContent = shortDate(bars.at(-1)?.as_of);
  drawChart(bars);
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
bind("command-search", async () => openMarketSearch());
document.querySelectorAll(".nav[data-view]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    history.replaceState(null, "", item.getAttribute("href"));
    setView(item.dataset.view);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});
document.querySelectorAll("[data-chart-range]").forEach((button) => {
  button.addEventListener("click", () => {
    state.chartRange = Number(button.dataset.chartRange);
    document.querySelectorAll("[data-chart-range]").forEach((item) =>
      item.classList.toggle("active", item === button),
    );
    renderChartRange();
  });
});
document.addEventListener("keydown", (event) => {
  if (state.token && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openMarketSearch();
  }
});
bind("logout", async () => {
  signOut();
  notice("Signed out of FinRisk on this page.");
});
bind(
  "onboarding-form",
  async () => {
    const result = await post("/v1/onboarding", {
      workspace_name: $("onboarding-workspace").value.trim(),
      portfolio_name: $("onboarding-portfolio").value.trim(),
      base_currency: $("onboarding-currency").value,
    });
    state.workspace = result.workspace.id;
    state.portfolio = result.portfolio.id;
    await loadWorkspaces();
    notice("Your workspace and first portfolio are ready.");
  },
  "submit",
);
bind(
  "onboarding-invite-form",
  async () => {
    const accepted = await post("/v1/invitations/accept", {
      token: $("onboarding-invite-code").value.trim(),
    });
    state.workspace = accepted.workspace_id;
    $("onboarding-invite-code").value = "";
    await loadWorkspaces();
    notice("Workspace invitation accepted.");
  },
  "submit",
);
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
    const data = await api("/v1/workspaces?limit=100");
    state.workspaceRole =
      data.items.find((w) => w.id === state.workspace)?.role || null;
    state.portfolio = null;
    await Promise.all([loadPortfolios(), loadTeam(), loadRisk(), loadSubscription()]);
  },
  "change",
);
bind(
  "invite-form",
  async () => {
    const invitation = await post(`${workspaceRoot()}/invitations`, {
      role: $("invite-role").value,
      expires_in_hours: Number($("invite-expiry").value),
    });
    $("invite-token").textContent = invitation.token;
    $("invite-secret").hidden = false;
    await loadTeam();
    $("invite-token").textContent = invitation.token;
    $("invite-secret").hidden = false;
  },
  "submit",
);
bind("copy-invite", async () => {
  await navigator.clipboard.writeText($("invite-token").textContent);
  notice("Invite code copied. Share it through a trusted channel.");
});
bind(
  "accept-invite-form",
  async () => {
    const code = $("invite-code").value.trim();
    const accepted = await post("/v1/invitations/accept", { token: code });
    state.workspace = accepted.workspace_id;
    $("invite-code").value = "";
    await loadWorkspaces();
    notice("Workspace invitation accepted.");
  },
  "submit",
);
bind(
  "portfolio-form",
  async () => {
    const p = await post(`${workspaceRoot()}/portfolios`, {
      name: $("portfolio-name").value.trim(),
      base_currency: $("base-currency").value,
    });
    state.portfolio = p.id;
    await Promise.all([loadPortfolios(), loadSubscription()]);
  },
  "submit",
);
bind(
  "portfolio-select",
  async () => {
    state.portfolio = $("portfolio-select").value;
    state.pendingImport = null;
    state.importPreview = null;
    await Promise.all([loadValuation(), loadImports(), loadRiskLab()]);
  },
  "change",
);
bind("search-form", async () => loadInstruments(), "submit");
bind("more-instruments", async () => loadInstruments(true));
bind("watch-instrument", async () => {
  if (!state.instrument) throw new Error("Select an instrument first.");
  await post(`${workspaceRoot()}/watchlist`, {
    instrument_id: state.instrument.id,
    alerts_enabled: true,
  });
  await Promise.all([loadRisk(), loadSubscription()]);
  notice(`${state.instrument.symbol} was added to the daily risk watchlist.`);
});
bind("run-risk-scan", async () => {
  const scan = await post(`${workspaceRoot()}/risk-scans`, {
    client_request_id: crypto.randomUUID(),
  });
  await Promise.all([loadRisk(), loadSubscription()]);
  $("risk-status").textContent =
    `Scanned ${scan.evaluated_count} rules · ${scan.elevated_count} elevated · ${scan.new_alert_count} new alerts.`;
});
bind("risk-lab-run", async () => loadRiskLab());
bind("risk-confidence", async () => loadRiskLab(), "change");
bind("risk-lookback", async () => loadRiskLab(), "change");
bind("save-risk-snapshot", async () => {
  const data = await post(`${portfolioRoot()}/risk-lab/snapshots`, {
    confidence: $("risk-confidence").value,
    lookback: Number($("risk-lookback").value),
  });
  renderRiskLab(data);
  $("risk-snapshot-status").textContent =
    `Saved risk evidence ${data.snapshot_id} Â· portfolio version ${data.portfolio_version}`;
});
bind("refresh", async () => {
  if (!state.token) return;
  await Promise.all([
    loadValuation(),
    loadTeam(),
    loadImports(),
    loadRisk(),
    loadRiskLab(),
    loadSubscription(),
  ]);
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
    await Promise.all([loadPortfolios(), loadSubscription()]);
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
    await Promise.all([loadValuation(), loadRiskLab()]);
    $("snapshot-status").textContent = "Completed trade recorded.";
  },
  "submit",
);
bind(
  "import-form",
  async () => {
    if (!state.portfolio) throw new Error("Create or select a portfolio first.");
    const file = $("import-file").files[0];
    if (!file) throw new Error("Select a CSV file.");
    if (file.size > 524288) throw new Error("CSV files are limited to 512 KiB.");
    const signature = `${portfolioRoot()}|${file.name}|${file.size}|${file.lastModified}`;
    if (!state.pendingImport || state.pendingImport.signature !== signature) {
      state.pendingImport = { signature, clientRequestId: crypto.randomUUID() };
    }
    const preview = await post(`${portfolioRoot()}/transaction-imports/preview`, {
      client_request_id: state.pendingImport.clientRequestId,
      filename: file.name,
      csv_text: await file.text(),
    });
    renderImportPreview(preview);
    await loadImports();
  },
  "submit",
);
bind("commit-import", async () => {
  if (!state.importPreview) throw new Error("Preview a CSV file first.");
  const result = await post(
    `${portfolioRoot()}/transaction-imports/${state.importPreview.id}/commit`,
  );
  state.pendingImport = null;
  state.importPreview.status = "committed";
  $("commit-import").disabled = true;
  $("import-status").textContent =
    `Imported ${result.imported_count} transactions · portfolio version ${result.portfolio_version}`;
  await Promise.all([loadValuation(), loadImports(), loadRiskLab()]);
});
bind("download-template", async () => {
  const content =
    "market,symbol,currency,side,quantity,price,fees,executed_at\n" +
    "XCAS,TICKER,MAD,buy,10,100.00,0,2026-01-01T16:00:00+00:00\n";
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "finrisk-transactions-template.csv";
  link.click();
  URL.revokeObjectURL(url);
});
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
