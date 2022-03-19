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
from starlette.websockets import WebSocket
from log import logger
from ws import broadcast_room_status_change
import db
import roles

recording_tasks: list[Task] = [] # TODO: 기록 태스크 모아보기
DEMOCRACY = "Democracy"

def jsonablify(injsonable: dict):
    remove_enum: Callable[[dict], dict] = lambda data: {key.name if isinstance(key, Enum) else key:value for key, value in {key:value.name if isinstance(value, Enum) else value for key, value in data.items()}.items()}
    remove_class: Callable[[dict], dict] = lambda data: {key.__name__ if inspect.isclass(key) else key:value for key, value in {key:value.__name__ if inspect.isclass(value) else value for key, value in data.items()}.items()}
    return remove_class(remove_enum(injsonable))

def is_command(msg: str, command: Command):
    return msg.startswith(command.value)

class SetupInvalid(Exception):
    """설정이 잘못된 경우."""

class SetupMalformed(Exception):
    """설정이 악의로 조작된 경우."""

@unique
class CrimeType(Enum):
    TRESPASS = "무단침입"
    KIDNAP = "납치"
    CORRUPTION = "부패"
    IDENTITY_THEFT = "신분도용"
    SOLICITING = "호객행위"
    MURDER = "살인"
    DISTURBING_THE_PEACE = "치안을 어지럽힘"
    CONSPIRICY = "음모"
    DISTRUCTION_OF_PROPERTY = "재물 손괴"
    ARSON = "방화"

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
    BEGIN = "/시작"
    PM = "/귓"
    COURT = "/개정"
    LYNCH = "/개시"
    MAYOR = "/발동"
    VOTE = "/투표"
    GUILTY = "/유죄"
    INNOCENT = "/무죄"
    ABSTENTION = "/기권"
    SKIP = "/생략"
    VISIT = "/방문"
    ACT = "/활동"
    RECRUIT = "/영입"
    JAIL = "/감금"
    SUICIDE = "/자살"
    NICKNAME = "/닉네임"

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
    """이벤트 종류를 나타내는 Enum."""
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
    """이벤트 클래스.
    누가 누구에게 어떤 이벤트를 어떤 내용으로 보내야 하는지가 적혀 있습니다.

    Arrtibutes:
        `event_type`: 이벤트 유형. `EventType`이어야 합니다.
        `to`: 이벤트를 받을 `Player`, `User`, 아니면 여러 명이 담긴 `list`.
        `content`: 이벤트로 보낼 `dict`. JSON으로 변환이 가능해야 합니다.
        `from_`: 이벤트를 보내는 사람의 정체(`User`). 기본값은 `None`입니다. 정체는 받는 사람에게 알려져서는 안 됩니다.
        `no_record`: 게임 중에 일어난 특정 이벤트를 기록하지 않을지 여부. 기본값은 `False`입니다.
    """
    def __init__(self,
                 event_type: EventType,
                 to: Union[list, User, Player],
                 content: dict,
                 from_: Optional[Union[User, Player]]=None,
                 no_record: bool=False):
        self.type = event_type
        self.to = to if isinstance(to, list) else [to]
        self.content = content
        self.from_ = from_.user if isinstance(from_, Player) else from_
        self.no_record = no_record
    
    def __repr__(self) -> str:
        return f"<Event {self.type} {self.from_ if self.from_ else ''} -> {self.to}>"

class Setup:
    """설정 클래스. 설정이 올바르지 않다면 만들어질 수 없습니다.

    Attributes:
        title: 설정명. 16자 이하입니다.
        inventor: 이 설정을 만든 `User`의 username. #TODO: unique id로 대체
        formation: 직업 구성.
        constraints: 직업 세부 설정.
        exclusion: 제외 설정.
    """
    def __init__(self,
                 title: str,
                 inventor: User,
                 formation: list[str],
                 constraints: dict[str, dict[str, Any]],
                 exclusion: dict[str, dict[str, bool]]):
        """설정이 올바르면 무사히 생성됩니다.
        올바르지 않으면 `Exception`을 띄웁니다.

        Parameters:
            `title`: 설정명. 16자 이하로 잘립니다.
            `inventor`: 설정을 만든 `User`.
            `formation`: 직업 구성.
            `constraints`: 직업 세부 설정.
            `exclusion`: 직업 제외 설정.
        Raises:
            `SetupInvalid`: 설정이 올바르지 않은 경우.
            `SetupMalformed`: 설정이 악의로 조작된 경우.
        """
        # TODO: inventor를 User ID로 받고, jsonablify()를 __init__()의 역함수로 만들기.
        pool = roles.pool()
        slots: list[Union[Type[roles.Role], Type[roles.Slot]]] = []
        competitors: set[Type[roles.Slot]] = set()
        constraints_with_constructors: dict[Type[roles.Role], dict[Union[roles.ConstraintKey, str], Union[roles.Level, str, bool, int]]] = dict()
        exclusion_with_constructors: dict[Type[roles.Slot], list[Type[Union[roles.Slot, roles.Role]]]] = dict()
        for slot in formation:
            for name, constructor in pool:
                if slot == name:
                    slots.append(constructor)
                    if constructor.team() is not None and constructor.against() != {}:
                        competitors.add(constructor.team())
                    break
            else:
                raise SetupMalformed(f"{slot}은 존재하지 않거나 직업 구성에 넣을 수 없는 칸입니다.")
        for slot, constraint in constraints.items():
            for name, constructor in {(n, c) for n, c in pool if roles.is_specific_role(c)}:
                if slot == name:
                    constraints_with_constructors[constructor] = dict()
                    if modifiable := constructor.modifiable_constraints():
                        for option, value in constraint.items():
                            value = roles.Level[value] if value in roles.Level.__members__ else value
                            option = roles.ConstraintKey[option] if option in roles.ConstraintKey.__members__ else option
                            if option not in modifiable:
                                raise SetupMalformed(f"{slot}의 세부 설정이 악의로 조작되었습니다. {option}은 존재하지 않는 설정입니다.")
                            option_range = modifiable[option][roles.ConstraintKey.OPTIONS]
                            if value in option_range:
                                constraints_with_constructors[constructor][option] = value
                            else:
                                raise SetupMalformed(f"{slot}의 세부 설정이 악의로 조작되었습니다. {option}의 선택지 {option_range}에 {value}가 없습니다.")
                    break
            else:
                raise SetupMalformed(f"직업이 아닌 {slot}을(를) 설정하려고 시도했습니다.")
        for from_, exclusion_dict in exclusion.items():
            for excluding_name, excluding_constructor in pool:
                if from_ == excluding_name:
                    exclusion_with_constructors[excluding_constructor] = []
                    for excluded in {name for name, is_excluded in exclusion_dict.items() if is_excluded}:
                        for excluded_name, excluded_constructor in pool:
                            if excluded == excluded_name:
                                exclusion_with_constructors[excluding_constructor].append(excluded_constructor)
                                break
                        else:
                            if excluding_constructor is roles.Any:
                                if excluded == roles.Killing.__name__:
                                    exclusion_with_constructors[excluding_constructor].append(roles.Killing)
                                else:
                                    for n, t in roles.teams():
                                        if excluded == n:
                                            exclusion_with_constructors[excluding_constructor].append(t)
                                            break
                                    else:
                                        raise SetupMalformed(f"{excluded}(이)란 칸은 제외할 수 없습니다.")
                            else:
                                raise SetupMalformed(f"{excluded}(이)란 칸은 제외할 수 없습니다.")
                    break
            else:
                raise SetupMalformed(f"{from_}(이)란 칸은 무작위 칸이 아닙니다.")
        if len(slots) < 5 or len(slots) > 15:
            raise SetupInvalid("설정은 5인 이상 15인 이하여야 합니다.")
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
            raise SetupInvalid("경쟁 세력이 없습니다.")
        for constructor in slots:
            if constructor.unique and slots.count(constructor) > 1:
                raise SetupInvalid(f"{constructor.__name__}은(는) 유일해야 합니다.")
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
                    f"{index+1}번 칸({slot_name})"
                    f"에 배정가능한 모든 직업(군)이 제외되어 해당 칸에서 직업을 생성할 수 없습니다."
                ))
            if roles.Spy in item and roles.Mafia not in competitors and roles.Triad not in competitors:
                raise SetupInvalid((
                    f"{roles.Spy.__name__}({index+1}번 칸 {slot_name})"
                    f"이 출현할 확률이 있다면, "
                    f"{roles.Mafia.__name__}나 {roles.Triad.__name__}가 확정으로 등장해야만 합니다."
                ))
            if roles.Executioner in item and constraints_with_constructors[roles.Executioner][roles.ConstraintKey.TARGET_IS_TOWN]:
                for team in competitors:
                    if issubclass(team, roles.Town):
                        break
                else:
                    raise SetupInvalid(f"{roles.Executioner.__name__}가 목표로 설정할 {roles.Town.__name__} 세력이 등장할 수 없습니다.")
        self.trial()
        self.title = title[:16].strip()
        self.inventor = inventor.username
        self.constraints = constraints_with_constructors
        self.exclusion = exclusion_with_constructors

    def trial(self) -> list[Type[roles.Role]]:
        """직업 구성에 의거하여 즉시 배정가능한 직업 목록을 생성합니다."""
        return [random.choice(pool) for pool in self.pool_per_slot]
    
    # @staticmethod
    # def _validate_uniqueness(slot_index: int,
    #                          reduced: list[list[Type[roles.Role]]],
    #                          excepted: list[roles.Role],
    #                          formation: list[str]):
    #     """모든 직업의 unique를 반영했을 때 `slot_index`번 칸에 생성가능한 직업이 있는지 검사합니다.

    #     생성가능한 직업이 있다면:
    #         `slot_index`번 칸에서 생성가능하면서 `unique==True`인 각 직업에 대하여,
    #         그 직업이 `slot_index`번 칸에서 생성된 경우에 `slot_index+1`번 칸에 생성가능한 직업이 있는지 검사합니다.
        
    #     Raises:
    #         `SetupInvalid`: `slot_index`번 칸에 생성가능한 직업이 없는 경우.
    #     """
    #     for index, pool in enumerate(reduced):
    #         if not pool:
    #             raise SetupInvalid((
    #                 f"{slot_index+1}번 칸({formation[slot_index]})에서 직업을 생성할 수 없습니다. "
    #                 f"{'' if slot_index==1 else '1~'}{slot_index}번 칸에서 "
    #                 f"유일해야만 하는 직업({', '.join(map(lambda r: r.__name__, excepted))})"
    #                 f"이 다 생성되는 경우에, {slot_index+1}번 칸에는 어떤 직업도 배정할 수 없게 됩니다. "
    #                 f"설정을 적절히 수정하세요."
    #             ))
    #         elif not (roles.Mayor.__name__ in formation and roles.Marshall.__name__ in formation):
    #             if pool == [roles.Mayor] and roles.Marshall in excepted or pool == [roles.Marshall] and roles.Mayor in excepted:
    #                 raise SetupInvalid((
    #                     f"{slot_index+1}번 칸 ({formation[slot_index]})에서 직업을 생성할 수 없습니다. "
    #                     f"{'' if slot_index==1 else '1~'}{slot_index}번 칸에서 "
    #                     f"유일해야만 하는 직업({', '.join(map(lambda r: r.__name__, excepted))})"
    #                     f"이 다 생성되는 경우에, {slot_index+1}번 칸에서 생성될 직업은 {pool[0].__name__}밖에 없습니다. "
    #                     f"하지만 {'Mayor은' if pool==[roles.Mayor] else 'Marshall는'} "
    #                     f"일부러 확정으로 같이 넣지 않는 이상은 {'Marshall와' if pool==[roles.Mayor] else 'Mayor과'} "
    #                     f"같이 생성될 수 없습니다. "
    #                     f"Mayor과 Marshall를 확정으로 같이 넣거나, "
    #                     f"{'' if slot_index==1 else '1~'}{slot_index}번 칸의 배정 가능 직업을 적절히 조정하세요."
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
    #     """비밀조합의 생성 조건인 직업(시민, 이교, 회계사)이 하나도 생성되지 않았는데
    #     비밀조합이 생성되어야만 하는 (즉 잘못된) 설정인지 검사합니다.
    #     """
    #     for index, pool in enumerate(reduced):
    #         for role in pool:
    #             if not issubclass(role, roles.Mason):
    #                 break
    #         else:
    #             raise SetupInvalid((
    #                 "Freemasonry은 Citizen, Cult, Auditor 중 하나가 있어야만 출현합니다. "
    #                 "그런데 이 설정은 Citizen, Cult, Auditor가 하나도 생성되지 않을 경우에도 "
    #                 f"Freemasonry이 {slot_index+1}번 칸({formation[slot_index]})에서 강제로 출현해야 합니다."
    #                 "Freemasonry의 생성 조건이 만족되도록 설정을 적절히 수정하세요."
    #             ))
    #         for unique in pool:
    #             if unique.unique:
    #                 Setup._validate_mason_dependency(slot_index+1, [[role for role in pool if role is not unique] for pool in reduced], formation)

    def jsonablify(self):
        """설정을 `JSON`으로 변환될 수 있는 `dict` 꼴로 반환합니다."""
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
                key.__name__:[slot.__name__ for slot in excluded]
                for key, excluded in self.exclusion.items()
            },
        }

class Room:
    """게임방.

    Attributes:
        Permananent: 변경은 가능하나 삭제는 되지 않고 영구히 유지되는 attributes.
            `host`: 방장.
            `title`: 방제. 10자 이하입니다.
            `capacity`: 정원. 15인 이하입니다.
            `id`: 방 ID.
            `password`: 비밀번호. 기본값은 `None`이며 이 경우 비번 없는 공방이 됩니다.
            `members`: 재실자 `User` 목록.
            `start_requested`: 게임 태스크가 만들어졌는지 여부. 자세한 것은 ws.process_message()를 참조하세요.
            `setup`: 게임 설정 `Setup` 인스턴스.
        In-game: 게임 시작 시 초기화되는 attributes.
            `role_name_pool`: 출현 가능한 직업 명단.
            `lineup_user`: 게임에 참가한 `User`.
            `lineup`: 실제 게임에서 행동하는 `Player`들.
            `dead_last_night`: 지난 밤 죽은 사람들.
            `jail_queue`: 감옥 큐. 선착순으로(/감금 명령어를 입력한 순으로) 감금이 진행됩니다.
            `private_chat`: 밤에 대화하거나(마피아, 이교도 등) 같은 메시지를 받는(정보원 등) 사람들의 목록.
            `graveyard`: 무덤.
            `winners`: 승자 목록.
            `hell`: 사망자 대화방.
            `leavers`: 탈주자.
            `day`: 인게임 날짜. 1일로 시작합니다.
            `_phase`: 현재 '단계'. 아침, 투표 시간, 밤 등을 말합니다.
            `skip_votes`: 생략 투표수.
            `in_court`: 재판 중인지 여부.
            `in_lynch`: 집단사형 중인지 여부.
            `mayor_reveal_today`: 오늘 시장이 나왔는지 여부.
            `executed`: 오늘 사형된 사람 목록.
            `suiciders`: 강제 자살자 목록.
            `TIME`: 단계별 제한시간.
            `record`: 게임 기록.
            `submitted_nickname`: 유저별 닉네임.
            `there_is`: 세력별 생존자.
    """
    def __init__(self,
                 host: User,
                 title: str,
                 capacity: int,
                 room_id: int,
                 password: Optional[str]=None):
        self.host = host
        self.members: list[User] = []
        self.title = title[:16].strip()
        self.capacity = capacity
        self.id = room_id
        self.password = password[:8] if password else None
        self.start_requested = False
        self._phase = PhaseType.IDLE
        self.setup: Setup = None

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
        """생존한 `Player`들."""
        return {i:p for i, p in self.lineup.items() if p.alive()}

    async def reveal_identity(self, dead: Player):
        """망자의 직업과 유언을 공표합니다.
        `dead.dead_sanitized==True`라면 숨긴 채로 공표합니다.
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
        """게임을 초기화합니다."""
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
        } # set이 아니라 list로 하는 것은 항상 첫 번째 teammate가 BOSS/INTERN이 되도록 하기 위함.
        # 자세한 건 trigger_evening_events() 참고.
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
                            self.submitted_nickname.get(user, str(user.username)+"in-game"), # TODO: 견본 닉네임
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
            "lineup": {i:p.nickname for i, p in self.lineup.items()}
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
                await asyncio.sleep(1 if debug_mode else 5) # 최소한 5초는 쉬고 낮이 됩니다.
                self.day +=1
                for i, r in self.remaining().items():
                    r.extend_action_record()
                # 아침
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
                # 토론
                await self.turn_phase(PhaseType.DISCUSSION)
                await self.timer(self.phase(), self.TIME[self.phase()])
                # 투표
                self.skip_votes = 0
                self.executed.clear()
                remaining = self.TIME[PhaseType.VOTE]
                while remaining > 0:
                    self.elected = None
                    await self.turn_phase(PhaseType.VOTE)
                    try:
                        began_at = time.time()
                        timer = asyncio.create_task(self.timer(self.phase(), remaining))
                        await asyncio.wait_for(self.election.wait(), remaining)
                    except asyncio.TimeoutError: # 아무도 달리지 않음.
                        break
                    else: # 누가 달렸거나 투표가 생략됨.
                        if self.skip_votes > len(self.remaining())/2:
                            # TODO: SKIP
                            break
                        remaining -= time.time()-began_at
                        self.elected = max(self.remaining().values(), key=lambda u:u.voted_count)
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
                            # TODO: 달리자마자 탈주한 사람들 즉시 사형
                            await self.turn_phase(PhaseType.DEFENSE)
                            await self.timer(self.phase(), self.TIME[self.phase()])
                            await self.turn_phase(PhaseType.VOTE_EXECUTION)
                            await self.timer(self.phase(), self.TIME[self.phase()])
                            result = {
                                i:voter.execution_choice.value*voter.role().votes
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
                                    self.suiciders[self.elected.role()] = random.choice(pool)
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
            recording_tasks.append(asyncio.create_task(db.archive(GameData(self))))
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
                    self.win_them_all(category, not issubclass(category, roles.NeutralKilling))
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
            first_winner: Player = sorted(self.winners, key=lambda u: _solo_priority(u[1]))[0]
            win_alone = len(self.winners) == 1 and len(list(itertools.filterfalse(lambda t:first_winner.role().belongs_to(t), {
                roles.Town,
                roles.Mafia,
                roles.Triad,
                roles.Cult
            })))==4 # 승자가 단 한 명뿐이고, 팀이 없는 경우
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
            "lineup": {i:m.nickname for i, m in self.lineup.items()} if self.in_game() else None,
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
                                and not NE.role().belongs_to(roles.Cult)], # 중살 이교 제외 중악만.
        }
        there_is_NK = self.there_is[roles.Arsonist]+self.there_is[roles.SerialKiller]+self.there_is[roles.MassMurderer]
        if len(remaining) < 3:
            return True
        if self.there_is[roles.Town]:
            return list(self.there_is.values()).count([]) == len(self.there_is) - 1 # 시민만 있다면
        if self.there_is[roles.Mafia]:
            return not self.there_is[roles.Triad] and not self.there_is[roles.Cult] and not there_is_NK
        if self.there_is[roles.Triad]:
            return not self.there_is[roles.Cult] and not there_is_NK
        if self.there_is[roles.Cult]:
            return not there_is_NK
        if there_is_NK:
            return len({NK.role().__class__.team() for NK in there_is_NK}) < 3 # 중살만 남았는데 3파전 이상이 아니라면
        return True # 중선들만 남았다면

    def win_them_all(self, category: Union[Type[roles.Slot], Type[roles.Role]], include_dead: bool):
        """직업이 `category`에 속하는 `Player`들을 승리시킵니다.
        `include_dead==True`라면 죽은 `Player`들도 포함합니다.
        재실 중이 아닌 `Player`는 승리하지 않습니다."""
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
                    converting_coros.append(r.be(roles.MasonLeader(r, self.setup.constraints[roles.MasonLeader])))
                    break
        for criminals in {roles.Mafia, roles.Triad}:
            if team := self.private_chat[criminals]:
                for C in team:
                    if C.role().belongs_to(roles.KillingVisiting) and C.role().opportunity > 0:
                        break
                else:
                    for C in team:
                        if C.role().belongs_to(roles.IdentityInvestigating) and C.role().constraints[roles.ConstraintKey.PROMOTED]:
                            converting_coros.append(C.be(match[criminals][BOSS](C, self.setup.constraints[match[criminals][BOSS]])))
                            break
                    else:
                        promoted = self.private_chat[criminals][0]
                        converting_coros.append(promoted.be(match[criminals][INTERN](promoted, self.setup.constraints[match[criminals][INTERN]])))
        converting_coros.extend(
            counsel.be(roles.Scumbag(counsel, self.setup.constraints[roles.Scumbag]))
            for counsel in self.remaining().values()
            if counsel.role().belongs_to(roles.Counsel)
            and r.role().goal_target.intersection(self.executed)
        )
        await asyncio.gather(*converting_coros)
        if not self.executed: # 사형이 있은 날에는 감금 불가.
            for jailor in self.jail_queue:
                if not jailor.jailed_by:
                    if jailor.role().want_to_jail.jailed_by:
                        pass # TODO
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
            # 방탄 착용
            roles.Survivor,
            roles.Citizen,
            # 조종
            roles.Witch,
            # 밤에 활동이 불가능하나 마녀에게 조종당하면 방문이 가능한 직업들.
            INACTIVE,
            # 마녀 조종 확정 이후에 능력 차단
            roles.Escort,
            roles.Consort,
            roles.Liaison,
            # 능력 차단 확정 이후에 잠입
            roles.Beguiler,
            roles.Deceiver,
            # 이제 방문자 전부 확정됨.
            roles.Framer,
            roles.Forger,
            roles.Arsonist, # 기름칠
            roles.Doctor,
            roles.WitchDoctor, # 치료
            roles.Bodyguard,
            # 살인 시작.
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
            roles.Arsonist, # 점화
            roles.MasonLeader, # 이교도 살인
            roles.MassMurderer,
            roles.Witch, # 저주
            SUICIDE,
            # 시체 훼손
            roles.Janitor,
            roles.IncenseMaster,
            # 조사
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
            roles.MasonLeader, # 영입
            roles.Cultist,
            roles.WitchDoctor, # 개종
            roles.Godfather, # 영입
            roles.DragonHead, # 영입
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
                    await left.die("leave") # 치료 불가
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
                    # TODO: ActiveAndVisiting 반영
                    events = None
                    if role in done:
                        if actor.role().do_second_task_today:
                            events = actor.role().second_task(self.day)
                    elif actor.visits[self.day] or actor.act[self.day]:
                        if determined := actor.visits[self.day]:
                            if actor.role().opportunity is not None and actor.role().opportunity <= 0: # 기회가 없는데 방문하도록 조종당하면
                                events = roles.Visiting.visit(actor.role(), self.day, determined)
                            else:
                                events = actor.role().visit(self.day, determined)
                        else:
                            events = actor.role().act(self.day)
                    else:
                        events = actor.role().action_when_inactive(self.day)
                    if not events: continue
                    for e in events if isinstance(events, list) else [events]:
                        if sound := e.get(roles.AbilityResultKey.SOUND):
                            affected = e[roles.AbilityResultKey.INDIVIDUAL].keys()
                            listening = set(self.members).difference({p.user for p in affected})
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
                                    m.role().opportunity = m.visits[self.day].role().opportunity or 1
                            else:
                                await self.emit(Event(EventType.ABILITY_RESULT, m, jsonablify(data)))
                        worked_roles.add(actor.role())
                done.add(role)
        await asyncio.gather(*[
            self.emit(Event(EventType.ABILITY_RESULT, spy, jsonablify(spy.role().after_night()[roles.AbilityResultKey.INDIVIDUAL][spy])))
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
        """`into` phase에 돌입합니다."""
        self._phase = into
        await self.emit(Event(EventType.PHASE, self.members, {
            ContentKey.PHASE.name: into.name,
            ContentKey.WHO.name:
                self.elected.index
                if self.in_game() and self.phase() is not PhaseType.INITIATING and self.elected
                else None,
        }, no_record=into is PhaseType.INITIATING or into is PhaseType.IDLE))
        await broadcast_room_status_change(self)

    def find_player_by_index(self, index: int):
        """`index`번 플레이어를 가져옵니다."""
        return self.lineup[index]
    
    async def submit_nickname(self, user: User, nickname: str):
        self.submitted_nickname[user] = nickname
        await self.emit(Event(EventType.NICKNAME_CONFIRMED, self.members, {"nickname": nickname}))

    async def emit(self, e: Event):
        """이벤트를 보내고 기록합니다.
        `emit()`은 철저히 `e`에 명시된 대로만 이벤트를 보내며,
        어떤 이벤트를 누구에게 어떤 타입으로 보내는지 결정하는 것은
        전적으로 `emit()`을 호출하는 함수의 몫입니다.
        """
        if self.in_game() and not e.no_record:
            data = {
                "type": e.type.name,
                "content": e.content,
                "from": e.from_.username if e.from_ else None, # TODO: username을 unique id로 대체
                "to": [
                    m.username
                    if isinstance(m, User)
                    else m.user.username
                    for m in e.to
                ], # TODO: username을 unique id로 대체
                "time": time.time()
            }
            self.record.append(data)
        await asyncio.gather(*[member.listen({
            "type": e.type.name,
            "content": e.content,
        }) for member in e.to])

class GameData:
    """게임 기록입니다. 메타데이터를 포함합니다."""
    def __init__(self, room: Room):
        self.title = room.title
        self.private = room.password is not None
        self.lineup = room.lineup
        self.setup = room.setup
        self.record = room.record[:]
        self.rank_mode = False # TODO

class User:
    """유저 오브젝트.

    Attributes:
        `username`: 사용자명.
        `ws`: 이 `User`에 연결된 `WebSocket`.
        `existing`: 중복 접속 여부. 이 계정으로 중복 접속이 시도되면 기존 `User` 오브젝트에 `existing=True`가 적용됩니다.
        `room`: 현재 있는 `Room`.
        `player`: 현재 인게임 `Player`.
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
        return self.username # TODO

    async def enter(self, room: Room):
        self.room = room
        room.members.append(self)
        logger.debug(f"{self.username} enters {room}")
        room_info = room.get_room_ingame_info()
        if room.in_game():
            room.hell.append(self)
        enter_notice = {"who": self.username} # TODO: unique ID도 알려줌
        await room.emit(Event(EventType.GAME_INFO, self, jsonablify(room_info)))
        await room.emit(Event(EventType.ENTER, room.members, enter_notice))
        await broadcast_room_status_change(self.room)

    async def leave(self):
        """방을 나갑니다. 더 이상 `user.room`으로 방에 접근할 수 없습니다.
        게임 중 탈주도 이 함수에서 처리합니다.
        그러나 나갔는데 방이 비어서 삭제하는 것은 이 함수가 아니라 `leave()`를 호출하는 함수의 몫입니다.
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
        await broadcast_room_status_change(left)

    async def speak(self, msg: str):
        """`msg`가 말이라면 말을 하고, `/`로 시작하는 명령어라면 명령어를 처리합니다.
        `\\n`과 같은 공백 문자는 다 단칸 공백(`" "`)으로 대체됩니다. 이는 받는 사람을 보호하기 위함입니다.
        `msg`는 처리되기 전에 `msg = msg[:128].strip()`을 먼저 거칩니다."""
        msg = msg[:128].strip() # 최대 글자수
        for c in string.whitespace:
            msg = msg.replace(c, " ")
        msg = msg.strip()
        if not msg: return
        room = self.room
        if room.in_game():
            event = None
            if room.phase() is PhaseType.NICKNAME_SELECTION:
                if is_command(msg, Command.NICKNAME):
                    nickname = " ".join(msg.split()[1:])
                    if len(re.findall("[가-힣]|[a-z]|[A-Z]|[0-9]", nickname)) == len(nickname) and 1 <= len(nickname) <= 8:
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
                event = Event(EventType.MESSAGE, room.hell, jsonablify(content), self)
            if event:
                if not isinstance(event, list):
                    event = [event]
                await asyncio.gather(*[room.emit(e) for e in event])
        else:
            if is_command(msg, Command.SLASH):
                pass
            else:
                content = {ContentKey.FROM: self.username, ContentKey.MESSAGE: msg}
                await room.emit(Event(EventType.MESSAGE, room.members, content, self))
                logger.debug(f"[{room.id}] {self.username}: {msg}")

    async def listen(self, data: dict):
        try:
            await self.ws.send_json(data)
        except TypeError: # JSON 변환 불가
            raise
        except (RuntimeError, ConnectionClosed): # 나간 경우. 이때는 그냥 ws_endpoint의 finally까지 기다리기만 하면 됩니다.
            pass

class Player:
    """인게임 플레이어. 시체를 겸합니다."""
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
        self._role_record: list[Union[roles.Role, roles.Slot]] = [role(self, constraints)]
        self.has_left = False
        self.lw = ""
        self.crimes = {c:False for c in CrimeType}
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
        """`role`로 전직합니다. 기존 팀이 있다면 이들에게도 전직 이벤트를 전송합니다."""
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
            ContentKey.GOAL_TARGET: sorted([p.index for p in self.role().goal_target]) or None
        }
        if existing_group:
            for_team = {
                ContentKey.WHAT: self.role().name,
                ContentKey.WHO: self.index,
            }
            await asyncio.gather(*[
                self.room.emit(Event(EventType.EMPLOYED, self, jsonablify(content))),
                self.room.emit(Event(EventType.EMPLOYED, self.room.private_chat[existing_group], for_team))
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
        """투표를 취소합니다. `skip==True`면 생략 투표를 취소합니다."""
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
                    event = self._make_event(EventType.SUICIDE, self, {ContentKey.WILL: self.will_suicide})
                elif is_command(msg, Command.VISIT):
                    pass # TODO
            else:
                event = self._make_event(EventType.ERROR, self, {ContentKey.REASON: "협박당해 말을 할 수 없습니다."})
        else:
            phase = room.phase()
            if phase is PhaseType.MORNING:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(int(msg.split()[1]))
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
                        received = room.find_player_by_index(int(msg.split()[1]))
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
                        received = room.find_player_by_index(int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.COURT) and self.role().can_activate():
                        if self.has_voted_to is None:
                            event = self.role().activate()
                        else:
                            event = self._make_event(EventType.ERROR, self, {
                                ContentKey.REASON.name: "개정을 하려면 방금 넣은 표를 빼세요. 추가 투표권은 기권 상태에서만 획득할 수 있습니다."
                            })
                    elif is_command(msg, Command.LYNCH) and self.role().can_activate():
                        event = self.role().activate()
                    elif is_command(msg, Command.MAYOR) and self.role().can_activate():
                        if self.has_voted_to is None:
                            event = self.role().activate()
                        else:
                            event = self._make_event(EventType.ERROR, self, {
                                ContentKey.REASON.name: "발동을 하려면 방금 넣은 표를 빼세요. 추가 투표권은 기권 상태에서만 획득할 수 있습니다."
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
                        event = self._make_jail_event(room.find_player_by_index(int(msg.split()[1])))
                elif room.elected is self:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.VOTE_EXECUTION:
                if is_command(msg, Command.SLASH):
                    if is_command(msg, Command.PM) and not room.in_court:
                        received = room.find_player_by_index(int(msg.split()[1]))
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
                        received = room.find_player_by_index(int(msg.split()[1]))
                        if received is not self:
                            event = self.make_message_event(msg, pm=True)
                    elif is_command(msg, Command.MAYOR) and self.role().can_activate():
                        pass # TODO
                else:
                    event = self.make_message_event(msg)
            elif phase is PhaseType.EVENING:
                if is_command(msg, Command.SLASH):
                    if self.jailed_by:
                        if is_command(msg, Command.SUICIDE):
                            pass
                    # 이하로는 수감 시 사용 불가능한 명령어
                    elif room.day <= self.role().rest_till:
                        content = {ContentKey.ROLE: self.role().name, ContentKey.REASON: f"{self.role().rest_till}일째 밤까지 쉬어야 합니다."}
                        event = self._make_event(EventType.ERROR, self, content)
                        # 이 이하로는 DELAY에 영향을 받는 행동.
                    elif is_command(msg, Command.VISIT) and self.role().belongs_to(roles.Visiting) and (self.role().opportunity is None or self.role().opportunity > 0):
                        splitted = msg.split()
                        if len(splitted) == 1:
                            target_index = None
                        elif len(splitted) == 2:
                            target_index = int(splitted[1])
                        else:
                            target_index, second_index = map(int, splitted[1:3])
                        target = room.find_player_by_index(target_index)
                        if self.role().for_dead:
                            if target.death_announced():
                                if self.role().belongs_to(roles.Amnesiac) and target.role().unique:
                                    pass
                                else:
                                    event = self.visit_and_make_visit_event(target)
                        else:
                            if self.role().belongs_to(roles.Witch):
                                if second_target := room.find_player_by_index(second_index):
                                    event = self.visit_and_make_visit_event(target, second_target)
                            elif self.role().belongs_to(roles.Visiting) and not self.role().for_dead:
                                if target is self:
                                    if self.role().can_target_self:
                                        event = self.visit_and_make_visit_event(target)
                                elif (self.role().belongs_to(roles.KillingVisiting)
                                    and room.private_chat.get(self.role().__class__.team())
                                    and room.private_chat[self.role().__class__.team()] is room.private_chat.get(target.role().__class__.team())):
                                    pass
                                else:
                                    event = self.visit_and_make_visit_event(target)
                    elif is_command(msg, Command.ACT):
                        if self.role().belongs_to(roles.ActiveAndVisiting) and not self.role().can_at_the_same_time and self.visits[room.day]:
                            content = {ContentKey.ROLE: self.role().name, ContentKey.REASON: "하루에 고유 능력을 사용하거나 방문하거나 둘 중 하나만 할 수 있습니다."}
                            event = self._make_event(EventType.ERROR, self, content)
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
                                [self.role().is_jailing()] + room.private_chat[self.role().__class__.team()]
                                if self.role().belongs_to(roles.Jailing) and self.role().__class__.team() in room.private_chat
                                else [self, self.role().is_jailing()],
                                content
                            )
                    elif is_command(msg, Command.RECRUIT) and self.role().belongs_to(roles.Boss):
                        self.role().recruit_target = room.find_player_by_index(int(msg.split()[1]))
                        self.role().do_second_task_today = True
                        content = {ContentKey.ROLE: self.role().name, ContentKey.TARGET: self.role().recruit_target.index}
                        event = self._make_event(EventType.SECOND_VISIT, room.private_chat[self.role().__class__.team()], content)
                elif jailing := self.jailed_by:
                    if team := room.private_chat.get(jailing.role().__class__.team()):
                        content = {ContentKey.FROM: self.index, ContentKey.MESSAGE: msg}
                        event = [self._make_event(EventType.MESSAGE, [self]+team, content)]
                        # content[ContentKey.FROM] = "수감자"
                        # event.append(self._make_event(EventType.MESSAGE, room.private_chat[roles.Spy], content=content)) # 정보원 상향
                    else:
                        content = {ContentKey.FROM: self.index, ContentKey.MESSAGE: msg}
                        event = self._make_event(EventType.MESSAGE, [self, jailing.index], content)
                elif self.role().belongs_to(roles.Jailing):
                    if jailed := self.role().is_jailing():
                        for_jailed = {ContentKey.FROM: roles.Jailor.__name__, ContentKey.MESSAGE: msg, ContentKey.SHOW_ROLE_NAME: True}
                        event = [self._make_event(EventType.MESSAGE, jailed, for_jailed)]
                        for_jailing = {ContentKey.FROM: self.index, ContentKey.MESSAGE: msg}
                        to = room.private_chat.get(self.role().__class__.team()) or self
                        event.append(self._make_event(EventType.MESSAGE, to, for_jailing))
                elif team_chat := room.private_chat.get(self.role().__class__.team()):
                    content = {ContentKey.FROM: self.index, ContentKey.MESSAGE: msg}
                    event = [self._make_event(EventType.MESSAGE, team_chat, content)]
                    if self.role().__class__.team() in {roles.Mafia, roles.Triad}:
                        content2 = {ContentKey.FROM: self.role().__class__.team().__name__, ContentKey.MESSAGE: msg, ContentKey.SHOW_ROLE_NAME: True}
                        event.append(self._make_event(EventType.MESSAGE, room.private_chat[roles.Spy], content2))
                elif self.role().belongs_to(roles.Crying):
                    content = {ContentKey.FROM: roles.Crier.__name__, ContentKey.MESSAGE: msg, ContentKey.SHOW_ROLE_NAME: True}
                    event = self._make_event(EventType.MESSAGE, room.members, content)
            elif phase is PhaseType.NIGHT:
                content = {ContentKey.REASON: "사건이 일어나는 밤에는 아무것도 할 수 없습니다."}
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
    
    def visit_and_make_visit_event(self, target: Player, second: Optional[Player]=None):
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
    
    def make_message_event(self, msg: str, pm: bool=False):
        """인게임 메시지 이벤트를 만듭니다.

        Parameters:
            `msg`: 보낼 메시지.
            `pm`: 귓속말 여부.
        """
        if pm:
            to, msg = msg.split()[1], " ".join(msg.split()[2:])
            for_to = {ContentKey.MESSAGE: msg, ContentKey.FROM: self.index}
            for_from = {ContentKey.MESSAGE: msg, ContentKey.TO: to}
            events = [
                self._make_event(EventType.PM, self.room.find_player_by_index(int(to)), for_to),
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