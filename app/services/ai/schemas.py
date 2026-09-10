from dataclasses import dataclass
from typing import Optional


ALLOWED_CATEGORIES = [
    "Billing",
    "Payment",
    "Refund",
    "Delivery",
    "Product Issue",
    "Technical Issue",
    "Account",
    "Subscription",
    "Security",
    "General",
]

ALLOWED_SENTIMENTS = [
    "Positive",
    "Neutral",
    "Negative",
    "Very Negative",
]

ALLOWED_PRIORITIES = [
    "Low",
    "Medium",
    "High",
    "Critical",
]


@dataclass
class AIAnalysisResult:
    """Structured AI analysis result container."""
    category: str
    sentiment: str
    priority: str
    confidence: float
    reason: str
    model_name: Optional[str] = None
    provider: Optional[str] = None
    raw_response: Optional[str] = None

    def validate(self) -> tuple[bool, str]:
        """Validate result against allowed taxonomy constraints."""
        if not self.category or self.category not in ALLOWED_CATEGORIES:
            return False, f"Invalid category '{self.category}'. Must be one of {ALLOWED_CATEGORIES}."

        if not self.sentiment or self.sentiment not in ALLOWED_SENTIMENTS:
            return False, f"Invalid sentiment '{self.sentiment}'. Must be one of {ALLOWED_SENTIMENTS}."

        if not self.priority or self.priority not in ALLOWED_PRIORITIES:
            return False, f"Invalid priority '{self.priority}'. Must be one of {ALLOWED_PRIORITIES}."

        if self.confidence is None or not isinstance(self.confidence, (int, float)):
            return False, "Confidence must be a numeric value."

        if not (0.0 <= float(self.confidence) <= 1.0):
            return False, f"Confidence '{self.confidence}' out of valid 0.0 to 1.0 range."

        if not self.reason or not isinstance(self.reason, str) or not self.reason.strip():
            return False, "Reason explanation is required."

        return True, ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "sentiment": self.sentiment,
            "priority": self.priority,
            "confidence": round(float(self.confidence), 2),
            "confidence_percent": int(round(float(self.confidence) * 100)),
            "reason": self.reason,
            "model_name": self.model_name,
            "provider": self.provider,
        }
