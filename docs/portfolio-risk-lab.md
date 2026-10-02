# Portfolio Risk Lab

The Risk Lab turns the current portfolio ledger and stored daily market evidence into an explainable portfolio-risk report. It is designed for portfolio decisions and review, not trade recommendations or forecasts.

## Results

For 95% or 99% confidence and a selected history window, the service reports:

- historical Value at Risk and Expected Shortfall;
- annualized volatility, maximum drawdown, worst and best day, and downside frequency;
- Herfindahl concentration, effective holdings, largest exposure, and diversification ratio;
- position weight, standalone volatility, correlation to the portfolio, and contribution to portfolio volatility;
- deterministic broad-market, severe-market, largest-position, and foreign-currency stress scenarios;
- source quality, observation counts, evaluation limits, and a SHA-256 evidence fingerprint.

Expected Shortfall is included alongside VaR because VaR stops at a loss quantile while Expected Shortfall measures average loss beyond that cutoff. This follows the coherent-risk treatment in Acerbi and Tasche, [Expected Shortfall: a natural coherent alternative to Value at Risk](https://arxiv.org/abs/cond-mat/0105191) and [On the coherence of Expected Shortfall](https://arxiv.org/abs/cond-mat/0104295).

## Method

The method `current-weight-historical-v1`:

1. Creates a complete current valuation in the portfolio base currency.
2. Loads consistently adjusted daily closes for every open position.
3. Intersects session dates so each portfolio return uses evidence available for every position.
4. Applies current net-value weights to each aligned historical return.
5. Uses the empirical lower tail for VaR and Expected Shortfall.
6. Uses sample covariance to attribute portfolio volatility to each position.

At least 30 aligned return observations are required. Annualized volatility uses 252 sessions. Concentration uses absolute gross-exposure shares, while historical returns use net-value weights. Risk-contribution percentages can be negative when a position acted as a hedge.

## Limits and status

`complete` means all positions had sufficient accepted price history. `limited` means the calculation is usable but has a material disclosed limit. `insufficient_data` withholds metrics.

The first method version holds weights fixed, treats scenarios as illustrations without probabilities, and does not model taxes, liquidity, transaction costs, intraday movement, or future rebalancing. Historical FX returns are not yet part of the return series; a portfolio with foreign-currency positions is marked `limited` and still uses the latest accepted FX rate for current valuation.

## API

- `GET /v1/workspaces/{workspace}/portfolios/{portfolio}/risk-lab?confidence=0.95&lookback=252`
- `POST /v1/workspaces/{workspace}/portfolios/{portfolio}/risk-lab/snapshots`
- `GET /v1/workspaces/{workspace}/portfolios/{portfolio}/risk-lab/snapshots/{snapshot}`

Snapshot creation requires owner, admin, or member access. Reads remain tenant-isolated through PostgreSQL row-level security. A saved snapshot retains the payload, parameters, portfolio version, method version, and evidence fingerprint.

## Native-code boundary

This version uses Python `Decimal` arithmetic because current workloads are interactive, deterministic, and I/O dominated. A C++ or Rust kernel should be introduced only after production benchmarks show that Monte Carlo paths, large covariance matrices, or optimization loops dominate latency. Keeping the boundary behind the analytics module allows a native implementation later without changing the API or evidence format.
