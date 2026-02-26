from playwright.async_api import Browser, BrowserContext, Playwright

STEALTH_JS = """
// Overrides and tweaks for bypassing detection
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
});

// Mock Chrome runtime
window.chrome = {
  runtime: {},
  app: {},
  csi: () => {},
  loadTimes: () => {}
};

// Mock plugins
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3],
});

// Fix WebGL
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
  if (parameter === 37445) return 'Intel Inc.';
  if (parameter === 37446) return 'Intel Iris OpenGL Engine';
  return getParameter.apply(this, arguments);
};

// Fix hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
  get: () => 4
});

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""

async def create_stealth_browser(playwright: Playwright, headless: bool = True, proxy: dict = None) -> Browser:
    """Launches a stealth Chromium browser."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage"
    ]
    
    launch_options = {
        "headless": headless,
        "args": args
    }
    
    if proxy:
        launch_options["proxy"] = proxy

    browser = await playwright.chromium.launch(**launch_options)
    return browser

async def apply_stealth_scripts(context: BrowserContext):
    """Injects stealth javascript before the page is created."""
    await context.add_init_script(STEALTH_JS)
