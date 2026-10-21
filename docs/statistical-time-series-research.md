# Experimental Time-Series Research (ARIMA / SARIMA)

This optional, offline research module is independent of the production Risk Lab. It does not create investment advice or change historical VaR, Expected Shortfall, valuation, or portfolio endpoints.

## What it does
- Validates an existing `load_history`-shaped payload containing **90+** chronologically ordered, consistently adjusted daily observations with valid provenance.
- Estimates an ARIMA(1,1,1) or a fixed SARIMA(1,1,0)(1,0,0,s) model on **log closing prices**. Orders are research baselines, not optimized choices.
- Produces an interval forecast for future **observation steps** (not calendar dates).
- Uses robust STL decomposition to summarize seasonal structure at the configured period.
- Performs an exploratory CUSUM residual-stability check and identifies a candidate single mean-shift split through the sum of squared errors.
- Compares one-step-ahead rolling-origin predictions with the last-observation (naive) baseline, reporting MAE and RMSE.

## Optional dependencies

Install separately in your analysis environment, not the base application:

```sh
python -m pip install "numpy>=1.26,<3" "statsmodels>=0.14,<0.16"
```

The runtime dependency group is deliberately *not* added to the production lockfile or Docker environment. Only import this module from an environment with scientific dependencies installed.

## Usage

```python
from services.analytics.statistical_research import analyze_time_series

# history: a quality-checked mapping with `bars` as returned by
# services.analytics.engine.load_history(..., limit=...).
result = analyze_time_series(
    history,
    model="arima",  # alternatively "sarima"
    seasonal_period=5,  # observed trading sessions, not weekdays
    horizon=5,
    folds=3,
)
print(result["backtest"])
print(result["forecast"])
```

## Scientific and operational limitations

- This is **experimental**. Tests use synthetic data, not demonstrated live-market forecast performance. No forecasting claim should be made on a CV before benchmark results on real, out-of-sample data.
- The data source needs sufficient history and complete adjusted sessions. Never silently fill gaps or mix adjusted and unadjusted prices. The module uses observation order; it does **not** detect missing market sessions on its own and relies on the upstream quality validator.
- SARIMA with a period of 5 represents a *hypothesis* about trading-session periodicity, not established financial seasonality.
- ARIMA on price levels is a baseline; a random-walk forecast often performs as well or better.
- Return-series CUSUM diagnostics can be distorted by dependence and heteroskedasticity. The chosen break location is exploratory and not an independently tested causal regime change.
- The confidence bounds are model-based; no calibrated coverage on live data has been established.
- Beta regression is not added: financial prices and unbounded returns are not beta-distributed proportion responses. Only add such modelling for a genuine bounded indicator.
- Cost of repeated model fitting grows with window length. Run in an offline research worker; do not call directly from a production request handler without resource/time limits.

## Validation

```sh
python -m pytest -q tests/test_statistical_research.py
```

Also run the existing unit and integration suites in the project's pinned environment before merging.
