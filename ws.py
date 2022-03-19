from __future__ import annotations
import json
import asyncio
from asyncio.exceptions import CancelledError
from asyncio.tasks import Task
from contextlib import suppress
from starlette.websockets import WebSocket, WebSocketDisconnect
from log import logger
import game

online: set[game.User] = set()
rooms: dict[int, game.Room] = dict()
running_games: list[Task] = []
blacklist = set()

async def game_endpoint(ws: WebSocket):
    if ws.app.debug:
        if hasattr(game_endpoint, "next_username"):
            game_endpoint.next_username += 1
        else:
            game_endpoint.next_username = 0
    elif not ws.user.is_authenticated:
        return
    username = game_endpoint.next_username if ws.app.debug else ws.user.username
    if game.User(username, ws) in online:
        logger.warning(f"multiple connection detected: {username}")
        if not ws.app.debug:
            for u in online:
                if u.username == username:
                    u.existing = True
                    await u.listen({"type": "multiple"})
                    if u.room:
                        await leave_and_delete_room_if_empty(u)
                    with suppress(Exception):
                        await u.ws.close()
                    break
    user = game.User(username, ws)
    online.add(user)
    await ws.accept()
    logger.info(f"connected: {username}")
    welcoming = asyncio.create_task(broadcast_connect(user))
    try:
        rooms_data = [room.info() for room in rooms.values()]
        data = {
            "type": "INITIAL_INFORMATION",
            "online": [user.username for user in online],
            "rooms": rooms_data,
            "username": username,
        }
        await user.listen(data)
        while message := await ws.receive_json():
            ws._raise_on_disconnect(message)
            await process_message(user, message)
    except WebSocketDisconnect:
        if user.room:
            await leave_and_delete_room_if_empty(user)
    finally:
        logger.info(f"{username} disconnected")
        welcoming.cancel()
        with suppress(CancelledError):
            await welcoming
        online.remove(user)
        if user.room: # user.ws.listen()에서 ConnectionClosedError가 난 경우.
            await leave_and_delete_room_if_empty(user)
        try:
            await ws.close()
        except:
            logger.error(f"ERROR while closing {ws} of {user}", exc_info=True)
        await broadcast_disconnect(user)

async def process_message(user: game.User, message: dict):
    msg_type = message["type"]
    if msg_type == game.EventType.CREATE.name and not user.room:
        assert message.get("title")
        if hasattr(process_message, "next_id"):
            process_message.next_id += 1
        else:
            process_message.next_id = 1
        created = game.Room(host=user,
                            title=message["title"],
                            password=message["password"],
                            capacity=15,
                            room_id=process_message.next_id)
        logger.debug(f"{user} creates {created}")
        await user.listen({"type": game.EventType.CREATE.name, "content": {"CREATED": created.id}}) # TODO: Event로 바꿔야 할까?
        await user.enter(created)
        rooms[created.id] = created
        await broadcast_new_room(created)
    elif msg_type == game.EventType.ENTER.name and not user.room:
        if room := rooms.get(message["id"]):
            if room.full():
                pass # TODO: 방이 가득 찼습니다.
            elif room.phase() is game.PhaseType.INITIATING:
                pass # TODO: 게임 초기화 중에는 입장할 수 없습니다. 최대 10초까지 기다렸다가 입장해 주세요.
            else:
                await user.enter(room)
        else:
            pass # TODO: 그런 방이 없습니다.
    elif msg_type == game.EventType.LEAVE.name and user.room:
        await leave_and_delete_room_if_empty(user)
    elif msg_type == game.EventType.MESSAGE.name and user.room:
        if game.is_command(message["text"], game.Command.BEGIN):
            if user is user.room.host:
                if user.room.in_game():
                    pass
                elif not user.room.setup:
                    await user.room.emit(game.Event(game.EventType.ERROR, user.room.members, {game.ContentKey.REASON.name: "설정이 없어 시작할 수 없습니다."}))
                elif len(user.room.members)!=len(user.room.setup.formation):
                    await user.room.emit(game.Event(game.EventType.ERROR, user.room.members, {
                        game.ContentKey.REASON.name: f"설정은 {len(user.room.setup.formation)}인이지만 현재 인원은 {len(user.room.members)}인입니다."
                    }))
                else:
                    logger.info(f"Host({user}) requested game start in {user.room}")
                    task_name = f"game in {user.room.id}"
                    await user.room.turn_phase(game.PhaseType.INITIATING)
                    running_games.append(asyncio.create_task(user.room.run_game(user.ws.app.debug), name=task_name))
                    logger.debug(f"create game task <{task_name}>")
            else:
                await user.room.emit(game.Event(game.EventType.ERROR, user, {game.ContentKey.REASON.name: "게임은 방장이 시작할 수 있습니다."}))
        else:
            try:
                await user.speak(message["text"])
            except:
                logger.error(f"Error while processing {user}'s message: {message['text']}", exc_info=True) # 유저 접속은 유지하고 예외만 띄움
    elif msg_type == game.EventType.SETUP.name and user.room and user is user.room.host:
        setup = message["setup"]
        try:
            user.room.setup = game.Setup(
                setup["title"],
                user,
                setup["formation"],
                setup["constraints"],
                setup["exclusion"]
            )
        except game.SetupMalformed as e:
            logger.warning(f"{user} malformed a formation({e}) for: {user.room}")
            # await leave_and_delete_room_if_empty(user)
            # await user.ws.close()
            # TODO: add to blacklist
            await user.room.emit(game.Event(game.EventType.ERROR, user, {game.ContentKey.REASON.name: "있을 수 없는 값이 설정에 있습니다."}))
        except game.SetupInvalid as e:
            await user.room.emit(game.Event(game.EventType.ERROR, user, {game.ContentKey.REASON.name: str(e)}))
        except:
            logger.error(f"{user}의 설정 적용 중 알 수 없는 오류가 발생했습니다.", exc_info=True)
            await user.room.emit(game.Event(game.EventType.ERROR, user, {game.ContentKey.REASON.name: "설정 적용 중 알 수 없는 오류가 발생했습니다."}))
        else:
            await user.room.emit(game.Event(game.EventType.SETUP, user.room.members, user.room.setup.jsonablify()))

async def leave_and_delete_room_if_empty(user: game.User):
    left = user.room
    await user.leave()
    if left.empty():
        if left.id in rooms:
            del rooms[left.id]
            await broadcast_deleted_room(left)

async def broadcast_connect(joinning: game.User):
    await asyncio.gather(*[user.listen({
        "type": "CONNECT",
        "content": {
            "username": joinning.username
        }
    }) for user in online if user is not joinning])

async def broadcast_disconnect(leaving: game.User):
    await asyncio.gather(*[user.listen({
        "type": "DISCONNECT",
        "content": {
            "username": leaving.username
        }
    }) for user in online])

async def broadcast_room_status_change(room: game.Room):
    await asyncio.gather(*[user.listen({
        "type": "ROOM_STATUS",
        "status": room.info()
    }) for user in online])

async def broadcast_new_room(room: game.Room):
    await asyncio.gather(*[user.listen({
        "type": "NEW_ROOM",
        "room": room.info()
    }) for user in online])

async def broadcast_deleted_room(room: game.Room):
    await asyncio.gather(*[user.listen({
        "type": "DELETED_ROOM",
        "id": room.id
    }) for user in online])

async def admin_endpoint(ws: WebSocket):
    # if not ws.user.is_authenticated:
    #     return
    await ws.accept()
    try:
        while message := await ws.receive_json():
            ws._raise_on_disconnect(message)
            await ws.send_json(await process_admin_message(message))
    except WebSocketDisconnect:
        pass
    finally: 
        await ws.close()

async def process_admin_message(message: dict):
    want = message["want"]
    if want == "online":
        return [str(user) for user in online]
    elif want == "rooms":
        return [str(room) for room in rooms.values()]
    elif want == "running":
        return [str(task) for task in running_games]
    elif want == "recording":
        return [str(task) for task in game.recording_tasks]