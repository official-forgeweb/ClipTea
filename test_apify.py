import asyncio
from services.apify_instagram import ApifyInstagramService

async def main():
    service = ApifyInstagramService()
    await service.init_tables()
    print("Testing get_video_metrics...")
    result = await service.get_video_metrics("https://www.instagram.com/p/DUxWKrzDKNd/")
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
