from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.templating import Jinja2Templates
import roles

templates = Jinja2Templates("dist")
REQUEST = "request"

def favicon(request: Request):
    return FileResponse("dist/favicon.ico")

def index(request: Request):
    """첫 화면."""
    return templates.TemplateResponse("index.html", {REQUEST: request})

def game(request: Request):
    """로비 화면. 게임방 화면도 겸합니다."""
    return templates.TemplateResponse("game.html", {
        REQUEST: request,
        "pool": roles.pool(),
        "roles": roles,
        "issubclass": issubclass,
        "isinstance": isinstance
    })

def about(request: Request):
    return templates.TemplateResponse("about.html", {REQUEST: request})

def archive(request: Request):
    return templates.TemplateResponse("archive.html", {REQUEST: request})

def patch_note(request: Request): # TODO: DB에 패치노트 기입
    return templates.TemplateResponse("patch-note.html", {REQUEST: request, "patch_notes": {
        "2022 01 09": [
            "버그: 총 154개 버그 중 140개 해결 완료.",
            "조작자/위조꾼 비활성화: 마땅히 떠오르는 상향안은 없는데 그냥 놔두자니 너무 약해서, 일단은 나오지 않도록 함.",
            "생존자 상향: 이제 현재 살아 있는 직업들을 알아냄. 혼자서 할 수 있는 게 아무것도 없었기 때문.",
            "포고꾼 하향: 생존자와 겹치는 '동향 파악' 능력 삭제. '말'을 할 수 있다는 점에 착안하여 다른 상향안을 강구.",
            "'시민' 상향: 이제 깡시민은 마피아/삼합회 말고도 누구와 1대1을 하든 무조건 승리함. (회계 간접 하향)",
            "경호 연쇄 구현 완료: 경호원에게 경호되는 경호원에게 경호되는 사람이 경호원에게 경호되는 경호원에게 경호되는 사람을 공격할 때, 더 이상 나올 경호원이 없을 때까지 계속 경호원이 나서도록 함."
        ],
    }})

def admin(request: Request):
    """관리 화면."""
    return templates.TemplateResponse("admin.html", {REQUEST: request})