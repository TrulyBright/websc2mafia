from __future__ import annotations
from contextlib import suppress
import re
import itertools
import time
import string
import random
import inspect
import asyncio
from asyncio.tasks import Task
from enum import Enum, IntEnum, auto, unique
from typing import Any, Optional, Union, Callable, Type
from websockets.exceptions import ConnectionClosed
from starlette.websockets import WebSocket, WebSocketDisconnect
from log import logger
import db
import roles

DEMOCRACY = "Democracy"

class BroadCaster:
    def __init__(self, server: GameServer):
        self.server = server

    async def connection(self, connected: User):
        await asyncio.gather(*[user.listen({
            "type": "CONNECT",
            "content": {
                "username": connected.username
            }
        }) for user in self.server.online if user is not connected])

    async def disconnection(self, disconnected: User):
        await asyncio.gather(*[user.listen({
            "type": "DISCONNECT",
            "content": {
                "username": disconnected.username
            }
        }) for user in self.server.online])

    async def room_status_change(self, room: Room):
        await asyncio.gather(*[user.listen({
            "type": "ROOM_STATUS",
            "status": room.info()
        }) for user in self.server.online])

    async def new_room(self, room: Room):
        await asyncio.gather(*[user.listen({
            "type": "NEW_ROOM",
            "room": room.info()
        }) for user in self.server.online])

    async def deleted_room(self, room: Room):
        await asyncio.gather(*[user.listen({
            "type": "DELETED_ROOM",
            "id": room.id
        }) for user in self.server.online])

class GameServer:
    def __init__(self):
        self.broadcaster = BroadCaster(self)
        self.online: set[User] = set()
        self.rooms: dict[int, Room] = dict()
        self.running_games: list[Task] = []
        self.recording_tasks: list[Task] = []
        self.next_username = 0
        self.next_room_id = 1

    async def endpoint(self, ws: WebSocket):
        if ws.app.debug:
            self.next_username += 1
        elif not ws.user.is_authenticated:
            return
        connected = User(
            self.next_username if ws.app.debug else ws.username, ws)
        self.online.add(connected)
        await ws.accept()
        logger.info(f"connected: {connected.username}")
        welcoming = asyncio.create_task(self.broadcaster.connection(connected))
        try:
            rooms_data = [room.info() for room in self.rooms.values()]
            data = {
                "type": "INITIAL_INFORMATION",
                "online": [user.username for user in self.online],
                "rooms": rooms_data,
                "username": connected.username,
            }
            await connected.listen(data)
            while message := await ws.receive_json():
                ws._raise_on_disconnect(message)
                await self.process_message(connected, message)
        except WebSocketDisconnect:
            if connected.room:
                await self.leave_and_delete_room_if_empty(connected)
        finally:
            logger.info(f"{connected} disconncted")
            welcoming.cancel()
            with suppress(asyncio.CancelledError):
                await welcoming
            self.online.remove(connected)
            if connected.room:
                await self.leave_and_delete_room_if_empty(connected)
            try:
                await ws.close()
            except:
                logger.error(
                    f"ERROR while closing {ws} of {connected}", exc_info=True)
            await self.broadcaster.disconnection(connected)

    async def leave_and_delete_room_if_empty(self, user: User):
        left = user.room
        await user.leave()
        if left.empty():
            if left.id in self.rooms:
                del self.rooms[left.id]
                await self.broadcaster.deleted_room(left)

    async def process_message(self, user: User, message: dict):
        msg_type = message["type"]
        if msg_type == EventType.CREATE.name and not user.room:
            assert message.get("title")
            self.next_room_id += 1
            created = Room(host=user,
                           title=message["title"],
                           password=message["password"],
                           capacity=15,
                           room_id=self.next_room_id)
            logger.debug(f"{user} creates {created}")
            # TODO: Event??? ????????? ???????
            await user.listen({"type": EventType.CREATE.name, "content": {"CREATED": created.id}})
            await user.enter(created)
            self.rooms[created.id] = created
            await self.broadcaster.new_room(created)
        elif msg_type == EventType.ENTER.name and not user.room:
            if room := self.rooms.get(message["id"]):
                if room.full():
                    pass  # TODO: ?????? ?????? ????????????.
                elif room.phase() is PhaseType.INITIATING:
                    # TODO: ?????? ????????? ????????? ????????? ??? ????????????. ?????? 10????????? ??????????????? ????????? ?????????.
                    pass
                else:
                    await user.enter(room)
            else:
                pass  # TODO: ?????? ?????? ????????????.
        elif msg_type == EventType.LEAVE.name and user.room:
            await self.leave_and_delete_room_if_empty(user)
        elif msg_type == EventType.MESSAGE.name and user.room:
            if is_command(message["text"], Command.BEGIN):
                if user is user.room.host:
                    if user.room.in_game():
                        pass
                    elif not user.room.setup:
                        await user.room.emit(Event(EventType.ERROR, user.room.members, {
                            ContentKey.REASON.name: "????????? ?????? ????????? ??? ????????????."
                        }))
                    elif len(user.room.members) != len(user.room.setup.formation):
                        await user.room.emit(Event(EventType.ERROR, user.room.members, {
                            ContentKey.REASON.name: f"????????? {len(user.room.setup.formation)}???????????? ?????? ????????? {len(user.room.members)}????????????."
                        }))
                    else:
                        logger.info(
                            f"Host({user}) requested game start in {user.room}")
                        task_name = f"game in {user.room.id}"
                        await user.room.turn_phase(PhaseType.INITIATING)
                        self.running_games.append(asyncio.create_task(
                            user.room.run_game(user.ws.app.debug), name=task_name))
                        logger.debug(f"create game task <{task_name}>")
                else:
                    await user.room.emit(Event(EventType.ERROR, user, {ContentKey.REASON.name: "????????? ????????? ????????? ??? ????????????."}))
            else:
                try:
                    await user.speak(message["text"])
                except:
                    # ?????? ????????? ???????????? ????????? ??????
                    logger.error(
                        f"Error while processing {user}'s message: {message['text']}", exc_info=True)
        elif msg_type == EventType.SETUP.name and user.room and user is user.room.host:
            setup = message["setup"]
            try:
                user.room.setup = Setup(
                    setup["title"],
                    user,
                    setup["formation"],
                    setup["constraints"],
                    setup["exclusion"]
                )
            except SetupMalformed as e:
                logger.warning(
                    f"{user} malformed a formation({e}) for: {user.room}")
                # await leave_and_delete_room_if_empty(user)
                # await user.ws.close()
                # TODO: add to blacklist
                await user.room.emit(Event(EventType.ERROR, user, {ContentKey.REASON.name: "?????? ??? ?????? ?????? ????????? ????????????."}))
            except SetupInvalid as e:
                await user.room.emit(Event(EventType.ERROR, user, {ContentKey.REASON.name: str(e)}))
            except:
                logger.error(
                    f"{user}??? ?????? ?????? ??? ??? ??? ?????? ????????? ??????????????????.", exc_info=True)
                await user.room.emit(Event(EventType.ERROR, user, {ContentKey.REASON.name: "?????? ?????? ??? ??? ??? ?????? ????????? ??????????????????."}))
            else:
                await user.room.emit(Event(EventType.SETUP, user.room.members, user.room.setup.jsonablify()))


def jsonablify(injsonable: dict):
    remove_enum: Callable[[dict], dict] = lambda data: {key.name if isinstance(key, Enum) else key: value for key, value in {
        key: value.name if isinstance(value, Enum) else value for key, value in data.items()}.items()}
    remove_class: Callable[[dict], dict] = lambda data: {key.__name__ if inspect.isclass(key) else key: value for key, value in {
        key: value.__name__ if inspect.isclass(value) else value for key, value in data.items()}.items()}
    return remove_class(remove_enum(injsonable))


def is_command(msg: str, command: Command):
    return msg.startswith(command.value)


class SetupInvalid(Exception):
    """????????? ????????? ??????."""


class SetupMalformed(Exception):
    """????????? ????????? ????????? ??????."""


@unique
class CrimeType(Enum):
    TRESPASS = "????????????"
    KIDNAP = "??????"
    CORRUPTION = "??????"
    IDENTITY_THEFT = "????????????"
    SOLICITING = "????????????"
    MURDER = "??????"
    DISTURBING_THE_PEACE = "????????? ????????????"
    CONSPIRICY = "??????"
    DISTRUCTION_OF_PROPERTY = "?????? ??????"
    ARSON = "??????"


@unique
class VoteType(IntEnum):
    ABSTENTION = 0
    GUILTY = 1
    INNOCENT = -1
    SKIP = 58826974


@unique
class PhaseType(Enum):
    IDLE = auto()
    INITIATING = auto()
    NICKNAME_SELECTION = auto()
    FINISHING = auto()
    MORNING = auto()
    DISCUSSION = auto()
    VOTE = auto()
    ELECTION = auto()
    DEFENSE = auto()
    VOTE_EXECUTION = auto()
    LAST_WORDS = auto()
    POST_EXECUTION = auto()
    EVENING = auto()
    NIGHT = auto()


@unique
class Command(Enum):
    SLASH = "/"
    BEGIN = "/??????"
    PM = "/???"
    COURT = "/??????"
    LYNCH = "/??????"
    MAYOR = "/??????"
    VOTE = "/??????"
    GUILTY = "/??????"
    INNOCENT = "/??????"
    ABSTENTION = "/??????"
    SKIP = "/??????"
    VISIT = "/??????"
    ACT = "/??????"
    RECRUIT = "/??????"
    JAIL = "/??????"
    SUICIDE = "/??????"
    NICKNAME = "/?????????"


@unique
class ContentKey(Enum):
    MESSAGE = auto()
    FROM = auto()
    TO = auto()
    WILL = auto()
    WHO = auto()
    DEFENSE = auto()
    REASON = auto()
    ROLE = auto()
    TARGET = auto()
    SECOND_TARGET = auto()
    GOAL_TARGET = auto()
    ACTIVE = auto()
    PHASE = auto()
    TIME = auto()
    WHAT = auto()
    OPPORTUNITY = auto()
    SHOW_ROLE_NAME = auto()
    IS_LINEUP_MEMBER = auto()


@unique
class EventType(Enum):
    """????????? ????????? ???????????? Enum."""
    CREATE = auto()
    ENTER = auto()
    LEAVE = auto()
    AFK = auto()
    GAME_INFO = auto()
    SETUP = auto()
    BACK_TO_IDLE = auto()

    BEGIN = auto()
    FINISH = auto()
    EMPLOYED = auto()
    TEAMMATES = auto()
    ROLE_POOL = auto()
    VOTE = auto()

    NICKNAME = auto()
    LINEUP = auto()
    NICKNAME_CONFIRMED = auto()
    MESSAGE = auto()
    PM = auto()
    PM_SENT = auto()
    BLACKMAILED = auto()

    PHASE = auto()
    SKIP = auto()
    TIME = auto()
    DAY_EVENT = auto()
    VOTE_EXECUTION_RESULT = auto()

    VISIT = auto()
    ACT = auto()
    SECOND_VISIT = auto()
    SUICIDE = auto()
    ABILITY_RESULT = auto()
    ERROR = auto()

    SOUND = auto()
    DEAD = auto()
    IDENTITY_REVEAL = auto()
    NUMBER_OF_DEAD = auto()


class Event:
    """????????? ?????????.
    ?????? ???????????? ?????? ???????????? ?????? ???????????? ????????? ???????????? ?????? ????????????.

    Arrtibutes:
        `event_type`: ????????? ??????. `EventType`????????? ?????????.
        `to`: ???????????? ?????? `Player`, `User`, ????????? ?????? ?????? ?????? `list`.
        `content`: ???????????? ?????? `dict`. JSON?????? ????????? ???????????? ?????????.
        `from_`: ???????????? ????????? ????????? ??????(`User`). ???????????? `None`?????????. ????????? ?????? ???????????? ??????????????? ??? ?????????.
        `no_record`: ?????? ?????? ????????? ?????? ???????????? ???????????? ????????? ??????. ???????????? `False`?????????.
    """

    def __init__(self,
                 event_type: EventType,
                 to: Union[list, User, Player],
                 content: dict,
                 from_: Optional[Union[User, Player]] = None,
                 no_record: bool = False):
        self.type = event_type
        self.to = to if isinstance(to, list) else [to]
        self.content = content
        self.from_ = from_.user if isinstance(from_, Player) else from_
        self.no_record = no_record

    def __repr__(self) -> str:
        return f"<Event {self.type} {self.from_ if self.from_ else ''} -> {self.to}>"


class Setup:
    """?????? ?????????. ????????? ???????????? ????????? ???????????? ??? ????????????.

    Attributes:
        title: ?????????. 16??? ???????????????.
        inventor: ??? ????????? ?????? `User`??? username. #TODO: unique id??? ??????
        formation: ?????? ??????.
        constraints: ?????? ?????? ??????.
        exclusion: ?????? ??????.
    """

    def __init__(self,
                 title: str,
                 inventor: User,
                 formation: list[str],
                 constraints: dict[str, dict[str, Any]],
                 exclusion: dict[str, dict[str, bool]]):
        """????????? ???????????? ????????? ???????????????.
        ???????????? ????????? `Exception`??? ????????????.

        Parameters:
            `title`: ?????????. 16??? ????????? ????????????.
            `inventor`: ????????? ?????? `User`.
            `formation`: ?????? ??????.
            `constraints`: ?????? ?????? ??????.
            `exclusion`: ?????? ?????? ??????.
        Raises:
            `SetupInvalid`: ????????? ???????????? ?????? ??????.
            `SetupMalformed`: ????????? ????????? ????????? ??????.
        """
        # TODO: inventor??? User ID??? ??????, jsonablify()??? __init__()??? ???????????? ?????????.
        pool = roles.pool()
        slots: list[Union[Type[roles.Role], Type[roles.Slot]]] = []
        competitors: set[Type[roles.Slot]] = set()
        constraints_with_constructors: dict[Type[roles.Role],
                                            dict[Union[roles.ConstraintKey, str], Union[roles.Level, str, bool, int]]] = dict()
        exclusion_with_constructors: dict[Type[roles.Slot],
                                          list[Type[Union[roles.Slot, roles.Role]]]] = dict()
        for slot in formation:
            for name, constructor in pool:
                if slot == name:
                    slots.append(constructor)
                    if constructor.team() is not None and constructor.against() != {}:
                        competitors.add(constructor.team())
                    break
            else:
                raise SetupMalformed(f"{slot}??? ???????????? ????????? ?????? ????????? ?????? ??? ?????? ????????????.")
        for slot, constraint in constraints.items():
            for name, constructor in {(n, c) for n, c in pool if roles.is_specific_role(c)}:
                if slot == name:
                    constraints_with_constructors[constructor] = dict()
                    if modifiable := constructor.modifiable_constraints():
                        for option, value in constraint.items():
                            value = roles.Level[value] if value in roles.Level.__members__ else value
                            option = roles.ConstraintKey[option] if option in roles.ConstraintKey.__members__ else option
                            if option not in modifiable:
                                raise SetupMalformed(
                                    f"{slot}??? ?????? ????????? ????????? ?????????????????????. {option}??? ???????????? ?????? ???????????????.")
                            option_range = modifiable[option][roles.ConstraintKey.OPTIONS]
                            if value in option_range:
                                constraints_with_constructors[constructor][option] = value
                            else:
                                raise SetupMalformed(
                                    f"{slot}??? ?????? ????????? ????????? ?????????????????????. {option}??? ????????? {option_range}??? {value}??? ????????????.")
                    break
            else:
                raise SetupMalformed(f"????????? ?????? {slot}???(???) ??????????????? ??????????????????.")
        for from_, exclusion_dict in exclusion.items():
            for excluding_name, excluding_constructor in pool:
                if from_ == excluding_name:
                    exclusion_with_constructors[excluding_constructor] = []
                    for excluded in {name for name, is_excluded in exclusion_dict.items() if is_excluded}:
                        for excluded_name, excluded_constructor in pool:
                            if excluded == excluded_name:
                                exclusion_with_constructors[excluding_constructor].append(
                                    excluded_constructor)
                                break
                        else:
                            if excluding_constructor is roles.Any:
                                if excluded == roles.Killing.__name__:
                                    exclusion_with_constructors[excluding_constructor].append(
                                        roles.Killing)
                                else:
                                    for n, t in roles.teams():
                                        if excluded == n:
                                            exclusion_with_constructors[excluding_constructor].append(
                                                t)
                                            break
                                    else:
                                        raise SetupMalformed(
                                            f"{excluded}(???)??? ?????? ????????? ??? ????????????.")
                            else:
                                raise SetupMalformed(
                                    f"{excluded}(???)??? ?????? ????????? ??? ????????????.")
                    break
            else:
                raise SetupMalformed(f"{from_}(???)??? ?????? ????????? ?????? ????????????.")
        if len(slots) < 5 or len(slots) > 15:
            raise SetupInvalid("????????? 5??? ?????? 15??? ???????????? ?????????.")
        for fighter in competitors:
            enemies = fighter.against()
            for other in competitors:
                found = False
                for against in enemies:
                    if issubclass(other, against):
                        found = True
                        break
                if found:
                    break
            if found:
                break
        else:
            raise SetupInvalid("?????? ????????? ????????????.")
        for constructor in slots:
            if constructor.unique and slots.count(constructor) > 1:
                raise SetupInvalid(f"{constructor.__name__}???(???) ???????????? ?????????.")
        self.formation = slots
        match = {
            roles.Any: roles.Role,
            roles.TownAny: roles.Town,
            roles.MafiaAny: roles.Mafia,
            roles.TriadAny: roles.Triad,
            roles.NeutralAny: roles.Neutral
        }
        self.pool_per_slot = [
            [roles.Mason] if slot is roles.Mason
            else [
                available for _, available in pool
                if roles.is_specific_role(available)
                and issubclass(available, match.get(slot, slot))
                and available not in itertools.chain(*[
                    [
                        excluded for _, excluded in pool
                        if roles.is_specific_role(excluded)
                        and issubclass(excluded, excluded_category)
                    ] for excluded_category in exclusion_with_constructors.get(slot) or []
                ])
            ] for slot in self.formation
        ]
        for index, item in enumerate(self.pool_per_slot):
            slot = self.formation[index]
            slot_name = slot.__name__
            if item == []:
                raise SetupInvalid((
                    f"{index+1}??? ???({slot_name})"
                    f"??? ??????????????? ?????? ??????(???)??? ???????????? ?????? ????????? ????????? ????????? ??? ????????????."
                ))
            if roles.Spy in item and roles.Mafia not in competitors and roles.Triad not in competitors:
                raise SetupInvalid((
                    f"{roles.Spy.__name__}({index+1}??? ??? {slot_name})"
                    f"??? ????????? ????????? ?????????, "
                    f"{roles.Mafia.__name__}??? {roles.Triad.__name__}??? ???????????? ??????????????? ?????????."
                ))
            if roles.Executioner in item and constraints_with_constructors[roles.Executioner][roles.ConstraintKey.TARGET_IS_TOWN]:
                for team in competitors:
                    if issubclass(team, roles.Town):
                        break
                else:
                    raise SetupInvalid(
                        f"{roles.Executioner.__name__}??? ????????? ????????? {roles.Town.__name__} ????????? ????????? ??? ????????????.")
        self.trial()
        self.title = title[:16].strip()
        self.inventor = inventor.username
        self.constraints = constraints_with_constructors
        self.exclusion = exclusion_with_constructors

    def trial(self) -> list[Type[roles.Role]]:
        """?????? ????????? ???????????? ?????? ??????????????? ?????? ????????? ???????????????."""
        return [random.choice(pool) for pool in self.pool_per_slot]

    # @staticmethod
    # def _validate_uniqueness(slot_index: int,
    #                          reduced: list[list[Type[roles.Role]]],
    #                          excepted: list[roles.Role],
    #                          formation: list[str]):
    #     """?????? ????????? unique??? ???????????? ??? `slot_index`??? ?????? ??????????????? ????????? ????????? ???????????????.

    #     ??????????????? ????????? ?????????:
    #         `slot_index`??? ????????? ????????????????????? `unique==True`??? ??? ????????? ?????????,
    #         ??? ????????? `slot_index`??? ????????? ????????? ????????? `slot_index+1`??? ?????? ??????????????? ????????? ????????? ???????????????.

    #     Raises:
    #         `SetupInvalid`: `slot_index`??? ?????? ??????????????? ????????? ?????? ??????.
    #     """
    #     for index, pool in enumerate(reduced):
    #         if not pool:
    #             raise SetupInvalid((
    #                 f"{slot_index+1}??? ???({formation[slot_index]})?????? ????????? ????????? ??? ????????????. "
    #                 f"{'' if slot_index==1 else '1~'}{slot_index}??? ????????? "
    #                 f"??????????????? ?????? ??????({', '.join(map(lambda r: r.__name__, excepted))})"
    #                 f"??? ??? ???????????? ?????????, {slot_index+1}??? ????????? ?????? ????????? ????????? ??? ?????? ?????????. "
    #                 f"????????? ????????? ???????????????."
    #             ))
    #         elif not (roles.Mayor.__name__ in formation and roles.Marshall.__name__ in formation):
    #             if pool == [roles.Mayor] and roles.Marshall in excepted or pool == [roles.Marshall] and roles.Mayor in excepted:
    #                 raise SetupInvalid((
    #                     f"{slot_index+1}??? ??? ({formation[slot_index]})?????? ????????? ????????? ??? ????????????. "
    #                     f"{'' if slot_index==1 else '1~'}{slot_index}??? ????????? "
    #                     f"??????????????? ?????? ??????({', '.join(map(lambda r: r.__name__, excepted))})"
    #                     f"??? ??? ???????????? ?????????, {slot_index+1}??? ????????? ????????? ????????? {pool[0].__name__}?????? ????????????. "
    #                     f"????????? {'Mayor???' if pool==[roles.Mayor] else 'Marshall???'} "
    #                     f"????????? ???????????? ?????? ?????? ?????? ????????? {'Marshall???' if pool==[roles.Mayor] else 'Mayor???'} "
    #                     f"?????? ????????? ??? ????????????. "
    #                     f"Mayor??? Marshall??? ???????????? ?????? ?????????, "
    #                     f"{'' if slot_index==1 else '1~'}{slot_index}??? ?????? ?????? ?????? ????????? ????????? ???????????????."
    #                 ))
    #         for unique in pool:
    #             if unique.unique:
    #                 Setup._validate_uniqueness(
    #                     slot_index+1,
    #                     [
    #                         [role for role in pool if role is not unique]
    #                         for pool in reduced[index+1:]
    #                     ],
    #                     excepted+[unique],
    #                     formation)
    # @staticmethod
    # def _validate_mason_dependency(slot_index: int, reduced: list[list[Type[roles.Role]]], formation: list[str]):
    #     """??????????????? ?????? ????????? ??????(??????, ??????, ?????????)??? ????????? ???????????? ????????????
    #     ??????????????? ?????????????????? ?????? (??? ?????????) ???????????? ???????????????.
    #     """
    #     for index, pool in enumerate(reduced):
    #         for role in pool:
    #             if not issubclass(role, roles.Mason):
    #                 break
    #         else:
    #             raise SetupInvalid((
    #                 "Freemasonry??? Citizen, Cult, Auditor ??? ????????? ???????????? ???????????????. "
    #                 "????????? ??? ????????? Citizen, Cult, Auditor??? ????????? ???????????? ?????? ???????????? "
    #                 f"Freemasonry??? {slot_index+1}??? ???({formation[slot_index]})?????? ????????? ???????????? ?????????."
    #                 "Freemasonry??? ?????? ????????? ??????????????? ????????? ????????? ???????????????."
    #             ))
    #         for unique in pool:
    #             if unique.unique:
    #                 Setup._validate_mason_dependency(slot_index+1, [[role for role in pool if role is not unique] for pool in reduced], formation)

    def jsonablify(self):
        """????????? `JSON`?????? ????????? ??? ?????? `dict` ?????? ???????????????."""
        return {
            "title": self.title,
            "inventor": self.inventor,
            "formation": [slot.__name__ for slot in self.formation],
            "constraints": {
                role.__name__: {
                    key.name if isinstance(key, roles.ConstraintKey) else key:
                    value.name if isinstance(value, roles.Level) else value
                    for key, value in constraint.items()
                }
                for role, constraint in self.constraints.items()
            },
            "exclusion": {
                key.__name__: [slot.__name__ for slot in excluded]
                for key, excluded in self.exclusion.items()
            },
        }


class Room:
    """?????????.

    Attributes:
        Permananent: ????????? ???????????? ????????? ?????? ?????? ????????? ???????????? attributes.
            `host`: ??????.
            `title`: ??????. 10??? ???????????????.
            `capacity`: ??????. 15??? ???????????????.
            `id`: ??? ID.
            `password`: ????????????. ???????????? `None`?????? ??? ?????? ?????? ?????? ????????? ?????????.
            `members`: ????????? `User` ??????.
            `start_requested`: ?????? ???????????? ?????????????????? ??????. ????????? ?????? ws.process_message()??? ???????????????.
            `setup`: ?????? ?????? `Setup` ????????????.
        In-game: ?????? ?????? ??? ??????????????? attributes.
            `role_name_pool`: ?????? ????????? ?????? ??????.
            `lineup_user`: ????????? ????????? `User`.
            `lineup`: ?????? ???????????? ???????????? `Player`???.
            `dead_last_night`: ?????? ??? ?????? ?????????.
            `jail_queue`: ?????? ???. ???????????????(/?????? ???????????? ????????? ?????????) ????????? ???????????????.
            `private_chat`: ?????? ???????????????(?????????, ????????? ???) ?????? ???????????? ??????(????????? ???) ???????????? ??????.
            `graveyard`: ??????.
            `winners`: ?????? ??????.
            `hell`: ????????? ?????????.
            `leavers`: ?????????.
            `day`: ????????? ??????. 1?????? ???????????????.
            `_phase`: ?????? '??????'. ??????, ?????? ??????, ??? ?????? ????????????.
            `skip_votes`: ?????? ?????????.
            `in_court`: ?????? ????????? ??????.
            `in_lynch`: ???????????? ????????? ??????.
            `mayor_reveal_today`: ?????? ????????? ???????????? ??????.
            `executed`: ?????? ????????? ?????? ??????.
            `suiciders`: ?????? ????????? ??????.
            `TIME`: ????????? ????????????.
            `record`: ?????? ??????.
            `submitted_nickname`: ????????? ?????????.
            `there_is`: ????????? ?????????.
    """

    def __init__(self,
                 host: User,
                 title: str,
                 capacity: int,
                 room_id: int,
                 broadcaster: BroadCaster,
                 recording_tasks: list[Task],
                 password: Optional[str] = None):
        self.host = host
        self.members: list[User] = []
        self.title = title[:16].strip()
        self.capacity = capacity
        self.id = room_id
        self.broadcaster = broadcaster
        self.password = password[:8] if password else None
        self.start_requested = False
        self._phase = PhaseType.IDLE
        self.setup: Setup = None
        self.recording_tasks = recording_tasks

    def __repr__(self):
        return f"<Room #{self.id} {len(self.members)}/{self.capacity}{' '+self.phase().name if hasattr(self, '_phase') else ''}>"

    def info(self):
        return {
            "id": self.id,
            "title": self.title,
            "host": self.host.username,
            "members": len(self.members),
            "capacity": self.capacity,
            "phase": self.phase().name,
            "password": self.password is not None
        }

    def full(self):
        return len(self.members) >= self.capacity

    def empty(self):
        return self.members == []

    def remaining(self):
        """????????? `Player`???."""
        return {i: p for i, p in self.lineup.items() if p.alive()}

    async def reveal_identity(self, dead: Player):
        """????????? ????????? ????????? ???????????????.
        `dead.dead_sanitized==True`?????? ?????? ?????? ???????????????.
        """
        content = {"index": dead.index}
        if dead.cause_of_death[-1] == DEMOCRACY:
            content["reason"] = [] if dead.dead_sanitized else dead.cause_of_death
            content["role"] = None if dead.dead_sanitized else dead.role().name
            await self.emit(Event(EventType.IDENTITY_REVEAL, self.members, content))
            await asyncio.sleep(1)
            content["lw"] = None if dead.dead_sanitized else dead.lw
            await self.emit(Event(EventType.IDENTITY_REVEAL, self.members, content))
        else:
            await self.emit(Event(EventType.IDENTITY_REVEAL, self.members, content))
            await asyncio.sleep(3)
            content["reason"] = [] if dead.dead_sanitized else dead.cause_of_death
            await self.emit(Event(EventType.IDENTITY_REVEAL, self.members, content))
            await asyncio.sleep(3)
            content["role"] = None if dead.dead_sanitized else dead.role().name
            await self.emit(Event(EventType.IDENTITY_REVEAL, self.members, content))
            await asyncio.sleep(3)
            content["lw"] = None if dead.dead_sanitized else dead.lw
            await self.emit(Event(EventType.IDENTITY_REVEAL, self.members, content))
        self.graveyard.append(dead)
        await asyncio.sleep(3 if dead.cause_of_death[-1] == DEMOCRACY else 5)

    async def init_game(self, debug_mode: bool):
        """????????? ??????????????????."""
        self.record = []
        logger.info(f"Initiating a game in: {self}")
        self.formation = self.setup.trial()
        self.dead_last_night: list[Player] = []
        self.jail_queue: list[Player] = []
        self.private_chat: dict[Type[roles.Slot], list[Player]] = {
            roles.Mafia: [],
            roles.Triad: [],
            roles.Mason: [],
            roles.Cult: [],
            roles.Spy: [],
        }  # set??? ????????? list??? ?????? ?????? ?????? ??? ?????? teammate??? BOSS/INTERN??? ????????? ?????? ??????.
        # ????????? ??? trigger_evening_events() ??????.
        self.graveyard: list[Player] = []
        self.winners: list[tuple[Player, roles.Role]] = []
        self.hell: list[Player] = []
        self.leavers: list[Player] = []
        self.day = 1
        self.skip_votes = 0
        self.in_court = False
        self.in_lynch = False
        self.mayor_reveal_today = False
        self.election = asyncio.Event()
        self.elected: Optional[Player] = None
        self.executed: list[Player] = []
        self.suiciders: dict[roles.Role, list[Player]] = dict()
        self.TIME = {
            PhaseType.DISCUSSION: 3 if debug_mode else 36,
            PhaseType.VOTE: 3 if debug_mode else 120,
            PhaseType.ELECTION: 3 if debug_mode else 5,
            PhaseType.DEFENSE: 3 if debug_mode else 10,
            PhaseType.VOTE_EXECUTION: 10 if debug_mode else 15,
            PhaseType.LAST_WORDS: 3 if debug_mode else 5,
            PhaseType.EVENING: 3 if debug_mode else 36,
        }
        self.lineup_users = self.members[:]
        if not debug_mode:
            random.shuffle(self.formation)
            random.shuffle(self.lineup_users)
        self.submitted_nickname: dict[User, str] = dict()
        await self.turn_phase(PhaseType.NICKNAME_SELECTION)
        await asyncio.sleep(5 if debug_mode else 30)
        self.lineup = {
            index+1: Player(user,
                            self.submitted_nickname.get(
                                user, str(user.username)+"in-game"),  # TODO: ?????? ?????????
                            index+1,
                            self.formation[index],
                            self.setup.constraints[self.formation[index]],
                            self)
            for index, user in enumerate(self.lineup_users)
        }
        for r in self.lineup.values():
            r.role().set_goal_target()
            r.user.player = r
        await asyncio.gather(*[
            self.emit(Event(EventType.NICKNAME, p.user, {
                "index": p.index,
                "yours": p.nickname,
            })) for p in self.lineup.values()
        ])
        await self.emit(Event(EventType.LINEUP, self.members, {
            "lineup": {i: p.nickname for i, p in self.lineup.items()}
        }))
        await asyncio.sleep(5)
        await asyncio.gather(*[
            self.emit(Event(EventType.EMPLOYED, p, {"WHAT": p.role().name}))
            for p in self.lineup.values()
        ])
        await asyncio.gather(*[
            p.join_private_chat(p.role().__class__.team())
            for p in self.lineup.values()
            if p.role().__class__.team() in self.private_chat
        ])
        await asyncio.gather(*[
            self.emit(Event(EventType.TEAMMATES, teammates, {
                "team": team.__name__,
                "teammates": [{
                    "index": m.index,
                    "role": m.role().name
                } for m in teammates]
            })) for team, teammates in self.private_chat.items()
        ])

    async def run_game(self, debug_mode: bool):
        try:
            await self.init_game(debug_mode)
            logger.info(f"Running a game in: {self}")
        except:
            logger.error(f"GAME TERMINATED IN {self}", exc_info=True)
            content = {
                "type": "BOOM"
            }
            await asyncio.gather(*[u.listen(content) for u in self.members], return_exceptions=True)
            return
        try:
            while True:
                await self.turn_phase(PhaseType.EVENING)
                await self.trigger_evening_events()
                await self.timer(self.phase(), self.TIME[self.phase()])
                await self.turn_phase(PhaseType.NIGHT)
                await self.trigger_night_events()
                # ????????? 5?????? ?????? ?????? ?????????.
                await asyncio.sleep(1 if debug_mode else 5)
                self.day += 1
                for i, r in self.remaining().items():
                    r.extend_action_record()
                # ??????
                self.jail_queue.clear()
                await self.turn_phase(PhaseType.MORNING)
                if self.dead_last_night:
                    await asyncio.sleep(1)
                    number = len(self.dead_last_night)
                    if not self.remaining():
                        word = "all"
                    elif number == 1:
                        word = "one"
                    elif 2 <= number <= 3:
                        word = "some"
                    elif 4 <= number <= 5:
                        word = "many"
                    elif 6 <= number <= 7:
                        word = "toomany"
                    else:
                        word = "most"
                    await self.emit(Event(EventType.NUMBER_OF_DEAD, self.members, {
                        "word": word
                    }))
                    for dead in self.dead_last_night:
                        await self.reveal_identity(dead)
                    self.dead_last_night.clear()
                if self.game_over():
                    break
                # ??????
                await self.turn_phase(PhaseType.DISCUSSION)
                await self.timer(self.phase(), self.TIME[self.phase()])
                # ??????
                self.skip_votes = 0
                self.executed.clear()
                remaining = self.TIME[PhaseType.VOTE]
                while remaining > 0:
                    self.elected = None
                    await self.turn_phase(PhaseType.VOTE)
                    try:
                        began_at = time.time()
                        timer = asyncio.create_task(
                            self.timer(self.phase(), remaining))
                        await asyncio.wait_for(self.election.wait(), remaining)
                    except asyncio.TimeoutError:  # ????????? ????????? ??????.
                        break
                    else:  # ?????? ???????????? ????????? ?????????.
                        if self.skip_votes > len(self.remaining())/2:
                            # TODO: SKIP
                            break
                        remaining -= time.time()-began_at
                        self.elected = max(
                            self.remaining().values(), key=lambda u: u.voted_count)
                        hung = False
                        await self.turn_phase(PhaseType.ELECTION)
                        await self.timer(self.phase(), self.TIME[self.phase()])
                        if self.in_lynch:
                            # TODO
                            hung = True
                        elif self.in_court:
                            # TODO
                            hung = True
                        else:
                            # TODO: ??????????????? ????????? ????????? ?????? ??????
                            await self.turn_phase(PhaseType.DEFENSE)
                            await self.timer(self.phase(), self.TIME[self.phase()])
                            await self.turn_phase(PhaseType.VOTE_EXECUTION)
                            await self.timer(self.phase(), self.TIME[self.phase()])
                            result = {
                                i: voter.execution_choice.value*voter.role().votes
                                for i, voter in self.remaining().items()
                            }
                            await self.emit(Event(EventType.VOTE_EXECUTION_RESULT, self.members, result))
                            await asyncio.sleep(1)
                            if sum(result.values()) > 0:
                                await self.turn_phase(PhaseType.LAST_WORDS)
                                await self.timer(self.phase(), self.TIME[self.phase()])
                                hung = True
                        if hung:
                            if self.elected.role().belongs_to(roles.Jester):
                                self.elected.win()
                                pool = [
                                    r
                                    for i, r in self.remaining().items()
                                    if r.has_voted_to is self.elected
                                    or r.execution_choice is VoteType.GUILTY
                                ]
                                if self.elected.role().constraints[roles.ConstraintKey.VICTIMS] == "ONE":
                                    self.suiciders[self.elected.role()] = random.choice(
                                        pool)
                                else:
                                    self.suiciders[self.elected.role()] = pool
                            await self.elected.die(DEMOCRACY)
                            self.executed.append(self.elected)
                            if not self.in_lynch or len(self.executed) >= self.setup.constraints[roles.Marshall][roles.ConstraintKey.QUOTA_PER_LYNCH]:
                                break
                    finally:
                        with suppress(asyncio.CancelledError):
                            timer.cancel()
                            await timer
                        for i, r in self.remaining().items():
                            r.voted_count = 0
                            r.has_voted_to = None
                            r.execution_choice = VoteType.ABSTENTION
                        self.election.clear()
                        self.elected = None
                        for i, m in self.remaining().items():
                            if (m.role().belongs_to(roles.Counsel)
                                and m.role().goal_target.intersection(self.executed)
                                    and m.role().constraints[roles.ConstraintKey.IF_FAIL] == "SUICIDE"):
                                self.suiciders[m.role()] = [m]
                await self.turn_phase(PhaseType.POST_EXECUTION)
                for e in self.executed:
                    await self.reveal_identity(e)
                self.in_court = self.in_lynch = False
                if self.game_over():
                    break
            await self.finish_game()
        except:
            logger.error(f"GAME TERMINATED IN {self}", exc_info=True)
            content = {
                "type": "BOOM"
            }
            await asyncio.gather(*[u.listen(content) for u in self.members], return_exceptions=True)
        else:
            logger.info(f"A game finished in: {self}")
        finally:
            self.recording_tasks.append(
                asyncio.create_task(db.archive(GameData(self))))
            for r in self.members:
                if r.player in self.lineup.values():
                    r.player = None
            await self.emit(Event(EventType.BACK_TO_IDLE, self.members, {"members": [u.username for u in self.members]}, no_record=True))
            await self.turn_phase(PhaseType.IDLE)

    async def finish_game(self):
        await self.turn_phase(PhaseType.FINISHING)
        logger.info(f"Finishing a game in: {self}")
        main_winner = None
        win_alone = False
        citizen_tie = False
        if len(self.remaining()) == 2:
            for r in self.remaining().values():
                if r.role().belongs_to(roles.Citizen):
                    self.win_them_all(roles.Town, True)
                    main_winner = roles.Town
                    citizen_tie = True
                    break
        if not citizen_tie:
            priority = (
                roles.Arsonist,
                roles.SerialKiller,
                roles.MassMurderer,
                roles.Triad,
                roles.Mafia,
                roles.Cult
            )
            for category in priority:
                if self.there_is[category]:
                    self.win_them_all(category, not issubclass(
                        category, roles.NeutralKilling))
                    main_winner = category
                    break
            else:
                if self.there_is[roles.Town]:
                    self.win_them_all(roles.Town, True)
                    main_winner = roles.Town
            self.win_them_all(roles.NeutralEvil, False)
        self.win_them_all(roles.Survivor, False)
        self.win_them_all(roles.Amnesiac, False)
        for i, m in self.lineup.items():
            with suppress(KeyError):
                if (
                    m.alive()
                    and m.role().belongs_to(roles.Executioner)
                    and m.user in self.members
                    and DEMOCRACY in m.role().goal_target.pop().cause_of_death
                ):
                    m.win()
        if main_winner is None and self.winners:
            def _solo_priority(role: roles.Role):
                if role.belongs_to(roles.Scumbag):
                    return 0
                if role.belongs_to(roles.Witch):
                    return 1
                if role.belongs_to(roles.Judge):
                    return 2
                if role.belongs_to(roles.Auditor):
                    return 3
                if role.belongs_to(roles.Executioner):
                    return 4
                if role.belongs_to(roles.Jester):
                    return 5
                if role.belongs_to(roles.Survivor):
                    return 6
                if role.belongs_to(roles.Amnesiac):
                    return 7
            first_winner: Player = sorted(
                self.winners, key=lambda u: _solo_priority(u[1]))[0]
            win_alone = len(self.winners) == 1 and len(list(itertools.filterfalse(lambda t: first_winner.role().belongs_to(t), {
                roles.Town,
                roles.Mafia,
                roles.Triad,
                roles.Cult
            }))) == 4  # ????????? ??? ??? ????????????, ?????? ?????? ??????
            main_winner = (
                first_winner.role().__class__
                if first_winner.role().__class__.team() in {roles.NeutralBenign, roles.NeutralEvil}
                else first_winner.role().__class__.team()
            )
        content = {"end statement": True}
        await self.emit(Event(EventType.FINISH, self.members, content))
        await asyncio.sleep(1)
        content = {
            "main_winner": main_winner.__name__ if main_winner else None,
            "win_alone": win_alone
        }
        await self.emit(Event(EventType.FINISH, self.members, content))
        await asyncio.sleep(1)
        for player, role in sorted(self.winners, key=lambda pair: pair[0].index):
            content = {
                "index": player.index,
                "role": role.name
            }
            await self.emit(Event(EventType.FINISH, self.members, content))
            await asyncio.sleep(1)

    def get_room_ingame_info(self):
        return {
            "id": self.id,
            "title": self.title,
            "host": self.host.username,
            "private": self.password is not None,
            "capacity": self.capacity,
            "setup": self.setup.jsonablify() if self.setup else self.setup,
            "phase": self.phase().name,
            "members": [m.username for m in self.members],
            "lineup": {i: m.nickname for i, m in self.lineup.items()} if self.in_game() else None,
            "graveyard": [p.index for p in self.graveyard] if self.in_game() else None
        }

    def in_game(self):
        return self.phase() is not PhaseType.IDLE

    def game_over(self) -> bool:
        remaining = self.remaining().values()
        self.there_is = {
            roles.Town: [T for T in remaining if T.role().belongs_to(roles.Town)],
            roles.Mafia: [M for M in remaining if M.role().belongs_to(roles.Mafia)],
            roles.Triad: [T for T in remaining if T.role().belongs_to(roles.Triad)],
            roles.Arsonist: [N for N in remaining if N.role().belongs_to(roles.Arsonist)],
            roles.SerialKiller: [SK for SK in remaining if SK.role().belongs_to(roles.SerialKiller)],
            roles.MassMurderer: [MM for MM in remaining if MM.role().belongs_to(roles.MassMurderer)],
            roles.Cult: [C for C in remaining if C.role().belongs_to(roles.Cult)],
            roles.NeutralEvil: [NE for NE
                                in remaining
                                if NE.role().belongs_to(roles.NeutralEvil)
                                and not NE.role().belongs_to(roles.NeutralKilling)
                                and not NE.role().belongs_to(roles.Cult)],  # ?????? ?????? ?????? ?????????.
        }
        there_is_NK = self.there_is[roles.Arsonist] + \
            self.there_is[roles.SerialKiller]+self.there_is[roles.MassMurderer]
        if len(remaining) < 3:
            return True
        if self.there_is[roles.Town]:
            # ????????? ?????????
            return list(self.there_is.values()).count([]) == len(self.there_is) - 1
        if self.there_is[roles.Mafia]:
            return not self.there_is[roles.Triad] and not self.there_is[roles.Cult] and not there_is_NK
        if self.there_is[roles.Triad]:
            return not self.there_is[roles.Cult] and not there_is_NK
        if self.there_is[roles.Cult]:
            return not there_is_NK
        if there_is_NK:
            # ????????? ???????????? 3?????? ????????? ????????????
            return len({NK.role().__class__.team() for NK in there_is_NK}) < 3
        return True  # ???????????? ????????????

    def win_them_all(self, category: Union[Type[roles.Slot], Type[roles.Role]], include_dead: bool):
        """????????? `category`??? ????????? `Player`?????? ??????????????????.
        `include_dead==True`?????? ?????? `Player`?????? ???????????????.
        ?????? ?????? ?????? `Player`??? ???????????? ????????????."""
        for i, m in self.lineup.items() if include_dead else self.remaining().items():
            if m.role().belongs_to(category) and m.user in self.members:
                m.win()

    async def trigger_evening_events(self):
        converting_coros = []
        INTERN = 0
        BOSS = 1
        match: dict[Type[roles.Slot], dict[str, Type[roles.Role]]] = {
            roles.Mafia: {INTERN: roles.Mafioso, BOSS: roles.Godfather},
            roles.Triad: {INTERN: roles.Enforcer, BOSS: roles.DragonHead},
        }
        for i, r in self.remaining().items():
            if r.role().belongs_to(roles.MasonLeader):
                break
        else:
            for i, r in self.remaining().items():
                if r.role().belongs_to(roles.Mason):
                    converting_coros.append(r.be(roles.MasonLeader(
                        r, self.setup.constraints[roles.MasonLeader])))
                    break
        for criminals in {roles.Mafia, roles.Triad}:
            if team := self.private_chat[criminals]:
                for C in team:
                    if C.role().belongs_to(roles.KillingVisiting) and C.role().opportunity > 0:
                        break
                else:
                    for C in team:
                        if C.role().belongs_to(roles.IdentityInvestigating) and C.role().constraints[roles.ConstraintKey.PROMOTED]:
                            converting_coros.append(C.be(match[criminals][BOSS](
                                C, self.setup.constraints[match[criminals][BOSS]])))
                            break
                    else:
                        promoted = self.private_chat[criminals][0]
                        converting_coros.append(promoted.be(match[criminals][INTERN](
                            promoted, self.setup.constraints[match[criminals][INTERN]])))
        converting_coros.extend(
            counsel.be(roles.Scumbag(
                counsel, self.setup.constraints[roles.Scumbag]))
            for counsel in self.remaining().values()
            if counsel.role().belongs_to(roles.Counsel)
            and r.role().goal_target.intersection(self.executed)
        )
        await asyncio.gather(*converting_coros)
        if not self.executed:  # ????????? ?????? ????????? ?????? ??????.
            for jailor in self.jail_queue:
                if not jailor.jailed_by:
                    if jailor.role().want_to_jail.jailed_by:
                        pass  # TODO
                    else:
                        for m, data in jailor.role().jail(jailor.role().want_to_jail)[roles.AbilityResultKey.INDIVIDUAL].items():
                            await self.emit(Event(EventType.ABILITY_RESULT, m, jsonablify(data)))
        await self.emit(Event(EventType.ABILITY_RESULT, [s for s in self.remaining().values() if s.role().belongs_to(roles.Survivor)], {
            "ROLE": roles.Survivor.__name__,
            "EVENING": True,
            "REMAINING": list({m.role().name for m in self.remaining().values()})
        }))
        await self.emit(Event(EventType.ABILITY_RESULT, [am for am in self.remaining().values() if am.role().belongs_to(roles.Amnesiac)], {
            "ROLE": roles.Amnesiac.__name__,
            "EVENING": True,
            "POOL": [dead.index for dead in self.graveyard if not dead.role().unique]
        }))
        await self.emit(Event(EventType.ABILITY_RESULT, [ar for ar in self.remaining().values() if ar.role().belongs_to(roles.Arsonist)], {
            "ROLE": roles.Arsonist.__name__,
            "EVENING": True,
            "OILED": [i for i, m in self.remaining().items() if m.oiled]
        }))

    async def trigger_night_events(self):
        self.actors_today = self.remaining().values()
        INACTIVE = "INACTIVE"
        SUICIDE = "SUICIDE"
        priority: tuple[roles.Role] = (
            # ?????? ??????
            roles.Survivor,
            roles.Citizen,
            # ??????
            roles.Witch,
            # ?????? ????????? ??????????????? ???????????? ??????????????? ????????? ????????? ?????????.
            INACTIVE,
            # ?????? ?????? ?????? ????????? ?????? ??????
            roles.Escort,
            roles.Consort,
            roles.Liaison,
            # ?????? ?????? ?????? ????????? ??????
            roles.Beguiler,
            roles.Deceiver,
            # ?????? ????????? ?????? ?????????.
            roles.Framer,
            roles.Forger,
            roles.Arsonist,  # ?????????
            roles.Doctor,
            roles.WitchDoctor,  # ??????
            roles.Bodyguard,
            # ?????? ??????.
            roles.Veteran,
            roles.Jailor,
            roles.Kidnapper,
            roles.Interrogator,
            roles.Vigilante,
            roles.Mafioso,
            roles.Godfather,
            roles.Enforcer,
            roles.DragonHead,
            roles.SerialKiller,
            roles.Arsonist,  # ??????
            roles.MasonLeader,  # ????????? ??????
            roles.MassMurderer,
            roles.Witch,  # ??????
            SUICIDE,
            # ?????? ??????
            roles.Janitor,
            roles.IncenseMaster,
            # ??????
            roles.Coroner,
            roles.Detective,
            roles.Lookout,
            roles.Sheriff,
            roles.Consigliere,
            roles.Administrator,
            roles.Agent,
            roles.Vanguard,
            # TODO: Disguiser, Informant
            roles.Spy,
            roles.Investigator,
            roles.Auditor,
            roles.MasonLeader,  # ??????
            roles.Cultist,
            roles.WitchDoctor,  # ??????
            roles.Godfather,  # ??????
            roles.DragonHead,  # ??????
            roles.Amnesiac,
            roles.Blackmailer,
            roles.Silencer,
        )
        done: set[Type[roles.Role]] = set()
        worked_roles: set[roles.Role] = set()
        for role in priority:
            if role == SUICIDE:
                self.suiciders.update({
                    "will": actor
                    for actor in self.actors_today
                    if actor.will_suicide
                })
                for trigger, suiciders in self.suiciders.items():
                    for s in suiciders:
                        if s.is_healed():
                            for m, data in s.healed_by.pop().heal_against(SUICIDE):
                                await self.emit(Event(EventType.ABILITY_RESULT, m, data))
                        else:
                            await self.emit(Event(EventType.SOUND, self.members, {roles.AbilityResultKey.SOUND.name: SUICIDE}))
                            await s.die(trigger if isinstance(trigger, str) else trigger.name)
                            await asyncio.sleep(1)
                for left in self.leavers:
                    await self.emit(Event(EventType.SOUND, self.members, {roles.AbilityResultKey.SOUND.name: SUICIDE}))
                    await left.die("leave")  # ?????? ??????
                self.leavers.clear()
                self.suiciders.clear()
            else:
                if role == INACTIVE:
                    actors_for_this_priority = [
                        actor
                        for actor in self.remaining().values()
                        if not actor.role().belongs_to(roles.Visiting)
                        and not actor.role().belongs_to(roles.ActiveOnly)
                    ]
                elif issubclass(role, roles.Killing):
                    actors_for_this_priority = [
                        actor
                        for actor in self.actors_today
                        if actor.role().belongs_to(role)
                        and not (
                            actor.role().belongs_to(roles.KillingVisiting)
                            and actor.visits[self.day]
                            and actor.visits[self.day].role().belongs_to(roles.Veteran)
                            and actor.visits[self.day].act[self.day]
                        )
                    ]
                else:
                    actors_for_this_priority = [
                        actor
                        for actor in self.remaining().values()
                        if actor.role().belongs_to(role)
                    ]
                for actor in actors_for_this_priority:
                    # TODO: ActiveAndVisiting ??????
                    events = None
                    if role in done:
                        if actor.role().do_second_task_today:
                            events = actor.role().second_task(self.day)
                    elif actor.visits[self.day] or actor.act[self.day]:
                        if determined := actor.visits[self.day]:
                            if actor.role().opportunity is not None and actor.role().opportunity <= 0:  # ????????? ????????? ??????????????? ???????????????
                                events = roles.Visiting.visit(
                                    actor.role(), self.day, determined)
                            else:
                                events = actor.role().visit(self.day, determined)
                        else:
                            events = actor.role().act(self.day)
                    else:
                        events = actor.role().action_when_inactive(self.day)
                    if not events:
                        continue
                    for e in events if isinstance(events, list) else [events]:
                        if sound := e.get(roles.AbilityResultKey.SOUND):
                            affected = e[roles.AbilityResultKey.INDIVIDUAL].keys()
                            listening = set(self.members).difference(
                                {p.user for p in affected})
                            await asyncio.gather(*[self.emit(Event(EventType.SOUND, m, {
                                roles.AbilityResultKey.SOUND.name: sound if isinstance(sound, str) else sound.__name__,
                                roles.AbilityResultKey.LENGTH.name: e.get(roles.AbilityResultKey.LENGTH),
                                "data": jsonablify(e[roles.AbilityResultKey.INDIVIDUAL][m])
                            })) for m in affected] + [self.emit(Event(EventType.SOUND, listening, {
                                roles.AbilityResultKey.SOUND.name: sound if isinstance(sound, str) else sound.__name__,
                                roles.AbilityResultKey.LENGTH.name: e.get(roles.AbilityResultKey.LENGTH),
                            }))])
                            await asyncio.sleep(1)
                        for m, data in e[roles.AbilityResultKey.INDIVIDUAL].items():
                            result_type = data.get(roles.AbilityResultKey.TYPE)
                            if result_type is roles.AbilityResultKey.KILLED:
                                await m.die(
                                    data[roles.AbilityResultKey.BY]
                                    if isinstance(data[roles.AbilityResultKey.BY], str)
                                    else data[roles.AbilityResultKey.BY].__name__
                                )
                            elif result_type is roles.AbilityResultKey.CONVERTED:
                                await m.be(data[roles.AbilityResultKey.INTO](m, self.setup.constraints[data[roles.AbilityResultKey.INTO]]), jsonablify(data))
                                if data.get("notes") is roles.Amnesiac and m.visits[self.day].role().opportunity is not None:
                                    m.role().opportunity = m.visits[self.day].role(
                                    ).opportunity or 1
                            else:
                                await self.emit(Event(EventType.ABILITY_RESULT, m, jsonablify(data)))
                        worked_roles.add(actor.role())
                done.add(role)
        await asyncio.gather(*[
            self.emit(Event(EventType.ABILITY_RESULT, spy, jsonablify(
                spy.role().after_night()[roles.AbilityResultKey.INDIVIDUAL][spy])))
            for spy in self.private_chat[roles.Spy]
        ])
        for worked in worked_roles:
            worked.after_night()
        for jailor in self.actors_today:
            if jailor.role().belongs_to(roles.Jailing) and jailor.role().is_jailing():
                jailor.role().after_night()
        for exe in self.remaining().values():
            if exe.role().belongs_to(roles.Executioner) and list(exe.role().goal_target)[0] in self.dead_last_night:
                await exe.be(roles.Jester(exe, self.setup.constraints[roles.Jester]))

    async def timer(self, of: PhaseType, for_: Union[float, int]):
        wake_at = (60, 30, 10, 5, 0)
        for sec in wake_at:
            if for_ > sec:
                await asyncio.sleep(for_-sec)
                if sec != 0:
                    await self.emit(Event(EventType.TIME, self.members, content={
                        ContentKey.PHASE.name: of.name,
                        ContentKey.TIME.name: sec,
                    }))
                    for_ = sec

    def phase(self):
        return self._phase

    async def turn_phase(self, into: PhaseType):
        """`into` phase??? ???????????????."""
        self._phase = into
        await self.emit(Event(EventType.PHASE, self.members, {
            ContentKey.PHASE.name: into.name,
            ContentKey.WHO.name:
                self.elected.index
                if self.in_game() and self.phase() is not PhaseType.INITIATING and self.elected
                else None,
        }, no_record=into is PhaseType.INITIATING or into is PhaseType.IDLE))
        await self.broadcaster.room_status_change(self)

    def find_player_by_index(self, index: int):
        """`index`??? ??????????????? ???????????????."""
        return self.lineup[index]

    async def submit_nickname(self, user: User, nickname: str):
        self.submitted_nickname[user] = nickname
        await self.emit(Event(EventType.NICKNAME_CONFIRMED, self.members, {"nickname": nickname}))

    async def emit(self, e: Event):
        """???????????? ????????? ???????????????.
        `emit()`??? ????????? `e`??? ????????? ????????? ???????????? ?????????,
        ?????? ???????????? ???????????? ?????? ???????????? ???????????? ???????????? ??????
        ???????????? `emit()`??? ???????????? ????????? ????????????.
        """
        if self.in_game() and not e.no_record:
            data = {
                "type": e.type.name,
                "content": e.content,
                "from": e.from_.username if e.from_ else None,  # TODO: username??? unique id??? ??????
                "to": [
                    m.username
                    if isinstance(m, User)
                    else m.user.username
                    for m in e.to
                ],  # TODO: username??? unique id??? ??????
                "time": time.time()
            }
            self.record.append(data)
        await asyncio.gather(*[member.listen({
            "type": e.type.name,
            "content": e.content,
        }) for member in e.to])


class GameData:
    """?????? ???????????????. ?????????????????? ???????????????."""

    def __init__(self, room: Room):
        self.title = room.title
        self.private = room.password is not None
        self.lineup = room.lineup
        self.setup = room.setup
        self.record = room.record[:]
        self.rank_mode = False  # TODO


class User:
    """?????? ????????????.

    Attributes:
        `username`: ????????????.
        `ws`: ??? `User`??? ????????? `WebSocket`.
        `existing`: ?????? ?????? ??????. ??? ???????????? ?????? ????????? ???????????? ?????? `User` ??????????????? `existing=True`??? ???????????????.
        `room`: ?????? ?????? `Room`.
        `player`: ?????? ????????? `Player`.
    """

    def __init__(self, username: str, ws: WebSocket):
        self.username = username
        # TODO: self.id
        self.ws = ws
        self.existing = False
        self.room: Room = None
        self.in_game = False
        self.player: Player = None

    def __repr__(self):
        return f"<User [{self.username}]>"

    def __eq__(self, other: User):
        if isinstance(other, User):
            return self.username == other.username
        return NotImplemented

    def __hash__(self):
        return self.username  # TODO

    async def enter(self, room: Room):
        self.room = room
        room.members.append(self)
        logger.debug(f"{self.username} enters {room}")
        room_info = room.get_room_ingame_info()
        if room.in_game():
            room.hell.append(self)
        enter_notice = {"who": self.username}  # TODO: unique ID??? ?????????
        await room.emit(Event(EventType.GAME_INFO, self, jsonablify(room_info)))
        await room.emit(Event(EventType.ENTER, room.members, enter_notice))
        await self.room.broadcaster.room_status_change(self.room)

    async def leave(self):
        """?????? ????????????. ??? ?????? `user.room`?????? ?????? ????????? ??? ????????????.
        ?????? ??? ????????? ??? ???????????? ???????????????.
        ????????? ???????????? ?????? ????????? ???????????? ?????? ??? ????????? ????????? `leave()`??? ???????????? ????????? ????????????.
        """
        left = self.room
        self.room.members.remove(self)
        if self is left.host and not left.empty():
            left.host = left.members[0]
            logger.debug(f"{left.host} now hosts {left}.")
            # TODO: announce new host
        if self.player:
            if self.player.alive():
                logger.warning(f"{self} left {left} alive")
                left.leavers.append(self)
                await left.emit(Event(EventType.LEAVE, left.members, {"index": self.player.index}))
            else:
                left.hell.remove(self)
            self.player = None
        else:
            await left.emit(Event(EventType.LEAVE, left.members, {"who": self.username}))
        self.room = None
        logger.debug(f"{self} leaves room #{left.id}")
        await left.broadcaster.room_status_change(left)

    async def speak(self, msg: str):
        """`msg`??? ???????????? ?????? ??????, `/`??? ???????????? ??????????????? ???????????? ???????????????.
        `\\n`??? ?????? ?????? ????????? ??? ?????? ??????(`" "`)?????? ???????????????. ?????? ?????? ????????? ???????????? ???????????????.
        `msg`??? ???????????? ?????? `msg = msg[:128].strip()`??? ?????? ????????????."""
        msg = msg[:128].strip()  # ?????? ?????????
        for c in string.whitespace:
            msg = msg.replace(c, " ")
        msg = msg.strip()
        if not msg:
            return
        room = self.room
        if room.in_game():
            event = None
            if room.phase() is PhaseType.NICKNAME_SELECTION:
                if is_command(msg, Command.NICKNAME):
                    nickname = " ".join(msg.split()[1:])
                    if len(re.findall("[???-???]|[a-z]|[A-Z]|[0-9]", nickname)) == len(nickname) and 1 <= len(nickname) <= 8:
                        await room.submit_nickname(self, nickname)
            elif self.player in room.lineup.values():
                event = await self.player.speak(msg)
            else:
                name = self.username
                content = {
                    ContentKey.FROM: name,
                    ContentKey.MESSAGE: msg,
                    "hell": True
                }
                event = Event(EventType.MESSAGE, room.hell,
                              jsonablify(content), self)
            if event:
                if not isinstance(event, list):
                    event = [event]
                await asyncio.gather(*[room.emit(e) for e in event])
        else:
            if is_command(msg, Command.SLASH):
                pass
            else:
                content = {ContentKey.FROM: self.username,
                           ContentKey.MESSAGE: msg}
                await room.emit(Event(EventType.MESSAGE, room.members, content, self))
                logger.debug(f"[{room.id}] {self.username}: {msg}")

    async def listen(self, data: dict):
        try:
            await self.ws.send_json(data)
        except TypeError:  # JSON ?????? ??????
            raise
        # ?????? ??????. ????????? ?????? ws_endpoint??? finally?????? ??????????????? ?????? ?????????.
        except (RuntimeError, ConnectionClosed):
            pass


class Player:
    """????????? ????????????. ????????? ????????????."""

    def __init__(self,
                 user: User,
                 nickname: str,
                 index: int,
                 role: Type[roles.Role],
                 constraints: dict,
                 room: Room):
        self.user = user
        self.index = index
        self.nickname = nickname
        self.room = room
        self._role_record: list[Union[roles.Role, roles.Slot]] = [
            role(self, constraints)]
        self.has_left = False
        self.lw = ""
        self.crimes = {c: False for c in CrimeType}
        self.visits: list[Union[None, Player]] = [None, None]
        self.visited_by: list[set[Player]] = [None, set()]
        self.bodyguarded_by: list[Player] = []
        self.healed_by: list[Player] = []
        self.act: list[bool] = [False, False]
        self.oiled = False
        self.is_behind: Player = None
        self.has_voted_to: Player = None
        self.has_voted_to_skip = False
        self.voted_count = 0
        self.execution_choice = VoteType.ABSTENTION
        self.will_suicide = False
        self.jailed_by: Player = None
        self.controlled_by: Player = None
        self.framed: dict = dict()
        self.blackmailed_on = 0
        self.cause_of_death = []
        self.dead_sanitized = False

    def __repr__(self) -> str:
        return f"<{self.user}'s Player #{self.index} as {self.role()} {'alive' if self.alive() else 'dead'}"

    def alive(self):
        return self.cause_of_death == []

    def role(self):
        return self._role_record[-1]

    def is_healed(self):
        return self.role().healable and self.healed_by

    def death_announced(self):
        return self in self.room.graveyard

    async def join_private_chat(self, group: Type[roles.Role]):
        self.room.private_chat[group].append(self)

    async def leave_private_chat(self, group: Type[roles.Role]):
        self.room.private_chat[group].remove(self)

    async def be(self, role: Type[roles.Role], constraints: dict):
        """`role`??? ???????????????. ?????? ?????? ????????? ??????????????? ?????? ???????????? ???????????????."""
        existing_group = False
        if self._role_record:
            for group, members in self.room.private_chat.items():
                if self.role().belongs_to(group) and not issubclass(role, group):
                    await self.leave_private_chat(group)
                    if group is not roles.Spy:
                        existing_group = group
                    break
        for group, members in self.room.private_chat.items():
            if issubclass(role, group):
                await self.join_private_chat(group)
                break
        self._role_record.append(role(self, constraints))
        self.role().set_goal_target()
        content = {
            ContentKey.WHAT: self.role().name,
            ContentKey.OPPORTUNITY: self.role().opportunity,
            ContentKey.GOAL_TARGET: sorted(
                [p.index for p in self.role().goal_target]) or None
        }
        if existing_group:
            for_team = {
                ContentKey.WHAT: self.role().name,
                ContentKey.WHO: self.index,
            }
            await asyncio.gather(*[
                self.room.emit(
                    Event(EventType.EMPLOYED, self, jsonablify(content))),
                self.room.emit(
                    Event(EventType.EMPLOYED, self.room.private_chat[existing_group], for_team))
            ])
        else:
            await self.room.emit(Event(EventType.EMPLOYED, self, jsonablify(content)))

    async def listen(self, data: dict):
        if not self.has_left:
            await self.user.listen(data)

    async def vote(self, voted: Union[Player, VoteType]):
        if self.room.phase() is PhaseType.VOTE_EXECUTION:
            self.execution_choice = voted
            await self.room.emit(Event(EventType.VOTE, self.room.members, {
                "index": self.index
            }))
        else:
            if voted is VoteType.SKIP:
                self.room.skip_votes += self.role().votes
            else:
                voted.voted_count += self.role().votes
                self.has_voted_to = voted
            await asyncio.gather(*[self.room.emit(Event(EventType.VOTE, self.room.members, {
                "court": self.room.in_court,
                "index": None if self.room.in_court else self.index,
                "skip_count": self.room.skip_votes
            }))]*self.role().votes)
            if (
                self.room.skip_votes > len(self.room.remaining()) / 2
                or voted.voted_count > len(self.room.remaining()) / 2
            ):
                self.room.election.set()

    async def cancel_vote(self, skip=False):
        """????????? ???????????????. `skip==True`??? ?????? ????????? ???????????????."""
        if self.room.phase() is PhaseType.VOTE_EXECUTION:
            await self.vote(VoteType.ABSTENTION)
        else:
            if skip:
                self.has_voted_to = False
                self.room.skip_votes -= self.role().votes
            else:
                self.has_voted_to.voted_count -= self.role().votes
                self.has_voted_to = None
            await asyncio.gather(*[self.room.emit(Event(EventType.VOTE, self.room.members, {
                "court": self.room.in_court,
                "index": None if self.room.in_court else self.index,
                "skip_count": self.room.skip_votes
            }))]*self.role().votes)

    async def die(self, cause: str):
        logger.debug(f"{self} dies in {self.room}")
        self.cause_of_death.append(cause)
        await self.room.emit(Event(EventType.DEAD, self, {"cause": cause}))

    def win(self):
        self.room.winners.append((self, self.role()))

    def commit_crime(self, crime: CrimeType):
        self.crimes[crime] = True

    def write_lw(self, lw: str):
        self.lw = lw

    async def speak(self, msg: str):
        room = self.room
        event = None
        if self.blackmailed_on == room.day:
            if is_command(msg, Command.SLASH):
                if is_command(msg, Command.SUICIDE):
                    self.will_suicide = not self.will_suicide
                    event = self._make_event(EventType.SUICIDE, self, {
                                             ContentKey.WILL: self.will_suicide})
                elif is_command(msg, Command.VISIT):
                    pass  # TODO
            else:
                event = self._make_event(EventType.ERROR, self, {
                                         ContentKey.REASON: "???????????? ?????? ??? ??? ????????????."})
        else:
            phase = room.phase()
            if phase is PhaseType.MORNING:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(
                            int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.JAIL) and self.role().belongs_to(roles.Jailing):
                        jailed = room.find_player_by_index(int(msg.split()[1]))
                        if jailed is not self:
                            event = self._make_jail_event(jailed, True)
                else:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.DISCUSSION:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(
                            int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.COURT) or is_command(msg, Command.LYNCH) or is_command(msg, Command.MAYOR):
                        if self.role().can_activate():
                            event = self.role().activate()
                    elif is_command(msg, Command.JAIL) and self.role().belongs_to(roles.Jailing):
                        jailed = room.find_player_by_index(int(msg.split()[1]))
                        if jailed is not self:
                            event = self._make_jail_event(jailed, True)
                else:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.VOTE:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.SKIP):
                        if self.has_voted_to_skip:
                            await self.cancel_vote(skip=True)
                        else:
                            await self.vote(VoteType.SKIP)
                    elif is_command(msg, Command.VOTE) and self.role().votes > 0:
                        voted = room.find_player_by_index(int(msg.split()[1]))
                        if voted is not self:
                            await self.vote(voted)
                    elif is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(
                            int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.COURT) and self.role().can_activate():
                        if self.has_voted_to is None:
                            event = self.role().activate()
                        else:
                            event = self._make_event(EventType.ERROR, self, {
                                ContentKey.REASON.name: "????????? ????????? ?????? ?????? ?????? ?????????. ?????? ???????????? ?????? ??????????????? ????????? ??? ????????????."
                            })
                    elif is_command(msg, Command.LYNCH) and self.role().can_activate():
                        event = self.role().activate()
                    elif is_command(msg, Command.MAYOR) and self.role().can_activate():
                        if self.has_voted_to is None:
                            event = self.role().activate()
                        else:
                            event = self._make_event(EventType.ERROR, self, {
                                ContentKey.REASON.name: "????????? ????????? ?????? ?????? ?????? ?????????. ?????? ???????????? ?????? ??????????????? ????????? ??? ????????????."
                            })
                    elif is_command(msg, Command.JAIL) and self.role().belongs_to(roles.Jailing):
                        jailed = room.find_player_by_index(int(msg.split()[1]))
                        if jailed is not self:
                            event = self._make_jail_event(jailed, True)
                else:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.DEFENSE:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.JAIL) and self.role().belongs_to(roles.Jailing):
                        event = self._make_jail_event(
                            room.find_player_by_index(int(msg.split()[1])))
                elif room.elected is self:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.VOTE_EXECUTION:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(
                            int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.MAYOR) and self.role().can_activate():
                        event = self.role().activate()
                    elif is_command(msg, Command.JAIL) and self.role().belongs_to(roles.Jailing):
                        jailed = room.find_player_by_index(int(msg.split()[1]))
                        if jailed is not self:
                            event = self._make_jail_event(jailed, True)
                    elif (is_command(msg, Command.GUILTY) or is_command(msg, Command.INNOCENT)) and self.role().votes > 0:
                        await self.vote(VoteType.GUILTY if is_command(msg, Command.GUILTY) else VoteType.INNOCENT)
                    elif is_command(msg, Command.ABSTENTION) and self.role().votes > 0:
                        await self.cancel_vote()
                else:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.LAST_WORDS and room.elected is self:
                event = self.make_message_event(msg)
            elif phase is PhaseType.POST_EXECUTION and not room.in_court and not room.in_lynch:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(
                            int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.MAYOR) and self.role().can_activate():
                        pass  # TODO
                else:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.EVENING:
                if is_command(msg, Command.SLASH):
                    if self.jailed_by:
                        if is_command(msg, Command.SUICIDE):
                            pass
                    # ???????????? ?????? ??? ?????? ???????????? ?????????
                    elif room.day <= self.role().rest_till:
                        content = {ContentKey.ROLE: self.role(
                        ).name, ContentKey.REASON: f"{self.role().rest_till}?????? ????????? ????????? ?????????."}
                        event = self._make_event(
                            EventType.ERROR, self, content)
                        # ??? ???????????? DELAY??? ????????? ?????? ??????.
                    elif is_command(msg, Command.VISIT) and self.role().belongs_to(roles.Visiting) and (self.role().opportunity is None or self.role().opportunity > 0):
                        splitted = msg.split()
                        if len(splitted) == 1:
                            target_index = None
                        elif len(splitted) == 2:
                            target_index = int(splitted[1])
                        else:
                            target_index, second_index = map(
                                int, splitted[1:3])
                        target = room.find_player_by_index(target_index)
                        if self.role().for_dead:
                            if target.death_announced():
                                if self.role().belongs_to(roles.Amnesiac) and target.role().unique:
                                    pass
                                else:
                                    event = self.visit_and_make_visit_event(
                                        target)
                        else:
                            if self.role().belongs_to(roles.Witch):
                                if second_target := room.find_player_by_index(second_index):
                                    event = self.visit_and_make_visit_event(
                                        target, second_target)
                            elif self.role().belongs_to(roles.Visiting) and not self.role().for_dead:
                                if target is self:
                                    if self.role().can_target_self:
                                        event = self.visit_and_make_visit_event(
                                            target)
                                elif (self.role().belongs_to(roles.KillingVisiting)
                                      and room.private_chat.get(self.role().__class__.team())
                                      and room.private_chat[self.role().__class__.team()] is room.private_chat.get(target.role().__class__.team())):
                                    pass
                                else:
                                    event = self.visit_and_make_visit_event(
                                        target)
                    elif is_command(msg, Command.ACT):
                        if self.role().belongs_to(roles.ActiveAndVisiting) and not self.role().can_at_the_same_time and self.visits[room.day]:
                            content = {ContentKey.ROLE: self.role(
                            ).name, ContentKey.REASON: "????????? ?????? ????????? ??????????????? ??????????????? ??? ??? ????????? ??? ??? ????????????."}
                            event = self._make_event(
                                EventType.ERROR, self, content)
                        elif self.role().opportunity > 0 and (not self.role().belongs_to(roles.Jailing) or self.role().is_jailing()):
                            self.act[room.day] = not self.act[room.day]
                            content = {
                                ContentKey.ROLE: roles.Jailor.__name__
                                if self.role().belongs_to(roles.Jailing)
                                else self.role().name,
                                ContentKey.ACTIVE: self.act[room.day]
                            }
                            event = self._make_event(
                                EventType.ACT,
                                [self.role().is_jailing()] +
                                room.private_chat[self.role().__class__.team()]
                                if self.role().belongs_to(roles.Jailing) and self.role().__class__.team() in room.private_chat
                                else [self, self.role().is_jailing()],
                                content
                            )
                    elif is_command(msg, Command.RECRUIT) and self.role().belongs_to(roles.Boss):
                        self.role().recruit_target = room.find_player_by_index(
                            int(msg.split()[1]))
                        self.role().do_second_task_today = True
                        content = {ContentKey.ROLE: self.role(
                        ).name, ContentKey.TARGET: self.role().recruit_target.index}
                        event = self._make_event(
                            EventType.SECOND_VISIT, room.private_chat[self.role().__class__.team()], content)
                elif jailing := self.jailed_by:
                    if team := room.private_chat.get(jailing.role().__class__.team()):
                        content = {ContentKey.FROM: self.index,
                                   ContentKey.MESSAGE: msg}
                        event = [self._make_event(
                            EventType.MESSAGE, [self]+team, content)]
                        # content[ContentKey.FROM] = "?????????"
                        # event.append(self._make_event(EventType.MESSAGE, room.private_chat[roles.Spy], content=content)) # ????????? ??????
                    else:
                        content = {ContentKey.FROM: self.index,
                                   ContentKey.MESSAGE: msg}
                        event = self._make_event(
                            EventType.MESSAGE, [self, jailing.index], content)
                elif self.role().belongs_to(roles.Jailing):
                    if jailed := self.role().is_jailing():
                        for_jailed = {ContentKey.FROM: roles.Jailor.__name__,
                                      ContentKey.MESSAGE: msg, ContentKey.SHOW_ROLE_NAME: True}
                        event = [self._make_event(
                            EventType.MESSAGE, jailed, for_jailed)]
                        for_jailing = {
                            ContentKey.FROM: self.index, ContentKey.MESSAGE: msg}
                        to = room.private_chat.get(
                            self.role().__class__.team()) or self
                        event.append(self._make_event(
                            EventType.MESSAGE, to, for_jailing))
                elif team_chat := room.private_chat.get(self.role().__class__.team()):
                    content = {ContentKey.FROM: self.index,
                               ContentKey.MESSAGE: msg}
                    event = [self._make_event(
                        EventType.MESSAGE, team_chat, content)]
                    if self.role().__class__.team() in {roles.Mafia, roles.Triad}:
                        content2 = {ContentKey.FROM: self.role().__class__.team(
                        ).__name__, ContentKey.MESSAGE: msg, ContentKey.SHOW_ROLE_NAME: True}
                        event.append(self._make_event(
                            EventType.MESSAGE, room.private_chat[roles.Spy], content2))
                elif self.role().belongs_to(roles.Crying):
                    content = {ContentKey.FROM: roles.Crier.__name__,
                               ContentKey.MESSAGE: msg, ContentKey.SHOW_ROLE_NAME: True}
                    event = self._make_event(
                        EventType.MESSAGE, room.members, content)
            elif phase is PhaseType.NIGHT:
                content = {ContentKey.REASON: "????????? ???????????? ????????? ???????????? ??? ??? ????????????."}
                event = self._make_event(EventType.ERROR, self, content)
        return event

    def extend_action_record(self):
        self.visits.append(None)
        self.visited_by.append(set())
        self.act.append(False)
        self.healed_by.clear()
        self.bodyguarded_by.clear()

    def _make_event(self,
                    event_type: EventType,
                    to: Union[Player, User, list[Union[Player, User, int]]],
                    content: Optional[dict]):
        if event_type is EventType.BLACKMAILED:
            content = None
        else:
            content = jsonablify(content)
        return Event(event_type,
                     [to] if isinstance(to, Player) or isinstance(to, User)
                     else [self.room.lineup[r] if isinstance(r, int) else r for r in to],
                     content,
                     self)

    def _make_jail_event(self, target: Player):
        self.role().want_to_jail = target
        if self in self.room.jail_queue:
            self.room.jail_queue.remove(self)
        self.room.jail_queue.append(self)
        return Event(EventType.DAY_EVENT, self, jsonablify({
            ContentKey.ROLE: self.role().name,
            ContentKey.TARGET: target.index
        }))

    def visit_and_make_visit_event(self, target: Player, second: Optional[Player] = None):
        self.visits[self.room.day] = target
        content = {
            ContentKey.FROM: self.index,
            ContentKey.ROLE: self.role().name,
            ContentKey.TARGET: target.index,
        }
        if second:
            self.role().second_target = second
            content[ContentKey.SECOND_TARGET] = second.index
        teammates = self.room.private_chat.get(self.role().__class__.team())
        event = self._make_event(EventType.VISIT, teammates or self, content)
        return event

    def make_message_event(self, msg: str, pm: bool = False):
        """????????? ????????? ???????????? ????????????.

        Parameters:
            `msg`: ?????? ?????????.
            `pm`: ????????? ??????.
        """
        if pm:
            to, msg = msg.split()[1], " ".join(msg.split()[2:])
            for_to = {ContentKey.MESSAGE: msg, ContentKey.FROM: self.index}
            for_from = {ContentKey.MESSAGE: msg, ContentKey.TO: to}
            events = [
                self._make_event(
                    EventType.PM, self.room.find_player_by_index(int(to)), for_to),
                self._make_event(EventType.PM_SENT, self, for_from)
            ]
            return events
        content = {ContentKey.MESSAGE: msg}
        if self.room.in_court:
            content[ContentKey.SHOW_ROLE_NAME] = True
            if self.role().belongs_to(roles.Crying):
                content[ContentKey.FROM] = "Judge"
            else:
                content[ContentKey.FROM] = "Jury"
        elif self.room.phase() in {PhaseType.DEFENSE, PhaseType.VOTE_EXECUTION, PhaseType.LAST_WORDS} and self.room.elected is self:
            content[ContentKey.FROM] = self.index
            content[ContentKey.DEFENSE] = True
        else:
            content[ContentKey.FROM] = self.index
        event = self._make_event(EventType.MESSAGE, self.room.members, content)
        return event
