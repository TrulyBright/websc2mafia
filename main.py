import random
import base64
import logging
import binascii
from starlette.applications import Starlette
from starlette.config import Config
from starlette.requests import Request
from starlette.authentication import AuthenticationBackend, AuthenticationError, SimpleUser, UnauthenticatedUser, AuthCredentials
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles
import views
import ws
from log import logger

class BasicAuthBackend(AuthenticationBackend):
    async def authenticate(self, request:Request):
        if auth := request.headers.get("Authorization"):
            try:
                scheme, credentials = auth.split()
                if scheme.lower() != "basic":
                    return
                decoded = base64.b64decode(credentials).decode("ascii")
            except (ValueError, UnicodeDecodeError, binascii.Error) as e:
                raise AuthenticationError("Invalid basic auth credentials")
            
            username, _, password = decoded.partition(":")
            return AuthCredentials(["Authenticated"]), SimpleUser(username)

conf = Config(".env")
DEBUG = conf("DEBUG", cast=bool, default=False)
logger.setLevel(logging.INFO)
routes = [
    Route("/", views.index),
    Route("/game", views.game),
    Route("/about", views.about),
    Route("/archive", views.archive),
    Route("/patch-note", views.patch_note),
    Route("/admin", views.admin),
    Route("/favicon.ico", views.favicon),
    Mount("/assets", StaticFiles(directory="dist/assets")),
    WebSocketRoute("/game", ws.game_endpoint),
    WebSocketRoute("/admin", ws.admin_endpoint)
]
middleware = [
    Middleware(AuthenticationMiddleware, backend=BasicAuthBackend())
]

app = Starlette(debug=DEBUG, routes=routes, middleware=middleware)

random.seed()