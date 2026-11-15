"""Documented upstream flare positions; persistence alone does not identify a flare."""
import csv

import numpy as np
from scipy.spatial import cKDTree


def xyz(coords):
    a = np.radians(np.asarray(coords, dtype=float))
    return 6371007.181 * np.column_stack((np.cos(a[:, 0]) * np.cos(a[:, 1]),
        np.cos(a[:, 0]) * np.sin(a[:, 1]), np.sin(a[:, 0])))


def load_matcher(root):
    path = root / 'data/lookup/flare_reference.csv'
    locations = {}
    if path.is_file():
        with path.open(encoding='utf-8') as stream:
            for row in csv.DictReader(stream):
                locations.setdefault(int(row['year']), []).append((float(row['latitude']), float(row['longitude'])))
    trees = {year: cKDTree(xyz(coords)) for year, coords in locations.items()}
    bounds = {year: (np.min(coords, axis=0), np.max(coords, axis=0)) for year, coords in locations.items()}

    def matches(latitude, longitude, year):
        if year not in trees:
            return False
        lo, hi = bounds[year]
        if not (lo[0] - .02 <= latitude <= hi[0] + .02 and lo[1] - .02 <= longitude <= hi[1] + .02):
            return False
        distance, _ = trees[year].query(xyz([(latitude, longitude)])[0])
        return bool(distance <= 1000.)
    return matches
