"""Check numerical prose against typed tool quantities and stated precision."""
import math
import re


NUMBER = r'(?<![\w])\d+(?:,\d{3})*(?:\.\d+)?'


def unsupported_numbers(text, evidence):
    """Counts cannot justify GJ. Decimal display rounding is deterministic.

    Integer quantities remain exact: a count, year or duration never acquires a
    relative tolerance. This checks numerical support, not arbitrary prose truth.
    """
    values = []
    typed = {'gj': [], 'mw': [], 'tonnes': [], 'km²': []}
    def visit(value, key=''):
        if isinstance(value, dict):
            for name, item in value.items():
                visit(item, str(name))
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            values.append(float(value))
            unit = ('gj' if key.endswith('_gj') or key == 'annual_gj' else 'mw' if key.endswith('_mw')
                    else 'tonnes' if key.endswith('_tonnes') else 'km²' if key.endswith('_km2') else None)
            if unit:
                typed[unit].append(float(value))
        elif isinstance(value, str):
            values.extend(float(n.replace(',', '')) for n in re.findall(NUMBER, value))
    visit(evidence)
    clean = re.sub(r'\[(?:[A-Z]*\d+(?:_\d+)?)\]', '', text)
    serialized = str(evidence)
    for sensor in ('20','21'):
        if f'N{sensor}' in serialized or f'NOAA-{sensor}' in serialized:
            clean = re.sub(rf'\bNOAA[- ]{sensor}\b', 'NOAA', clean, flags=re.I)
    clean = re.sub(r'(?<=\d)[\u202f\u00a0](?=\d{3}\b)', '', clean)
    invalid = []
    for match in re.finditer(NUMBER, clean):
        token = match[0].replace(',', '')
        number = float(token)
        suffix = re.match(r'\s*(?:\*\*)?\s*(GJ|MW|tonnes|km²)\b', clean[match.end():], re.I)
        candidates = typed[suffix[1].lower()] if suffix else values
        # Textual method notes are available for definitions, but physical totals
        # must come from the corresponding typed measurement tool.
        precision = len(token.partition('.')[2])
        supported = any(number == value or (precision > 0 and token == f'{value:.{precision}f}') for value in candidates)
        if not supported:
            invalid.append(match[0])
    return invalid


def unsupported_incident_match(text):
    """A regional article is not a geospatial match to selected observations.

    No tool currently provides an incident-perimeter join. Reject explicit
    affirmative matches; this narrow check does not certify arbitrary prose.
    """
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', text.replace('**','')):
        if re.search(r'\b(no|not|cannot|consistent|likely|probable|possibly|may|could|unconfirmed|unverified)\b',sentence,re.I):
            continue
        direct = re.search(r'^\s*yes[,!. ]+(?:this|it|these)\b.*\b(?:fire|wildfire)\b',sentence,re.I)
        relationship = re.search(r'\b(?:signals|activity|detections|observations)\b.{0,100}\b(?:correspond|belong|match)\w*\b|\b(?:confirm|identify|establish|prove)\w*\b.{0,120}\b(?:this|these)\s+(?:thermal\s+)?(?:signals|activity|detections|observations|incident)\b',sentence,re.I)
        if direct or relationship:
            return True
    return False
