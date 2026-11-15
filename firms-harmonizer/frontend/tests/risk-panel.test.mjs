import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';

const dir = await mkdtemp(new URL('../node_modules/.risk-', import.meta.url));
after(() => rm(dir, {recursive: true, force: true}));
const source = await readFile(new URL('../src/components/Risk/riskPresentation.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'p.mjs'), ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText);
const P = await import(pathToFileURL(join(dir, 'p.mjs')).href);

const validation = {samples: 0, positives: 0, brier_score: null, roc_auc: null, reliability: []};
const horizon = (days, combined) => ({days, wildfire_prob_pct: null, accident_prob_pct: null, combined_risk_pct: combined,
  wildfire_validation: validation, accident_validation: validation, combined_validation: validation});
const series = Array.from({length: 5}, (_, i) => ({date: `2026-08-0${i + 1}`, wildfire_prob_pct: i * 10, accident_prob_pct: i === 2 ? null : 5,
  baseline_prob_pct: 20, observed_event: i === 1 || i === 4}));
/** Full new-style assessment. */
const full = {
  as_of_date: '2026-08-10', validation_start_date: '2025-01-01', combined_risk_pct: 30.0,
  overall_hazard_level: 'HIGH', horizons: [horizon(1, 30), horizon(7, 52.5), horizon(14, 71)],
  top_risk_factors: [
    {feature: 'Heat', impact_pct: 40, direction: 'raises', description: 'd', signed_impact_pct: 14.2, observed_value: 31.5, unit: '°C'},
    {feature: 'Rain', impact_pct: 10, direction: 'lowers', description: 'd', signed_impact_pct: -7.1}],
  industrial_risk_factors: [], daily_probability_series: series,
  baseline_climatology_pct: 12.5, multi_year_trend_delta_pct: 3.2, short_term_anomaly_delta_pct: 14.3, anomaly_multiplier: 2.4,
  markov_persistence: 0.68, horizon_explanation: 'x',
  observation: {status: 'Nominal coverage', coverage_nominal: true, uncertainty_pct: 4.26, days_since_observation: 0},
  outlook_series: [{date: '2026-08-11', prob_pct: 30, baseline_prob_pct: 12}, {date: '2026-08-12', prob_pct: null, baseline_prob_pct: 12}, {date: '2026-08-13', prob_pct: 40, baseline_prob_pct: 12}],
};
/** Old backend: none of the new fields. */
const old = {
  as_of_date: '2026-08-10', validation_start_date: '2025-01-01', combined_risk_pct: 12, overall_hazard_level: null,
  horizons: [horizon(1, 12)], top_risk_factors: [{feature: 'Heat', impact_pct: 30, direction: 'raises', description: 'd'}],
  industrial_risk_factors: [], daily_probability_series: [{date: '2026-08-01', wildfire_prob_pct: 1, accident_prob_pct: 2}],
};

test('formatPct: one decimal, thresholds, null safe', () => {
  assert.equal(P.formatPct(12.345), '12.3%');
  assert.equal(P.formatPct(0.04), '<0.1%');
  assert.equal(P.formatPct(0), '0.0%');
  assert.equal(P.formatPct(99.95), '>99.9%');
  assert.equal(P.formatPct(null), 'not available');
  assert.equal(P.formatPct(NaN), 'not available');
  assert.equal(P.formatPct(undefined), 'not available');
});

test('formatSignedPct: real minus, explicit plus, no negative zero', () => {
  assert.equal(P.formatSignedPct(14.24), '+14.2%');
  assert.equal(P.formatSignedPct(-5.1), '−5.1%');
  assert.equal(P.formatSignedPct(-0), '0.0%');
  assert.equal(P.formatSignedPct(-0.04), '0.0%');
  assert.equal(P.formatSignedPct(0.04), '0.0%');
  assert.equal(P.formatSignedPct(null), 'not available');
  assert.ok(!P.formatSignedPct(-0.04).includes('-'));
});

test('formatMultiplier', () => {
  assert.equal(P.formatMultiplier(2.44), '2.4×');
  assert.equal(P.formatMultiplier(null), 'not available');
  assert.equal(P.formatMultiplier(Infinity), 'not available');
});

test('hazard level: explicit wins, fallback from combined, null otherwise', () => {
  assert.equal(P.hazardLevel(full), 'HIGH');
  assert.equal(P.hazardLevel(old), 'LOW');
  assert.equal(P.hazardLevel({overall_hazard_level: null, combined_risk_pct: 20}), 'MODERATE');
  assert.equal(P.hazardLevel({overall_hazard_level: null, combined_risk_pct: 50}), 'HIGH');
  assert.equal(P.hazardLevel({overall_hazard_level: null, combined_risk_pct: 80}), 'CRITICAL');
  assert.equal(P.hazardLevel({overall_hazard_level: null, combined_risk_pct: null}), null);
});

test('equation bar closes to the total and is null when a part is missing', () => {
  const eq = P.buildEquation(full);
  assert.deepEqual(eq.terms.map((t) => t.text), ['12.5%', '+3.2%', '+14.3%']);
  assert.equal(eq.total.text, '30.0%');
  assert.equal(eq.total.multiplier, '2.4× seasonal norm');
  assert.ok(Math.abs(eq.residual) < 1e-9);
  assert.equal(eq.closes, true);
  assert.equal(P.buildEquation({...full, short_term_anomaly_delta_pct: -4}).closes, false);
  assert.equal(P.buildEquation(old), null);
  assert.equal(P.buildEquation({...full, multi_year_trend_delta_pct: null}), null);
  assert.equal(P.buildEquation({...full, combined_risk_pct: null}), null);
  const noMult = P.buildEquation({...full, anomaly_multiplier: null});
  assert.equal(noMult.total.multiplier, null);
  const neg = P.buildEquation({...full, multi_year_trend_delta_pct: -2});
  assert.equal(neg.terms[1].text, '−2.0%');
});

test('observation pill', () => {
  const pill = P.observationPill(full.observation);
  assert.equal(pill.warning, false);
  assert.deepEqual(pill.parts, ['Nominal coverage', '4.3% of the last 7 days unobserved']);
  const warn = P.observationPill({status: 'Stale', coverage_nominal: false, uncertainty_pct: null, days_since_observation: 3});
  assert.equal(warn.warning, true);
  assert.deepEqual(warn.parts, ['Stale', 'last observation 3 d ago']);
  assert.equal(P.observationPill(null), null);
  assert.equal(P.observationPill(undefined), null);
  assert.equal(P.observationPill({status: '', coverage_nominal: true}), null);
});

test('peak phrasing', () => {
  assert.equal(P.peakPhrase(9, 'Aug 19'), '9 days before peak · Aug 19');
  assert.equal(P.peakPhrase(1, null), '1 day before peak');
  assert.equal(P.peakPhrase(-12, 'Jul 1'), '12 days after peak · Jul 1');
  assert.equal(P.peakPhrase(-1, null), '1 day after peak');
  assert.equal(P.peakPhrase(0, 'Aug 1'), 'At seasonal peak · Aug 1');
  assert.equal(P.peakPhrase(null, 'Aug 1'), 'not available');
  assert.equal(P.driftPhrase(2.34), '+2.3 days/decade');
  assert.equal(P.driftPhrase(-1.5), '−1.5 days/decade');
  assert.equal(P.driftPhrase(null), 'not available');
});

test('driver bars: signed scaling relative to the largest, side and tone', () => {
  const bars = P.driverBars(full.top_risk_factors);
  assert.equal(bars.length, 2);
  assert.equal(bars[0].label, '+14.2%');
  assert.equal(bars[0].side, 'right');
  assert.equal(bars[0].tone, 'raises');
  assert.equal(bars[0].widthPct, 100);
  assert.equal(bars[0].observed, '31.5 °C');
  assert.equal(bars[1].label, '−7.1%');
  assert.equal(bars[1].side, 'left');
  assert.equal(bars[1].tone, 'lowers');
  assert.ok(Math.abs(bars[1].widthPct - 50) < 1e-9);
  assert.equal(bars[1].observed, null);
});

test('driver bars: fallback to impact_pct/direction, drops invalid rows', () => {
  const bars = P.driverBars([...old.top_risk_factors, {feature: '', impact_pct: 5, direction: 'raises', description: ''},
    {feature: 'Bad', impact_pct: NaN, direction: 'lowers', description: ''}]);
  assert.equal(bars.length, 1);
  assert.equal(bars[0].label, 'Raises · 30.0%');
  assert.equal(bars[0].widthPct, 30);
  assert.deepEqual(P.driverBars([{feature: 'Z', impact_pct: 0, direction: 'raises', description: '', signed_impact_pct: 0}]).map((b) => b.widthPct), [0]);
});

test('trajectory chart geometry', () => {
  const g = P.buildTrajectory(full.daily_probability_series);
  assert.equal(g.points.length, 5);
  assert.equal(g.points[0].x, g.plot.left);
  assert.equal(g.points[4].x, g.plot.left + g.plot.width);
  assert.equal(g.points[0].yFire, g.plot.top + g.plot.height);
  assert.ok(g.firePath.startsWith('M '));
  assert.equal((g.firePath.match(/L/g) ?? []).length, 4);
  // accident gap at index 2 starts a new sub-path instead of bridging
  assert.equal((g.accPath.match(/M/g) ?? []).length, 2);
  assert.ok(g.baselinePath.length > 0);
  assert.deepEqual(g.events.map((e) => e.date), ['2026-08-02', '2026-08-05']);
  assert.equal(g.events[0].x, g.points[1].x);
  assert.deepEqual([g.firstLabel, g.lastLabel], ['2026-08-01', '2026-08-05']);
  assert.equal(P.buildTrajectory([series[0]]), null);
});

test('trajectory chart: old backend renders without baseline or events', () => {
  const g = P.buildTrajectory([{date: 'a', wildfire_prob_pct: 1, accident_prob_pct: 2}, {date: 'b', wildfire_prob_pct: 3, accident_prob_pct: 4}]);
  assert.equal(g.baselinePath, '');
  assert.deepEqual(g.events, []);
  assert.equal(g.hasBaseline, false);
});

test('probability values are clamped to the 0-100 axis', () => {
  const g = P.buildTrajectory([{date: 'a', wildfire_prob_pct: 140, accident_prob_pct: -5}, {date: 'b', wildfire_prob_pct: 1, accident_prob_pct: 1}]);
  assert.equal(g.points[0].yFire, g.plot.top);
  assert.equal(g.points[0].yAcc, g.plot.top + g.plot.height);
});

test('nearestIndex', () => {
  assert.equal(P.nearestIndex(0, 5), 0);
  assert.equal(P.nearestIndex(0.5, 5), 2);
  assert.equal(P.nearestIndex(2, 5), 4);
  assert.equal(P.nearestIndex(-1, 5), 0);
  assert.equal(P.nearestIndex(0.5, 1), 0);
});

test('outlook strip', () => {
  const o = P.buildOutlook(full.outlook_series);
  assert.equal(o.points.length, 3);
  assert.equal((o.probPath.match(/M/g) ?? []).length, 2);
  assert.ok(o.baselinePath.startsWith('M '));
  assert.equal(P.buildOutlook(null), null);
  assert.equal(P.buildOutlook([{date: 'a', prob_pct: 1}]), null);
  assert.equal(P.buildOutlook([{date: 'a', prob_pct: null}, {date: 'b', prob_pct: null}]), null);
});

test('horizon escalation path', () => {
  const h = P.buildEscalation(full.horizons);
  assert.deepEqual(h.points.map((p) => p.label), ['24h', '7d', '14d']);
  assert.deepEqual(h.points.map((p) => p.text), ['30.0%', '52.5%', '71.0%']);
  assert.ok(h.points[2].y < h.points[0].y);
  assert.ok(h.path.startsWith('M '));
  assert.equal(P.buildEscalation(old.horizons), null);
  assert.equal(P.buildEscalation([horizon(1, 10), horizon(7, null), horizon(14, 20)]).points.length, 2);
  assert.equal(P.persistencePhrase(0.684), 'persistence ρ = 0.68');
  assert.equal(P.persistencePhrase(null), null);
});

test('small phrase helpers handle null', () => {
  assert.equal(P.diurnalPhrase(1.84), '×1.8 afternoon ramp (13:30 / 10:30)');
  assert.equal(P.diurnalPhrase(null), 'not available');
  assert.equal(P.formatMw(12.34), '12.3 MW');
  assert.equal(P.formatMw(null), 'not available');
  assert.equal(P.formatTonnes(1234.5), '1,234.5 t');
  assert.equal(P.formatTonnes(undefined), 'not available');
});
