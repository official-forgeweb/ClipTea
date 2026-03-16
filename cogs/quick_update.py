import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import time
import sqlite3
import aiosqlite

from scrapers.socialdata import socialdata_get_video, extract_shortcode
from database.manager import DatabaseManager
from config import DATABASE_PATH

class QuickUpdateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()
    
    @app_commands.command(
        name="quick-update",
        description="Update latest N videos using SocialData API"
    )
    @app_commands.describe(
        count="Number of latest videos to update (1-50)"
    )
    async def quick_update(
        self, 
        interaction: discord.Interaction, 
        count: app_commands.Range[int, 1, 50] = 3
    ):
        """
        Fetches the latest N videos from database and updates their 
        views using SocialData.tools API. Shows BEFORE vs AFTER in 
        both Discord and terminal.
        """
        
        # Check if user has admin permission
        if not interaction.user.guild_permissions.administrator:
            # We can also check role ID based on bot_settings
            admin_role_id = await self.db.get_setting("admin_role_id")
            has_role = False
            if admin_role_id and admin_role_id.isdigit():
                role = discord.utils.get(interaction.user.roles, id=int(admin_role_id))
                if role:
                    has_role = True
            
            if not has_role:
                await interaction.response.send_message("❌ Admin only.", ephemeral=True)
                return
        
        await interaction.response.defer(thinking=True)
        
        # ===== GET LATEST N VIDEOS FROM DATABASE =====
        query = """
            SELECT sv.id, sv.video_url, COALESCE(latest.views, 0) as views, 
                   COALESCE(latest.likes, 0) as likes, COALESCE(latest.comments, 0) as comments
            FROM submitted_videos sv
            LEFT JOIN (
                SELECT video_id, views, likes, comments
                FROM metric_snapshots m1
                WHERE id = (
                    SELECT MAX(id) FROM metric_snapshots m2 WHERE m2.video_id = m1.video_id
                )
            ) latest ON sv.id = latest.video_id
            WHERE sv.platform = 'instagram' AND sv.status = 'tracking'
            ORDER BY sv.submitted_at DESC
            LIMIT ?
        """
        
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query, (count,)) as cursor:
                    videos = [dict(row) for row in await cursor.fetchall()]
        except Exception as e:
            await interaction.followup.send(
                f"❌ Database error: {e}\n"
                "Check terminal for details."
            )
            print(f"[QUICK-UPDATE] ❌ Database error: {e}")
            return
        
        if not videos:
            await interaction.followup.send(
                f"❌ No Instagram videos found in database."
            )
            return
        
        # ===== PRINT HEADER IN TERMINAL =====
        print("\n" + "=" * 80)
        print(f"[QUICK-UPDATE] 🚀 Updating {len(videos)} latest videos via SocialData API")
        print("=" * 80)
        print(f"{'#':<4} {'URL':<55} {'BEFORE':<12} {'AFTER':<12} {'STATUS'}")
        print("-" * 80)
        
        # ===== PROCESS EACH VIDEO =====
        results = []
        success_count = 0
        fail_count = 0
        
        for i, video in enumerate(videos, 1):
            video_id = video["id"]
            url = video["video_url"]
            old_views = video.get("views", 0)
            
            # Handle None or -1 views
            if old_views is None or old_views == -1:
                old_views_display = "N/A"
                old_views_num = 0
            else:
                old_views_display = f"{old_views:,}"
                old_views_num = old_views
            
            # ===== CALL SOCIALDATA API =====
            result = await socialdata_get_video(url)
            
            if result["success"] and result.get("views") is not None:
                new_views = result["views"]
                new_likes = result["likes"]
                new_comments = result["comments"]
                
                # Calculate difference
                if old_views_num > 0:
                    diff = new_views - old_views_num
                    diff_text = f"(+{diff:,})" if diff >= 0 else f"({diff:,})"
                else:
                    diff_text = "(new)"
                
                # ===== UPDATE DATABASE =====
                try:
                    await self.db.save_metric_snapshot(
                        video_id=video_id,
                        views=new_views,
                        likes=new_likes,
                        comments=new_comments,
                        extra_data="socialdata_quick"
                    )
                except Exception as e:
                    print(f"[QUICK-UPDATE] ❌ DB update failed: {e}")
                
                # ===== PRINT TO TERMINAL =====
                shortcode = extract_shortcode(url) or url[-20:]
                status = f"✅ {diff_text}"
                print(
                    f"{i:<4} "
                    f"...{shortcode:<52} "
                    f"{old_views_display:<12} "
                    f"{new_views:>10,}  "
                    f"{status}"
                )
                
                results.append({
                    "url": url,
                    "shortcode": shortcode,
                    "old_views": old_views_display,
                    "new_views": new_views,
                    "new_likes": new_likes,
                    "diff_text": diff_text,
                    "success": True
                })
                success_count += 1
                
            else:
                # FAILED
                error_msg = result.get("error", "Unknown error")
                shortcode = extract_shortcode(url) or url[-20:]
                print(
                    f"{i:<4} "
                    f"...{shortcode:<52} "
                    f"{old_views_display:<12} "
                    f"{'FAILED':<12} "
                    f"❌ {error_msg}"
                )
                
                results.append({
                    "url": url,
                    "shortcode": shortcode,
                    "old_views": old_views_display,
                    "new_views": None,
                    "success": False,
                    "error": error_msg
                })
                fail_count += 1
            
            # Small delay between API calls
            if i < len(videos):
                await asyncio.sleep(2)
        
        # ===== PRINT SUMMARY IN TERMINAL =====
        print("-" * 80)
        print(
            f"[QUICK-UPDATE] DONE: "
            f"{success_count} ✅ success, "
            f"{fail_count} ❌ failed, "
            f"{len(videos)} total"
        )
        print("=" * 80 + "\n")
        
        # ===== SEND DISCORD EMBED =====
        embed = discord.Embed(
            title=f"📊 Quick Update — {len(videos)} Videos",
            color=discord.Color.green() if fail_count == 0 else discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        
        # Build results table for embed
        table_lines = []
        for r in results:
            if r["success"]:
                table_lines.append(
                    f"✅ `{r['shortcode']}` — "
                    f"**{r['new_views']:,}** views "
                    f"(was {r['old_views']}) "
                    f"{r['diff_text']}"
                )
            else:
                table_lines.append(
                    f"❌ `{r['shortcode']}` — {r['error']}"
                )
        
        # Discord embed field max is 1024 chars, split if needed
        table_text = "\n".join(table_lines)
        if len(table_text) <= 1024:
            embed.add_field(
                name="Results",
                value=table_text,
                inline=False
            )
        else:
            # Split into chunks
            chunk = ""
            chunk_num = 1
            for line in table_lines:
                if len(chunk) + len(line) + 1 > 1020:
                    embed.add_field(
                        name=f"Results (Part {chunk_num})",
                        value=chunk,
                        inline=False
                    )
                    chunk = line + "\n"
                    chunk_num += 1
                else:
                    chunk += line + "\n"
            if chunk:
                embed.add_field(
                    name=f"Results (Part {chunk_num})",
                    value=chunk,
                    inline=False
                )
        
        embed.set_footer(
            text=f"✅ {success_count} updated | ❌ {fail_count} failed | Source: SocialData API"
        )
        
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(QuickUpdateCog(bot))
