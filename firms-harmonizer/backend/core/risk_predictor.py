"""Local models for satellite thermal-event proxies, using dated observations only.

Every quantity reported for day t is computed from records dated on or before t.
The 24-hour probability is a stacked logistic model whose offset is the causal
seasonal base rate of the forecast day, so a day without thermal signal stays at
(or below) that base rate. Longer horizons accumulate daily probabilities with a
first-order autocorrelated Markov chain that relaxes toward the seasonal base
rate of each future day.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.linalg import solve
from scipy.linalg.blas import dgemv, dsyrk
from scipy.ndimage import gaussian_filter1d
from scipy.special import expit, logit
from scipy.stats import rankdata, theilslopes

HORIZONS = (1, 7, 14)
LEAD_DAYS = max(HORIZONS)
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
TARGET_NAMES = ("wildfire", "accident", "combined")
PRIOR_DAILY_RATE = 0.005
PRIOR_STRENGTH = 100

# Seasonal base rate: event-day frequency within DOY +/- 15 days of the forecast day.
SEASONAL_HALF_WINDOW = 15
RECENT_YEARS = 5
# Pseudo-days of the pooled causal rate added to each long-term window (one window-year).
LONG_TERM_SHRINKAGE_DAYS = 2 * SEASONAL_HALF_WINDOW + 1
# Pseudo-days of the long-term rate added to the recent five-year window (two window-years).
RECENT_SHRINKAGE_DAYS = 2 * LONG_TERM_SHRINKAGE_DAYS
# Day-to-day persistence; equals the default AR(1) coefficient phi of the RTS Kalman smoother.
DEFAULT_MARKOV_PERSISTENCE = 0.68
PERSISTENCE_GRID = (0.55, 0.60, 0.65, 0.68, 0.70, 0.75, 0.80, 0.85)
LOGIT_CLIP = 12.0
# State-aware persistence offset: pseudo day-pairs shrinking each transition lift toward zero,
# the largest admissible lift, and the feature column that carries the state term per target
# (wildfire and combined: today's non-persistent heat; accident: persistent-source excursion).
PERSISTENCE_PSEUDO_PAIRS = 10.0
STATE_LIFT_MAX = 0.95
STATE_FEATURE = (1, 13, 1)
# Candidate stump splits; the upper quantiles reach the 90th-percentile event threshold.
STUMP_QUANTILES = (0.2, 0.5, 0.8, 0.9, 0.95)
# Pure calendar columns (historical baseline, seasonal cosine/sine, peak proximity). The seasonal
# offset already carries the annual cycle, so the base learners only model departures from it.
CALENDAR_COLUMNS = (4, 5, 6, 7)
# Wooster et al. (2005) combustion factor and the cube's one-hour FRP integration proxy.
BIOMASS_COMBUSTION_KG_PER_MJ = 0.368
FRP_INTEGRATION_SECONDS = 3600.0
DAYS_PER_YEAR = 365.25
ENTROPY_VEGETATIVE_MAX = 0.60
ENTROPY_PERSISTENT_MIN = 0.75
# A persistent-source regime also needs persistent cells to supply most trailing-year energy.
PERSISTENT_SHARE_CAP = 0.99
INTENSITY_BANDS = (
    (25.0, "Dormant / Low Surface Intensity", "Direct ground attack feasible"),
    (120.0, "Moderate Surface Fire", "Active spread; flank containment required"),
    (350.0, "High-Intensity Crown Transition", "Heavy aerial and mechanical support required"),
    (np.inf, "Extreme Convective / Plume-Driven", "Spotting hazard; prioritise perimeter safety"),
)
STATUS_NOMINAL = "Nominal multi-sensor coverage"
STATUS_UNCERTAIN = "Cloud / sensor gap uncertainty (ground reconnaissance advised)"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _calendar(epoch):
    """Return calendar year and zero-based day of year (0..365) for UTC epoch days."""
    dates = np.datetime64("1970-01-01") + np.asarray(epoch, dtype=np.int64).astype("timedelta64[D]")
    years = dates.astype("datetime64[Y]")
    return years.astype(int) + 1970, (dates - years).astype(int)


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


def _window_sum(values):
    """Circular sum over day-of-year bins within SEASONAL_HALF_WINDOW of each bin."""
    w = SEASONAL_HALF_WINDOW
    padded = np.concatenate((values[..., -w:], values, values[..., :w]), axis=-1)
    cumulative = np.cumsum(padded, axis=-1)
    cumulative = np.concatenate((np.zeros(cumulative.shape[:-1] + (1,)), cumulative), axis=-1)
    return cumulative[..., 2 * w + 1:] - cumulative[..., :-2 * w - 1]


def seasonal_base_rates(epoch_day: np.ndarray, events: np.ndarray, valid: np.ndarray,
                        lead_days: int = LEAD_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Causal event-day frequency of each target around the day of year of t+k.

    ``events`` has shape (targets, days). Column k of the result (k = 0..lead_days)
    is the base rate for calendar day t+k, built only from data dated on or before t:
    DOY +/- 15 day windows of strictly earlier calendar years, shrunk toward the
    pooled rate of all valid days through t, which is itself shrunk toward
    PRIOR_DAILY_RATE with PRIOR_STRENGTH pseudo-days. The recent rate uses the last
    RECENT_YEARS earlier years, shrunk toward the long-term rate by sample size.
    Returns (long_term, recent), each shaped (targets, days, lead_days + 1).
    """
    n = len(np.asarray(epoch_day))
    [(long_term, recent, _)] = _seasonal_tables(epoch_day, events, valid, [(np.arange(n), np.arange(lead_days + 1))])
    return long_term, recent


def _seasonal_tables(epoch_day, events, valid, requests):
    """Base rates and prior-year window support for each requested (row indices, lead days) grid.

    Each request returns (long_term, recent, support) shaped (targets, rows, leads) and
    (rows, leads); building the yearly tables once serves every request.
    """
    epoch = np.asarray(epoch_day, dtype=np.int64)
    valid = np.asarray(valid, dtype=bool)
    events = np.atleast_2d(np.asarray(events, dtype=bool)) & valid
    targets = events.shape[0]
    years, doy = _calendar(epoch)
    year_length = 365 + ((years % 4 == 0) & ((years % 100 != 0) | (years % 400 == 0)))
    pooled = ((np.cumsum(events, axis=1) + PRIOR_STRENGTH * PRIOR_DAILY_RATE)
              / (np.cumsum(valid) + PRIOR_STRENGTH))
    # Block b is the b-th calendar year in the record; tables of block b use blocks < b only.
    block = np.cumsum(np.r_[0, years[1:] != years[:-1]])
    blocks = int(block[-1]) + 1
    slot = (block * 366 + doy)[valid]
    days = np.bincount(slot, minlength=blocks * 366).reshape(blocks, 366).astype(float)
    hits = np.stack([np.bincount(slot, weights=hit[valid].astype(float), minlength=blocks * 366)
                     for hit in events]).reshape(targets, blocks, 366)
    earlier_days = np.concatenate((np.zeros((1, 366)), np.cumsum(days, axis=0)))
    earlier_hits = np.concatenate((np.zeros((targets, 1, 366)), np.cumsum(hits, axis=1)), axis=1)
    index = np.arange(blocks)
    first = np.maximum(0, index - RECENT_YEARS)
    all_days = _window_sum(earlier_days[index])
    all_hits = _window_sum(earlier_hits[:, index])
    new_days = _window_sum(earlier_days[index] - earlier_days[first])
    new_hits = _window_sum(earlier_hits[:, index] - earlier_hits[:, first])
    results = []
    for rows, leads in requests:
        length = year_length[rows, None]
        future_doy = doy[rows, None] + np.asarray(leads)[None, :]
        future_doy = np.where(future_doy >= length, future_doy - length, future_doy)
        owner = block[rows, None]
        support = all_days[owner, future_doy]
        long_term = ((all_hits[:, owner, future_doy] + LONG_TERM_SHRINKAGE_DAYS * pooled[:, rows, None])
                     / (support + LONG_TERM_SHRINKAGE_DAYS))
        recent = ((new_hits[:, owner, future_doy] + RECENT_SHRINKAGE_DAYS * long_term)
                  / (new_days[owner, future_doy] + RECENT_SHRINKAGE_DAYS))
        results.append((long_term, recent, support))
    return results


def _event_threshold(vegetation):
    """90th percentile of positive non-persistent FRP in the first fifth of the record (1 MW if none)."""
    reference = vegetation[:len(vegetation) // 5]
    reference = reference[np.isfinite(reference) & (reference > 0)]
    return (float(np.quantile(reference, 0.9)) if len(reference) else 1.0), len(reference)


def _event_runs(event, valid):
    """Consecutive valid event days ending at each day: 0 on a non-event day, -1 when unobserved."""
    index = np.arange(len(event))
    breaks = ~(event & valid)
    run = index - np.maximum.accumulate(np.where(breaks, index, -1))
    return np.where(valid, run, -1)


def _state_shifts(event, valid, base_next, seasonal_support=None, freeze_before=None):
    """As-of-t state shifts, the variant frozen before ``freeze_before`` (or None) and run lengths."""
    event, valid = np.asarray(event, dtype=bool), np.asarray(valid, dtype=bool)
    n = len(event)
    run = _event_runs(event, valid)
    state = np.where(run < 0, -1, np.minimum(run, 3) - (run >= 2))  # -1 unknown, 0 none, 1 run 1-2, 2 run >= 3
    base = np.clip(np.asarray(base_next, dtype=float), 1e-9, 1 - 1e-9)
    following = np.r_[event[1:], False].astype(float)
    pair = valid & np.r_[valid[1:], False]
    if seasonal_support is not None:
        pair &= np.asarray(seasonal_support) >= LONG_TERM_SHRINKAGE_DAYS
    calm = state == 0
    numerator = np.where(calm, base - following, following - base) * pair
    denominator = np.where(calm, base, 1 - base) * pair
    onehot = state[None, :] == np.arange(3)[:, None]
    cumulative = np.cumsum(np.stack((numerator * onehot, denominator * onehot)), axis=2)
    num, den = np.concatenate((np.zeros((2, 3, 1)), cumulative[:, :, :-1]), axis=2)
    pseudo = PERSISTENCE_PSEUDO_PAIRS
    pooled = (num[1] + num[2]) / (den[1] + den[2] + pseudo)
    lift = np.clip(np.stack((num[0] / (den[0] + pseudo),
                             (num[1] + pseudo * pooled) / (den[1] + pseudo),
                             (num[2] + pseudo * pooled) / (den[2] + pseudo))), 0.0, STATE_LIFT_MAX)

    def shifted(own_lift):
        probability = np.where(calm, base * (1 - own_lift), base + own_lift * (1 - base))
        probability = np.where(state < 0, base, probability)
        return logit(np.clip(probability, 1e-9, 1 - 1e-9)) - logit(base)

    known = np.maximum(state, 0)
    shift = shifted(lift[known, np.arange(n)])
    frozen = None
    if freeze_before is not None:
        frozen = shift.copy()
        if 0 < freeze_before < n:
            early = slice(0, freeze_before)
            frozen[early] = shifted(lift[known, freeze_before])[early]
    return shift, frozen, run


def _markov_daily(p1, future_base, rho, horizon=LEAD_DAYS):
    """Daily probabilities p_k (k = 1..horizon) relaxing from p_1 toward the base of day t+k."""
    weight = rho ** np.arange(horizon)
    return weight * np.asarray(p1, dtype=float)[:, None] + (1 - weight) * future_base[:, 1:horizon + 1]


def markov_horizon_probability(p1: np.ndarray, future_base: np.ndarray, rho: float, horizon: int) -> np.ndarray:
    """P(event within H days) = 1 - (1 - p_1) * prod_{k=2..H} (1 - p_k * (1 - rho)).

    ``future_base[:, k]`` is the seasonal base rate of day t+k; p_k = rho^(k-1) p_1 +
    (1 - rho^(k-1)) base_k. Every factor lies in [0, 1], so the result never decreases
    with H.
    """
    p1 = np.asarray(p1, dtype=float)
    daily = _markov_daily(p1, future_base, rho, horizon)
    return 1 - (1 - p1) * np.prod(1 - daily[:, 1:] * (1 - rho), axis=1)


class LogisticHazardModel:
    """L2-regularized logistic regression with bounded Newton steps and an optional fixed offset."""

    def fit(self, x, y, penalty=2.0, iterations=8, offset=None, intercept_penalty=1e-5):
        design = np.asfortranarray(np.column_stack((np.ones(len(x)), x)))
        base = np.zeros(len(x)) if offset is None else np.asarray(offset, dtype=float)
        coef = np.zeros(design.shape[1])
        if offset is None:
            coef[0] = logit(np.clip(y.mean(), 0.001, 0.999))
        regularizer = np.eye(len(coef)) * penalty
        regularizer[0, 0] = intercept_penalty
        for _ in range(iterations):
            p = expit(np.einsum("ij,j->i", design, coef) + base)
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

    def contributions(self, x):
        """Per-feature additive logit terms w_i x_i (intercept excluded)."""
        return x * self.weights


class BoostedTreesHazardModel:
    """Newton boosting of shallow trees at training-set quantile thresholds."""

    def fit(self, masks, thresholds, y, offset=None):
        design = np.asfortranarray(masks, dtype=float)
        start = np.zeros(len(y)) if offset is None else np.asarray(offset, dtype=float)
        if offset is None:
            self.base = float(logit(np.clip(y.mean(), 0.001, 0.999)))
        else:
            self.base = 0.0
            for _ in range(3):
                p = expit(start + self.base)
                self.base += float((y - p).sum() / ((p * (1 - p)).sum() + 2))
        pred = start + self.base
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

    def contributions(self, x):
        """Per-feature logit terms: each stump splits a single feature."""
        out = np.zeros(x.shape)
        for column, threshold, left, right in self.stumps:
            out[:, column] += np.where(x[:, column] <= threshold, left, right)
        return out


class IndustrialAccidentClassifier:
    """Gaussian naive Bayes likelihoods with shrinkage for rare thermal excursions."""

    def fit(self, x, y):
        groups = [x[~y], x[y]]
        self.means = np.stack([group.mean(axis=0) for group in groups])
        self.variances = np.stack([0.85 * group.var(axis=0) + 0.15 for group in groups])
        self.base = logit((y.sum()+1)/(len(y)+2))
        return self

    def contributions(self, x):
        """Per-feature log-likelihood ratios of the event and non-event classes."""
        delta = x[:, None, :] - self.means
        loss = 0.5 * (np.log(self.variances) + delta**2 / self.variances)
        return loss[:, 0] - loss[:, 1]

    def predict_logits(self, x):
        return self.base + self.contributions(x).sum(axis=1)


def _future_event(event, valid, horizon):
    """Labels cover t+1 through t+h; unknown windows are censored."""
    event_windows = sliding_window_view(np.r_[event[1:], np.zeros(horizon, bool)], horizon)
    valid_windows = sliding_window_view(np.r_[valid[1:], np.zeros(horizon, bool)], horizon)
    return event_windows.any(axis=1), valid_windows.all(axis=1)


def _support(y):
    positives = np.count_nonzero(y)
    return min(positives, len(y) - positives) >= 5


def _intercept_in_the_large(residual, offset, y, iterations=6):
    """Constant a with sum(sigma(offset + clip(residual + a))) = sum(y) on the training rows."""
    a = 0.0
    for _ in range(iterations):
        p = expit(offset + np.clip(residual + a, -LOGIT_CLIP, LOGIT_CLIP))
        a += float((y - p).sum() / ((p * (1 - p)).sum() + 1e-8))
    return a


def _fit_target(z, offset, labels, known, calibration_start, test_start, rows, seasonal_support,
                training_offset=None):
    """One 24-hour stacked fit with the seasonal offset; returns per-row logits and attributions.

    Base learners see rows whose labels end before the calibration slice and whose
    offset already rests on at least one prior-year DOY window, so they learn the
    departure from the seasonal base rate rather than the seasonal cycle itself.
    Each learner's residual logit s_m (its logit relative to the offset) is
    calibrated in the large on the training rows. The calibrator adds
    b0 + sum_m b_m s_m to the fixed offset, with b0 strongly penalized toward zero.
    Per-feature terms are centered on the average training day; the constant part
    of every s_m forms the intercept remainder.
    """
    fit = known[:calibration_start-1].copy()
    fit[:30] = False
    fit &= seasonal_support[:len(fit)] >= LONG_TERM_SHRINKAGE_DAYS
    y = labels[:len(fit)][fit]
    cal_rows = np.flatnonzero(known[calibration_start:test_start-1]) + calibration_start
    cal_y = labels[cal_rows]
    if not _support(y) or not _support(cal_y):
        return None
    z = z.copy()
    z[:, CALENDAR_COLUMNS] = 0.0
    training_offset = offset if training_offset is None else training_offset
    x, fit_offset = z[:len(fit)][fit], training_offset[:len(fit)][fit]
    quantiles = np.quantile(x, STUMP_QUANTILES, axis=0)
    thresholds = [(i, threshold) for i, maximum in enumerate(x.max(axis=0))
                  for threshold in np.unique(quantiles[:, i]) if threshold < maximum]
    columns = np.array([i for i, _ in thresholds], dtype=int)
    cuts = np.array([cut for _, cut in thresholds])
    masks = x[:, columns] <= cuts
    logistic = LogisticHazardModel().fit(x, y, offset=fit_offset)
    trees = BoostedTreesHazardModel().fit(masks, thresholds, y, offset=fit_offset) if len(cuts) else logistic
    bayes = IndustrialAccidentClassifier().fit(x, y)
    models = (logistic, trees, bayes)
    train_parts = [model.contributions(x) for model in models]
    centers = [part.mean(axis=0) for part in train_parts]
    constants = np.array([center.sum() + _intercept_in_the_large(part.sum(axis=1), fit_offset, y)
                          for part, center in zip(train_parts, centers)])

    def residuals(values):
        """Centered per-feature terms (rows, models, features) and constants (rows, models)."""
        parts = np.stack([model.contributions(values) - center for model, center in zip(models, centers)], axis=1)
        totals = parts.sum(axis=2) + constants
        # Bounded learner logits; scaling keeps the per-feature split exact.
        scale = np.minimum(1.0, LOGIT_CLIP / np.maximum(np.abs(totals), 1e-12))
        return parts * scale[..., None], constants * scale

    cal_parts, cal_constants = residuals(z[cal_rows])
    calibrator = LogisticHazardModel().fit(
        cal_parts.sum(axis=2) + cal_constants, cal_y, penalty=5, offset=offset[cal_rows],
        intercept_penalty=0.25 * len(cal_rows))
    parts, row_constants = residuals(z[rows])
    contributions = np.einsum("rmi,m->ri", parts, calibrator.weights)
    remainder = calibrator.intercept + row_constants @ calibrator.weights
    logits = offset[rows] + remainder + contributions.sum(axis=1)
    return logits, contributions, remainder, calibrator.weights


def _prior_terms(features, target):
    """Bounded, declared log-odds adjustments of the seasonal prior (no fitted parameters)."""
    terms = np.zeros_like(features)
    if target in (0, 2):
        terms[:, 0] = 0.35 * np.tanh(features[:, 0] / 4)
        terms[:, 2] = 0.60 * np.tanh(features[:, 2] / 4)
    if target in (1, 2):
        terms[:, 12] = 0.40 * np.clip(features[:, 12], 0, 1)
        terms[:, 13] = 0.80 * np.tanh(np.maximum(features[:, 13], 0) / 2.5)
    return terms


def _select_persistence(p1, future_base, labels, known, rows, calibration_start, test_start):
    """Grid value of rho minimizing the 7-day Brier score on the calibration slice."""
    horizon = 7
    mask = (rows >= calibration_start) & (rows < test_start - horizon)
    mask[mask] &= known[rows[mask]]
    y = labels[rows[mask]]
    if not _support(y):
        return DEFAULT_MARKOV_PERSISTENCE
    scores = [float(np.mean((markov_horizon_probability(p1[mask], future_base[mask], rho, horizon) - y) ** 2))
              for rho in PERSISTENCE_GRID]
    return float(PERSISTENCE_GRID[int(np.argmin(scores))])


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


def _drivers(offset_logit, contributions, remainder, shrink, readouts):
    """Signed attribution of sigma(l0 + C) - sigma(l0) in proportion to each feature's c_i."""
    magnitude = np.abs(contributions)
    total_magnitude = magnitude.sum()
    if not total_magnitude:
        base = float(expit(offset_logit))
        return [dict(feature=FEATURES[4][0], impact_pct=100.0, signed_impact_pct=0.0,
                     direction="raises" if base > 0.5 else "lowers",
                     description=f"No feature departs from its reference value; the forecast rests on "
                                 f"the seasonal base rate of {_fmt_pct(100 * base)}.",
                     observed_value=readouts[4]["observed_value"], unit=readouts[4]["unit"])]
    shift = float(contributions.sum() + remainder)
    if abs(shift) > 1e-9:
        slope = (expit(offset_logit + shift) - expit(offset_logit)) / shift
    else:
        slope = expit(offset_logit) * (1 - expit(offset_logit))
    signed = np.clip(100 * shrink * slope * contributions, -100, 100)
    order = np.argsort(-magnitude, kind="stable")[:4]
    return [dict(feature=FEATURES[i][0],
                 impact_pct=float(np.floor(10000 * magnitude[i] / total_magnitude) / 100),
                 direction="raises" if contributions[i] > 0 else "lowers",
                 description=readouts[i]["description"],
                 signed_impact_pct=_round(signed[i], 3),
                 observed_value=readouts[i]["observed_value"], unit=readouts[i]["unit"])
            for i in order if magnitude[i] > 0]


def _temper_for_observation_gap(probability, base_rate, blend):
    """Shrink toward the causal seasonal base rate as the outage grows (fully after 7 days)."""
    return probability + blend * (base_rate - probability)


def with_observation_gap(daily: dict[str, np.ndarray], through_epoch: int) -> dict[str, np.ndarray]:
    """Extend a historical series through the forecast origin with unknown observations."""
    days = int(through_epoch - daily["epoch_day"][-1])
    if days <= 0:
        return daily
    return {
        name: np.r_[values, np.arange(values[-1] + 1, through_epoch + 1)] if name == "epoch_day"
        else np.r_[values, np.full(days, 1 if name == "gap" else np.nan)]
        for name, values in daily.items()
    }


# ----------------------------------------------------------------- physical read-outs

def _best_fisher_kappa(r):
    """Best and Fisher inverse mean resultant length (same formula as von_mises)."""
    if r < .53:
        return 2.0 * r + r**3 + 5.0 * r**5 / 6.0
    if r < .85:
        return -.4 + 1.39 * r + .43 / (1.0 - r)
    return 1.0 / max(1e-4, r**3 - 4.0 * r**2 + 3.0 * r)


def _doy_label(day):
    """Year-independent day label on the leap year 2000 (same convention as von_mises)."""
    date = str(np.datetime64("2000-01-01") + np.timedelta64(int(np.floor(day + .5)) - 1, "D"))
    return f"{int(date[8:10])} {_MONTHS[int(date[5:7]) - 1]}"


def _peak_trend_days_per_decade(years, doy1, energy):
    """Theil-Sen trend of yearly energy-weighted peak days (von_mises convention), in days/decade."""
    unique, index = np.unique(years, return_inverse=True)
    theta = 2.0 * np.pi * doy1 / DAYS_PER_YEAR
    total = np.bincount(index, weights=energy, minlength=len(unique))
    safe = np.where(total > 0, total, 1.0)
    moment = (np.bincount(index, weights=energy * np.cos(theta), minlength=len(unique))
              + 1j * np.bincount(index, weights=energy * np.sin(theta), minlength=len(unique))) / safe
    keep = (total > 0) & (np.clip(np.abs(moment), 0.0, 1.0) > 1e-12)
    directional, angles = unique[keep].astype(float), np.angle(moment[keep])
    if len(angles) < 5:
        return None
    unwrapped = np.unwrap(angles) * DAYS_PER_YEAR / (2.0 * np.pi)
    if np.ptp(unwrapped) <= 1e-10:
        return 0.0
    return float(theilslopes(unwrapped, directional).slope * 10.0)


def _fmt_pct(value):
    return f"{value:.2f}%" if abs(value) < 1 else f"{value:.1f}%"


def _round(value, digits):
    """Round and normalise negative zero to 0.0."""
    return round(float(value), digits) + 0.0


def _round_array(values, digits):
    return (np.round(np.asarray(values, dtype=float), digits) + 0.0).tolist()


def _finite_or_none(value, digits=3):
    return _round(value, digits) if value is not None and np.isfinite(value) else None


def _clean(values):
    values = np.asarray(values, dtype=float)
    return np.where(np.isfinite(values), np.maximum(values, 0.0), np.nan)


def _physical_context(daily):
    """Physical quantities of the forecast origin (last row), from rows dated on or before it."""
    epoch = np.asarray(daily["epoch_day"], dtype=np.int64)
    n, t = len(epoch), len(epoch) - 1
    years, doy0 = _calendar(epoch)
    doy1 = doy0 + 1
    heat_raw = np.asarray(daily["vegetation_frp"], dtype=float)
    heat = _clean(heat_raw)
    neighbor = _clean(daily["neighbor_frp"])
    gap = np.nan_to_num(np.asarray(daily["gap"], dtype=float), nan=1.0)
    cloud = np.asarray(daily["cloud"], dtype=float)
    cloud_fraction = np.where(np.isfinite(cloud), np.where(cloud > 1, cloud / 100, cloud), np.nan)
    share = np.asarray(daily["persistent_share"], dtype=float)
    seen = np.isfinite(heat)
    energy = np.where(seen, heat, 0.0)
    threshold, _ = _event_threshold(heat_raw)
    valid = np.isfinite(heat_raw) & (gap == 0)
    excursion = np.asarray(daily["industrial_z"], dtype=float)
    fire_run = _event_runs(valid & (heat_raw >= threshold), valid)
    excursion_run = _event_runs(valid & (excursion >= INDUSTRIAL_EXCURSION), valid)
    context = dict(threshold=threshold, fire_run=int(fire_run[t]), excursion_run=int(excursion_run[t]),
                   n=n, t=t, years=years, doy0=doy0, doy1=doy1, heat=heat, neighbor=neighbor, gap=gap,
                   cloud_fraction=cloud_fraction, share=share, seen=seen,
                   excursion=excursion)
    peak = kappa = days_to_peak = label = width = None
    total = energy.sum()
    if total > 0:
        moment = np.sum(energy * np.exp(1j * 2 * np.pi * doy1 / DAYS_PER_YEAR)) / total
        resultant = float(np.clip(abs(moment), 0.0, 1.0))
        if resultant > 1e-12:
            peak = float(np.clip((np.angle(moment) % (2 * np.pi)) * DAYS_PER_YEAR / (2 * np.pi), 1.0, DAYS_PER_YEAR))
            kappa = float(_best_fisher_kappa(resultant))
            ahead = (peak - doy1[t] + DAYS_PER_YEAR / 2) % DAYS_PER_YEAR - DAYS_PER_YEAR / 2
            days_to_peak = int(np.clip(np.round(ahead), -183, 183))
            label = _doy_label(peak)
            width = float(min(365.0, DAYS_PER_YEAR / np.sqrt(max(.15, kappa))))
    prior_years = years < years[t]
    shift = _peak_trend_days_per_decade(years[prior_years], doy1[prior_years], energy[prior_years])
    # Trailing-year monthly FRP energy (non-persistent heat plus the persistent share implied by
    # persistent_share); AOI-wide active-day counts are near-uniform for large areas.
    window = slice(max(0, n - 365), n)
    persistent = np.clip(np.nan_to_num(share[window]), 0.0, PERSISTENT_SHARE_CAP)
    total_energy = energy[window] / (1.0 - persistent)
    months = (np.datetime64("1970-01-01") + epoch[window].astype("timedelta64[D]")).astype("datetime64[M]")
    monthly = np.bincount(months.astype(int) % 12, weights=total_energy, minlength=12)
    entropy = regime = None
    if monthly.sum() > 0:
        fractions = monthly / (monthly.sum() + 1e-12)
        entropy = float(np.clip(-np.sum(fractions * np.log(fractions + 1e-12)) / np.log(12.0), 0.0, 1.0))
        persistent_fraction = float((total_energy - energy[window]).sum() / total_energy.sum())
        if entropy < ENTROPY_VEGETATIVE_MAX:
            regime = "Vegetative fuel regime"
        elif entropy > ENTROPY_PERSISTENT_MIN and persistent_fraction >= 0.5:
            regime = "Persistent-source regime"
        else:
            regime = "Mixed regime"
    trailing = heat[max(0, n - 7):]
    biomass = None
    if np.isfinite(trailing).any():
        biomass = BIOMASS_COMBUSTION_KG_PER_MJ * float(np.nansum(trailing)) * FRP_INTEGRATION_SECONDS / 1000
    context.update(peak=peak, kappa=kappa, days_to_peak=days_to_peak, label=label, width=width, shift=shift,
                   entropy=entropy, regime=regime, biomass=biomass)
    return context


def _readout(description, value=None, unit=None):
    return dict(description=description, observed_value=_finite_or_none(value), unit=unit)


def factor_readouts(daily: dict[str, np.ndarray], features: np.ndarray | None = None,
                    context: dict | None = None) -> list[dict]:
    """One English sentence, observed value and unit per FEATURES entry, at the last day."""
    features = build_causal_features(daily) if features is None else features
    c = _physical_context(daily) if context is None else context
    t, heat, neighbor, row = c["t"], c["heat"], c["neighbor"], features[-1]
    readouts = []

    value = neighbor[t]
    if not np.isfinite(value):
        readouts.append(_readout("Adjacent-cell heat at t-1 was not observed.", None, "MW"))
    elif value <= 0:
        readouts.append(_readout("No adjacent-cell heat at t-1.", 0.0, "MW"))
    else:
        distance = np.abs(c["doy0"] - c["doy0"][t])
        same_season = (c["years"] < c["years"][t]) & (np.minimum(distance, 366 - distance) <= SEASONAL_HALF_WINDOW)
        history = neighbor[same_season & np.isfinite(neighbor)]
        norm = float(history.mean()) if len(history) else 0.0
        ratio = f"{value / norm:.1f}× seasonal norm" if norm > 0 else "no prior-year seasonal norm"
        readouts.append(_readout(f"Adjacent-cell heat at t-1 is {value:.1f} MW ({ratio}) — lateral spread active.",
                                 value, "MW"))

    run, level = c["fire_run"], c["threshold"]
    if run > 1:
        state = f"heat has met the {level:.1f} MW event level on {run} consecutive days"
    elif run == 1:
        state = f"heat met the {level:.1f} MW event level today"
    elif run == 0:
        state = f"today's heat is below the {level:.1f} MW event level"
    else:
        state = "today's event state is unobserved"
    recent = heat[max(0, t - 2):][np.isfinite(heat[max(0, t - 2):])]
    if len(recent):
        readouts.append(_readout(f"3-day mean non-persistent FRP is {recent.mean():.1f} MW; {state}.",
                                 recent.mean(), "MW"))
    else:
        readouts.append(_readout(f"No observed non-persistent FRP in the last 3 days; {state}.", None, "MW"))

    observed_days = np.flatnonzero(c["seen"])[-7:]
    if len(observed_days) >= 2:
        x, y = observed_days.astype(float), heat[observed_days]
        slope = float(np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2))
        readouts.append(_readout(f"7-day non-persistent FRP trend is {slope:+.1f} MW/day (mean {y.mean():.1f} MW).",
                                 slope, "MW/day"))
    else:
        readouts.append(_readout("Too few observed days to estimate a 7-day non-persistent FRP trend.", None, "MW/day"))

    fortnight = heat[max(0, t - 13):][np.isfinite(heat[max(0, t - 13):])]
    if len(fortnight):
        readouts.append(_readout(f"Largest non-persistent FRP in the trailing 14 days is {fortnight.max():.1f} MW.",
                                 fortnight.max(), "MW"))
    else:
        readouts.append(_readout("No observed non-persistent FRP in the trailing 14 days.", None, "MW"))

    if c["years"][t] > c["years"][0]:
        norm = float(np.expm1(row[4]))
        readouts.append(_readout(f"Prior-years smoothed seasonal norm for this date is {norm:.1f} MW "
                                 "(log-mean equivalent).", norm, "MW"))
    else:
        readouts.append(_readout("No completed prior year provides a seasonal norm for this date.", None, "MW"))

    day = int(c["doy1"][t])
    readouts.append(_readout(f"Day {day} of the year sits at annual-cycle cosine {row[5]:+.2f}.", row[5], None))
    readouts.append(_readout(f"Day {day} of the year sits at annual-cycle sine {row[6]:+.2f}.", row[6], None))

    if c["days_to_peak"] is None:
        readouts.append(_readout("No recorded heat defines a regional peak burning window yet.", None, "days"))
    else:
        d, window = c["days_to_peak"], f"({c['label']}, concentration κ = {c['kappa']:.1f})"
        if d > 0:
            text = f"Date is {d} days before the regional peak burning window {window}."
        elif d < 0:
            text = f"Date is {-d} days after the regional peak burning window {window}."
        else:
            text = f"Date falls on the regional peak burning window {window}."
        readouts.append(_readout(text, d, "days"))

    if c["seen"][t]:
        readouts.append(_readout(f"Non-persistent heat is {row[8]:+.1f} standard deviations from the prior-years "
                                 "seasonal norm.", row[8], "standard deviations"))
    else:
        readouts.append(_readout("Thermal anomaly is not evaluated because the origin day has no observation.",
                                 None, "standard deviations"))

    quiet = c["seen"] & (np.nan_to_num(heat) < 5) & (c["gap"] == 0)
    streak = 0
    for index in range(t - 1, -1, -1):
        if not quiet[index]:
            break
        streak += 1
    rise = neighbor[t] - neighbor[t - 1] if t >= 1 else np.nan
    if np.isfinite(rise) and rise > 0:
        text = f"Adjacent-cell heat rose by {rise:.1f} MW after {streak} quiet days."
    else:
        text = f"Adjacent-cell heat did not rise after {streak} quiet days."
    readouts.append(_readout(text, streak, "days"))

    clouds = c["cloud_fraction"][max(0, t - 2):]
    clouds = clouds[np.isfinite(clouds)]
    if len(clouds):
        readouts.append(_readout(f"Cloud cover averages {100 * clouds.mean():.0f}% over the last 3 days.",
                                 100 * clouds.mean(), "%"))
    else:
        readouts.append(_readout("No ancillary cloud measurement covers the last 3 days.", None, "%"))

    week = slice(max(0, t - 6), t + 1)
    flagged = ~c["seen"][week] | (c["gap"][week] != 0)
    readouts.append(_readout(f"{int(flagged.sum())} of the last {len(flagged)} days are missing or flagged.",
                             100 * flagged.mean(), "%"))

    share = c["share"][t]
    share_text = (f"persistent sources supply {100 * share:.0f}% of the origin-day FRP" if np.isfinite(share)
                  else "the origin-day persistent-source share was not observed")
    if c["entropy"] is None:
        text = f"No active heat in the trailing 365 days defines a temporal persistence entropy; {share_text}."
    else:
        text = f"Temporal persistence entropy H = {c['entropy']:.2f} — {c['regime'].lower()}; {share_text}."
    readouts.append(_readout(text, 100 * share if np.isfinite(share) else None, "%"))

    excursion = c["excursion"][t]
    if not np.isfinite(excursion):
        text = "No persistent-source reading on the origin day."
    elif excursion <= 0:
        text = "No persistent-source thermal excursion on the origin day."
    elif c["excursion_run"] > 0:
        days = c["excursion_run"]
        when = f"on {days} consecutive days" if days > 1 else "today"
        text = (f"Persistent-source heat is {excursion:.1f} standard deviations above its trailing baseline, at or "
                f"above the {INDUSTRIAL_EXCURSION} event level {when}.")
    else:
        text = (f"Persistent-source heat is {excursion:.1f} standard deviations above its trailing baseline, "
                f"below the {INDUSTRIAL_EXCURSION} event level.")
    readouts.append(_readout(text, excursion if np.isfinite(excursion) else None, "standard deviations"))
    return readouts


def _observation_status(c):
    t = c["t"]
    last3 = slice(max(0, t - 2), t + 1)
    clouds = c["cloud_fraction"][last3]
    cloudy = bool(np.isfinite(clouds).any() and np.nanmean(clouds) >= 0.5)
    nominal = bool(c["seen"][last3].all() and not (c["gap"][last3] != 0).any() and not cloudy)
    week = slice(max(0, t - 6), t + 1)
    missing = (~c["seen"][week] | (c["gap"][week] != 0)).astype(float)
    uncertainty = np.maximum(missing, np.nan_to_num(np.clip(c["cloud_fraction"][week], 0, 1)))
    observed = np.flatnonzero(c["seen"])
    return dict(status=STATUS_NOMINAL if nominal else STATUS_UNCERTAIN, coverage_nominal=nominal,
                uncertainty_pct=_round(100 * uncertainty.mean(), 2),
                days_since_observation=int(t - observed[-1]) if len(observed) else None)


def _intensity_regime(daily, c):
    t = c["t"]
    # Bands apply to the peak per-detection FRP; AOI or cell-day sums are on another scale.
    source = daily.get("peak_detection_frp")
    if source is None:
        return None
    values = _clean(source)
    recent = [i for i in range(t, max(-1, t - 3), -1) if np.isfinite(values[i])]
    if not recent:
        return None
    index = recent[0]
    mw = float(values[index])
    neighbor = c["neighbor"][index]
    _, regime, guidance = _band(mw)
    if np.isfinite(neighbor) and neighbor > 0:
        origin = "Adjacent-cell spread"
    elif mw > 0:
        origin = "Isolated ignition inside area"
    else:
        origin = "No active heat"
    return dict(regime=regime, guidance=guidance, intensity_mw=_round(mw, 2), diurnal_amplification_ratio=None,
                contagion_origin=origin, neighbor_frp_mw=_finite_or_none(neighbor, 2))


def _band(mw):
    if mw < 25:
        return INTENSITY_BANDS[0]
    if mw < 120:
        return INTENSITY_BANDS[1]
    if mw <= 350:
        return INTENSITY_BANDS[2]
    return INTENSITY_BANDS[3]


def _phenology(c):
    return dict(days_to_peak=c["days_to_peak"], peak_date_label=c["label"], kappa=_finite_or_none(c["kappa"]),
                season_width_days=_finite_or_none(c["width"], 2), decadal_shift_days=_finite_or_none(c["shift"], 2),
                biomass_exposure_tonnes=_finite_or_none(c["biomass"], 2),
                persistence_entropy=_finite_or_none(c["entropy"]), fuel_regime=c["regime"])


def _horizon_explanation(daily_path, base_path, rho, cumulative_14d):
    """One sentence on why the combined probability changes between 24 hours and 14 days."""
    first, last = 100 * daily_path[0], 100 * daily_path[-1]
    base_first, base_last = 100 * base_path[0], 100 * base_path[-1]
    if base_last > 1.05 * base_first + 0.01:
        season = "rising"
    elif base_last < base_first / 1.05 - 0.01:
        season = "falling"
    else:
        season = "steady"
    if last > first + 0.05:
        trend = f"escalates from {_fmt_pct(first)} tomorrow to {_fmt_pct(last)} on day 14"
    elif last < first - 0.05:
        trend = f"decays from {_fmt_pct(first)} tomorrow to {_fmt_pct(last)} on day 14"
    else:
        trend = f"stays near {_fmt_pct(first)} from tomorrow to day 14"
    return (f"Daily event probability {trend} as current conditions relax toward a {season} seasonal base rate "
            f"({_fmt_pct(base_first)} to {_fmt_pct(base_last)} per day) with day-to-day persistence "
            f"ρ = {rho:.2f}, so the chance of at least one event within 14 days is {_fmt_pct(100 * cumulative_14d)}.")


def _frechet(union, wildfire, accident):
    return np.clip(union, np.maximum(wildfire, accident), np.minimum(1.0, wildfire + accident))


def predict_risk(daily: dict[str, np.ndarray]) -> dict | None:
    """Fit on a chronological prefix and score only unseen forecast origins."""
    n = len(daily["epoch_day"])
    if not n:
        return None
    if n > MAX_DAYS or not np.all(np.diff(daily["epoch_day"]) == 1):
        raise ValueError("Risk features require at most 9,500 consecutive UTC days.")
    epoch = np.asarray(daily["epoch_day"], dtype=np.int64)
    features = build_causal_features(daily)
    calibration_start, test_start = int(0.6*n), int(0.8*n)
    z = None
    if n >= MIN_DAYS:
        fit_reference = features[30:calibration_start-max(HORIZONS)]
        z = np.clip((features - fit_reference.mean(axis=0)) / np.maximum(0.01, fit_reference.std(axis=0)), -8, 8)
    vegetation = np.asarray(daily["vegetation_frp"], dtype=float)
    observed = np.isfinite(vegetation)
    indices = np.arange(n)
    age = indices - np.maximum.accumulate(np.where(observed, indices, -1))
    rows = np.arange(calibration_start, n)
    blend = np.minimum(1.0, age[rows] / 7)
    threshold, reference_days = _event_threshold(vegetation)
    valid = observed & (np.asarray(daily["gap"]) == 0)
    wildfire = valid & (vegetation >= threshold)
    accident = valid & (np.asarray(daily["industrial_z"]) >= INDUSTRIAL_EXCURSION)
    events = np.stack((wildfire, accident, wildfire | accident))
    # Lead 1 (tomorrow) for every row; the full 14-day lead grid only for the scored rows.
    (_, tomorrow, tomorrow_support), (future_long, future_base, _) = _seasonal_tables(
        epoch, events, valid, [(indices, np.array([1])), (rows, np.arange(LEAD_DAYS + 1))])
    tomorrow, tomorrow_support = tomorrow[:, :, 0], tomorrow_support[:, 0]
    context = _physical_context(daily)
    readouts = factor_readouts(daily, features, context)
    windows = {(target, horizon): _future_event(events[target], valid, horizon)
               for target in range(3) for horizon in HORIZONS}

    p1 = np.zeros((3, len(rows)))
    rho = [DEFAULT_MARKOV_PERSISTENCE] * 3
    fitted = [False] * 3
    prior_targets, drivers, calibrated = [], [], None
    for target in range(3):
        labels, known = windows[target, 1]
        seasonal = logit(np.clip(tomorrow[target], 1e-9, 1 - 1e-9))
        # Learners train on the lifts estimated over their own slice; scored rows stay as-of-t.
        state_shift, training_shift, _ = _state_shifts(events[target], valid, tomorrow[target],
                                                       tomorrow_support, calibration_start)
        offset = seasonal + state_shift
        training_offset = seasonal + training_shift
        model = None
        if z is not None and reference_days > 0:
            model = _fit_target(z, offset, labels, known, calibration_start, test_start, rows,
                                tomorrow_support, training_offset)
        if model is None:
            prior_targets.append(TARGET_NAMES[target])
            contributions = _prior_terms(features[rows], target)
            remainder = np.zeros(len(rows))
            logits = offset[rows] + contributions.sum(axis=1)
        else:
            logits, contributions, remainder, weights = model
            fitted[target] = True
            if target == 0:
                calibrated = weights
        # The state term is today's thermal state, so it is attributed to that state's feature.
        contributions[:, STATE_FEATURE[target]] += state_shift[rows]
        p1[target] = _temper_for_observation_gap(expit(logits), future_base[target, :, 1], blend)
        if target < 2:
            drivers.append(_drivers(seasonal[-1], contributions[-1], remainder[-1], 1 - blend[-1], readouts))
    p1[2] = _frechet(p1[2], p1[0], p1[1])
    for target in range(3):
        if fitted[target]:
            labels, known = windows[target, 7]
            rho[target] = _select_persistence(p1[target], future_base[target], labels, known, rows,
                                              calibration_start, test_start)

    holdout = rows >= test_start
    horizons = []
    cumulative = {}
    for horizon in HORIZONS:
        probabilities = [markov_horizon_probability(p1[target], future_base[target], rho[target], horizon)
                         for target in range(3)]
        probabilities[2] = _frechet(probabilities[2], probabilities[0], probabilities[1])
        cumulative[horizon] = probabilities
        last = [_round(100 * p[-1], 4) for p in probabilities]
        last[2] = _round(np.clip(last[2], max(last[0], last[1]), min(100.0, last[0] + last[1])), 6)
        summary = {"days": horizon, "prior_targets": list(prior_targets)}
        for target, (name, p, value) in enumerate(zip(TARGET_NAMES, probabilities, last)):
            labels, known = windows[target, horizon]
            summary["combined_risk_pct" if name == "combined" else name + "_prob_pct"] = value
            summary[name + "_validation"] = _validation(p[holdout], labels[test_start:], known[test_start:])
        horizons.append(summary)

    risk = horizons[0]["combined_risk_pct"]
    baseline = _round(100 * future_long[2, -1, 1], 2)
    trend = _round(100 * (future_base[2, -1, 1] - future_long[2, -1, 1]), 2)
    anomaly = _round(risk - baseline - trend, 2)
    combined_daily = _markov_daily(p1[2, -1:], future_base[2, -1:], rho[2])[0]
    dates = np.datetime64("1970-01-01") + epoch[test_start:].astype("timedelta64[D]")
    origin = np.datetime64("1970-01-01") + np.timedelta64(int(epoch[-1]), "D")
    series = [dict(date=day, wildfire_prob_pct=fire, accident_prob_pct=industrial, baseline_prob_pct=base,
                   observed_event=bool(hit) if seen else None)
              for day, fire, industrial, base, hit, seen in zip(
                  np.datetime_as_string(dates).tolist(), _round_array(100 * p1[0, holdout], 4),
                  _round_array(100 * p1[1, holdout], 4), _round_array(100 * future_base[0, holdout, 1], 4),
                  wildfire[rows[holdout]].tolist(), valid[rows[holdout]].tolist())]
    outlook = [dict(date=str(origin + np.timedelta64(k, "D")),
                    prob_pct=_round(100 * combined_daily[k - 1], 4),
                    baseline_prob_pct=_round(100 * future_base[2, -1, k], 4))
               for k in range(1, LEAD_DAYS + 1)]
    model_weights = {"causal_prior": 1.0}
    if calibrated is not None:
        model_weights = dict(zip(MODEL_NAMES, map(float, calibrated)))
    metric = horizons[0]["wildfire_validation"]
    level = ("LOW", "MODERATE", "HIGH", "CRITICAL")[np.searchsorted([20, 50, 75], risk, side="right")]
    return dict(
        as_of_date=str(dates[-1]), validation_start_date=str(dates[0]), horizons=horizons,
        wildfire_prob_24h_pct=horizons[0]["wildfire_prob_pct"],
        wildfire_prob_7d_pct=horizons[1]["wildfire_prob_pct"],
        industrial_accident_prob_pct=horizons[0]["accident_prob_pct"], overall_hazard_level=level,
        combined_risk_pct=risk,
        vegetation_event_threshold_mw=threshold,
        model_metrics=dict(**metric, model_weights=model_weights),
        top_risk_factors=drivers[0],
        industrial_risk_factors=drivers[1],
        daily_probability_series=series,
        baseline_climatology_pct=baseline,
        multi_year_trend_delta_pct=trend,
        short_term_anomaly_delta_pct=anomaly,
        anomaly_multiplier=_round(risk / max(1.0, baseline), 3),
        markov_persistence=rho[2],
        horizon_explanation=_horizon_explanation(combined_daily, future_base[2, -1, 1:], rho[2],
                                                 cumulative[14][2][-1]),
        observation=_observation_status(context),
        intensity=_intensity_regime(daily, context),
        phenology=_phenology(context),
        outlook_series=outlook,
    )
