class BandwidthOptimizer:
    """Blocks unnecessary resources to save bandwidth and speed up scrapes."""
    def __init__(self):
        self.blocked_resource_types = {
            "image", "media", "font", "stylesheet"
        }
        self.blocked_domains = [
            "google-analytics.com", "facebook.com", "facebook.net",
            "doubleclick.net", "googlesyndication.com"
        ]

    async def route_handler(self, route):
        """Playwright route handler to intercept and block or allow requests."""
        request = route.request
        
        # Block by resource type
        if request.resource_type in self.blocked_resource_types:
            await route.abort()
            return
            
        # Block by tracking domains
        for domain in self.blocked_domains:
            if domain in request.url:
                await route.abort()
                return
                
        # Allow everything else
        await route.continue_()
