import math
import numpy as np
from scipy.stats import pearsonr, spearmanr, norm

def calculate_correlation(v1, v2, method='pearson'):
    """
    Calculates the correlation between two vectors.
    
    Args:
        v1 (list or np.array): First vector of ratings.
        v2 (list or np.array): Second vector of ratings.
        method (str): Correlation method ('pearson' or 'spearman').
        
    Returns:
        tuple: (correlation, p_value)
    """
    if len(v1) < 2:
        return None, None
        
    if method == 'spearman':
        corr_obj = spearmanr(v1, v2)
        return corr_obj.correlation, corr_obj.pvalue
    else:
        # Default to pearson
        corr, p_val = pearsonr(v1, v2)
        return corr, p_val

def calculate_confidence(corr, n, target_threshold, method='pearson'):
    """
    Calculates the confidence percentage that the true correlation magnitude
    is greater than the target_threshold using the Fisher transformation.
    
    Args:
        corr (float): The observed correlation coefficient.
        n (int): The number of observations (co-raters).
        target_threshold (float): The threshold to test against (e.g., 0.5).
        method (str): Correlation method ('pearson' or 'spearman').
        
    Returns:
        float: Confidence percentage (0-100).
    """
    if n <= 3 or corr is None or math.isnan(corr):
        return 0.0
        
    # Fisher Z-transformation
    # Prevent inf for r=1.0
    z = np.arctanh(min(abs(corr), 0.9999))
    z0 = np.arctanh(target_threshold)
    
    if method == 'spearman':
        # For Spearman, the standard error is often approximated as 1.03/sqrt(n-3)
        # Some sources use 1/sqrt((n-3)/1.06) or similar.
        # We'll use 1.03 / sqrt(n-3) as a reasonable standard approximation.
        se = 1.03 / np.sqrt(n - 3)
    else:
        # Pearson SE
        se = 1.0 / np.sqrt(n - 3)
        
    z_stat = (z - z0) / se
    conf_pct = norm.cdf(z_stat) * 100
    return conf_pct
