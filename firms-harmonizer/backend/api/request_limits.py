"""Bound request bodies, request rates and simultaneous analytical work."""
from collections import defaultdict, deque
from threading import BoundedSemaphore, Lock
from time import monotonic
import os

from starlette.responses import JSONResponse

# A single range selection queries one map period per year (up to 27), so the
# regular budget must absorb that legitimate burst. Copilot keeps its own,
# much lower LLM-cost budget.
REGULAR_REQUESTS_PER_MINUTE = 120
COPILOT_REQUESTS_PER_MINUTE = 10


class RequestLimits:
    def __init__(self, app):
        self.app = app
        self.history = defaultdict(deque)
        self.lock = Lock()
        self.slots = BoundedSemaphore(4)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST':
            return await self.app(scope, receive, send)
        path = scope['path']
        if not path.startswith('/api/'):
            return await self.app(scope, receive, send)
        copilot = path == '/api/explain-spike'
        key = ((scope.get('client') or ('local',))[0], copilot)
        now = monotonic()
        with self.lock:
            # Expire clients as well as individual requests to bound bookkeeping.
            for old in [k for k, v in self.history.items() if not v or v[-1] <= now - 60]:
                del self.history[old]
            queue = self.history[key]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            limit = COPILOT_REQUESTS_PER_MINUTE if copilot else REGULAR_REQUESTS_PER_MINUTE
            denied = len(queue) >= limit * max(1, int(os.environ.get("REQUEST_RATE_MULTIPLIER", "1")))
            if not denied:
                queue.append(now)
        if denied:
            return await JSONResponse({'detail': 'Request rate exceeded.'}, 429,
                                      headers={'Retry-After': '60'})(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > 256 * 1024:
                return await JSONResponse({'detail': 'Request exceeds 256 KiB.'}, 413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        if not self.slots.acquire(blocking=False):
            return await JSONResponse({'detail': 'Analytical workers are busy.'}, 429,
                                      headers={'Retry-After': '1'})(scope, receive, send)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        try:
            await self.app(scope, replay, send)
        finally:
            self.slots.release()
