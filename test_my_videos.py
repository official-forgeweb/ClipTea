import asyncio
from database.manager import DatabaseManager
from utils.formatters import format_number, format_currency, format_timestamp, format_date, platform_emoji

async def main():
    db = DatabaseManager('cliptea.db')
    
    # Try generic fake user id
    videos = await db.get_user_videos('651478297495027732')  # Replace with actual discord user ID if needed
    if not videos:
        # Get any video
        videos = await db.get_all_tracking_videos()
        if videos:
            videos = await db.get_user_videos(videos[0]['discord_user_id'])
            
    print(f"Found {len(videos)} videos")
    
    for v in videos[:10]:
        metrics = await db.get_latest_metrics(v['id'])
        views = metrics.get('views', 0) if metrics else 0
        likes = metrics.get('likes', 0) if metrics else 0

        rate_campaign = await db.get_campaign(v['campaign_id'])
        rate = rate_campaign.get('rate_per_10k_views', 10.0) if rate_campaign else 10.0
        
        from campaign.payment_calculator import calculate_earnings
        earned = calculate_earnings(views, rate)
        
        print(f"Platform: {v['platform']}, Emoji: {platform_emoji(v['platform'])}")
        print(f"{platform_emoji(v['platform'])} {v.get('campaign_name', v['campaign_id'])}")
        print(f"👁️ {format_number(views)} views │ ❤️ {format_number(likes)} likes │ 💵 {format_currency(earned)}")
        print(f"📅 Submitted: {format_date(v.get('submitted_at', ''))}")
        
asyncio.run(main())
