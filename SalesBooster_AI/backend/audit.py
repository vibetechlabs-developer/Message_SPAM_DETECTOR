import random

def generate_mock_audit(url: str):
    score = random.randint(45, 80)
    issues = [
        "Images are not optimized (WebP recommended).",
        "No caching headers detected.",
        "Mobile responsiveness fails.",
        "Missing meta descriptions.",
        "Slow server response time."
    ]
    
    selected_issues = random.sample(issues, 3)
    
    report = {
        "url": url,
        "performance_score": f"{score}/100",
        "status": "Poor" if score < 60 else "Needs Improvement",
        "critical_issues_found": selected_issues,
        "recommendation": "We recommend a full code refactor and UI update. Our tech team can fix this rapidly.",
        "estimated_cost_to_fix": f"${random.randint(5, 15) * 100}"
    }
    
    return report
