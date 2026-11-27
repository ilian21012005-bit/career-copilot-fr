"""Bot de candidatures HelloWork.

The automated Playwright flow is restricted to direct HelloWork forms covered
by the user's authorization. External ATS redirects and unknown required
answers are stopped rather than guessed.
"""

__all__ = ["alerts", "cli", "kit", "offer", "profile", "report", "score", "store"]
