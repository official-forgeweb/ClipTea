def check_fraud(views: int, likes: int, comments: int) -> list:
    """
    Very basic heuristic to flag potential view/like botting.
    Returns a list of warning strings.
    """
    warnings = []
    
    # 1. Suspiciously high view-to-engagement ratio
    if views > 1000:
        total_engagement = likes + comments
        engagement_rate = (total_engagement / views) * 100
        
        # If views are huge but likes/comments are almost zero
        if engagement_rate < 0.1:
            warnings.append(f"🚨 Extremely low engagement rate ({engagement_rate:.2f}%). Potential view botting.")
            
    # 2. Suspiciously high like-to-view ratio (more likes than views)
    if likes > views and views > 0:
        warnings.append("🚨 More likes than views detected. Possible metric manipulation.")
        
    # 3. Comment spam detection (very basic)
    if comments > likes and likes > 10:
        warnings.append("🚨 More comments than likes detected. Possible comment botting.")
        
    return warnings
