"""Payment calculation logic based on views and rate per 10K."""


def calculate_earnings(total_views: int, rate_per_10k: float) -> float:
    """Calculate earnings based on total views and rate per 10K views.
    
    Args:
        total_views: Total number of views
        rate_per_10k: Payment rate per 10,000 views
        
    Returns:
        Earnings as a float rounded to 2 decimal places.
    """
    if total_views <= 0 or rate_per_10k <= 0:
        return 0.0
    return round((total_views / 10_000) * rate_per_10k, 2)


def calculate_remaining_budget(budget: float, total_views: int, rate_per_10k: float) -> float:
    """Calculate remaining budget after current earnings.
    
    Args:
        budget: Total campaign budget (None means unlimited)
        total_views: Current total views
        rate_per_10k: Payment rate per 10K views
        
    Returns:
        Remaining budget, or float('inf') if unlimited.
    """
    if budget is None:
        return float('inf')
    earned = calculate_earnings(total_views, rate_per_10k)
    return max(0.0, round(budget - earned, 2))


def budget_percentage_used(budget: float, total_views: int, rate_per_10k: float) -> float:
    """Calculate percentage of budget used.
    
    Returns:
        Percentage (0-100) of budget used, or 0 if unlimited.
    """
    if budget is None or budget <= 0:
        return 0.0
    earned = calculate_earnings(total_views, rate_per_10k)
    return min(100.0, round((earned / budget) * 100, 1))


def is_budget_exhausted(budget: float, total_views: int, rate_per_10k: float) -> bool:
    """Check if the campaign budget has been exhausted."""
    if budget is None:
        return False
    earned = calculate_earnings(total_views, rate_per_10k)
    return earned >= budget


def views_until_budget_cap(budget: float, total_views: int, rate_per_10k: float) -> int:
    """Calculate how many more views until budget is exhausted.
    
    Returns:
        Number of views remaining, or -1 if unlimited.
    """
    if budget is None:
        return -1
    remaining = calculate_remaining_budget(budget, total_views, rate_per_10k)
    if remaining <= 0:
        return 0
    return int((remaining / rate_per_10k) * 10_000)
