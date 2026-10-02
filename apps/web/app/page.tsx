import {
  Activity,
  ArrowRight,
  BarChart3,
  Bell,
  BookOpen,
  BriefcaseBusiness,
  Building2,
  ChartCandlestick,
  Check,
  ChevronDown,
  CircleUserRound,
  FileUp,
  Gauge,
  LockKeyhole,
  Menu,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UsersRound,
  WalletCards,
} from "lucide-react";

const navItems = [
  ["overview", "Overview", Gauge],
  ["portfolio", "Portfolio", BriefcaseBusiness],
  ["markets", "Markets", ChartCandlestick],
  ["alerts", "Risk alerts", Bell],
  ["paper", "Paper trading", WalletCards],
  ["team", "Team access", UsersRound],
] as const;

function Brand({ inverse = false }: { inverse?: boolean }) {
  return (
    <a className={`brand ${inverse ? "brand-inverse" : ""}`} href="#top" aria-label="FinRisk Sentinel home">
      <span className="brand-symbol"><i /><i /><i /></span>
      <span><strong>FINRISK</strong><small>SENTINEL</small></span>
    </a>
  );
}

function Landing() {
  return (
    <div id="landing" className="landing">
      <nav className="public-nav" aria-label="Public navigation">
        <Brand />
        <div className="public-links">
          <a href="#platform">Platform</a><a href="#capabilities">Capabilities</a><a href="#security">Security</a>
        </div>
        <div className="public-actions"><a href="#access">Sign in</a><a className="button-dark" href="#access">Open workspace <ArrowRight /></a></div>
      </nav>

      <main id="top">
        <section className="hero landing-hero">
          <div className="hero-copy">
            <div className="release-pill"><Sparkles /> Portfolio intelligence, explained</div>
            <h1>Know what you own.<br /><span>See what could change.</span></h1>
            <p>Bring positions, market evidence, risk monitoring, and simulated execution into one precise financial workspace.</p>
            <div className="hero-buttons"><a className="button-lime" href="#access">Start with an account <ArrowRight /></a><a className="text-link" href="#platform">Explore the terminal <ArrowRight /></a></div>
            <div className="trust-row"><span><Check /> Evidence retained</span><span><Check /> Exact-decimal ledger</span><span><Check /> Workspace isolation</span></div>
          </div>

          <div id="platform" className="terminal-preview">
            <div className="preview-bar"><Brand inverse /><div className="preview-search"><Search /> Search instruments <kbd>⌘ K</kbd></div><span className="status-live"><i /> DATA ONLINE</span></div>
            <div className="preview-body">
              <aside className="preview-watch">
                <p className="micro-label">WATCHLIST</p>
                {[["DEMO-MA", "100.20", "+0.42%"], ["DEMO-SPIKE", "125.00", "+8.70%"], ["DEMO-US", "180.20", "−0.18%"]].map((row, index) => <div className={index === 1 ? "preview-selected" : ""} key={row[0]}><span><strong>{row[0]}</strong><small>{index === 2 ? "XNYS · USD" : "XCAS · MAD"}</small></span><span><b>{row[1]}</b><small className={index === 2 ? "negative" : "positive"}>{row[2]}</small></span></div>)}
              </aside>
              <section className="preview-chart">
                <div className="preview-chart-head"><span><small>XCAS / DEMO-SPIKE</small><strong>125.00 <em>MAD</em></strong></span><span className="status-alert"><Activity /> Elevated signal</span></div>
                <svg viewBox="0 0 720 270" role="img" aria-label="Illustrative portfolio price chart">
                  <defs><linearGradient id="hero-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#a3e635" stopOpacity=".35"/><stop offset="1" stopColor="#a3e635" stopOpacity="0"/></linearGradient></defs>
                  <path className="grid-lines" d="M0 35H720 M0 95H720 M0 155H720 M0 215H720" />
                  <path className="hero-area" d="M0 224L35 214L70 219L105 191L140 198L175 172L210 184L245 145L280 158L315 124L350 136L385 92L420 111L455 83L490 98L525 66L560 76L595 45L630 58L665 31L720 18V270H0Z" />
                  <path className="hero-line" d="M0 224L35 214L70 219L105 191L140 198L175 172L210 184L245 145L280 158L315 124L350 136L385 92L420 111L455 83L490 98L525 66L560 76L595 45L630 58L665 31L720 18" />
                </svg>
                <div className="preview-axis"><span>JUL 01</span><span>AUG 01</span><span>SEP 01</span><span>OCT 01</span></div>
              </section>
              <aside className="preview-summary"><p className="micro-label">PORTFOLIO</p><strong>20,272.00 <small>MAD</small></strong><span>Daily close valuation</span><div className="mini-allocation"><i/><i/><i/></div><dl><div><dt>DEMO-US</dt><dd>88.9%</dd></div><div><dt>DEMO-SPIKE</dt><dd>6.2%</dd></div><div><dt>DEMO-MA</dt><dd>4.9%</dd></div></dl></aside>
            </div>
          </div>
        </section>

        <section id="capabilities" className="capabilities-section">
          <div className="section-intro"><p className="micro-label">ONE WORKSPACE. THE WHOLE DECISION LOOP.</p><h2>Built for clarity when the numbers matter.</h2><p>Each view carries its source, status, and limits so you can judge the evidence before acting.</p></div>
          <div className="feature-grid">
            <article><span><BriefcaseBusiness /></span><small>01 / PORTFOLIO</small><h3>Exposure at a glance</h3><p>Holdings, currencies, allocation, valuation quality, and imports in one ledger.</p></article>
            <article><span><Activity /></span><small>02 / RISK</small><h3>Signals with context</h3><p>Review the statistics, reasons, source observations, and model version behind each alert.</p></article>
            <article><span><ChartCandlestick /></span><small>03 / MARKETS</small><h3>Research without noise</h3><p>Move from instrument discovery to sourced history without losing your portfolio context.</p></article>
            <article><span><BookOpen /></span><small>04 / PRACTICE</small><h3>Simulate the decision</h3><p>Test orders against explicit reference prices before any live broker is connected.</p></article>
          </div>
        </section>

        <section id="security" className="security-section">
          <div><p className="micro-label">ACCOUNT BASED BY DESIGN</p><h2>One identity.<br/>Only your workspaces.</h2><p>Every account gets isolated portfolio data and role-based access enforced all the way to the database.</p><ul><li><ShieldCheck /> Database-enforced tenant boundaries</li><li><LockKeyhole /> Short-lived authenticated sessions</li><li><UsersRound /> Owner, admin, member, and viewer roles</li></ul></div>
          <div className="security-visual"><div className="security-ring ring-a"/><div className="security-ring ring-b"/><div className="security-core"><ShieldCheck/><strong>Protected</strong><small>WORKSPACE</small></div><span className="security-tag tag-one">PORTFOLIO</span><span className="security-tag tag-two">RISK</span><span className="security-tag tag-three">TEAM</span></div>
        </section>

        <section id="access" className="access-section">
          <div><p className="micro-label">START NOW</p><h2>Your financial workspace is ready.</h2><p>Create an account or continue securely to your portfolios, alerts, and simulated trading desk.</p></div>
          <section id="login-panel" className="login-card">
            <div className="login-icon"><CircleUserRound /></div><div><small>SECURE ACCESS</small><h3>Sign in to FinRisk</h3><p id="login-description">Loading sign-in options…</p></div>
            <form id="login-form" hidden><label>Local demo identity<select id="login-user" defaultValue="alice"><option value="alice">Alice</option><option value="bob">Bob</option></select></label><button className="button-dark" type="submit">Continue to workspace <ArrowRight /></button></form>
            <button id="provider-login" className="button-dark" hidden>Continue securely <ArrowRight /></button>
          </section>
        </section>
      </main>
      <footer className="public-footer"><Brand /><p>Portfolio intelligence with evidence in view.</p><span>© 2026 FinRisk Sentinel</span></footer>
    </div>
  );
}

function Sidebar() {
  return (
    <aside id="app-sidebar" className="app-sidebar" hidden>
      <Brand inverse />
      <nav aria-label="Primary navigation">
        <p className="micro-label">WORKSPACE</p>
        {navItems.map(([view, name, Icon], i) => <a key={view} href={`#${view}`} data-view={view} className={`nav ${i === 0 ? "active" : ""}`}><Icon /><span>{name}</span>{view === "alerts" && <i className="nav-badge">0</i>}</a>)}
      </nav>
      <div className="sidebar-help"><span><ShieldCheck /></span><strong>Evidence first</strong><p>Review the source and model before every decision.</p></div>
      <div className="sidebar-user"><div>FR</div><span><strong>FinRisk account</strong><small>Authenticated workspace</small></span><ChevronDown /></div>
    </aside>
  );
}

function Topbar() {
  return (
    <header className="app-topbar">
      <button className="mobile-menu" aria-label="Open navigation"><Menu /></button>
      <div className="breadcrumb"><span>Workspace</span><b>/</b><strong id="view-name">Overview</strong></div>
      <div className="header-actions">
        <button id="command-search" className="command-search" hidden><Search/><span>Search markets</span><kbd>Ctrl K</kbd></button>
        <span id="mode" className="mode-pill"><i/> Checking configuration</span>
        <button id="refresh" className="icon-button" title="Refresh"><RefreshCw /></button>
        <button id="logout" className="account-button" hidden><CircleUserRound /><span>Sign out</span></button>
      </div>
    </header>
  );
}

function Metrics() {
  return <section className="metrics">
    <article className="metric metric-primary"><p>NET PORTFOLIO VALUE</p><strong id="total">—</strong><small id="valuation-status">Select a portfolio</small><div className="metric-watermark"><BarChart3 /></div></article>
    <article className="metric"><p>OPEN POSITIONS</p><strong id="position-count">—</strong><small>Across all currencies</small></article>
    <article className="metric"><p>SELECTED SIGNAL</p><strong id="signal-summary">—</strong><small id="signal-subtitle">No instrument selected</small></article>
    <article className="metric"><p>EXECUTION</p><strong className="positive">Simulation</strong><small><i className="live-dot"/> Reference close enabled</small></article>
  </section>;
}

function Markets() {
  return <>
    <section id="markets" className="market-grid">
      <article className="panel market-list-panel"><div className="panel-top"><div><p className="eyebrow">MARKET INTELLIGENCE</p><h2>Instrument watch</h2></div><span className="tag">DAILY</span></div>
        <form id="search-form" className="search"><Search/><input id="search" placeholder="Ticker, company or ISIN" aria-label="Search instruments"/><button>Search</button></form>
        <div id="instrument-list" className="instrument-list"/><button id="more-instruments" className="secondary-button wide" hidden>Load more instruments</button>
      </article>
      <article className="panel chart-panel"><div className="panel-top"><div><p id="chart-market" className="eyebrow">SELECT AN INSTRUMENT</p><h2 id="chart-name">Market history</h2></div><div className="inline"><button id="watch-instrument" className="secondary-button" disabled><Plus/> Add to watchlist</button><span id="data-quality" className="tag">NO DATA</span></div></div>
        <div className="price-row"><strong id="last-price">—</strong><span id="chart-currency"/></div>
        <div className="chart-toolbar"><span>PRICE HISTORY</span><div><button type="button" data-chart-range="22">1M</button><button type="button" data-chart-range="61" className="active">3M</button><button type="button" data-chart-range="0">ALL</button></div></div>
        <svg id="chart" viewBox="0 0 700 190" role="img" aria-label="Daily closing prices"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#a3e635" stopOpacity=".25"/><stop offset="1" stopColor="#a3e635" stopOpacity="0"/></linearGradient></defs><path id="chart-area" d=""/><path id="chart-path" d=""/></svg>
        <div className="chart-labels"><span id="chart-start">—</span><span id="chart-end">—</span></div><p id="price-source" className="footnote">Prices retain their source, timestamp and quality status.</p>
      </article>
    </section>
    <section className="panel signal-panel"><div><p className="eyebrow">EXPLAINABLE SIGNAL</p><h2 id="signal-title">Waiting for market evidence</h2><p id="signal-reason" className="muted">Select an instrument to inspect price and volume behavior.</p></div><div id="evidence" className="evidence"/><p className="footnote">“No anomaly detected” means these checks found no unusual pattern. It does not mean a trade is safe.</p></section>
  </>;
}

function Portfolio() {
  return <section id="portfolio" className="panel portfolio-panel">
    <div className="panel-top"><div><p className="eyebrow">POSITIONS & EXPOSURE</p><h2>Portfolio ledger</h2></div><div className="inline"><select id="portfolio-select" aria-label="Portfolio"/><button id="save-snapshot" className="secondary-button">Save valuation</button><button id="sample-portfolio" type="button" className="primary-button">Load sample</button></div></div>
    <div className="portfolio-toolbar"><form id="portfolio-form" className="compact-create"><input id="portfolio-name" defaultValue="My portfolio" required maxLength={100} aria-label="Portfolio name"/><select id="base-currency" defaultValue="MAD" aria-label="Base currency"><option>MAD</option><option>USD</option><option>EUR</option></select><button className="secondary-button"><Plus/> New portfolio</button></form><span id="snapshot-status" className="footnote"/></div>
    <section className="allocation-card" aria-labelledby="allocation-title"><div><p className="eyebrow">ALLOCATION</p><h3 id="allocation-title">Portfolio composition</h3><p id="allocation-caption" className="footnote">Add positions to calculate allocation.</p></div><div><div id="allocation-strip" className="allocation-strip" aria-label="Portfolio allocation"/><div id="allocation-legend" className="allocation-legend"/></div></section>
    <div className="table-wrap positions-table"><table><thead><tr><th>Instrument</th><th>Quantity</th><th>Last close</th><th>Value in base</th><th>Allocation</th><th>Data status</th></tr></thead><tbody id="positions"/></table></div>
    <div className="action-drawers">
      <details><summary><span><Plus/> Record completed trade</span><ChevronDown/></summary><form id="trade-form" className="form-grid"><label>Instrument<select id="trade-instrument" required/></label><label>Side<select id="trade-side" defaultValue="buy"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Quantity<input id="trade-quantity" defaultValue="1" required inputMode="decimal"/></label><label>Unit price<input id="trade-price" required inputMode="decimal"/></label><label>Fees<input id="trade-fees" defaultValue="0" required inputMode="decimal"/></label><label>Executed at<input id="trade-time" type="datetime-local" required/></label><button className="primary-button">Record trade</button></form><p className="footnote">Records historical activity in your ledger. It does not place an order.</p></details>
      <details id="import-details"><summary><span><FileUp/> Import transactions from CSV</span><ChevronDown/></summary><p className="footnote">Required columns: market, symbol, currency, side, quantity, price, executed_at.</p><form id="import-form" className="form-grid"><label>CSV file<input id="import-file" type="file" accept=".csv,text/csv" required/></label><button className="secondary-button">Preview import</button><button id="download-template" className="secondary-button" type="button">Download template</button><button id="commit-import" className="primary-button" type="button" disabled>Commit valid import</button></form><p id="import-status" className="footnote">Select a CSV file to begin.</p><div className="table-wrap"><table><thead><tr><th>Row</th><th>Instrument</th><th>Side</th><th>Quantity</th><th>Executed</th><th>Validation</th></tr></thead><tbody id="import-rows"/></table></div><p id="import-history" className="footnote"/></details>
    </div>
  </section>;
}

function RiskAlerts() {
  return <><PortfolioRiskLab/><section id="alerts" className="panel"><div className="panel-top"><div><p className="eyebrow">RISK OPERATIONS</p><h2>Watchlist and alert evidence</h2><p className="muted">Scan monitored instruments and preserve the evidence behind each finding.</p></div><div className="inline"><span id="open-alert-count" className="tag alert-tag">0 OPEN</span><button id="run-risk-scan" className="primary-button"><Activity/> Run risk scan</button></div></div><div className="risk-grid"><div><h3>MONITORED INSTRUMENTS</h3><div className="table-wrap"><table><thead><tr><th>Instrument</th><th>Rule</th><th>Action</th></tr></thead><tbody id="watchlist"/></table></div></div><div><h3>ALERT EVIDENCE</h3><div className="table-wrap"><table><thead><tr><th>Triggered</th><th>Instrument</th><th>Evidence</th><th>Action</th></tr></thead><tbody id="risk-alerts"/></table></div></div></div><p id="risk-status" className="footnote">Add an instrument to begin monitoring.</p></section></>;
}

function PortfolioRiskLab() {
  return <section id="risk-lab" className="panel risk-lab-panel"><div className="panel-top"><div><p className="eyebrow">PORTFOLIO RISK LAB</p><h2>Tail risk, drawdown, and stress exposure</h2><p className="muted">Current-weight historical simulation with evidence coverage and explicit model limits.</p></div><div className="risk-lab-controls"><label>Confidence<select id="risk-confidence" defaultValue="0.95"><option value="0.95">95%</option><option value="0.99">99%</option></select></label><label>History<select id="risk-lookback" defaultValue="252"><option value="63">3 months</option><option value="126">6 months</option><option value="252">1 year</option><option value="366">Max</option></select></label><button id="risk-lab-run" className="secondary-button"><Gauge/> Recalculate</button><button id="save-risk-snapshot" className="primary-button"><ShieldCheck/> Save evidence</button></div></div><div className="risk-lab-status-row"><span id="risk-lab-status" className="tag">WAITING</span><p id="risk-lab-window">Select a valued portfolio to calculate risk.</p></div><div className="risk-metrics"><article><small>EXPECTED SHORTFALL</small><strong id="risk-es">â€”</strong><span>Average loss in the model tail</span></article><article><small>VALUE AT RISK</small><strong id="risk-var">â€”</strong><span>Historical loss threshold</span></article><article><small>ANNUAL VOLATILITY</small><strong id="risk-volatility">â€”</strong><span>252-session convention</span></article><article><small>MAX DRAWDOWN</small><strong id="risk-drawdown">â€”</strong><span>Peak-to-trough in window</span></article><article><small>DIVERSIFICATION</small><strong id="risk-diversification">â€”</strong><span>Ratio above 1 indicates benefit</span></article><article><small>EFFECTIVE HOLDINGS</small><strong id="risk-effective-holdings">â€”</strong><span>Concentration-adjusted count</span></article></div><div className="risk-lab-detail"><article><h3>EXPOSURE DIAGNOSTIC</h3><dl className="risk-diagnostic"><div><dt>Largest position</dt><dd id="risk-largest">â€”</dd></div><div><dt>Concentration index</dt><dd id="risk-hhi">â€”</dd></div><div><dt>Worst / best day</dt><dd id="risk-days">â€”</dd></div><div><dt>Downside frequency</dt><dd id="risk-downside">â€”</dd></div><div><dt>Evidence coverage</dt><dd id="risk-coverage">â€”</dd></div></dl></article><article><h3>DETERMINISTIC STRESS TESTS</h3><div className="table-wrap"><table><thead><tr><th>Scenario</th><th>Estimated impact</th><th>Portfolio</th></tr></thead><tbody id="risk-scenarios"/></table></div></article><article className="risk-attribution"><h3>POSITION RISK ATTRIBUTION</h3><div className="table-wrap"><table><thead><tr><th>Instrument</th><th>Current weight</th><th>Annual volatility</th><th>Portfolio correlation</th><th>Volatility contribution</th></tr></thead><tbody id="risk-attribution"/></table></div></article></div><p id="risk-limitations" className="risk-limitations">Results will state their assumptions and data limits here.</p><p id="risk-snapshot-status" className="footnote"/></section>;
}

function PaperTrading() {
  return <section id="paper" className="paper-layout"><article className="panel order-ticket"><div className="panel-top"><div><p className="eyebrow">SIMULATED EXECUTION</p><h2>Order ticket</h2></div><span className="tag success-tag">PAPER</span></div><form id="account-form" className="account-select"><label>Settlement currency<select id="account-currency" defaultValue="MAD"><option>MAD</option><option>USD</option></select></label><button className="secondary-button">Open / select account</button></form><div className="cash-balance"><small>AVAILABLE SIMULATED CASH</small><strong id="paper-cash">No account selected</strong></div><form id="order-form" className="order-form"><label>Instrument<select id="order-instrument" required/></label><div className="field-pair"><label>Side<select id="order-side" defaultValue="buy"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Quantity<input id="order-quantity" required defaultValue="1" inputMode="decimal"/></label></div><div className="reference-box"><small>REFERENCE PRICE</small><p id="order-reference">Select an instrument to load its reference price.</p></div><button className="primary-button wide" id="order-submit">Submit simulated order <ArrowRight/></button></form><p id="order-result" className="order-result" role="status"/></article><article className="panel orders-panel"><div className="panel-top"><div><p className="eyebrow">ACTIVITY</p><h2>Paper orders</h2></div></div><div className="table-wrap"><table><thead><tr><th>Submitted</th><th>Instrument</th><th>Side</th><th>Quantity</th><th>Fill price</th><th>Status</th></tr></thead><tbody id="orders"/></table></div></article></section>;
}

function Team() {
  return <section id="team" className="panel"><div className="panel-top"><div><p className="eyebrow">WORKSPACE ADMINISTRATION</p><h2>Team and permissions</h2><p className="muted">Invite collaborators and keep access aligned with their role.</p></div><span id="team-role" className="tag">MEMBER</span></div><section id="plan-summary" className="plan-summary"><div className="plan-identity"><small>CURRENT PLAN</small><strong id="plan-name">Loading</strong><span id="plan-status">Checking access</span></div><div className="plan-usage"><div><span>Seats</span><strong id="usage-seats">—</strong></div><div><span>Portfolios</span><strong id="usage-portfolios">—</strong></div><div><span>Watchlist</span><strong id="usage-watchlist">—</strong></div><div><span>Risk scans this month</span><strong id="usage-risk-scans">—</strong></div></div></section><form id="accept-invite-form" className="join-form"><label>Join with an invite code<input id="invite-code" autoComplete="off" minLength={32} maxLength={256} placeholder="Paste an invite code"/></label><button className="secondary-button">Join workspace</button></form><div id="invite-manager" className="invite-manager"><form id="invite-form" className="form-grid"><label>New member role<select id="invite-role" defaultValue="member"><option value="viewer">Viewer</option><option value="member">Member</option><option value="admin">Admin</option></select></label><label>Expires in<select id="invite-expiry" defaultValue="72"><option value="24">24 hours</option><option value="72">3 days</option><option value="168">7 days</option></select></label><button className="primary-button">Create invite code</button></form><div id="invite-secret" className="invite-secret" hidden><div><small>Share this code once. It is not shown again.</small><code id="invite-token"/></div><button id="copy-invite" className="secondary-button" type="button">Copy code</button></div></div><div className="team-grid"><div><h3>MEMBERS</h3><div className="table-wrap"><table><thead><tr><th>Identity</th><th>Role</th><th>Access</th></tr></thead><tbody id="members"/></table></div></div><div id="invitation-list-panel"><h3>INVITATIONS</h3><div className="table-wrap"><table><thead><tr><th>Role</th><th>Expires</th><th>Status</th><th/></tr></thead><tbody id="invitations"/></table></div></div></div></section>;
}

function Application() {
  return <><Sidebar/><main id="app-shell" className="app-shell" hidden><Topbar/><div id="notice" className="notice" role="status" aria-live="polite" hidden/><section id="onboarding" className="onboarding" hidden><div className="onboarding-intro"><span className="onboarding-mark"><BriefcaseBusiness/></span><p className="eyebrow">ACCOUNT READY</p><h1>Build your first financial workspace.</h1><p>Your workspace keeps portfolios, risk evidence, and team access together. Start with a portfolio now or join one you were invited to.</p><div className="onboarding-points"><span><Check/> Isolated account data</span><span><Check/> Exact-decimal portfolio ledger</span><span><Check/> Role-based team access</span></div></div><div className="onboarding-actions"><form id="onboarding-form" className="onboarding-card"><div><small>01 / CREATE</small><h2>Set up your workspace</h2><p>You can rename these later and add more portfolios at any time.</p></div><label>Workspace name<input id="onboarding-workspace" defaultValue="My workspace" required maxLength={100}/></label><label>First portfolio<input id="onboarding-portfolio" defaultValue="Main portfolio" required maxLength={100}/></label><label>Base currency<select id="onboarding-currency" defaultValue="MAD"><option>MAD</option><option>USD</option><option>EUR</option></select></label><button className="primary-button" type="submit">Create workspace <ArrowRight/></button></form><form id="onboarding-invite-form" className="onboarding-join"><div><small>HAVE AN INVITE?</small><h3>Join an existing team</h3></div><input id="onboarding-invite-code" aria-label="Invitation code" autoComplete="off" minLength={32} maxLength={256} placeholder="Paste invitation code" required/><button className="secondary-button">Join workspace</button></form></div></section><div id="workspace-content"><section className="app-heading"><div><p id="page-kicker" className="eyebrow">PORTFOLIO COMMAND CENTER</p><h1 id="page-title">Portfolio overview</h1><p id="page-description">Monitor exposure, market evidence, and simulated execution from one workspace.</p></div><div className="workspace-control"><Building2/><label><span>ACTIVE WORKSPACE</span><select id="workspace"/></label><form id="workspace-form"><input id="workspace-name" placeholder="New workspace name" aria-label="New workspace name" required maxLength={100}/><button type="submit" title="Create workspace"><Plus/></button></form></div></section><div className="last-updated"><span className="live-dot"/><span id="last-updated">Not connected</span><small> · End-of-day intelligence</small></div><div id="application" hidden><Metrics/><Portfolio/><Markets/><RiskAlerts/><PaperTrading/><Team/></div><footer className="app-footer"><span>FinRisk Sentinel</span><p>Data quality first. No automatic trade recommendations.</p></footer></div></main></>;
}

export default function Home() {
  return <><Landing/><Application/></>;
}
