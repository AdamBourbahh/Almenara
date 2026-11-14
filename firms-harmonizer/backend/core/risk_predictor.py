"""Local models for satellite thermal-event proxies, using dated observations only."""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.linalg import solve
from scipy.linalg.blas import dgemv, dsyrk
from scipy.ndimage import gaussian_filter1d
from scipy.special import expit, logit
from scipy.stats import rankdata

HORIZONS = (1, 7, 14)
MIN_DAYS = 365
MAX_DAYS = 9_500
INDUSTRIAL_EXCURSION = 2.5
FEATURES = (
    ("Neighbor contagion", "Previous-day FRP from adjacent H3 cells in the study area."),
    ("3-day thermal buildup", "Trailing average non-persistent thermal activity."),
    ("7-day thermal buildup", "Trailing average non-persistent thermal activity."),
    ("14-day thermal maximum", "Largest non-persistent thermal signal in the trailing two weeks."),
    ("Historical baseline", "Smoothed seasonal average from completed years."),
    ("Seasonal cosine", "Position within the annual cycle."),
    ("Seasonal sine", "Position within the annual cycle."),
    ("Peak season proximity", "Alignment with the thermal season estimated from completed years."),
    ("Thermal anomaly", "Standardized departure from previous years' seasonal activity."),
    ("Quiet spell and rising heat", "Prior low-activity days interacting with rising nearby heat."),
    ("Cloud cover", "Cloud fraction where the cube has ancillary measurements."),
    ("Observation uncertainty", "Missing observations or flagged sensor gaps over the trailing week."),
    ("Persistent-source share", "Share of FRP attributed to historically persistent H3 cells."),
    ("Persistent-source excursion", "Thermal departure from the source's trailing baseline."),
)
MODEL_NAMES = ("logistic", "boosted_stumps", "gaussian_naive_bayes")
PRIOR_DAILY_RATE = 0.005
PRIOR_STRENGTH = 100


def _mean(values, window):
    valid = np.isfinite(values)
    prefix = np.r_[0.0, np.cumsum(np.where(valid, values, 0.0))]
    counts = np.r_[0, np.cumsum(valid)]
    end = np.arange(1, len(prefix))
    start = np.maximum(0, end - window)
    return (prefix[end] - prefix[start]) / np.maximum(1, counts[end] - counts[start])


def _seasonal_history(epoch, heat, phase):
    """A prediction in year Y gets a prior made only from years before Y."""
    years = (np.datetime64("1970-01-01") + epoch.astype("timedelta64[D]")).astype("datetime64[Y]")
    bins = (phase * 366).astype(int)
    total, square, count = np.zeros((3, 366))
    baseline, scale, proximity = np.zeros((3, len(epoch)))
    angle = np.arange(366) * (2 * np.pi / 366)
    starts = np.r_[0, np.flatnonzero(years[1:] != years[:-1]) + 1, len(epoch)]
    for lo, hi in zip(starts[:-1], starts[1:]):
        idx = bins[lo:hi]
        smooth_sum, smooth_square, smooth_count = gaussian_filter1d(
            np.stack((total, square, count)), 5, mode="wrap")
        mean = smooth_sum / np.maximum(smooth_count, 1e-8)
        variance = smooth_square / np.maximum(smooth_count, 1e-8) - mean ** 2
        baseline[lo:hi] = mean[idx]
        scale[lo:hi] = np.sqrt(np.maximum(variance[idx], 0.25))
        # The circular resultant estimates the von Mises mean direction.
        peak = np.arctan2(total @ np.sin(angle), total @ np.cos(angle))
        if total.any():
            proximity[lo:hi] = np.cos(2 * np.pi * phase[lo:hi] - peak)
        observed = np.isfinite(heat[lo:hi])
        x, b = heat[lo:hi][observed], idx[observed]
        total += np.bincount(b, weights=x, minlength=366)
        square += np.bincount(b, weights=x*x, minlength=366)
        count += np.bincount(b, minlength=366)
    return baseline, scale, proximity


def build_causal_features(daily: dict[str, np.ndarray]) -> np.ndarray:
    """Construct each row from the current or earlier observations."""
    epoch = np.asarray(daily["epoch_day"], dtype=np.int64)
    dates = np.datetime64("1970-01-01") + epoch.astype("timedelta64[D]")
    phase = np.asarray((dates - dates.astype("datetime64[Y]")).astype(int)) / 365.25
    angle = 2 * np.pi * phase
    heat = np.log1p(np.maximum(daily["vegetation_frp"], 0))
    neighbor = np.log1p(np.maximum(daily["neighbor_frp"], 0))
    neighbor = np.where(np.isfinite(neighbor), neighbor, 0)
    prior, scale, peak = _seasonal_history(epoch, heat, phase)
    seen = np.isfinite(heat)
    safe_heat = np.where(seen, heat, 0)
    max14 = sliding_window_view(np.r_[np.zeros(13), safe_heat], 14).max(axis=1)
    t = np.arange(len(epoch))
    # Missing days end a known quiet streak. The streak excludes day t.
    quiet = seen & (safe_heat < np.log1p(5)) & (daily["gap"] == 0)
    last_active = np.maximum.accumulate(np.where(quiet, -1, t))
    quiet_before = np.r_[0, (t - last_active)[:-1]]
    rising = np.maximum(0, np.diff(neighbor, prepend=0))
    cloud = np.asarray(daily["cloud"])
    uncertainty = (~seen | (daily["gap"] != 0)).astype(float)
    matrix = np.column_stack((
        neighbor, _mean(heat, 3), _mean(heat, 7), max14, prior,
        np.cos(angle), np.sin(angle), peak, np.clip((safe_heat - prior) / scale, -8, 8),
        np.log1p(quiet_before) * rising, cloud, _mean(uncertainty, 7),
        daily["persistent_share"], daily["industrial_z"],
    ))
    matrix[~seen, 8] = 0
    return np.nan_to_num(matrix, nan=0, posinf=0, neginf=0)


class LogisticHazardModel:
    """L2-regularized logistic regression with bounded Newton steps."""

    def fit(self, x, y, penalty=2.0, iterations=8):
        design = np.asfortranarray(np.column_stack((np.ones(len(x)), x)))
        coef = np.zeros(design.shape[1])
        coef[0] = logit(np.clip(y.mean(), 0.001, 0.999))
        regularizer = np.eye(len(coef)) * penalty
        regularizer[0, 0] = 1e-5
        for _ in range(iterations):
            p = expit(np.einsum("ij,j->i", design, coef))
            score = dgemv(1, design, y - p, trans=1) - regularizer.diagonal() * coef
            weighted = design * np.sqrt(p*(1-p))[:, None]
            hessian = dsyrk(1, weighted, trans=1) + regularizer
            step = solve(hessian, score, assume_a="pos", lower=False, check_finite=False)
            coef += step / max(1, np.max(np.abs(step)) / 2)
            if np.max(np.abs(step)) < 0.001:
                break
        self.intercept, self.weights = coef[0], coef[1:]
        return self

    def predict_logits(self, x):
        return self.intercept + np.einsum("ij,j->i", x, self.weights)


class BoostedTreesHazardModel:
    """Newton boosting of shallow trees at training-set quantile thresholds."""

    def fit(self, masks, thresholds, y):
        design = np.asfortranarray(masks, dtype=float)
        self.base = float(logit(np.clip(y.mean(), 0.001, 0.999)))
        pred = np.full(len(y), self.base)
        self.stumps = []
        for _ in range(8):
            p = expit(pred)
            residual, weight = y - p, p*(1-p)
            left_g = dgemv(1, design, residual, trans=1)
            left_h = dgemv(1, design, weight, trans=1)
            right_g, right_h = residual.sum() - left_g, weight.sum() - left_h
            gain = left_g**2/(left_h+2) + right_g**2/(right_h+2)
            best = int(gain.argmax())
            if gain[best] < 1e-6:
                break
            left = 0.35 * left_g[best] / (left_h[best]+2)
            right = 0.35 * right_g[best] / (right_h[best]+2)
            column, threshold = thresholds[best]
            self.stumps.append((column, threshold, left, right))
            pred += np.where(masks[:, best], left, right)
        return self

    def predict_logits(self, x):
        pred = np.full(len(x), self.base)
        for column, threshold, left, right in self.stumps:
            pred += np.where(x[:, column] <= threshold, left, right)
        return pred


class IndustrialAccidentClassifier:
    """Gaussian naive Bayes likelihoods with shrinkage for rare thermal excursions."""

    def fit(self, x, y):
        groups = [x[~y], x[y]]
        self.means = np.stack([group.mean(axis=0) for group in groups])
        self.variances = np.stack([0.85 * group.var(axis=0) + 0.15 for group in groups])
        self.base = logit((y.sum()+1)/(len(y)+2))
        return self

    def predict_logits(self, x):
        delta = x[:, None, :] - self.means
        loss = 0.5 * (np.log(self.variances) + delta**2 / self.variances).sum(axis=2)
        return self.base + loss[:, 0] - loss[:, 1]


def _future_event(event, valid, horizon):
    """Labels cover t+1 through t+h; unknown windows are censored."""
    event_windows = sliding_window_view(np.r_[event[1:], np.zeros(horizon, bool)], horizon)
    valid_windows = sliding_window_view(np.r_[valid[1:], np.zeros(horizon, bool)], horizon)
    return event_windows.any(axis=1), valid_windows.all(axis=1)


def _support(y):
    positives = np.count_nonzero(y)
    return min(positives, len(y) - positives) >= 5


def _fit_stack(z, labels, valid, horizon, calibration_start, test_start, prediction_x):
    fit = valid[:calibration_start-horizon].copy()
    fit[:30] = False
    y = labels[:len(fit)][fit]
    cal = valid[calibration_start:test_start-horizon]
    cal_y = labels[calibration_start:test_start-horizon][cal]
    if not _support(y) or not _support(cal_y):
        return None, None, None
    x = z[:len(fit)][fit]
    quantiles = np.quantile(x, [0.2, 0.5, 0.8], axis=0)
    thresholds = [(i, threshold) for i, maximum in enumerate(x.max(axis=0))
                  for threshold in np.unique(quantiles[:, i]) if threshold < maximum]
    columns = np.array([i for i, _ in thresholds], dtype=int)
    cuts = np.array([cut for _, cut in thresholds])
    masks = x[:, columns] <= cuts
    logistic = LogisticHazardModel().fit(x, y)
    trees = BoostedTreesHazardModel().fit(masks, thresholds, y) if len(cuts) else logistic
    bayes = IndustrialAccidentClassifier().fit(x, y)
    models = (logistic, trees, bayes)

    def stack(values):
        return np.clip(np.column_stack([model.predict_logits(values) for model in models]), -12, 12)

    cal_x = z[calibration_start:test_start-horizon][cal]
    calibrator = LogisticHazardModel().fit(stack(cal_x), cal_y, penalty=5)
    return expit(calibrator.predict_logits(stack(prediction_x))), logistic.weights, calibrator.weights


def _validation(probability, labels, valid):
    if probability is None:
        return dict(samples=0, positives=0, brier_score=None, roc_auc=None, reliability=[])
    p, y = probability[valid], labels[valid]
    n, positives = len(y), int(y.sum())
    if not n:
        return dict(samples=0, positives=0, brier_score=None, roc_auc=None, reliability=[])
    negatives = n - positives
    auc = None
    if positives and negatives:
        auc = float((rankdata(p)[y].sum() - positives*(positives+1)/2) / (positives*negatives))
    bins = np.minimum(4, (p * 5).astype(int))
    reliability = []
    for i in np.unique(bins):
        group = bins == i
        reliability.append(dict(samples=int(group.sum()), mean_predicted_pct=float(100*p[group].mean()),
                                observed_pct=float(100*y[group].mean())))
    return dict(samples=n, positives=positives, brier_score=float(np.mean((p-y)**2)),
                roc_auc=auc, reliability=reliability)


def _drivers(row, weights):
    if weights is None:
        return []
    contributions = row * weights
    magnitude = np.abs(contributions)
    total = magnitude.sum()
    if not total:
        return []
    return [dict(feature=FEATURES[i][0], impact_pct=float(100*(magnitude[i]/total)),
                 direction="raises" if contributions[i] > 0 else "lowers", description=FEATURES[i][1])
            for i in np.argsort(-magnitude)[:4] if magnitude[i] > 0]


def _prior_prediction(features, labels, known, horizon, test_start, target):
    """Shrink historical event frequency to a fixed prior, then adjust its log odds."""
    fit_end = max(0, test_start - horizon)
    fit = known[:fit_end]
    prior = 1 - (1 - PRIOR_DAILY_RATE) ** horizon
    rate = (labels[:fit_end][fit].sum() + PRIOR_STRENGTH * prior) / (fit.sum() + PRIOR_STRENGTH)
    recent = features[test_start:]
    # These bounded terms are explicit prior assumptions, independent of the holdout.
    terms = np.zeros_like(recent)
    if target in (0, 2):
        terms[:, 0] = 0.35 * np.tanh(recent[:, 0] / 4)
        terms[:, 2] = 0.60 * np.tanh(recent[:, 2] / 4)
        terms[:, 7] = 0.35 * recent[:, 7]
    if target in (1, 2):
        terms[:, 12] = 0.40 * np.clip(recent[:, 12], 0, 1)
        terms[:, 13] = 0.80 * np.tanh(np.maximum(recent[:, 13], 0) / 2.5)
    probability = expit(logit(rate) + terms.sum(axis=1))
    drivers = _drivers(terms[-1], np.ones(len(FEATURES)))
    if not drivers:
        drivers = [dict(feature="Historical event frequency", impact_pct=100.0,
                        direction="raises" if rate > 0.5 else "lowers",
                        description="Baseline log odds from earlier event windows and the fixed prior.")]
    return probability, drivers


def predict_risk(daily: dict[str, np.ndarray]) -> dict | None:
    """Fit on a chronological prefix and score only unseen forecast origins."""
    n = len(daily["epoch_day"])
    if not n:
        return None
    if n > MAX_DAYS or not np.all(np.diff(daily["epoch_day"]) == 1):
        raise ValueError("Risk features require at most 9,500 consecutive UTC days.")
    features = build_causal_features(daily)
    calibration_start, test_start = int(0.6*n), int(0.8*n)
    z = None
    if n >= MIN_DAYS:
        fit_reference = features[30:calibration_start-max(HORIZONS)]
        z = np.clip((features - fit_reference.mean(axis=0)) / np.maximum(0.01, fit_reference.std(axis=0)), -8, 8)
    observed = np.isfinite(daily["vegetation_frp"])
    reference = daily["vegetation_frp"][:n//5]
    reference = reference[np.isfinite(reference) & (reference > 0)]
    threshold = float(np.quantile(reference, 0.9)) if len(reference) else 1.0
    valid = observed & (daily["gap"] == 0)
    wildfire = valid & (daily["vegetation_frp"] >= threshold)
    accident = valid & (daily["industrial_z"] >= INDUSTRIAL_EXCURSION)
    events = (wildfire, accident, wildfire | accident)
    predictions = [None, None, None]
    horizons, first_drivers, stack_weights = [], [], []
    first_predictions = None
    for horizon in HORIZONS:
        audits = []
        prior_targets = []
        names = ("wildfire", "accident", "combined")
        for index, event in enumerate(events):
            labels, known = _future_event(event, valid, horizon)
            p, weights, stack = None, None, None
            if z is not None and len(reference) > 0:
                p, weights, stack = _fit_stack(z, labels, known, horizon, calibration_start, test_start, z[test_start:])
            if p is None:
                p, drivers = _prior_prediction(features, labels, known, horizon, test_start, index)
                prior_targets.append(names[index])
            else:
                drivers = _drivers(z[-1], weights)
                if not drivers:
                    drivers = [dict(feature="Model baseline", impact_pct=100.0,
                                    direction="raises" if p[-1] > 0.5 else "lowers",
                                    description="Estimated likelihood at the model's reference feature values.")]
            if horizon == 1:
                first_drivers.append(drivers)
                stack_weights.append(stack)
            if predictions[index] is not None:
                p = np.maximum(p, predictions[index])
            predictions[index] = p
            audits.append((labels[test_start:], known[test_start:]))
        fire_p, accident_p, union_p = predictions
        predictions[2] = np.clip(union_p, np.maximum(fire_p, accident_p), fire_p + accident_p)
        if horizon == 1:
            first_predictions = predictions.copy()
        summary = {"days": horizon, "prior_targets": prior_targets}
        for name, p, audit in zip(names, predictions, audits):
            peak_key = "combined_risk_pct" if name == "combined" else name + "_prob_pct"
            summary[peak_key] = float(100 * p[-1])
            summary[name + "_validation"] = _validation(p, *audit)
        horizons.append(summary)
    dates = np.datetime_as_string(np.datetime64("1970-01-01") + daily["epoch_day"][test_start:].astype("timedelta64[D]"))
    calibrated = stack_weights[0]
    model_weights = {"causal_prior": 1.0}
    if calibrated is not None:
        model_weights = dict(zip(MODEL_NAMES, map(float, calibrated)))
    metric = horizons[0]["wildfire_validation"]
    risk = horizons[0]["combined_risk_pct"]
    level = ("LOW", "MODERATE", "HIGH", "CRITICAL")[np.searchsorted([20, 50, 75], risk, side="right")]
    series = [dict(date=str(day),
                   wildfire_prob_pct=float(100*first_predictions[0][i]),
                   accident_prob_pct=float(100*first_predictions[1][i]))
              for i, day in enumerate(dates)]
    return dict(
        as_of_date=str(dates[-1]), validation_start_date=str(dates[0]), horizons=horizons,
        wildfire_prob_24h_pct=horizons[0]["wildfire_prob_pct"],
        wildfire_prob_7d_pct=horizons[1]["wildfire_prob_pct"],
        industrial_accident_prob_pct=horizons[0]["accident_prob_pct"], overall_hazard_level=level,
        combined_risk_pct=risk,
        vegetation_event_threshold_mw=threshold,
        model_metrics=dict(**metric, model_weights=model_weights),
        top_risk_factors=first_drivers[0],
        industrial_risk_factors=first_drivers[1],
        daily_probability_series=series,
    )
