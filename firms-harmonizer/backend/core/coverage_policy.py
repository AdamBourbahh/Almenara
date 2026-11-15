"""Chronological coverage-policy selection with an untouched final-year holdout."""
import numpy as np
from backend.core.energy_forecast import project


def assess(dates,values,coverage):
    dates,values,coverage = np.asarray(dates),np.asarray(values,float),np.asarray(coverage,float)
    n = len(values)
    split = n-365
    candidates = []
    for threshold in (.70,.80,.90,.95):
        training = np.where(coverage>=threshold,values,np.nan)
        stages = {}
        for stage,first,last in [('selection',max(1095,n-730),split-14),('holdout',split,n-14)]:
            errors = {h:[] for h in (1,7,14)}
            seasons = set()
            for origin in range(max(1095,first),last,28):
                if not np.isfinite(coverage[origin]) or coverage[origin]<.95 or not np.isfinite(values[origin]):
                    continue
                if np.count_nonzero((coverage[:origin+1]>=.95)&np.isfinite(values[:origin+1]))<365:
                    continue
                prediction = project(dates[:origin+1],training[:origin+1],14)
                if prediction is None:
                    continue
                for h in errors:
                    target = origin+h
                    # Identical high-support labels across candidates; never score cloudy zeros.
                    if coverage[target]<.95 or not np.isfinite(coverage[target]) or not np.isfinite(values[target]):
                        continue
                    value = values[target]
                    errors[h].append((abs(value-prediction['predicted'][h-1]),abs(value-values[origin]),
                        abs(value-prediction['seasonal'][h-1]),prediction['lower'][h-1]<=value<=prediction['upper'][h-1],
                        prediction['predicted'][h-1]-value))
                    seasons.add((int(str(dates[target])[5:7])%12)//3)
            metrics = []
            for h,rows in errors.items():
                if rows:
                    means = np.mean(rows,axis=0)
                    metrics.append(dict(horizon_days=h,samples=len(rows),mae=float(means[0]),
                        persistence_mae=float(means[1]),climatology_mae=float(means[2]),
                        interval_coverage_pct=float(100*means[3]),bias=float(means[4])))
            stages[stage] = dict(metrics=metrics,season_groups=len(seasons))
        candidates.append(dict(threshold=threshold,**stages))
    def passes(stage):
        return stage['season_groups']>=4 and len(stage['metrics'])==3 and all(m['samples']>=12 and
            m['mae']<=min(m['persistence_mae'],m['climatology_mae']) and m['interval_coverage_pct']>=90 for m in stage['metrics'])
    eligible = [c for c in candidates if passes(c['selection'])]
    chosen = min(eligible,key=lambda c:(sum(m['mae'] for m in c['selection']['metrics']),-c['threshold'])) if eligible else None
    # Holdout never chooses a different threshold after observing its outcome.
    accepted = chosen is not None and passes(chosen['holdout'])
    return dict(selected_threshold=chosen['threshold'] if accepted else None,
        selection_candidate=chosen['threshold'] if chosen else None,candidates=candidates,
        reason=None if accepted else 'No coverage threshold passed chronological selection and the reserved final-year validation.')
