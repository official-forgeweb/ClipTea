"""
Smart Scrape Queue — processes Apify jobs one at a time with random delays,
automatic backoff on Instagram rate-limiting, and retry logic.

Architecture:
  MAIN QUEUE (priority-ordered)
    HIGH  → /submit  (clipper waiting)
    MED   → manual refresh
    LOW   → periodic scraper

  Processing: one job at a time
    → Call Apify → success / restricted / error
    → Random delay (scaled by backoff level)
    → Next job

  RETRY QUEUE (after main queue drains)
    → 5-minute cooldown → 60-90 s between retries → max 3 attempts
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Any


# ── Priority levels ────────────────────────────────
PRIORITY_HIGH = 1      # /submit — clipper is waiting
PRIORITY_MEDIUM = 5    # manual refresh
PRIORITY_LOW = 10      # periodic scraper


@dataclass(order=True)
class ScrapeJob:
    """A single scraping job in the queue."""
    priority: int
    sort_index: int = field(compare=True, repr=False)

    # These fields are NOT used for ordering
    video_url: str = field(compare=False, default="")
    shortcode: str = field(compare=False, default="")
    discord_user_id: str = field(compare=False, default="")
    campaign_id: str = field(compare=False, default="")
    attempt: int = field(compare=False, default=0)
    max_attempts: int = field(compare=False, default=3)
    created_at: float = field(compare=False, default_factory=time.time)

    # Signalling — callers can await this to get the result
    result_event: Optional[asyncio.Event] = field(compare=False, default=None, repr=False)
    result_data: Optional[dict] = field(compare=False, default=None, repr=False)


class ScrapeQueue:
    """
    Centralised queue that feeds Apify requests one at a time with
    intelligent delays and automatic backoff.
    """

    def __init__(self, apify_service, db_manager=None):
        self.apify = apify_service
        self.db = db_manager

        # Main priority queue (heapq via asyncio.PriorityQueue)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._job_counter = 0          # monotonic tie-breaker

        # Retry queue (simple list, processed after main queue drains)
        self.retry_queue: list[ScrapeJob] = []
        self._retry_cooldown = 300     # 5 minutes

        # Backoff state
        self._consecutive_errors = 0
        self._backoff_level = 0        # 0 / 1 / 2 / 3+

        # Stats
        self._jobs_processed = 0
        self._jobs_succeeded = 0
        self._jobs_failed = 0
        self._last_request_time: Optional[float] = None

        # Control
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()    # Only ONE Apify call at a time

    # ── Lifecycle ──────────────────────────────────────

    async def start(self):
        """Start the background queue processor."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        print("[QUEUE] Smart scrape queue started")

    async def stop(self):
        """Stop the queue processor gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[QUEUE] Smart scrape queue stopped")

    # ── Public API ─────────────────────────────────────

    async def submit_and_wait(self, video_url: str, discord_user_id: str = "",
                              campaign_id: str = "") -> dict:
        """
        HIGH PRIORITY: Submit a single video and WAIT for the result.
        Used by /submit.  Returns the metrics dict.
        Timeout: 3 minutes max wait.
        """
        event = asyncio.Event()
        job = self._make_job(
            video_url=video_url,
            discord_user_id=discord_user_id,
            campaign_id=campaign_id,
            priority=PRIORITY_HIGH,
            event=event,
        )
        await self._queue.put(job)
        print(f"[QUEUE] HIGH priority job queued: {video_url[:60]}")

        try:
            await asyncio.wait_for(event.wait(), timeout=180)  # 3 min
        except asyncio.TimeoutError:
            return {
                "views": 0, "likes": 0, "comments": 0, "shares": 0,
                "author_username": "", "method": "queue_timeout",
                "estimated": True, "cached": False,
                "error": "Queue processing timed out (3 min)",
            }

        return job.result_data or {
            "views": 0, "likes": 0, "comments": 0, "shares": 0,
            "author_username": "", "method": "queue_error",
            "estimated": True, "cached": False,
            "error": "No result returned from queue",
        }

    async def submit_bulk_and_track(self, video_urls: list,
                                     discord_user_id: str = "",
                                     campaign_id: str = "",
                                     progress_callback: Optional[Callable] = None) -> list:
        """
        HIGH PRIORITY: Submit multiple videos for bulk processing.
        Calls progress_callback(current_index, total, url, result) after each.
        Returns list of result dicts.
        """
        results = []
        total = len(video_urls)

        for i, url in enumerate(video_urls):
            result = await self.submit_and_wait(
                video_url=url,
                discord_user_id=discord_user_id,
                campaign_id=campaign_id,
            )
            results.append(result)

            if progress_callback:
                try:
                    await progress_callback(i, total, url, result)
                except Exception as cb_err:
                    print(f"[QUEUE] Progress callback error: {cb_err}")

        return results

    def add_periodic_job(self, video_url: str, shortcode: str = "",
                         discord_user_id: str = "", campaign_id: str = ""):
        """
        LOW PRIORITY: Add a job for periodic re-scraping.
        Fire-and-forget — result saved to DB automatically by the processor.
        """
        job = self._make_job(
            video_url=video_url,
            shortcode=shortcode,
            discord_user_id=discord_user_id,
            campaign_id=campaign_id,
            priority=PRIORITY_LOW,
        )
        self._queue.put_nowait(job)

    def get_stats(self) -> dict:
        """Return queue statistics for /queue_stats."""
        total = self._jobs_succeeded + self._jobs_failed
        if total > 0:
            rate = f"{(self._jobs_succeeded / total) * 100:.1f}%"
        else:
            rate = "N/A"

        delay_desc = self._delay_description()

        last_req = "never"
        if self._last_request_time:
            ago = int(time.time() - self._last_request_time)
            if ago < 60:
                last_req = f"{ago}s ago"
            elif ago < 3600:
                last_req = f"{ago // 60}m ago"
            else:
                last_req = f"{ago // 3600}h ago"

        return {
            "queue_size": self._queue.qsize(),
            "retry_queue_size": len(self.retry_queue),
            "jobs_processed": self._jobs_processed,
            "jobs_succeeded": self._jobs_succeeded,
            "jobs_failed": self._jobs_failed,
            "success_rate": rate,
            "consecutive_errors": self._consecutive_errors,
            "current_delay": delay_desc,
            "last_request": last_req,
        }

    # ── Background processor ──────────────────────────

    async def _process_loop(self):
        """Background loop that processes the queue forever."""
        print("[QUEUE] Processor loop started")
        while self._running:
            try:
                # --- Main queue ---
                try:
                    job = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    # If retry queue has items and cooldown elapsed, process retries
                    if self.retry_queue:
                        await self._process_retry_queue()
                    else:
                        await asyncio.sleep(2)  # idle polling
                    continue

                async with self._lock:
                    result = await self._process_single_job(job)

                # Signal waiting callers
                if job.result_event:
                    job.result_data = result
                    job.result_event.set()

                # Save metrics to DB for periodic jobs (no caller waiting)
                if not job.result_event and result and not result.get("error"):
                    await self._save_periodic_result(job, result)

                self._jobs_processed += 1

                # Inter-job delay
                delay = self._get_delay()
                print(f"[QUEUE] Waiting {delay:.1f}s before next job "
                      f"(backoff={self._consecutive_errors}, queue={self._queue.qsize()})")
                await asyncio.sleep(delay)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[QUEUE] Processor error: {e}")
                await asyncio.sleep(5)

        print("[QUEUE] Processor loop exited")

    async def _process_single_job(self, job: ScrapeJob) -> dict:
        """Process one job: call Apify, detect restrictions, handle backoff."""
        self._last_request_time = time.time()
        print(f"[QUEUE] Processing: {job.video_url[:60]} (attempt {job.attempt + 1}/{job.max_attempts})")

        try:
            result = await self.apify.get_video_metrics(job.video_url, use_cache=False)
        except Exception as e:
            print(f"[QUEUE] Apify exception: {e}")
            result = {"error": str(e), "views": 0, "likes": 0, "comments": 0}

        if not result:
            result = {"error": "No response from Apify", "views": 0, "likes": 0, "comments": 0}

        # ── Restriction / error detection ──────────────
        is_restricted = False
        has_error = bool(result.get("error"))

        if result:
            error_text = str(result.get("error", "")).lower()
            error_desc = str(result.get("errorDescription", "")).lower()

            if "restricted" in error_text or "restricted" in error_desc:
                is_restricted = True

            # Got a response but zero metrics with author → partial / restricted
            if (result.get("views", 0) == 0 and result.get("likes", 0) == 0
                    and result.get("author_username") and not has_error):
                is_restricted = True

        if is_restricted or has_error:
            self._increase_backoff()
            job.attempt += 1

            if job.attempt < job.max_attempts:
                self.retry_queue.append(job)
                print(f"[QUEUE] ⚠️ {'Restricted' if is_restricted else 'Error'} — "
                      f"added to retry queue (attempt {job.attempt}/{job.max_attempts})")
            else:
                # Max retries exhausted — use estimation fallback
                print(f"[QUEUE] ❌ Max retries exhausted for {job.video_url[:50]}")
                shortcode = self.apify._extract_shortcode(job.video_url)
                fallback = await self.apify._estimation_fallback(job.video_url, shortcode)
                self._jobs_failed += 1

                # Update DB error info
                await self._update_video_error(job, "max_retries_exhausted")
                return fallback

            self._jobs_failed += 1
            return result
        else:
            # Success
            self._decrease_backoff()
            self._jobs_succeeded += 1

            # Update last_scraped_at in DB
            await self._update_last_scraped(job)

            return result

    async def _process_retry_queue(self):
        """Process all retry jobs with longer delays after a cooldown."""
        if not self.retry_queue:
            return

        print(f"[QUEUE] Retry cooldown: waiting {self._retry_cooldown}s before processing "
              f"{len(self.retry_queue)} retry jobs...")
        await asyncio.sleep(self._retry_cooldown)

        # Take a snapshot so new retries added during processing wait for next cycle
        jobs_to_retry = list(self.retry_queue)
        self.retry_queue.clear()

        for job in jobs_to_retry:
            if not self._running:
                break

            async with self._lock:
                result = await self._process_single_job(job)

            if job.result_event:
                job.result_data = result
                job.result_event.set()

            if not job.result_event and result and not result.get("error"):
                await self._save_periodic_result(job, result)

            self._jobs_processed += 1

            # Retry delay is longer: 60-90 seconds
            delay = random.uniform(60, 90)
            print(f"[QUEUE] Retry delay: {delay:.1f}s")
            await asyncio.sleep(delay)

    # ── Backoff management ─────────────────────────────

    def _increase_backoff(self):
        """Increase delays after rate limiting detected."""
        self._consecutive_errors += 1
        self._backoff_level = min(self._consecutive_errors, 3)
        print(f"[QUEUE] 🔴 Backoff increased → level {self._backoff_level} "
              f"(consecutive errors: {self._consecutive_errors})")

    def _decrease_backoff(self):
        """Decrease delays after successful request."""
        if self._consecutive_errors > 0:
            self._consecutive_errors = max(0, self._consecutive_errors - 1)
            self._backoff_level = min(self._consecutive_errors, 3)
            print(f"[QUEUE] 🟢 Backoff decreased → level {self._backoff_level}")

    def _reset_backoff(self):
        """Reset delays to default values."""
        self._consecutive_errors = 0
        self._backoff_level = 0
        print("[QUEUE] Backoff reset to 0")

    def _get_delay(self) -> float:
        """Return the random delay for the current backoff level."""
        ranges = {
            0: (25, 45),
            1: (50, 90),
            2: (100, 180),
            3: (150, 240),
        }
        lo, hi = ranges.get(self._backoff_level, (150, 240))
        return random.uniform(lo, hi)

    def _delay_description(self) -> str:
        """Human-readable description of current delay range."""
        ranges = {
            0: "25-45s (normal)",
            1: "50-90s (level 1)",
            2: "100-180s (level 2)",
            3: "150-240s (level 3)",
        }
        return ranges.get(self._backoff_level, "150-240s (max)")

    # ── Helpers ────────────────────────────────────────

    def _make_job(self, video_url: str, priority: int,
                  shortcode: str = "", discord_user_id: str = "",
                  campaign_id: str = "", event: Optional[asyncio.Event] = None) -> ScrapeJob:
        """Create a ScrapeJob with a monotonic sort index."""
        self._job_counter += 1
        return ScrapeJob(
            priority=priority,
            sort_index=self._job_counter,
            video_url=video_url,
            shortcode=shortcode,
            discord_user_id=discord_user_id,
            campaign_id=campaign_id,
            result_event=event,
        )

    async def _save_periodic_result(self, job: ScrapeJob, result: dict):
        """Save scrape result to metric_snapshots for periodic jobs."""
        if not self.db:
            return
        try:
            # Find the video record by URL
            video = await self.db.get_video_by_url(job.video_url)
            if video and not video.get("is_final"):
                await self.db.save_metric_snapshot(
                    video_id=video["id"],
                    views=result.get("views", 0),
                    likes=result.get("likes", 0),
                    comments=result.get("comments", 0),
                    shares=result.get("shares", 0),
                )
                print(f"[QUEUE] 💾 Saved periodic result for {job.video_url[:50]} "
                      f"(views={result.get('views', 0)})")
        except Exception as e:
            print(f"[QUEUE] DB save error: {e}")

    async def _update_last_scraped(self, job: ScrapeJob):
        """Update last_scraped_at for the video after a successful scrape."""
        if not self.db:
            return
        try:
            import aiosqlite
            async with aiosqlite.connect(self.db.db_path) as db:
                await db.execute(
                    "UPDATE submitted_videos SET last_scraped_at = ? WHERE video_url = ?",
                    (datetime.now().isoformat(), job.video_url),
                )
                await db.commit()
        except Exception as e:
            print(f"[QUEUE] last_scraped_at update error: {e}")

    async def _update_video_error(self, job: ScrapeJob, error_msg: str):
        """Record the last error and increment attempt count in DB."""
        if not self.db:
            return
        try:
            import aiosqlite
            async with aiosqlite.connect(self.db.db_path) as db:
                await db.execute(
                    "UPDATE submitted_videos SET last_error = ?, "
                    "scrape_attempts = COALESCE(scrape_attempts, 0) + 1 "
                    "WHERE video_url = ?",
                    (error_msg, job.video_url),
                )
                await db.commit()
        except Exception as e:
            print(f"[QUEUE] error update error: {e}")
