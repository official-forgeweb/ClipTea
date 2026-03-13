"""
Apify Token Rotator — manages multiple Apify API tokens with smart rotation.

When a token gets rate-limited (restricted_page), it goes on cooldown.
Other tokens are used until the cooldown expires.
Cooldowns are TIERED by error type:
  INVALID_URL  → no cooldown (URL was bad, not the token)
  PARTIAL      → 30s cooldown
  RESTRICTED   → exponential, capped at 15min
  RATE_LIMITED  → exponential, capped at 30min
  UNKNOWN      → exponential, capped at 30min

NEVER forces a cooling token.  Returns None so the queue can wait.
"""

import os
import time
from datetime import datetime, timedelta
from typing import Optional


class ApifyTokenRotator:
    """
    Rotates between multiple Apify API tokens.
    When a token gets rate-limited (restricted_page), it goes on cooldown.
    Other tokens are used while it cools down.
    """

    def __init__(self):
        # Load tokens from env (plural or singular)
        tokens_str = os.getenv("APIFY_TOKENS") or os.getenv("APIFY_TOKEN") or ""
        self.tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]

        # Per-token tracking
        self.token_stats: dict[str, dict] = {}
        self.invalid_tokens = set()

        for i, token in enumerate(self.tokens):
            short_name = f"Token-{i + 1}"
            self.token_stats[token] = {
                "name": short_name,
                "requests": 0,
                "successes": 0,
                "restrictions": 0,
                "errors": 0,
                "invalid": False,
                "consecutive_errors": 0,
                "last_restricted_at": None,
                "cooldown_until": None,
            }

        self.current_index = 0
        print(f"[TokenRotator] Loaded {len(self.tokens)} Apify token(s)")

    # ── Token selection ────────────────────────────────

    def get_next_token(self) -> Optional[str]:
        """Get next available token, skipping those on cooldown.
        
        Returns None if ALL tokens are cooling — caller must wait.
        NEVER forces a cooling token.
        """
        if not self.tokens:
            return None

        now = datetime.now()
        attempts = 0

        while attempts < len(self.tokens):
            token = self.tokens[self.current_index]
            stats = self.token_stats[token]
            self.current_index = (self.current_index + 1) % len(self.tokens)
            attempts += 1

            # Skip invalid
            if token in self.invalid_tokens:
                continue

            # Check cooldown
            if stats["cooldown_until"] and now < stats["cooldown_until"]:
                remaining = int((stats["cooldown_until"] - now).total_seconds())
                print(f"[TokenRotator] ⏳ {stats['name']} on cooldown ({remaining}s remaining)")
                continue

            # Token available — pick the best one
            stats["requests"] += 1
            success_rate = self._get_success_rate(token)
            print(f"[TokenRotator] 🔑 Using {stats['name']} (success: {success_rate})")
            return token

        # All valid tokens are cooling — DO NOT FORCE. Return None.
        valid_tokens = [t for t in self.tokens if t not in self.invalid_tokens]
        if not valid_tokens:
            print("[TokenRotator] 🛑 No valid tokens remaining!")
            return None

        wait = self.get_wait_time()
        print(f"[TokenRotator] ⏳ All tokens cooling. Next available in {wait:.0f}s. Returning None.")
        return None

    def get_wait_time(self) -> float:
        """Seconds until the next token becomes available."""
        now = datetime.now()
        valid_tokens = [t for t in self.tokens if t not in self.invalid_tokens]
        if not valid_tokens:
            return 60.0  # No tokens at all — default wait

        soonest = None
        for t in valid_tokens:
            cd = self.token_stats[t].get("cooldown_until")
            if cd is None:
                return 0.0  # Already available
            if soonest is None or cd < soonest:
                soonest = cd

        if soonest is None:
            return 0.0

        remaining = (soonest - now).total_seconds()
        return max(0.0, remaining)

    # ── Result reporting (tiered penalties) ─────────────

    def report_result(self, token: str, classification: dict):
        """Report a scrape result to the rotator with tiered penalties.
        
        classification must have a "type" key:
          SUCCESS, INVALID_URL, PARTIAL, RESTRICTED, RATE_LIMITED, UNKNOWN
        """
        if token not in self.token_stats:
            return

        error_type = classification.get("type", "UNKNOWN")

        if error_type == "SUCCESS":
            self.report_success(token)
        elif error_type == "INVALID_URL":
            # DO NOT penalize — the URL was bad, not the token
            pass
        elif error_type == "PARTIAL":
            self._apply_cooldown(token, seconds=30, label="partial")
        elif error_type == "RESTRICTED":
            self._apply_exponential_cooldown(token, base=120, cap=900, label="restricted")
        elif error_type == "RATE_LIMITED":
            self._apply_exponential_cooldown(token, base=300, cap=1800, label="rate-limited")
        else:
            self._apply_exponential_cooldown(token, base=120, cap=1800, label="unknown-error")

    def report_success(self, token: str):
        """Token successfully scraped a video with real data."""
        if token not in self.token_stats:
            return
        stats = self.token_stats[token]
        stats["successes"] += 1
        stats["consecutive_errors"] = 0
        stats["cooldown_until"] = None  # Clear cooldown on success
        print(f"[TokenRotator] ✅ {stats['name']} success")

    def report_restriction(self, token: str):
        """Token got restricted_page error. (Legacy method — kept for compatibility.)"""
        self.report_result(token, {"type": "RESTRICTED"})

    def report_exhausted(self, token: str):
        """Token reached Apify usage limit (403). Cooldown for 24 hours."""
        if token not in self.token_stats:
            return
        stats = self.token_stats[token]
        stats["cooldown_until"] = datetime.now() + timedelta(hours=24)
        print(f"[TokenRotator] 🛑 {stats['name']} QUOTA EXCEEDED! Cooling for 24h.")

    def report_invalid(self, token: str):
        """Token returns 401 (invalid/expired). Stop using it."""
        if token not in self.token_stats:
            return
        stats = self.token_stats[token]
        stats["invalid"] = True
        self.invalid_tokens.add(token)
        print(f"[TokenRotator] ❌ {stats['name']} is INVALID (401). Disabling it.")

    def report_error(self, token: str):
        """Token had a non-restriction error (timeout, connection, etc.)."""
        if token not in self.token_stats:
            return
        stats = self.token_stats[token]
        stats["errors"] += 1
        # Don't put on cooldown for general errors

    # ── Internal cooldown helpers ──────────────────────

    def _apply_cooldown(self, token: str, seconds: float, label: str = ""):
        """Apply a fixed cooldown to a token."""
        stats = self.token_stats[token]
        stats["consecutive_errors"] += 1
        stats["cooldown_until"] = datetime.now() + timedelta(seconds=seconds)
        print(f"[TokenRotator] ⚠️ {stats['name']} {label} → {seconds:.0f}s cooldown")

    def _apply_exponential_cooldown(self, token: str, base: float, cap: float, label: str = ""):
        """Apply exponential cooldown capped at `cap` seconds."""
        stats = self.token_stats[token]
        stats["consecutive_errors"] += 1
        stats["restrictions"] += 1
        stats["last_restricted_at"] = datetime.now()

        cooldown = min(base * (2 ** (stats["consecutive_errors"] - 1)), cap)
        stats["cooldown_until"] = datetime.now() + timedelta(seconds=cooldown)
        print(f"[TokenRotator] ⚠️ {stats['name']} {label} → {cooldown:.0f}s cooldown "
              f"(consecutive: {stats['consecutive_errors']})")

    # ── Stats ──────────────────────────────────────────

    def _get_success_rate(self, token: str) -> str:
        """Get success rate as a formatted string."""
        stats = self.token_stats[token]
        total = stats["requests"]
        if total == 0:
            return "N/A"
        return f"{(stats['successes'] / total) * 100:.0f}%"

    def get_all_stats(self) -> list:
        """Get stats for all tokens (for admin /queue_stats command)."""
        now = datetime.now()
        result = []
        for token in self.tokens:
            stats = self.token_stats[token]
            cooldown_str = "None"
            if stats["cooldown_until"] and now < stats["cooldown_until"]:
                remaining = int((stats["cooldown_until"] - now).total_seconds())
                cooldown_str = f"{remaining}s"

            result.append({
                "name": stats["name"],
                "requests": stats["requests"],
                "successes": stats["successes"],
                "restrictions": stats["restrictions"],
                "errors": stats["errors"],
                "success_rate": self._get_success_rate(token),
                "cooldown": cooldown_str,
            })
        return result

    def reset_all_cooldowns(self):
        """Admin: reset all cooldowns immediately."""
        for token in self.tokens:
            self.token_stats[token]["cooldown_until"] = None
            self.token_stats[token]["consecutive_errors"] = 0
        print("[TokenRotator] All cooldowns reset")
