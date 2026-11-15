"""Dry biomass and primary PM2.5 emission estimates; not surface concentrations.

Andreae 2019, Table 1, field means (g PM2.5/kg dry matter):
https://doi.org/10.5194/acp-19-8523-2019
Source XLSX: acp-19-8523-2019-t01.xlsx, row 124; SDs are inter-study
spread, not confidence bounds. Land-cover mapping is an explicit fuel proxy.
"""
import numpy as np

PM25_G_PER_KG = {'savanna': (6.7, 3.3), 'tropical_forest': (8.3, 3.3),
                'temperate_forest': (18.5, 14.4), 'boreal_forest': (18.7, 15.9),
                'agricultural_residue': (8.2, 4.4)}


def factor_stats(igbp, latitude):
    if igbp in (1, 2, 3, 4, 5):
        category = ('tropical_forest' if abs(latitude) <= 23.5 else
                    'boreal_forest' if abs(latitude) >= 50 else 'temperate_forest')
    elif igbp in (8, 9, 10):
        category = 'savanna'
    elif igbp == 12:
        category = 'agricultural_residue'
    else:
        return None
    return PM25_G_PER_KG[category]


def factor(igbp, latitude):
    stats = factor_stats(igbp, latitude)
    return stats[0] if stats else None


def pm25_kg(energy_mj, emission_factor_g_per_kg):
    energy = np.asarray(energy_mj, dtype=float)
    ef = np.asarray(emission_factor_g_per_kg, dtype=float)
    if np.any(energy < 0) or np.any(ef < 0):
        raise ValueError('Energy and emission factors must be non-negative.')
    return energy * 0.368 * ef / 1000
