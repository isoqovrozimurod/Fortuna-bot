import os
import asyncio
from aiohttp import web

async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="Fortuna-bot is running and alive ✅", status=200)

async def start_server():
    """Asinxron HTTP server ishga tushirish"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_head('/', health_check)  # Render HEAD so'rovi uchun
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"✅ Keep-alive server started on http://0.0.0.0:{port}")
    
    # Serverni abadiy ishlab turish
    while True:
        await asyncio.sleep(3600)  # Har soatda tekshirish

def keep_alive():
    """Asinxron task yaratish"""
    asyncio.create_task(start_server())
