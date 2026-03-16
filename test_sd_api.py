import asyncio
import aiohttp


async def test_free_apis():
    print("=" * 60)
    print("[TEST] Free Instagram APIs (No signup needed)")
    print("=" * 60)

    shortcode = "DVvlESMj56y"
    full_url = "https://www.instagram.com/reel/DVvlESMj56y"

    tests = [
        {
            "name": "Instagram oEmbed (Official, free, no key)",
            "url": f"https://api.instagram.com/oembed/?url={full_url}",
            "headers": {},
            "note": "Returns title+author but NOT views. Tests if URL is valid."
        },
        {
            "name": "Instagram Web ?__a=1",
            "url": f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            "note": "Sometimes returns full post JSON"
        },
        {
            "name": "Instagram GraphQL",
            "url": f"https://www.instagram.com/graphql/query/?query_hash=b3055c01b4b222b8a47dc12b090e4e64&variables=%7B%22shortcode%22%3A%22{shortcode}%22%7D",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            "note": "Instagram GraphQL endpoint"
        },
    ]

    async with aiohttp.ClientSession() as session:
        for test in tests:
            print(f"\n--- {test['name']} ---")
            print(f"Note: {test['note']}")

            try:
                async with session.get(
                    test["url"],
                    headers=test["headers"],
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    status = resp.status
                    body = await resp.text()

                    if status == 200:
                        print(f"✅ Status: {status}")
                        print(f"Response: {body[:500]}")
                    else:
                        print(f"❌ Status: {status}")
                        print(f"Response: {body[:300]}")
            except Exception as e:
                print(f"💥 Error: {e}")


asyncio.run(test_free_apis())