"""
Smart Scrape Queue — processes Apify jobs one at a time with random delays,
automatic backoff on Instagram rate-limiting, and retry logic.

Architecture:
  MAIN QUEUE (priority-ordered)
    HIGH  → /submit  (clipper waiting)
    MED   → manual refresh
    LOW   → periodic scraper

  Processing: one job at a time
    → Validate URL (reject fakes BEFORE API call)
    → Check token availability (WAIT if all cooling, never force)
    → Call Apify → classify response
    → Random delay (capped between 15–120 seconds)
    → Next job

  RETRY QUEUE (after main queue drains)
    → 5-minute cooldown → 60-90 s between retries → max 3 attempts
    → On final attempt: save best available data
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

    # Stores parsed data between retries (e.g. likes from description)
    partial_result: Optional[dict] = field(compare=False, default=None, repr=False)


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
        self._jobs_invalid = 0         # Rejected due to invalid URL
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
            "jobs_invalid": self._jobs_invalid,
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
                    # If retry queue has items, process retries with cooldown
                    if self.retry_queue:
                        await self._process_retry_queue()
                    else:
                        await asyncio.sleep(2)  # idle polling
                    continue

                async with self._lock:
                    await self._process_single_job(job)

                self._jobs_processed += 1

                # Inter-job delay
                delay = self._get_delay()
                print(f"[QUEUE] Waiting {delay:.1f}s before next job "
                      f"(backoff={self._consecutive_errors}, "
                      f"queue={self._queue.qsize()}, "
                      f"retry={len(self.retry_queue)})")
                await asyncio.sleep(delay)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[QUEUE] Processor error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(5)

        print("[QUEUE] Processor loop exited")

    async def _process_single_job(self, job: ScrapeJob):
        """
        Process one job: validate URL, check token, call Apify, classify response.
        
        Key rules:
        - Invalid URLs are caught BEFORE any API call
        - Token is never forced when cooling (we wait instead)
        - INVALID_URL errors do NOT penalize token or increase backoff
        - Backoff fully resets on success
        """
        self._last_request_time = time.time()
        print(f"[QUEUE] Processing: {job.video_url[:60]} "
              f"(attempt {job.attempt + 1}/{job.max_attempts})")

        # ── STEP 1: Validate Instagram URL before API call ──
        from services.apify_instagram import validate_instagram_url
        from utils.platform_detector import detect_platform

        platform = detect_platform(job.video_url)

        if platform == "instagram":
            validation = validate_instagram_url(job.video_url)
            if not validation["valid"]:
                print(f"[QUEUE] ❌ Invalid URL rejected: {job.video_url} — {validation['reason']}")
                self._jobs_invalid += 1
                # NO token penalty, NO backoff increase, NO retry
                error_result = {
                    "views": 0, "likes": 0, "comments": 0, "shares": 0,
                    "author_username": "", "method": "invalid_url",
                    "estimated": False, "cached": False,
                    "error": f"Invalid URL: {validation['reason']}",
                }
                await self._finalize_job(job, error_result)
                return

            # Use the normalized (clean) URL
            job.video_url = validation["clean_url"]
            job.shortcode = validation["shortcode"]

        # ── STEP 2: Check token availability — WAIT if all cooling ──
        token = self.apify.token_rotator.get_next_token()
        if token is None:
            wait_time = self.apify.token_rotator.get_wait_time()
            capped_wait = min(wait_time + 5, 120)
            print(f"[QUEUE] ⏳ All tokens cooling. Waiting {capped_wait:.0f}s (actual cooldown: {wait_time:.0f}s)")
            # Put job back at front of queue
            job_copy = self._make_job(
                video_url=job.video_url,
                shortcode=job.shortcode,
                discord_user_id=job.discord_user_id,
                campaign_id=job.campaign_id,
                priority=job.priority,
                event=job.result_event,
            )
            job_copy.attempt = job.attempt
            job_copy.partial_result = job.partial_result
            job_copy.result_data = job.result_data
            await self._queue.put(job_copy)
            await asyncio.sleep(capped_wait)
            return

        # ── STEP 3: Call Apify ──
        try:
            result = await self.apify.get_video_metrics(job.video_url, use_cache=False)
        except Exception as e:
            print(f"[QUEUE] Apify exception: {e}")
            result = {"error": str(e), "views": 0, "likes": 0, "comments": 0}

        if not result:
            result = {"error": "No response from Apify", "views": 0, "likes": 0, "comments": 0}

        # ═══ CLASSIFY THE RESULT ═══
        is_restricted = False
        has_error = False
        is_views_unknown = result.get("views_unknown", False)

        # Check 1: Explicit restricted_page error
        error_text = str(result.get("error", "")).lower()
        if "restricted" in error_text or result.get("restricted"):
            is_restricted = True

        # Check 2: Got response but views=0 AND likes=0 with no error
        #           (Apify returned empty data — treat as restriction)
        if (not result.get("error") and
            int(result.get("views", 0) or 0) in (0, -1) and
            int(result.get("likes", 0) or 0) in (0, -1) and
            result.get("method") not in ("estimation", "cache", "queue_timeout",
                                          "invalid_url", "embed_fallback")):
            is_restricted = True

        # Check 2.1: It is partial, NOT restricted
        is_partial = is_views_unknown and int(result.get("likes", 0) or 0) > 0
        if is_partial:
            is_restricted = False

        # Check 3: Invalid URL response from Apify
        if result.get("method") == "invalid_url":
            # Already handled above, but just in case it comes through Apify
            print(f"[QUEUE] 🗑️ Apify confirmed invalid URL: {job.video_url}")
            self._jobs_invalid += 1
            # NO backoff increase, NO token penalty
            await self._finalize_job(job, result)
            return

        # Check 4: Non-restriction error
        if result.get("error") and not is_restricted:
            has_error = True

        # ═══ HANDLE BASED ON CLASSIFICATION ═══

        if not is_restricted and not has_error and (
            result.get("views", 0) > 0 or result.get("likes", 0) > 0
        ):
            # ─── SUCCESS ───
            if not result.get("estimated") and result.get("views", 0) > 0 and not is_views_unknown:
                # FULL success — got real views
                print(f"[QUEUE] ✅ Full success: views={result['views']}, "
                      f"likes={result.get('likes', 0)}")
                self._jobs_succeeded += 1
                self._reset_backoff()  # Fully reset on success
            else:
                # Has parsed data (real likes, views unknown)
                print(f"[QUEUE] ⚠️ Got partial data (likes={result.get('likes', 0)}, views_unknown={is_views_unknown})")
                self._jobs_succeeded += 1 # Count as success
                
                # Signal caller ASAP so UI shows "views pending"
                await self._finalize_job(job, result)
                
                # Spin off ONE delayed retry (30 mins) if we still have attempts
                if job.attempt < job.max_attempts - 1:
                    print(f"[QUEUE] ⏳ Scheduling one 30-minute retry for partial data: {job.video_url[:50]}")
                    async def delayed_retry():
                        await asyncio.sleep(1800)
                        retry_job = self._make_job(
                            video_url=job.video_url,
                            discord_user_id=job.discord_user_id,
                            campaign_id=job.campaign_id,
                            priority=PRIORITY_LOW,
                            event=None
                        )
                        retry_job.attempt = job.max_attempts - 1
                        retry_job.partial_result = result
                        await self._queue.put(retry_job)
                        
                    asyncio.create_task(delayed_retry())
                    
                return

            # Save + signal
            await self._finalize_job(job, result)

        elif is_restricted:
            # ─── RESTRICTED ───
            self._increase_backoff()
            job.attempt += 1

            # Save any parsed data from this attempt
            if result.get("likes", 0) > 0:
                job.partial_result = result

            if job.attempt < job.max_attempts:
                print(f"[QUEUE] 🔄 Restricted, added to retry queue "
                      f"(attempt {job.attempt}/{job.max_attempts})")
                self.retry_queue.append(job)
                # DON'T save to DB, DON'T signal caller — will retry
            else:
                # Max retries exhausted
                print(f"[QUEUE] ❌ Max retries exhausted for {job.video_url[:50]}")
                self._jobs_failed += 1

                # Use best available: partial_result > current result > embed fallback
                final_result = job.partial_result or result
                if final_result.get("views", 0) == 0 and final_result.get("likes", 0) == 0:
                    shortcode = self.apify._extract_shortcode(job.video_url)
                    final_result = await self.apify._estimation_fallback(
                        job.video_url, shortcode
                    )

                await self._update_video_error(job, "max_retries_exhausted")
                await self._finalize_job(job, final_result)

        else:
            # ─── OTHER ERROR ───
            job.attempt += 1
            self._increase_backoff()

            if job.attempt < job.max_attempts:
                print(f"[QUEUE] 🔄 Error: {error_text[:50]}, retry queue "
                      f"(attempt {job.attempt}/{job.max_attempts})")
                self.retry_queue.append(job)
            else:
                print(f"[QUEUE] ❌ Max retries for {job.video_url[:50]}: {error_text[:50]}")
                self._jobs_failed += 1

                # Use partial or embed fallback
                final_result = job.partial_result
                if not final_result or (
                    final_result.get("views", 0) == 0 and
                    final_result.get("likes", 0) == 0
                ):
                    shortcode = self.apify._extract_shortcode(job.video_url)
                    final_result = await self.apify._estimation_fallback(
                        job.video_url, shortcode
                    )

                await self._update_video_error(job, error_text[:100])
                await self._finalize_job(job, final_result)

    async def _finalize_job(self, job: ScrapeJob, result: dict):
        """Save result to DB and signal waiting callers."""
        # Signal waiting callers (/submit)
        if job.result_event:
            job.result_data = result
            job.result_event.set()

        # Save metrics for periodic jobs (no caller waiting)
        if not job.result_event and result and not result.get("error"):
            await self._save_periodic_result(job, result)
        elif not job.result_event and result:
            # Even with error, save if we have usable data
            if result.get("views", 0) > 0 or result.get("likes", 0) > 0:
                await self._save_periodic_result(job, result)

        # Update last_scraped_at — always update for periodic jobs so they
        # don't get re-queued on restart (queue persistence via DB)
        if not job.result_event:
            # Periodic job — always mark as scraped
            await self._update_last_scraped(job)
        elif not result.get("error") or result.get("views", 0) > 0:
            # /submit job — only mark on success
            await self._update_last_scraped(job)

    async def _process_retry_queue(self):
        """Process all retry jobs with longer delays after a cooldown."""
        if not self.retry_queue:
            return

        retry_count = len(self.retry_queue)
        print(f"[QUEUE] 🔄 {retry_count} videos in retry queue. "
              f"Cooling down {self._retry_cooldown}s before retrying...")
        await asyncio.sleep(self._retry_cooldown)

        # Take a snapshot so new retries added during processing wait for next cycle
        jobs_to_retry = list(self.retry_queue)
        self.retry_queue.clear()

        print(f"[QUEUE] 🔄 Starting retry processing ({len(jobs_to_retry)} videos)...")

        for job in jobs_to_retry:
            if not self._running:
                break

            async with self._lock:
                await self._process_single_job(job)

            self._jobs_processed += 1

            # Retry delay is longer: 60-90 seconds
            delay = random.uniform(60, 90)
            print(f"[QUEUE] Retry delay: {delay:.1f}s "
                  f"(remaining retries: {len(self.retry_queue)})")
            await asyncio.sleep(delay)

        print("[QUEUE] 🔄 Retry queue processing complete")

        # Reset backoff after full retry cycle
        self._reset_backoff()

    # ── Backoff management ─────────────────────────────

    def _increase_backoff(self):
        """Increase delays after rate limiting detected."""
        self._consecutive_errors += 1
        self._backoff_level = min(self._consecutive_errors, 3)
        print(f"[QUEUE] 🔴 Backoff increased → level {self._backoff_level} "
              f"(consecutive errors: {self._consecutive_errors})")

    def _decrease_backoff(self):
        """Decrease delays after successful request. (Legacy — now just resets.)"""
        self._reset_backoff()

    def _reset_backoff(self):
        """Fully reset delays to default values."""
        if self._consecutive_errors > 0:
            print(f"[QUEUE] 🟢 Backoff RESET (was level {self._backoff_level}, "
                  f"errors={self._consecutive_errors})")
        self._consecutive_errors = 0
        self._backoff_level = 0

    def _get_delay(self) -> float:
        """Return the random delay for the current backoff level.
        
        Capped between 15 and 120 seconds (never higher).
        """
        ranges = {
            0: (15, 25),     # normal
            1: (30, 50),     # mild
            2: (50, 80),     # medium
            3: (80, 120),    # high — hard cap
        }
        lo, hi = ranges.get(self._backoff_level, (80, 120))
        return random.uniform(lo, hi)

    def _delay_description(self) -> str:
        """Human-readable description of current delay range."""
        ranges = {
            0: "15-25s (normal)",
            1: "30-50s (level 1)",
            2: "50-80s (level 2)",
            3: "80-120s (level 3 — max)",
        }
        return ranges.get(self._backoff_level, "80-120s (max)")

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
                new_views = int(result.get("views", 0) or 0)

                # View regression protection: don't save if new views < previous
                latest = await self.db.get_latest_metrics(video["id"])
                if latest:
                    old_views = int(latest.get("views", 0) or 0)
                    if old_views > 0 and new_views < old_views:
                        print(f"[QUEUE] ⚠️ View regression blocked for {job.video_url[:50]} "
                              f"(old={old_views:,}, new={new_views:,}) — keeping old record")
                        return

                await self.db.save_metric_snapshot(
                    video_id=video["id"],
                    views=new_views,
                    likes=result.get("likes", 0),
                    comments=result.get("comments", 0),
                    shares=result.get("shares", 0),
                )
                est_marker = " (estimated)" if result.get("estimated") else ""
                print(f"[QUEUE] 💾 Saved periodic result for {job.video_url[:50]} "
                      f"(views={new_views}{est_marker})")
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