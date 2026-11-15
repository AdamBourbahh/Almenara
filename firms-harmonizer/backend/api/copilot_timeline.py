"""A labeled observation comparison window that never changes chat selection."""
from dataclasses import replace
from datetime import date, timedelta

from backend.api import fire_copilot as local
from backend.db import duckdb_engine


def observation_timeline(scope):
    if not scope.start or not scope.end or not scope.coordinates:
        return {'status': 'missing_scope', 'message': 'An area and incident date are needed for a timeline comparison.'}
    anchor = date.fromisoformat(scope.start)
    end = date.fromisoformat(scope.end)
    if (end-anchor).days > 30:
        return {'status': 'wide_selection', 'message': 'This selection contains multiple possible incidents. Profile an episode before comparing incident timelines.'}
    window_start = (anchor-timedelta(days=7)).isoformat()
    window_end = min(max(end, anchor+timedelta(days=15)), anchor+timedelta(days=30)).isoformat()
    result = local.retrieve_observations(replace(scope, start=window_start, end=window_end))
    if result.get('status') != 'ok':
        return result
    last = duckdb_engine.last_epoch_day()
    return {'status': 'ok', 'selected_start': scope.start, 'selected_end': scope.end,
            'comparison_start': window_start, 'comparison_end': window_end,
            'archive_available_through': (date(1970,1,1)+timedelta(days=last)).isoformat() if last is not None else None,
            'daily_detections': result['daily_detections'], 'last_detection_in_comparison': result['last_detection'],
            'confidence_level': scope.confidence_level, 'industrial_excluded': scope.exclude_industrial,
            'limits': 'This explicitly labeled comparison extends beyond selected dates without changing them. Later detections are local thermal observations, not proof of the same incident. A last detection or statistical episode end is not containment or extinction. Official duration requires matching incident records. These counts do not establish why detection rates changed: no matching coverage or fire-phase measurement is supplied. Thermal sensors can detect flaming and sufficiently hot smoldering; they do not observe only flaming fronts.'}


def timeline_answer(scope, evidence, question):
    if evidence.get('status')!='ok':
        return evidence.get('message','The local observation timeline is unavailable.')
    referenced=local.question_period(question,int(scope.start[:4]))
    cutoff=referenced[-1] if referenced else scope.end
    later=[row for row in evidence['daily_detections'] if row['date']>cutoff]
    if later:
        detail='; '.join(f"{row['date']}: {row['detections']} detections" for row in later)
        lead=f"The local archive does not stop on **{cutoff}**. Later observations in this area include {detail}. [5]"
    else:
        lead=f"No later detections were found after **{cutoff}** within this comparison window. That does not establish extinction. [5]"
    return (lead+f"\n\nThis comparison covers {evidence['comparison_start']} to {evidence['comparison_end']}; "
            f"the attached selection remains {scope.start} to {scope.end}. Later heat may belong to another incident. "
            "The claimed official incident duration is **unverified offline**. Matching containment, extinction and investigation records require external evidence; satellite detections alone cannot establish those dates.")
