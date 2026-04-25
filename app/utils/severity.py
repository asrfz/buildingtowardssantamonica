def compute_severity(deviation_score: float) -> str:
    if deviation_score >= 15:
        return "CRITICAL"
    if deviation_score >= 8:
        return "HIGH"
    if deviation_score >= 4:
        return "MEDIUM"
    return "LOW"
