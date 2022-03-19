from __future__ import annotations
import sys
import random
import inspect
from enum import Enum, IntEnum, auto, unique
from typing import Optional, Union, Type
from game import ContentKey, Event, EventType, PhaseType, Player, CrimeType, jsonablify

def role_order_key(class_):
    if issubclass(class_, Mafia):
        return 0
    if issubclass(class_, Triad):
        return 1
    if issubclass(class_, Neutral):
        return 2
    if issubclass(class_, Town):
        return 3
    return -1

def pool() -> list[tuple[str, Union[Type[Slot], Type[Role]]]]:
    is_possible_slot = lambda obj: obj is Any or (inspect.isclass(obj) and issubclass(obj, Slot) and issubclass(obj, Team) and not obj.not_for_first and not obj.disabled)
    return sorted(sorted(inspect.getmembers(sys.modules[__name__], is_possible_slot)), key=lambda item:role_order_key(item[1]))

def teams():
    return sorted([(n, c) for n, c in inspect.getmembers(sys.modules[__name__]) if inspect.isclass(c) and Team in c.__bases__], key=lambda item:role_order_key(item[1]))

def team_alignments():
    team_list = {c for n, c in teams()}
    alignment_list = {c for n, c in inspect.getmembers(sys.modules[__name__], lambda obj: inspect.isclass(obj) and Alignment in obj.__bases__)}
    alignment_list.add(NeutralKilling)
    return [
        item for item in pool()
        if (set(item[1].__bases__).intersection(team_list) or Any in item[1].__bases__)
        and set(item[1].__bases__).intersection(alignment_list)
    ]

def is_specific_role(class_: Union[Type[Slot], Type[Role]]):
    return issubclass(class_, Slot) and issubclass(class_, Role)

@unique
class ConstraintKey(Enum):
    OPPORTUNITY = auto()
    NOTIFIED = auto()
    DELAY = auto()
    OFFENSE_LEVEL = auto()
    DEFENSE_LEVEL = auto()
    PROMOTED = auto()
    DETECT_EXACT_ROLE = auto()
    DETECTION_IMMUNE = auto()
    SURVIVE_TO_WIN = auto()
    RECRUITABLE = auto()
    TARGET_IS_TOWN = auto()
    QUOTA_PER_LYNCH = auto()
    WIRETAP_JAILED = auto()
    IF_FAIL = auto()
    VICTIMS = auto()
    OPTIONS = auto()
    DEFAULT = auto()

@unique
class AbilityResultKey(Enum):
    INDIVIDUAL = auto()
    SOUND = auto()
    LENGTH = auto()
    ROLE = auto()
    TYPE = auto()
    VISIT = auto()
    ACT = auto()
    THREATENED = auto()
    BLOCKED = auto()
    KILLED = auto()
    ATTACKED = auto()
    HEALED = auto()
    CONVERTED = auto()
    JOINED = auto()
    ALMOST_DIED = auto()
    BODYGUARDED = auto()
    CONTACTED = auto()
    JAILED = auto()
    REVEALED = auto()
    AGAINST = auto()
    INTO = auto()
    BY = auto() # 실제 사망 이유
    BY_PUBLIC = auto() # 대외적으로 밝혀지는 사망 이유
    CRIMES = auto()
    SUCCESS = auto()
    INDEX = auto()
    RESULT = auto()
    LW = auto()
    SECOND_TASK = auto()
    NOTIFIED = auto()

@unique
class Level(IntEnum):
    NONE = auto()
    BASIC = auto()
    STRONG = auto()
    ABSOLUTE = auto()

@unique
class FrameKey(Enum):
    TO = auto()
    ROLE = auto()

class Slot:
    """이 클래스를 상속하는 클래스는 `formation`에 `slot`으로 들어갈 수 있습니다.

    Class Attributes:
        `not_for_first`: 첫 직업이 될 수 없는지 여부.
        `default_to_exclude`: 임의직 칸에서 제외되는 것이 기본값인지 여부.
        `unique`: 게임 시작 시 둘 이상 있을 수 없는지 여부.
        `disabled`: 비활성화되어 게임에서 나올 수 없는지 여부.
    """
    not_for_first = False
    default_to_exclude = False
    unique = False
    disabled = False

    def against() -> set[Slot]:
        """적대 세력이 담긴 `set`을 반환합니다."""

    def team() -> Type[Slot]:
        """바로 상위에 있는 팀을 반환합니다.

        Examples:
            `Mafioso.team()==Mafia`
            `MasonLeader.team()==Mason`
            `Veteran.team()==Veteran`
            `Cultist.team()==Cult`
            `Arsonist.team()==Arsonist`,
            `Jester.team()==Jester`
        """

class Role:
    """직업 클래스. 이 클래스를 상속하는 클래스만이 실제로 배정될 수 있습니다.
    
    Class Attiributes:
        `for_dead`: 죽은 자를 대상으로 하는 직업인지 여부.
    """
    for_dead = False

    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        """변경 가능한 설정과 기본값을 반홥합니다.
        모든 설정은 제각기 기본값이 명시되어 있어야 합니다.
        `OPTIONS==[True, False]`면 켜거나 끄는 설정이 되고,
        이외에는 선택지 여럿 중 택일하는 설정이 됩니다.

        Examples:
            Veteran.constraints() == {
                ConstraintKey.OPPORTUNITY: {
                    ConstraintKey.OPTIONS: [2,3,4],
                    ConstraintKey.DEFAULT: 2,
                }
            }
            Hiding.constraints() == {
                ConstraintKey.OPPORTUNITY: {
                    ConstraintKey.OPTIONS: [1,2,3,4],
                    ConstraintKey.DEFAULT: 2,
                },
                ConstraintKey.NOTIFIED: {
                    ConstraintKey.OPTIONS: [True, False],
                    ConstraintKey.DEFAULT: False,
                }
            }
        """

    def __init__(self, me: Player, constraints: dict):
        """`me`에게 배정되는 직업을 `constraints`를 반영하여 생성합니다.
        
        Attributes:
            `offense_level`: 공격 수준.
            `defense_level`: 방어 수준.
            `me`: 이 `Role`의 주인인 `Player`.
            `constraints`: 이 `Role`에 적용되는 설정.
            `name`: 직업 영문명. CamelCase입니다.
            `blockable`: 능력을 차단당할 수 있는지 여부.
            `healable`: 치료될 수 있는지 여부.
            `immune_to_detection`: 검출 면역인지 여부.
            `opportunity`: 능력 사용 기회. `None`이면 무제한입니다.
            `recruitable_into`: 영입 정보.
            `do_second_task_today`: `second_task()`를 오늘 밤 실행할지 여부. 자세한 것은 각 직업 클래스를 참고하세요.
            `convertable`: 직업이 바뀔 수 있는지 여부.
            `votes`: 보유 투표권.
            `rest_till`: n일 밤까지 쉬어야 함을 말합니다. `rest_till==3`이면 3일쨰 밤까지 능력을 사용할 수 없습니다.
            `goal_target`: 승리 목표와 관련이 있는 목표.
            `can_target_self`: 스스로 방문할 수 있는지 여부입니다.
        """
        self.constraints = constraints
        self.offense_level: Level = self.constraints.get(ConstraintKey.OFFENSE_LEVEL, Level.NONE)
        self.defense_level: Level = self.constraints.get(ConstraintKey.DEFENSE_LEVEL, Level.NONE)
        self.me = me
        self.name = self.__class__.__name__
        self.blockable = True
        self.healable = True
        self.immune_to_detection = self.constraints.get(ConstraintKey.DETECTION_IMMUNE, False)
        self.opportunity: Optional[int] = self.constraints.get(ConstraintKey.OPPORTUNITY)
        self.recruitable_into: dict[Role, Role] = dict()
        self.do_second_task_today = False
        self.convertable = True
        self.votes = 1
        self.rest_till = 0
        self.goal_target: set[Player] = set()
        self.can_target_self = False

    def __repr__(self):
        return f"<{self.name}>"

    def visit(self, day: int, target: Player):
        """`target`을 방문합니다. `target`이 누구 뒤에 숨었다면 앞에 있는 사람을 방문합니다.
        
        Returns:
            `dict`: 방문 결과 데이터. 자세한 것은 각 직업 클래스를 참고하세요.
        """
        self.me.visits[day] = target.is_behind or target
        if not self.me.visits[day].death_announced():
            self.me.visits[day].visited_by[day].add(self.me)
        return {AbilityResultKey.INDIVIDUAL: {self.me: {AbilityResultKey.ROLE: self.__class__}}}

    def after_night(self):
        """밤이 끝나면 할 작업입니다."""
        self.do_second_task_today = False
    
    def second_task(self, day: int):
        """밤에 활동을 2번 하는 직업(대부 살인/영입, 방화범 기름/방화 등)의 2번째 활동을 하는 함수입니다."""
    
    def action_when_inactive(self, day: int):
        """무활 시 기본으로 하는 활동입니다.
        일부 특수한 직업은 `action_when_inactive`에 조건이 있습니다.
        가령 연쇄살인마는 능력을 차단당하는 경우에만 `action_when_inactive`가 발동합니다."""
    
    def respond_to_block(self, blocker: Player):
        """능력 차단에 대응하는 함수입니다."""
    
    def belongs_to(self, alignment_or_team: Type[Union[Role, Slot]]):
        return isinstance(self, alignment_or_team)
    
    def can_kill(self, attacked: Role):
        return self.offense_level > attacked.defense_level
    
    def set_goal_target(self):
        pass
"""
==========
Teams
==========
"""
class Team:
    def against() -> set[Slot]:
        pass

    def team() -> Type[Slot]:
        pass

class Town(Team):
    def against() -> set[Slot]:
        return {Mafia, Triad, NeutralEvil}
    
    def team() -> Type[Slot]:
        return Town

class Mafia(Team):
    def against() -> set[Slot]:
        return {Town, Triad, NeutralKilling, Cult}

    def team() -> Type[Slot]:
        return Mafia

class Triad(Team):
    def against() -> set[Slot]:
        return {Town, Mafia, NeutralKilling, Cult}

    def team() -> Type[Slot]:
        return Triad

class Neutral(Team):
    pass
"""
==========
Alignment
==========
"""
class Alignment(Slot):
    pass

class Any(Alignment):
    pass

class Killing(Alignment):
    pass

class Government(Alignment):
    pass

class Protective(Alignment):
    pass

class Investigative(Alignment):
    pass

class Power(Alignment):
    pass

class Support(Alignment):
    pass

class Deception(Alignment):
    pass

class Benign(Alignment):
    pass

class Evil(Alignment):
    pass

# Any
class TownAny(Town, Any):
    pass

class MafiaAny(Mafia, Any):
    pass

class TriadAny(Triad, Any):
    pass

class NeutralAny(Neutral, Any):
    pass

# Town
class TownGovernment(Town, Government):
    pass

class TownProtective(Town, Protective):
    pass

class TownKilling(Town, Killing):
    pass

class TownInvestigative(Town, Investigative):
    pass

class TownPower(Town, Power):
    pass

# Mafia
class MafiaKilling(Mafia, Killing):
    pass

class MafiaSupport(Mafia, Support):
    pass

class MafiaDeception(Mafia, Deception):
    pass

# Triad
class TriadKilling(Triad, Killing):
    pass

class TriadSupport(Triad, Support):
    pass

class TriadDeception(Triad, Deception):
    pass

# Neutral
class NeutralBenign(Neutral, Benign):
    def against() -> set[Slot]:
        return {}
    
    def team() -> Type[Slot]:
        return NeutralBenign

class NeutralEvil(Neutral, Evil):
    def against() -> set[Slot]:
        return {Town}
    
    def team() -> Type[Slot]:
        return NeutralEvil

class NeutralKilling(NeutralEvil, Neutral, Killing):
    default_to_exclude = True

    def team() -> Type[Slot]:
        return NeutralKilling

"""
==========
Types by ability
==========
"""

class Visiting(Role):
    pass

class ActiveOnly(Role):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.can_at_the_same_time = False

    def act(self, day: int):
        return {AbilityResultKey.INDIVIDUAL: {self.me: {AbilityResultKey.ROLE: self.__class__}}}

class ActiveAndVisiting(Visiting):
    """방문도 하고 방문하지 않고 능력 사용도 하는 직업."""
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.can_at_the_same_time = False

class KillingVisiting(Visiting, Killing):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.offense_level = Level.BASIC

    def visit(self, day: int, target: Player):
        data = super().visit(day, target)
        self.opportunity -= 1
        if self.me.visits[day] is self.me:
            data[AbilityResultKey.SOUND] = Beguiler # 마녀여도 Beguiler.
            if self.can_kill(self):
                data[AbilityResultKey.INDIVIDUAL][self.me].update({
                    AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                    AbilityResultKey.BY: self.me.controlled_by.role().__class__,
                    AbilityResultKey.BY_PUBLIC: Witch if self.me.controlled_by.role().belongs_to(Witch) else Beguiler
                })
                if self.me.controlled_by.role().belongs_to(Hiding):
                    self.me.controlled_by.commit_crime(CrimeType.MURDER)
            else:
                data[AbilityResultKey.INDIVIDUAL][self.me].update({
                    AbilityResultKey.ALMOST_DIED: True,
                    AbilityResultKey.BY: Witch if self.me.controlled_by.role().belongs_to(Witch) else Beguiler,
                })
        else:
            self.me.commit_crime(CrimeType.TRESPASS)
            if self.me.visits[day].bodyguarded_by:
                return self.me.visits[day].bodyguarded_by.pop().role().guard_from(self.me)
            data[AbilityResultKey.SOUND] = self.__class__
            if self.can_kill(self.me.visits[day].role()):
                data[AbilityResultKey.INDIVIDUAL][self.me].update({
                    AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                    AbilityResultKey.SUCCESS: True,
                })
                if self.me.visits[day].is_healed():
                    data.update(self.me.visits[day].healed_by.pop().role().heal_against(self))
                else:
                    self.me.commit_crime(CrimeType.MURDER)
                    data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                        AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                        AbilityResultKey.BY: self.__class__
                    }
            else:
                data[AbilityResultKey.INDIVIDUAL][self.me].update({
                    AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                    AbilityResultKey.SUCCESS: False,
                })
                data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                    AbilityResultKey.TYPE: AbilityResultKey.ATTACKED
                }
        return data

class CriminalKillingVisiting(KillingVisiting):
    def visit(self, day: int, target: Player):
        data = super().visit(day, target)
        if data[AbilityResultKey.SOUND] is Bodyguard:
            return data
        data[AbilityResultKey.SOUND] = Mafioso
        data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]][AbilityResultKey.BY_PUBLIC] = Mafioso
        return data

class Boss(CriminalKillingVisiting):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 999
        self.recruit_target: Optional[Player] = None
        self.immune_to_detection = True

    def second_task(self: Union[Godfather, DragonHead], day: int):
        super().second_task(day)
        offered = self.recruit_target.is_behind or self.recruit_target
        if into := offered.role().recruitable_into.get(self.__class__):
            data = {
                AbilityResultKey.INDIVIDUAL: {
                    offered: {
                        AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
                        AbilityResultKey.BY: self.__class__,
                        AbilityResultKey.INTO: into
                    }
                }
            }
            for member in self.me.room.private_chat[self.__class__.team()]:
                data[AbilityResultKey.INDIVIDUAL][member] = {
                    AbilityResultKey.TYPE: AbilityResultKey.JOINED,
                    AbilityResultKey.INDEX: offered.index,
                    AbilityResultKey.INTO: into,
                }
        else:
            data = {
                AbilityResultKey.INDIVIDUAL: {
                    self.me: {
                        AbilityResultKey.ROLE: self.__class__,
                        AbilityResultKey.TYPE: AbilityResultKey.SECOND_TASK,
                        AbilityResultKey.SUCCESS: False,
                    },
                    offered: {
                        AbilityResultKey.TYPE: AbilityResultKey.CONTACTED,
                        AbilityResultKey.BY: None,
                    }
                }
            }
        return data
    
    def after_night(self):
        super().after_night()
        self.recruit_target = None

class Healing(Visiting):
    def visit(self, day: int, target: Player):
        data = super().visit(day, target)
        self.me.visits[day].healed_by.append(self.me)
        return data
    
    def heal_against(self, attacker: Union[Role, str]):
        """피격자와 의사에게 전달될 정보를 만듭니다."""
        return {
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.ROLE: self.__class__,
                    AbilityResultKey.SUCCESS: True,
                },
                self.me.visits[self.me.room.day]: {
                    AbilityResultKey.TYPE: AbilityResultKey.HEALED,
                    AbilityResultKey.AGAINST: attacker.__class__ if isinstance(attacker, Role) else attacker,
                },
            }
        }

class Blocking(Visiting):
    def visit(self, day: int, blocked: Player):
        data = super().visit(day, blocked)
        if self.me.visits[day].role().belongs_to(Veteran) and self.me.visits[day].act[day]:
            pass
        elif self.me.visits[day].role().blockable:
            self.me.visits[day].visits[day] = None
            self.me.visits[day].act[day] = False
            if self.me.visits[day].role().belongs_to(Town):
                self.me.commit_crime(CrimeType.DISTURBING_THE_PEACE)
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.BLOCKED,
                AbilityResultKey.SUCCESS: True
            }
            self.me.visits[day].role().respond_to_block(self.me)
        self.me.commit_crime(CrimeType.SOLICITING)
        return data

class Hiding(Visiting):
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [2,3,4],
                ConstraintKey.DEFAULT: 3
            },
            ConstraintKey.NOTIFIED: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: True
            }
        }

    def visit(self, day: int, front: Player):
        data = super().visit(day, front)
        self.me.commit_crime(CrimeType.TRESPASS)
        self.opportunity -= 1
        self.me.is_behind = self.me.visits[day]
        self.me.visits[day].controlled_by = self.me
        if self.constraints[ConstraintKey.NOTIFIED]:
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.NOTIFIED,
                AbilityResultKey.BY: Hiding
            }
        return data

    def after_night(self):
        super().after_night()
        self.me.is_behind = None
        self.me.visits[self.me.room.day].controlled_by = None

class Threatening(Visiting):
    def visit(self, day: int, threatened: Player):
        data = super().visit(day, threatened)
        self.me.visits[day].blackmailed_on = day + 1
        data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
            AbilityResultKey.TYPE: AbilityResultKey.THREATENED
        }
        return data

class Sanitizing(Visiting):
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [1,2,3],
                ConstraintKey.DEFAULT: 2,
            }
        }

    def visit(self, day: int, sanitized: Player):
        data = super().visit(day, sanitized)
        self.me.commit_crime(CrimeType.TRESPASS)
        if (
            self.opportunity > 0
            and not self.me.visits[day].alive()
            and self.me.visits[day] not in self.me.room.graveyard.values()
        ):
            self.me.visits[day].dead_sanitized = True
            self.opportunity -= 1
            data[AbilityResultKey.INDIVIDUAL][self.me].update({
                AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                AbilityResultKey.SUCCESS: True,
                AbilityResultKey.LW: self.me.visits[day].lw,
            })
            return data

class Framing(Visiting):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.immune_to_detection = True

    def visit(self, day: int, framed: Player):
        data = super().visit(day, framed)
        self.me.commit_crime(CrimeType.TRESPASS)
        crime_pool = [c for c, done in self.me.visits[day].crimes.items() if not done]
        dest_pool = [evil.visits[day] for evil in self.me.room.remaining().values()
                     if evil.role().belongs_to(Mafia)
                        or evil.role().belongs_to(Triad)
                        or evil.role().belongs_to(NeutralEvil)]
        role_pool = [evil.role() for evil in self.me.room.remaining().values()
                     if evil.role().belongs_to(Mafia)
                        or evil.role().belongs_to(Triad)
                        or evil.role().belongs_to(NeutralEvil)]
        framed_crime = random.choice(crime_pool) # TODO: 가장 그럴듯한 범죄 추가.
        if crime_pool:
            self.me.visits[day].commit_crime(framed_crime)
        framed_to = random.choice(dest_pool)
        framed_to.visited_by[day].add(self.me.visits[day])
        self.me.visits[day].framed[FrameKey.TO] = framed_to
        self.me.visits[day].framed[FrameKey.ROLE] = random.choice(role_pool)
        data[AbilityResultKey.INDIVIDUAL][self.me].update({
            "framed_crime": framed_crime,
            "framed_to": framed_to.index,
            "framed_role": self.me.visits[day][FrameKey.ROLE]
        })
        return data

    def after_night(self):
        super().after_night()
        self.me.visits[self.me.room.day].framed.clear()

class Investigating(Visiting):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.ignore_immune = False

    def investigate(self, day: int, investigated: Player):
        pass

    def visit(self, day: int, investigated: Player):
        data = super().visit(day, investigated)
        data[AbilityResultKey.INDIVIDUAL][self.me][AbilityResultKey.RESULT] = self.investigate(day, self.me.visits[day])
        return data

class Following(Investigating):
    def investigate(self, day: int, investiagted: Player):
        self.me.commit_crime(CrimeType.TRESPASS)
        if framed_to := investiagted.framed.get(FrameKey.TO):
            result = {
                "visits": framed_to,
                "act": investiagted.framed[FrameKey.ROLE].belongs_to(ActiveOnly),
            }
        elif self.ignore_immune:
            result = {
                "visits": investiagted.visits[day].index
                        if investiagted.visits[day]
                        else None,
                "act": investiagted.act[day]
            }
        else:
            result = {
                "visits": investiagted.visits[day].index
                        if (not investiagted.role().immune_to_detection
                            and investiagted.visits[day])
                        else None,
                "act": False if investiagted.role().immune_to_detection
                    else investiagted.act[day]
            }
        return result

class Watching(Investigating):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.can_target_self = True
    
    def investigate(self, day: int, investigated: Player):
        self.me.commit_crime(CrimeType.TRESPASS)
        return sorted({
            v.index
            for v in self.me.room.actors_today
            if v.visits[day] is investigated
            and (v.role().belongs_to(KillingVisiting) or v.alive())
            and (self.ignore_immune or not v.role().immune_to_detection)
        })

class FollowingAndWatching(Following, Watching):
    def modifiable_constraints():
        return {
            ConstraintKey.DELAY: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            }
        }
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.ignore_immune = True

    def investigate(self, day: int, target: Player):
        result = {
            Following.__name__.upper(): Following.investigate(self, day, target),
            Watching.__name__.upper(): Watching.investigate(self, day, target)
        }
        return result
    
    def visit(self, day: int, investigated: Player):
        if self.constraints[ConstraintKey.DELAY]:
            self.rest_till = day + 1
        return super().visit(day, investigated)

class IdentityInvestigating(Investigating):
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        return {
            ConstraintKey.DETECT_EXACT_ROLE: {
                ConstraintKey.OPTIONS: ["CRIME", "ROLE"],
                ConstraintKey.DEFAULT: "ROLE",
            }
        }
    
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.detect_exact_role = self.constraints.get(ConstraintKey.DETECT_EXACT_ROLE) == "ROLE"

    def investigate(self, investigated: Player):
        self.me.commit_crime(CrimeType.TRESPASS)
        if self.detect_exact_role:
            if framed_role := investigated.framed.get(FrameKey.ROLE):
                return {"role": framed_role.name}
            if self.ignore_immune:
                return {"role": investigated.role().name}
            elif self.me.visits[self.me.room.day].role().immune_to_detection:
                return {"role": Citizen(self.me).name}
            return {"role": investigated.role().name}
        else:
            if self.ignore_immune:
                return {"crimes": {c.name:value for c, value in investigated.crimes.items()}}
            elif investigated.role().immune_to_detection:
                return {"crimes": {c.name:False for c in CrimeType}}
            return {"crimes": investigated.crimes}

class Jailing(ActiveOnly, Killing):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self._jailed = None
        self.opportunity = 2
        self.offense_level = Level.ABSOLUTE
        self.want_to_jail: Optional[Player] = None

    def jail(self, jailed: Player):
        self.me.commit_crime(CrimeType.KIDNAP)
        self._jailed = jailed
        self.is_jailing().jailed_by = self.me
        self._target_defense_level_before_jailed = self.is_jailing().role().defense_level
        self.is_jailing().role().defense_level = max(self.is_jailing().role().defense_level, Level.BASIC)
        self.is_jailing().role().respond_to_block(self.me)
        data = {
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.ROLE: self.__class__,
                    "jailed_index": self.is_jailing().index,
                },
                self.is_jailing(): {
                    AbilityResultKey.TYPE: AbilityResultKey.JAILED,
                }
            }
        }
        return data

    def act(self, day: int):
        data = super().act(day)
        self.opportunity -= 1
        self.me.commit_crime(CrimeType.MURDER)
        data[AbilityResultKey.SOUND] = Jailor
        data[AbilityResultKey.INDIVIDUAL][self.is_jailing()] = {
            AbilityResultKey.TYPE: AbilityResultKey.KILLED,
            AbilityResultKey.BY: self.__class__,
        }
        return data

    def is_jailing(self):
        return self._jailed

    def after_night(self):
        super().after_night()
        self.want_to_jail = None
        if self._jailed:
            self._jailed.jailed_by = None
            self._jailed.role().defense_level = self._target_defense_level_before_jailed
            self._jailed = None

class Surviving(ActiveOnly):
    def act(self, day: int):
        data = super().act(day)
        self.opportunity -= 1
        self.defense_level = Level.BASIC
        return data

    def after_night(self):
        super().after_night()
        self.defense_level = Level.NONE

class Crying(Role):
    pass

# Cult
class Cult(NeutralEvil):
    def against() -> set[Slot]:
        return {Town, Mafia, Triad, NeutralKilling}

    def reveal_identity_to(self: Role, to: Player):
        data = {
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.ROLE: self.__class__,
                    AbilityResultKey.TYPE: AbilityResultKey.REVEALED,
                    "to": to.nickname,
                },
                to: {
                    AbilityResultKey.ROLE: to.role().__class__,
                    AbilityResultKey.TYPE: AbilityResultKey.CONTACTED,
                    AbilityResultKey.BY: self.__class__,
                    AbilityResultKey.INDEX: self.me.index,
                }
            }
        }
        return data

    def team():
        return Cult
    
    def __init__(self) -> None:
        super().__init__()
        self.convertable = False
"""
==========
Roles
==========
"""
class Scumbag(Role, NeutralEvil):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.recruitable_into = {Godfather:Mafioso, DragonHead:Enforcer}

class Executioner(Role, NeutralBenign):
    def modifiable_constraints():
        return {
            ConstraintKey.TARGET_IS_TOWN: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: True,
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.defense_level = Level.BASIC

    def set_goal_target(self):
        pool = [
            p
            for p in self.me.room.lineup.values()
            if (
                not self.constraints[ConstraintKey.TARGET_IS_TOWN]
                or p.role().belongs_to(Town)
            ) and p is not self.me
        ]
        if pool:
            self.goal_target = {random.choice(pool)}

class Spy(Role, TownPower):
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        return {
            ConstraintKey.WIRETAP_JAILED: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            }
        }

    def team():
        return Spy
    
    def after_night(self):
        super().after_night()
        data = {
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.ROLE: Spy,
                    Mafia: {
                        "Killing": [],
                        "Visiting": [
                            visited.visits[self.me.room.day].index
                            for visited in self.me.room.actors_today
                            if visited.role().belongs_to(Mafia)
                            and visited.visits[self.me.room.day]
                            and not visited.role().belongs_to(CriminalKillingVisiting)
                        ]
                    },
                    Triad: {
                        "Killing": [],
                        "Visiting": [
                            visited.visits[self.me.room.day].index
                            for visited in self.me.room.actors_today
                            if visited.role().belongs_to(Triad)
                            and visited.visits[self.me.room.day]
                            and not visited.role().belongs_to(CriminalKillingVisiting)
                        ]
                    },
                }
            }
        }
        for m in self.me.room.actors_today:
            if m.role().belongs_to(CriminalKillingVisiting) and m.visits[self.me.room.day]:
                data[AbilityResultKey.INDIVIDUAL][self.me][m.role().__class__.team()]["Killing"] = m.visits[self.me.room.day].index
        return data

class Stump(Role, TownPower):
    not_for_first = True
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.votes = 0
        self.defense_level = Level.BASIC

class Mason(Role, TownGovernment):
    def team():
        return Mason

class Marshall(Role, TownGovernment):
    unique = True
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [1, 2],
                ConstraintKey.DEFAULT: 2
            },
            ConstraintKey.QUOTA_PER_LYNCH: {
                ConstraintKey.OPTIONS: [2, 3, 4],
                ConstraintKey.DEFAULT: 3
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.healable = False
        self.quota_per_lynch = self.constraints[ConstraintKey.QUOTA_PER_LYNCH]

    def can_activate(self):
        return not self.me.room.in_lynch and self.opportunity > 0
 
    def activate(self):
        self.opportunity -= 1
        self.me.room.in_lynch = True
        return Event(EventType.DAY_EVENT, self.me.room.members, jsonablify({
            ContentKey.ROLE: self.__class__,
            "index": self.me.index,
            "ace-attorney": self.me.room.in_court
        }))

class Mayor(Role, TownGovernment): # TODO: 능력 발동 안 한 상태에서 투표한 뒤 발동하고서 투표 빼는 경우에 득표자의 득표수가 음수가 되는 버그 수정
    unique = True
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.activated = False
        self.healable = False
    
    def can_activate(self):
        return not self.activated

    def activate(self):
        self.activated = True
        self.me.room.mayor_reveal_today = True
        self.votes = 4
        return Event(EventType.DAY_EVENT, self.me.room.members, jsonablify({
            ContentKey.ROLE: self.__class__,
            "index": self.me.index
        }))

class Judge(Crying, NeutralEvil):
    unique = True
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [1,2,],
                ConstraintKey.DEFAULT: 2,
            }
        }
    
    def can_activate(self):
        return not self.me.room.in_court and self.me.room.day > self.rest_till and self.opportunity > 0

    def activate(self):
        self.opportunity -= 1
        self.votes = 4
        self.me.room.in_court = True
        self.rest_till = self.me.room.day + 1
        return Event(EventType.DAY_EVENT, self.me.room.members, jsonablify({
            ContentKey.ROLE: self.__class__,
            "ace-attorney": self.me.room.in_lynch
        }))
    
    def after_night(self):
        super().after_night()
        self.votes = 1

class Crier(Crying, TownGovernment):
    unique = True

class Sheriff(Investigating, TownInvestigative):
    def investigate(self, day: int, investigated: Player):
        if investigated.role().immune_to_detection:
            return None
        for evil in {Mafia, Triad, SerialKiller, MassMurderer, Arsonist, Cult}:
            if (self.me.visits[day].framed.get(FrameKey.ROLE) or self.me.visits[day].role()).belongs_to(evil):
                return evil.__name__
        return None

class Coroner(Investigating, TownInvestigative):
    for_dead = True
    def investigate(self, day: int, investigated: Player):
        if investigated.death_announced():
            return {
                "role": investigated.role().name,
                "cause_of_death": investigated.cause_of_death,
                "last_target": investigated.visits[-1],
                "visitors": [sorted([visitor.role().name for visitor in visitors])
                             for visitors in investigated.visited_by[1:]],
            }
        return {"alive": True}

class Detective(Following, TownInvestigative):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.ignore_immune = True

class Lookout(Watching, TownInvestigative):
    pass

class Agent(FollowingAndWatching, MafiaSupport):
    pass

class Vanguard(FollowingAndWatching, TriadSupport):
    pass

class Investigator(IdentityInvestigating, TownInvestigative):
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        data = IdentityInvestigating.modifiable_constraints()
        data[ConstraintKey.DETECT_EXACT_ROLE][ConstraintKey.DEFAULT] = "CRIME"
        return data

class Secretary(IdentityInvestigating):
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        data = IdentityInvestigating.modifiable_constraints()
        data.update({
            ConstraintKey.PROMOTED: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: True,
            }
        })
        return data
    
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.ignore_immune = True

class Consigliere(Secretary, MafiaSupport):
    pass

class Administrator(Secretary, TriadSupport):
    pass

class Counsel(IdentityInvestigating, NeutralBenign):
    unique = True
    def modifiable_constraints():
        return {
            ConstraintKey.DEFENSE_LEVEL: {
                ConstraintKey.OPTIONS: [Level.NONE, Level.BASIC],
                ConstraintKey.DEFAULT: Level.BASIC,
            },
            ConstraintKey.IF_FAIL: {
                ConstraintKey.OPTIONS: ["SUICIDE", "BE_SCUMBAG"],
                ConstraintKey.DEFAULT: "SUICIDE",
            },
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.detect_exact_role = True
    
    def set_goal_target(self):
        self.goal_target = set(random.choices([
            p
            for p in self.me.room.remaining().values()
            if p is not self.me
        ], k=3))

    def visit(self, day: int, investigated: Player):
        data = super().visit(day, investigated)
        self.target_was_detection_immune = self.me.visits[day].role().immune_to_detection
        self.me.visits[day].role().immune_to_detection = True
        return data

    def after_night(self):
        super().after_night()
        self.me.visits[self.me.room.day].role().immune_to_detection = self.target_was_detection_immune

class Beguiler(Hiding, MafiaDeception):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 3

class Deceiver(Hiding, TriadDeception):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 3

class Escort(Blocking, TownProtective):
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        return {
            ConstraintKey.RECRUITABLE:  {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        if self.constraints[ConstraintKey.RECRUITABLE]:
            self.recruitable_into = {Godfather:Consort, DragonHead:Liaison}

class Consort(Blocking, MafiaSupport):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.blockable = False

class Liaison(Blocking, TriadSupport):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.blockable = False

class Framer(Framing, MafiaDeception):
    disabled = True

class Forger(Framing, TriadDeception):
    disabled = True

class Blackmailer(Threatening, MafiaSupport):
    pass

class Silencer(Threatening, TriadSupport):
    pass

class Janitor(Sanitizing, MafiaDeception):
    pass

class IncenseMaster(Sanitizing, TriadDeception):
    pass

class Bodyguard(Visiting, TownProtective, TownKilling):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.offense_level = Level.STRONG

    def visit(self, day: int, guarded: Player):
        data = super().visit(day, guarded)
        self.me.visits[day].bodyguarded_by.append(self.me)
        self._target_was_convertable_before_guarded = self.me.visits[day].role().convertable
        self.me.visits[day].role().convertable = False
        return data

    def guard_from(self, attacker: Player) -> dict[AbilityResultKey, dict[Player, dict[AbilityResultKey, Type[Role]]]]:
        """경호원, 공격자, 피보호자에게 갈 정보를 만듭니다."""
        if self.me.bodyguarded_by:
            return self.me.bodyguarded_by.pop().role().guard_from(attacker)
        self.healable = False
        attacker.commit_crime(CrimeType.MURDER)
        data = {
            AbilityResultKey.SOUND: self.__class__,
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.ROLE: self.__class__,
                    AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                    AbilityResultKey.BY: "DUTY",
                    "from": attacker.role().__class__
                },
                self.me.visits[self.me.room.day]: {
                    AbilityResultKey.TYPE: AbilityResultKey.BODYGUARDED,
                    "from": attacker.role().__class__
                },
            }
        }
        if attacker.bodyguarded_by:
            data.update(attacker.bodyguarded_by.pop().role().guard_from(self.me))
            data[AbilityResultKey.INDIVIDUAL][self.me][AbilityResultKey.BY] = "DUTY"
        elif self.can_kill(attacker.role()):
            if attacker.is_healed():
                data.update(attacker.healed_by.pop().heal_against(self))
            else:
                data[AbilityResultKey.INDIVIDUAL][attacker] = {
                    AbilityResultKey.ROLE: attacker.role().__class__,
                    AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                    AbilityResultKey.BY: self.__class__,
                }
                self.me.commit_crime(CrimeType.MURDER)
        else:
            data[AbilityResultKey.INDIVIDUAL][attacker] = {
                AbilityResultKey.TYPE: AbilityResultKey.ALMOST_DIED,
                AbilityResultKey.BY: self.__class__,
            }
        return data

    def after_night(self):
        super().after_night()
        self.me.visits[self.me.room.day].role().convertable = self._target_was_convertable_before_guarded

class Jailor(Jailing, TownPower, TownKilling):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 2

class Kidnapper(Jailing, MafiaKilling, MafiaSupport):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 2

class Interrogator(Jailing, TriadKilling, TriadSupport):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 2

class MasonLeader(KillingVisiting, TownKilling, Mason):
    unique = True
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.offense_level = Level.BASIC
        self.opportunity = 999

    def visit(self, day: int, target: Player): # 기본 로직은 KillingVisiting의 visit과 같아야 합니다.
        data = Visiting.visit(self, day, target)
        self.opportunity -= 1
        self._target_was_convertable_before_offered = self.me.visits[day].role().convertable
        self.me.visits[day].role().convertable = False
        if self.me.visits[day] is self.me:
            pass
        else:
            self.me.commit_crime(CrimeType.SOLICITING)
            if self.me.visits[day].role().belongs_to(Cult):
                self.me.commit_crime(CrimeType.TRESPASS)
                if self.me.visits[day].bodyguarded_by:
                    return self.me.visits[day].bodyguarded_by.pop().role().guard_from(self.me)
                data[AbilityResultKey.SOUND] = self.__class__
                if self.can_kill(self.me.visits[day].role()):
                    data[AbilityResultKey.INDIVIDUAL][self.me].update({
                        AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                        AbilityResultKey.SUCCESS: True,
                    })
                    if self.me.visits[day].is_healed():
                        data.update(self.me.visits[day].healed_by.pop().role().heal_against(self))
                    else:
                        self.me.commit_crime(CrimeType.MURDER)
                        data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                            AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                            AbilityResultKey.BY: self.__class__
                        }
                else:
                    data[AbilityResultKey.INDIVIDUAL][self.me].update({
                        AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                        AbilityResultKey.SUCCESS: False,
                    })
                    data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                        AbilityResultKey.TYPE: AbilityResultKey.ATTACKED
                    }
            else:
                self.do_second_task_today = True
        return data

    def second_task(self, day: int):
        super().second_task(day)
        if not self.me.visits[day].alive(): return
        data = {
            AbilityResultKey.INDIVIDUAL: {
                self.me: dict(),
                self.me.visits[day]: dict(),
            }
        }
        if self.me.visits[day].role().belongs_to(Citizen):
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
                AbilityResultKey.BY: self.__class__,
                AbilityResultKey.INTO: Mason,
            }
            data[AbilityResultKey.INDIVIDUAL].update({
                member: {
                    AbilityResultKey.TYPE: AbilityResultKey.JOINED,
                    AbilityResultKey.INDEX: self.me.visits[day].index,
                    AbilityResultKey.INTO: Mason,
                } for member in self.me.room.private_chat[self.__class__.team()]})
        else:
            data[AbilityResultKey.INDIVIDUAL][self.me] = {
                AbilityResultKey.ROLE: self.__class__,
                AbilityResultKey.TYPE: AbilityResultKey.SECOND_TASK,
                AbilityResultKey.SUCCESS: False
            }
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.CONTACTED,
                AbilityResultKey.BY: None,
            }
        return data

    def after_night(self):
        super().after_night()
        self.me.visits[self.me.room.day].role().convertable = self._target_was_convertable_before_offered

class Veteran(ActiveOnly, TownKilling, TownPower):
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [2,3, 4, 999],
                ConstraintKey.DEFAULT: 3,
            },
            ConstraintKey.OFFENSE_LEVEL: {
                ConstraintKey.OPTIONS: [Level.BASIC, Level.STRONG],
                ConstraintKey.DEFAULT: Level.STRONG,
            }
        }

    def act(self, day: int):
        super().act(day)
        self.opportunity -= 1
        self.me.commit_crime(CrimeType.DISTRUCTION_OF_PROPERTY)
        self.defense_level = Level.STRONG
        events = [{
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.TYPE: AbilityResultKey.ACT,
                }
            }
        }]
        for visitor in [v for v in self.me.room.actors_today if v.visits[day] is self.me and not v.role().belongs_to(Lookout)]:
            self.me.visited_by[day].add(visitor)
            event = {
                AbilityResultKey.SOUND: self.__class__,
                AbilityResultKey.INDIVIDUAL: {}
            }
            if visitor.bodyguarded_by:
                event = visitor.bodyguarded_by.pop().role().guard_from(self.me)
            elif self.can_kill(visitor.role()):
                if visitor.is_healed():
                    event.update(visitor.healed_by.pop().heal_against(self))
                else:
                    event[AbilityResultKey.INDIVIDUAL][visitor] = {
                        AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                        AbilityResultKey.BY: self.__class__,
                    }
                    self.me.commit_crime(CrimeType.MURDER)
            else:
                event[AbilityResultKey.INDIVIDUAL][visitor] = {
                    AbilityResultKey.TYPE: AbilityResultKey.ALMOST_DIED,
                    AbilityResultKey.BY: self.__class__,
                }
            events.append(event)
        return events
    
    def after_night(self):
        super().after_night()
        self.defense_level = Level.NONE

class Vigilante(KillingVisiting, TownKilling):
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [2,3,4,999,],
                ConstraintKey.DEFAULT: 3,
            },
            ConstraintKey.TARGET_IS_TOWN: {
                ConstraintKey.OPTIONS: ["SUICIDE", "LOSE_ALL_BULLETS"],
                ConstraintKey.DEFAULT: "SUICIDE",
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.rest_till = 1 # 첫날 밤 살인 불가. 단 조종당하면 가능.
    
    def visit(self, day: int, target: Player):
        data = super().visit(day, target)
        if (self.me.visits[day] is not self.me
            and self.me.visits[day].role().belongs_to(Town)
            and data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]][AbilityResultKey.TYPE] is AbilityResultKey.KILLED):
            if self.constraints[ConstraintKey.TARGET_IS_TOWN] == "LOSE_ALL_BULLETS":
                self.opportunity = 0
            return [data, {
                AbilityResultKey.SOUND: "SUICIDE",
                AbilityResultKey.INDIVIDUAL: {
                    self.me: {
                        AbilityResultKey.ROLE: Vigilante,
                        AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                        AbilityResultKey.BY: "FEELING_GUILTY_VIGILANTE"
                    }
                }
            } if self.constraints[ConstraintKey.TARGET_IS_TOWN] == "SUICIDE" else {
                AbilityResultKey.INDIVIDUAL: {
                    self.me: {
                        AbilityResultKey.ROLE: Vigilante,
                        AbilityResultKey.TYPE: "LOSE_ALL_BULLETS",
                    }
                }
            }]
        return data

class Mafioso(CriminalKillingVisiting, MafiaKilling):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 999

class Enforcer(CriminalKillingVisiting, TriadKilling):
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 999

class Godfather(Boss, MafiaKilling):
    unique = True

class DragonHead(Boss, TriadKilling):
    unique = True

class Citizen(Surviving, TownGovernment):
    default_to_exclude = True
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        return {
            ConstraintKey.RECRUITABLE: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: True,
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 1
        if self.constraints[ConstraintKey.RECRUITABLE]:
            self.recruitable_into = {Godfather:Mafioso, DragonHead:Enforcer, MasonLeader:Mason}

class Survivor(Surviving, NeutralBenign):
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [1,2,3,4],
                ConstraintKey.DEFAULT: 4,
            }
        }

class Cultist(Visiting, Cult):
    def modifiable_constraints():
        return {
            "IGNORE_NIGHT_IMMUNE": {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            },
            ConstraintKey.DELAY: {
                ConstraintKey.OPTIONS: [0, 1, 2],
                ConstraintKey.DEFAULT: 1,
            }
        }

    def visit(self, day: int, culted: Player):
        data = super().visit(day, culted)
        self.me.commit_crime(CrimeType.SOLICITING)
        if self.me.visits[day].role().belongs_to(Mason):
            return self.reveal_identity_to(self.me.visits[day])
        elif (self.me.visits[day].role().belongs_to(Mafia)
            or self.me.visits[day].role().belongs_to(Triad)
            or self.me.visits[day].role().defense_level > Level.NONE
            or not self.me.visits[day].role().convertable
            or not self.me.visits[day].alive()):
            data[AbilityResultKey.INDIVIDUAL][self.me].update({
                AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                AbilityResultKey.SUCCESS: False
            })
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.CONTACTED,
                AbilityResultKey.BY: None,
            }
        else:
            self.me.commit_crime(CrimeType.CONSPIRICY)
            if self.me.visits[day].role().belongs_to(Doctor) or self.me.visits[day].role().belongs_to(Witch):
                for index, other in self.me.room.lineup.items():
                    if other.role().belongs_to(WitchDoctor):
                        into = Cultist
                        break
                else:
                    into = WitchDoctor
            else:
                into = Cultist
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
                AbilityResultKey.BY: self.__class__,
                AbilityResultKey.INTO: into,
            }
            for member in self.me.room.private_chat[self.__class__.team()]:
                data[AbilityResultKey.INDIVIDUAL][member] = {
                    AbilityResultKey.TYPE: AbilityResultKey.JOINED,
                    AbilityResultKey.INDEX: self.me.visits[day].index,
                    AbilityResultKey.INTO: into
                }
        return data

class Doctor(Healing, TownProtective):
    def visit(self, day: int, healed: Player):
        data = super().visit(day, healed)
        self._target_was_convertable_before_healed = self.me.visits[day].role().convertable
        self.me.visits[day].role().convertable = False
        return data

    def after_night(self):
        super().after_night()
        self.me.visits[self.me.room.day].role().convertable = self._target_was_convertable_before_healed

class WitchDoctor(Healing, Cult):
    unique = True
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [1,2,3,4,],
                ConstraintKey.DEFAULT: 3,
            },
            ConstraintKey.DELAY: {
                ConstraintKey.OPTIONS: [0,1,2,],
                ConstraintKey.DEFAULT: 1,
            },
            ConstraintKey.DETECTION_IMMUNE: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: True,
            }
        }

    def visit(self, day: int, healed: Player):
        data = super().visit(day, healed)
        if self.me.visits[day].role().belongs_to(Mason):
            return self.reveal_identity_to(self.me.visits[day])
        return data

    def heal_against(self, attacker: Union[Role, str]):
        """피격자와 의사에게 전달될 정보를 만듭니다."""
        data = super().heal_against(attacker)
        if self.me.visits[self.me.room.day].role().belongs_to(Mason):
            data = self.reveal_identity_to(self.me.visits[self.me.room.day])
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[self.me.room.day]].update({
                "healed": True,
            })
        elif (self.me.visits[self.me.room.day].role().belongs_to(Mafia)
            or self.me.visits[self.me.room.day].role().belongs_to(Triad)
            or self.me.visits[self.me.room.day].role().defense_level > Level.NONE
            or not self.me.visits[self.me.room.day].role().convertable):
            pass
        else:
            self.do_second_task_today = True
        self.rest_till = self.me.room.day + self.constraints[ConstraintKey.DELAY]
        return data
    
    def second_task(self, day: int):
        if not self.me.visits[day].alive(): return
        super().second_task(day)
        self.me.commit_crime(CrimeType.CONSPIRICY)
        self.opportunity -= 1
        data = {
            AbilityResultKey.INDIVIDUAL: {
                self.me.visits[day]: {
                    AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
                    AbilityResultKey.BY: self.__class__,
                    AbilityResultKey.INTO: Cultist,
                }
            }
        }
        data[AbilityResultKey.INDIVIDUAL].update({
            member: {
                AbilityResultKey.TYPE: AbilityResultKey.JOINED,
                AbilityResultKey.INDEX: self.me.visits[self.me.room.day].index,
                AbilityResultKey.INTO: Cultist
            } for member in self.me.room.private_chat[self.__class__.team()]
        })
        return data
    
    def after_night(self):
        super().after_night()

class Jester(Role, NeutralBenign):
    def modifiable_constraints() -> Union[None, dict[Union[ConstraintKey, str], dict[ConstraintKey, Union[list, Any]]]]:
        return {
            ConstraintKey.VICTIMS: {
                ConstraintKey.OPTIONS: ["ALL", "ONE"],
                ConstraintKey.DEFAULT: "ONE"
            }
        }

class Witch(Visiting, NeutralEvil):
    def modifiable_constraints():
        return {
            ConstraintKey.NOTIFIED: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.second_target: Optional[Player] = None
        self.can_target_self = True

    def visit(self, day: int, controlled: Player):
        if destination := self.second_target:
            data = super().visit(day, controlled)
            self.me.visits[day].visits[day] = destination
            data[AbilityResultKey.INDIVIDUAL][self.me].update({
                AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                "destination": self.me.visits[day].visits[day].index,
            })
            if self.constraints[ConstraintKey.NOTIFIED]:
                data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                    AbilityResultKey.TYPE: AbilityResultKey.NOTIFIED,
                    AbilityResultKey.BY: self.__class__
                }
            return data

    def after_night(self):
        super().after_night()

class Auditor(Visiting, NeutralEvil):
    def modifiable_constraints():
        return {
            ConstraintKey.OPPORTUNITY: {
                ConstraintKey.OPTIONS: [2,3,4,],
                ConstraintKey.DEFAULT: 3,
            }
        }

    def visit(self, day: int, auditted: Player):
        data = super().visit(day, auditted)
        target_role = self.me.visits[day].role()
        if target_role is self:
            data[AbilityResultKey.INDIVIDUAL][self.me].update({
                AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
                AbilityResultKey.INTO: Stump
            })
        elif not target_role.convertable or target_role.defense_level > Level.NONE:
            data[AbilityResultKey.INDIVIDUAL][self.me].update({
                AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                AbilityResultKey.SUCCESS: False,
            })
        else:
            self.opportunity -= 1
            if target_role.belongs_to(Town):
                into = Citizen
            elif target_role.belongs_to(Mafia):
                into = Mafioso
            elif target_role.belongs_to(Triad):
                into = Enforcer
            else:
                into = Scumbag
            data[AbilityResultKey.INDIVIDUAL][self.me].update({
                AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                AbilityResultKey.SUCCESS: True,
                AbilityResultKey.INDEX: self.me.visits[day].index,
                AbilityResultKey.INTO: into
            })
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
                AbilityResultKey.BY: Auditor,
                AbilityResultKey.INTO: into
            }
        return data

class Amnesiac(Visiting, NeutralBenign):
    for_dead = True
    def modifiable_constraints():
        return {
            ConstraintKey.NOTIFIED: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            },
            "NO_TOWN": {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: True,
            }
        }
    
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.blockable = False

    def visit(self, day: int, remembered: Player):
        data = super().visit(day, remembered)
        data[AbilityResultKey.INDIVIDUAL][self.me] = {
            AbilityResultKey.TYPE: AbilityResultKey.CONVERTED,
            AbilityResultKey.INTO: self.me.visits[day].role().__class__,
            "notes": self.__class__
        }

class SerialKiller(KillingVisiting, NeutralKilling):
    default_to_exclude = False
    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.opportunity = 999
        self.offense_level = Level.BASIC
        self.defense_level = Level.BASIC
        self.blocked_by: set[Player] = set()
        self.immune_to_detection = True
    
    def against() -> set[Slot]:
        return {Town, Mafia, Triad, Cult, MassMurderer, Arsonist}
    
    def team():
        return SerialKiller

    def action_when_inactive(self, day):
        super().action_when_inactive(day)
        if self.me.jailed_by and self.me.jailed_by.act[day]:
            return
        if blockers := self.blocked_by:
            blocker = self.me.jailed_by or blockers.pop() # 차단자가 여럿이어도 한 명만 죽입니다.
            return {
                AbilityResultKey.SOUND: self.__class__,
                AbilityResultKey.INDIVIDUAL: {
                    self.me: {
                        AbilityResultKey.ROLE: self.__class__,
                        "jailbreak": True
                    },
                    blocker: {
                        AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                        AbilityResultKey.BY: self.__class__,
                        "notes": "jailbreak",
                    }
                }
            } if blocker.role().belongs_to(Jailing) else {
                AbilityResultKey.SOUND: self.__class__,
                AbilityResultKey.INDIVIDUAL: {
                    self.me: {
                        AbilityResultKey.ROLE: self.__class__,
                        "kill_blocking": True,
                    },
                    blocker: {
                        AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                        AbilityResultKey.BY: self.__class__,
                        "notes": "kill_blocking",
                    }
                }
            }

    def respond_to_block(self, blocker: Player):
        self.blocked_by.add(blocker)

    def after_night(self):
        super().after_night()
        self.blocked_by.clear()

class MassMurderer(Visiting, NeutralKilling):
    default_to_exclude = False
    def modifiable_constraints():
        return {
            ConstraintKey.DELAY: {
                ConstraintKey.OPTIONS: [1,2],
                ConstraintKey.DEFAULT: 1,
            },
            ConstraintKey.DETECTION_IMMUNE: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.offense_level = Level.BASIC
        self.defense_level = Level.BASIC
        self.immune_to_detection = self.constraints[ConstraintKey.DETECTION_IMMUNE]
        self.can_target_self = True
    
    def against() -> set[Slot]:
        return {Town, Mafia, Triad, Cult, SerialKiller, Arsonist}

    def team():
        return MassMurderer

    def visit(self, day: int, landlord: Player):
        data = super().visit(day, landlord)
        victims = {v for v in landlord.visited_by[day] if v is not self.me}
        if not landlord.visits[day] and landlord is not self.me:
            victims.add(landlord)
        data.update({
            AbilityResultKey.SOUND: self.__class__,
            AbilityResultKey.LENGTH: len(victims)
        })
        for v in victims:
            if v.bodyguarded_by:
                return v.bodyguarded_by.pop().role().guard_from(self.me)
        for v in victims:
            if self.can_kill(v.role()):
                if v.is_healed():
                    data[AbilityResultKey.INDIVIDUAL].update(v.healed_by.pop().role().heal_against(self)[AbilityResultKey.INDIVIDUAL])
                else:
                    data[AbilityResultKey.INDIVIDUAL][v] = {
                        AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                        AbilityResultKey.BY: self.__class__
                    }
        if len(victims) > 1:
            self.rest_till = day + self.constraints[ConstraintKey.DELAY]
        return data

class Arsonist(ActiveAndVisiting, NeutralKilling):
    default_to_exclude = False
    def modifiable_constraints():
        return {
            ConstraintKey.NOTIFIED: {
                ConstraintKey.OPTIONS: [True, False],
                ConstraintKey.DEFAULT: False,
            }
        }

    def __init__(self, me: Player, constraints: dict):
        super().__init__(me, constraints)
        self.offense_level = Level.ABSOLUTE
        self.defense_level = Level.BASIC
        self.opportunity = 999
        self.blocked_by: set[Player] = set()

    def against() -> set[Slot]:
        return {Town, Mafia, Triad, Cult, SerialKiller, MassMurderer}

    def team():
        return Arsonist

    def visit(self, day: int, oiled: Player):
        data = super().visit(day, oiled)
        self.me.visits[day].oiled = True
        data[AbilityResultKey.INDIVIDUAL][self.me].update({
            AbilityResultKey.TYPE: AbilityResultKey.VISIT,
            AbilityResultKey.SUCCESS: True,
            AbilityResultKey.INDEX: self.me.visits[day].index,
        })
        self.me.commit_crime(CrimeType.TRESPASS)
        if self.constraints[ConstraintKey.NOTIFIED]:
            data[AbilityResultKey.INDIVIDUAL][self.me.visits[day]] = {
                AbilityResultKey.TYPE: AbilityResultKey.NOTIFIED,
                AbilityResultKey.BY: self.__class__
            }
        return data

    def action_when_inactive(self, day: int):
        super().action_when_inactive(day)
        if self.me.jailed_by and self.me.jailed_by.act[day]: return
        if self.blocked_by:
            for blocker in self.blocked_by:
                blocker.oiled = True
            data = [{
                AbilityResultKey.INDIVIDUAL: {
                    self.me: {
                        AbilityResultKey.ROLE: self.__class__,
                        AbilityResultKey.TYPE: AbilityResultKey.VISIT,
                        AbilityResultKey.SUCCESS: True,
                        AbilityResultKey.INDEX: blocker.index
                    }
                }
            } for blocker in self.blocked_by]
            if self.constraints[ConstraintKey.NOTIFIED]:
                for i, blocker in enumerate(self.blocked_by):
                    data[i][AbilityResultKey.INDIVIDUAL][blocker] = {
                        blocker: {
                            AbilityResultKey.TYPE: AbilityResultKey.NOTIFIED,
                            AbilityResultKey.BY: self.__class__
                        }
                    }
            return data

    def act(self, day: int):
        self.me.commit_crime(CrimeType.DISTRUCTION_OF_PROPERTY)
        self.me.commit_crime(CrimeType.ARSON)
        first_victims = {v for v in self.me.room.actors_today if v.oiled}
        second_victims = {v.visits[day] for v in first_victims if len(v.visits) > day and v.visits[day] and isinstance(v.visits[day], Player)}
        victims = first_victims.union(second_victims)
        data: dict[AbilityResultKey, dict[Player, dict[AbilityResultKey, type]]] = {
            AbilityResultKey.SOUND: self.__class__,
            AbilityResultKey.INDIVIDUAL: {
                self.me: {
                    AbilityResultKey.ROLE: self.__class__,
                    AbilityResultKey.TYPE: AbilityResultKey.ACT,
                },
            }
        }
        for v in victims:
            if v.is_healed():
                data[AbilityResultKey.INDIVIDUAL].update(v.healed_by.pop().role().heal_against(self))
            else:
                self.me.commit_crime(CrimeType.MURDER)
                data[AbilityResultKey.INDIVIDUAL][v] = {
                    AbilityResultKey.TYPE: AbilityResultKey.KILLED,
                    AbilityResultKey.BY: self.__class__,
                }
        return data

    def respond_to_block(self, blocker: Player):
        self.blocked_by.add(blocker)
    
    def after_night(self):
        super().after_night()
        self.blocked_by.clear()
        self.me.oiled = False