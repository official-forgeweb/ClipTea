"""
Apify Token Rotator — manages multiple Apify API tokens with smart rotation.

When a token gets rate-limited (restricted_page), it goes on cooldown.
Other tokens are used until the cooldown expires.
Cooldowns escalate: 3min → 6min → 9min → ... → max 30min.
"""

import os
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
                "consecutive_restrictions": 0,
                "last_restricted_at": None,
                "cooldown_until": None,
            }

        self.current_index = 0
        print(f"[TokenRotator] Loaded {len(self.tokens)} Apify token(s)")



    def get_next_token(self) -> Optional[str]:
        """Get next available token, skipping those on cooldown."""
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

            # Token available
            stats["requests"] += 1
            success_rate = self._get_success_rate(token)
            print(f"[TokenRotator] 🔑 Using {stats['name']} (success: {success_rate})")
            return token

        # All valid tokens are cooling — find the one expiring soonest
        valid_tokens = [t for t in self.tokens if t not in self.invalid_tokens]
        if not valid_tokens:
            print("[TokenRotator] 🛑 No valid tokens remaining!")
            return None

        soonest_token = min(
            valid_tokens,
            key=lambda t: self.token_stats[t].get("cooldown_until") or datetime.min
        )
        stats = self.token_stats[soonest_token]
        
        # If the soonest token is cooling for > 1 hour, it's exhausted.
        # Don't force it; return None so the caller can fall back to estimation.
        if stats["cooldown_until"] and (stats["cooldown_until"] - now) > timedelta(hours=1):
            print(f"[TokenRotator] 🛑 All tokens exhausted. {stats['name']} cooling for long time.")
            return None

        print(f"[TokenRotator] ⚠️ All tokens cooling. Forcing {stats['name']} (soonest)")
        stats["requests"] += 1
        return soonest_token


    def report_success(self, token: str):
        """Token successfully scraped a video with real data."""
        if token not in self.token_stats:
            return
        stats = self.token_stats[token]
        stats["successes"] += 1
        stats["consecutive_restrictions"] = 0
        stats["cooldown_until"] = None  # Clear cooldown on success
        print(f"[TokenRotator] ✅ {stats['name']} success")

    def report_restriction(self, token: str):
        """Token got restricted_page error."""
        if token not in self.token_stats:
            return
        stats = self.token_stats[token]
        stats["restrictions"] += 1
        stats["consecutive_restrictions"] += 1
        stats["last_restricted_at"] = datetime.now()

        # Escalating cooldown: 3, 6, 9, 12... max 30 minutes
        cooldown_min = min(stats["consecutive_restrictions"] * 3, 30)
        stats["cooldown_until"] = datetime.now() + timedelta(minutes=cooldown_min)

        print(f"[TokenRotator] ⚠️ {stats['name']} restricted! Cooldown: {cooldown_min}min")

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
            self.token_stats[token]["consecutive_restrictions"] = 0
        print("[TokenRotator] All cooldowns reset")
