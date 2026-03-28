import pytest
import numpy as np
from bgg_api.stats import calculate_correlation, calculate_confidence

def test_calculate_correlation_pearson():
    v1 = [1, 2, 3, 4, 5]
    v2 = [2, 4, 6, 8, 10]
    corr, p_val = calculate_correlation(v1, v2, method='pearson')
    assert pytest.approx(corr) == 1.0
    assert p_val < 0.05

def test_calculate_correlation_spearman():
    # Non-linear but monotonic
    v1 = [1, 2, 3, 4, 5]
    v2 = [1, 4, 9, 16, 25]
    # Pearson should be high but not 1.0
    corr_p, _ = calculate_correlation(v1, v2, method='pearson')
    assert corr_p < 1.0
    # Spearman should be 1.0
    corr_s, p_val = calculate_correlation(v1, v2, method='spearman')
    assert pytest.approx(corr_s) == 1.0
    assert p_val < 0.05

def test_calculate_confidence_pearson():
    # High correlation, many points -> high confidence
    corr = 0.9
    n = 20
    conf = calculate_confidence(corr, n, 0.5, method='pearson')
    assert conf > 95.0
    
    # Low correlation -> low confidence
    corr = 0.4
    conf = calculate_confidence(corr, n, 0.5, method='pearson')
    assert conf < 50.0

def test_calculate_confidence_spearman():
    # Spearman SE is higher, so confidence should be slightly lower than Pearson for same values
    corr = 0.8
    n = 10
    conf_p = calculate_confidence(corr, n, 0.5, method='pearson')
    conf_s = calculate_confidence(corr, n, 0.5, method='spearman')
    assert conf_s < conf_p
    assert conf_s > 0
    
def test_calculate_confidence_edge_cases():
    # Small n
    assert calculate_confidence(0.9, 3, 0.5) == 0.0
    # NaN/None corr
    assert calculate_confidence(None, 10, 0.5) == 0.0
    # Correlation exactly 1.0
    assert calculate_confidence(1.0, 10, 0.5) > 99.0
