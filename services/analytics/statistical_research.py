"""Optional research-only time-series models for adjusted daily market prices.

The runtime dependencies (numpy/statsmodels) are intentionally optional. This
module never changes portfolio risk/valuation or produces trading advice.
"""
import math
from datetime import date
from statistics import mean

METHOD_VERSION = "time-series-research-v1"
MIN_OBSERVATIONS = 90


def _prepare_history(history):
    if history.get("quality") not in {"end_of_day", "demo"}:
        raise ValueError("Only complete, current, provenance-checked market history is supported")
    bars = history.get("bars", [])
    if len(bars) < MIN_OBSERVATIONS:
        raise ValueError(f"At least {MIN_OBSERVATIONS} adjusted observations are required")
    dates, prices = [], []
    for bar in bars:
        if not bar.get("adjusted"):
            raise ValueError("All daily closing prices must be consistently adjusted")
        day = bar.get("session_date")
        if isinstance(day, str):
            day = date.fromisoformat(day)
        if not isinstance(day, date):
            raise ValueError("Every bar needs a valid session_date")
        price = float(bar["close"])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Closing prices must be positive and finite")
        if dates and day <= dates[-1]:
            raise ValueError("Session dates must be strictly increasing with no duplicates")
        dates.append(day)
        prices.append(price)
    return dates, prices


def _build_model(log_prices, model, seasonal_period):
    from statsmodels.tsa.arima.model import ARIMA

    if model == "arima":
        return ARIMA(log_prices, order=(1, 1, 1), trend="n").fit()
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    return SARIMAX(
        log_prices,
        order=(1, 1, 0),
        seasonal_order=(1, 0, 0, seasonal_period),
        trend="n",
        enforce_stationarity=True,
        enforce_invertibility=True,
    ).fit(disp=False, maxiter=75)


def _break_candidate(returns, dates):
    """Exploratory single break in mean returns; not a causal claim."""
    import numpy as np
    from statsmodels.regression.linear_model import OLS
    from statsmodels.stats.diagnostic import breaks_cusumolsresid

    n = len(returns)
    minimum = max(15, n // 10)
    centered = np.asarray(returns, dtype=float)
    total_sse = float(np.sum((centered - centered.mean()) ** 2))
    best_split, best_gain = None, 0.0
    for split in range(minimum, n - minimum + 1):
        left, right = centered[:split], centered[split:]
        sse = float(np.sum((left - left.mean()) ** 2) + np.sum((right - right.mean()) ** 2))
        gain = total_sse - sse
        if gain > best_gain:
            best_gain, best_split = gain, split
    fitted = OLS(centered, np.ones((n, 1))).fit()
    _, pvalue, _ = breaks_cusumolsresid(fitted.resid, ddof=1)
    return {
        "method": "CUSUM stability test + single mean-shift candidate (SSE)",
        "cusum_p_value": round(float(pvalue), 6),
        "instability_flag_5pct": bool(float(pvalue) < 0.05),
        "candidate_date": dates[best_split + 1].isoformat() if best_split is not None else None,
        "sse_improvement_fraction": round(best_gain / total_sse, 6) if total_sse > 0 else 0.0,
        "caveat": "Exploratory mean-shift screen: serial dependence, heteroskedasticity "
        "and multiple candidate dates limit interpretation.",
    }


def analyze_time_series(history, *, model="arima", seasonal_period=5, horizon=5, folds=3):
    """Fit log-price forecasting models and report honest one-step walk-forward errors.

    Seasonal period refers to trading observations, not calendar days.
    Predictions are step-indexed because future trading sessions are not known.
    """
    if model not in {"arima", "sarima"}:
        raise ValueError("model must be 'arima' or 'sarima'")
    if not 4 <= seasonal_period <= 30 or not 1 <= horizon <= 10 or not 1 <= folds <= 6:
        raise ValueError("Out-of-range seasonal_period, horizon, or folds")
    dates, prices = _prepare_history(history)
    if len(prices) < max(MIN_OBSERVATIONS, seasonal_period * 4, folds + 50):
        raise ValueError("Insufficient data for the requested seasonal period and backtest")

    import numpy as np
    from statsmodels.tsa.seasonal import STL

    levels = np.asarray(prices, dtype=float)
    log_prices = np.log(levels)
    if not np.isfinite(log_prices).all():
        raise ValueError("Log prices must be finite")

    # Each backtest origin uses only observations available before its target.
    errors, naive_errors = [], []
    for origin in range(len(levels) - folds, len(levels)):
        fitted = _build_model(log_prices[:origin], model, seasonal_period)
        prediction = float(np.exp(fitted.forecast(steps=1)[0]))
        if not math.isfinite(prediction):
            raise ValueError("Backtest produced a non-finite prediction")
        errors.append(prediction - prices[origin])
        naive_errors.append(prices[origin - 1] - prices[origin])

    fitted = _build_model(log_prices, model, seasonal_period)
    forecast = fitted.get_forecast(steps=horizon)
    log_prediction = np.asarray(forecast.predicted_mean, dtype=float)
    interval = np.asarray(forecast.conf_int(alpha=0.05), dtype=float)
    predicted, lower, upper = np.exp(log_prediction), np.exp(interval[:, 0]), np.exp(interval[:, 1])
    if not all(np.isfinite(v).all() for v in (predicted, lower, upper)):
        raise ValueError("Forecast exceeds representable numeric values")

    decomposition = STL(log_prices, period=seasonal_period, robust=True).fit()
    seasonal_variance = float(np.var(decomposition.seasonal + decomposition.resid))
    strength = (
        max(0.0, 1.0 - float(np.var(decomposition.resid)) / seasonal_variance)
        if seasonal_variance > 0 else 0.0
    )
    changes = np.diff(log_prices)
    return {
        "status": "complete",
        "method_version": METHOD_VERSION,
        "model": model.upper(),
        "parameters": {
            "seasonal_period_observations": seasonal_period,
            "forecast_steps": horizon,
            "walk_forward_folds": folds,
            "confidence": 0.95,
            "target": "adjusted close (modelled on log scale)",
        },
        "data": {
            "observations": len(prices),
            "first_session": dates[0].isoformat(),
            "last_session": dates[-1].isoformat(),
            "source": history.get("source"),
            "quality": history.get("quality"),
            "is_demo": any(bar.get("is_demo", False) for bar in history["bars"]),
        },
        "forecast": [
            {
                "step": i + 1,
                "predicted_close": round(float(predicted[i]), 6),
                "lower_95": round(float(lower[i]), 6),
                "upper_95": round(float(upper[i]), 6),
            }
            for i in range(horizon)
        ],
        "decomposition": {
            "method": "robust STL on log prices",
            "seasonal_strength": round(strength, 6),
            "latest_seasonal_pct": [
                round((math.exp(float(v)) - 1) * 100, 4)
                for v in decomposition.seasonal[-seasonal_period:]
            ],
        },
        "structural_break": _break_candidate(changes, dates),
        "backtest": {
            "method": "expanding-window one-step-ahead, no lookahead",
            "model_mae": round(mean(abs(x) for x in errors), 6),
            "naive_mae": round(mean(abs(x) for x in naive_errors), 6),
            "model_rmse": round(math.sqrt(mean(x * x for x in errors)), 6),
            "naive_rmse": round(math.sqrt(mean(x * x for x in naive_errors)), 6),
            "folds": folds,
        },
        "diagnostics": {"aic": round(float(fitted.aic), 4)},
        "limitations": [
            "Research-only analysis, not investment advice or evidence of forecasting skill.",
            "Seasonality is defined in observed sessions, not automatically in calendar time.",
            "ARIMA/SARIMA on log prices assumes the configured model is appropriate; "
            "compare against naive baseline before interpreting results.",
            "CUSUM and candidate date are exploratory, not a confirmed regime change.",
            "Missing sessions are never interpolated; forecasts omit future dates.",
        ],
    }
