import re
from typing import Callable, TYPE_CHECKING
import bcrypt
import asyncio
import aiosqlite
from datetime import datetime
from log import logger

if TYPE_CHECKING:
    from game import GameData
"""
DB 구조
1. user DB: 테이블 하나만 있음. 각 행에는 유저의 정보가 있음.
    1.1. 테이블 이름: "User"
        ID|Username|Password|Permission|Banned|Since|Setup1|Setup2|Setup3|...|Setup10
2. 전적 DB: 유저별로 테이블이 하나씩 있고, 테이블 각 행에는 그 유저가 플레이한 게임이 있음.
    2.1. 테이블 이름: "(User의 id)"
        순번|게임 ID
3. 게임 메타데이터 DB: 테이블 하나만 있음. 각 행에는 게임 ID, 게임 정보, 그 게임에 참여한 유저들이 있음.
    2.1. 테이블 이름: "EachGameMetadata"
        게임 ID|설정 이름|설정 주인|직업 구성|직업 설정|제외 설정|총원|참가자 1|참가자 2|참가자 3|...|참가자 15 (15인 미만이면 나머지는 NULL.)
4. 인게임 기록 DB: 게임별로 테이블이 하나씩 있고, 각 행에는 인게임 기록이 있음.
    4.1. 테이블 이름: "(게임의 ID)"
        순번|이벤트|내용|...
5. 견본 닉네임 DB: 테이블이 하나 있고 각 행에는 견본 닉네임이 있음.
    4.1. 테이블 이름: "SampleNicknames"
        순번|닉네임
"""
USERS_DB_PATH = "sql/users.db"
GAMES_PER_USER_DB_PATH = "sql/games-per-user.db"
EACH_GAME_METADATA_DB_PATH = "sql/each-game-metadata.db"
INGAME_RECORDS_DB_PATH = "sql/records.db"
SAMPLE_NICKNAMES_DB_PATH = "sql/sample-nicknames.db"
USER_TABLE_NAME = "Users"
EACH_GAME_METADATA_TABLE_NAME = "EachGameMetadata"
SAMPLE_NICKNAMES_TABLE_NAME = "SampleNicknames"
proper_name: Callable[[str], bool] = lambda name: name!='' and len(re.findall('[가-힣]|[a-z]|[A-Z]|[0-9]', name)) == len(name)
async def create_user_database():
    async with aiosqlite.connect(USERS_DB_PATH) as DB:
        await DB.execute(f"""
            CREATE TABLE IF NOT EXISTS {USER_TABLE_NAME} (
                ID INTEGER NOT NULL UNIQUE,
                Username text NOT NULL UNIQUE,
                Password text NOT NULL,
                Permission text NOT NULL,
                Banned bool not null default false,
                Since date NOT NULL,
                Setup1 text,
                Setup2 text,
                Setup3 text,
                Setup4 text,
                Setup5 text,
                Setup6 text,
                Setup7 text,
                Setup8 text,
                Setup9 text,
                Setup10 text,
            )
        """)

async def create_game_metadata_database():
    async with aiosqlite.connect(EACH_GAME_METADATA_DB_PATH) as DB:
        await DB.execute(f"""
            CREATE TABLE IF NOT EXISTS {EACH_GAME_METADATA_TABLE_NAME} (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                Title text not null,
                Inventor integer not null,
                Formation text not null,
                Constraints text not null,
                Exclusion text not null,
                Total INTEGER NOT NULL,
                Player1 INTEGER,
                Player2 INTEGER,
                Player3 INTEGER,
                Player4 INTEGER,
                Player5 INTEGER,
                Player6 INTEGER,
                Player7 INTEGER,
                Player8 INTEGER,
                Player9 INTEGER,
                Player10 INTEGER,
                Player11 INTEGER,
                Player12 INTEGER,
                Player13 INTEGER,
                Player14 INTEGER,
                Player15 INTEGER
            )
        """)

async def create_sample_nickname_database():
    async with aiosqlite.connect(SAMPLE_NICKNAMES_DB_PATH) as DB:
        await DB.execute(f"""
            CREATE TABLE IF NOT EXISTS {SAMPLE_NICKNAMES_TABLE_NAME} (
                Index integer primary key autoincrement,
                nickname text not null
            )
        """)

async def create_user(id: int, username: str, password: str):
    async with aiosqlite.connect(USERS_DB_PATH) as DB:
        await DB.execute("""
            INSERT INTO Users (ID, Username, Password, Permission, Since)
            VALUES (
                ?, ?, ?, ?, ?
            )
        """, (id, username, bcrypt.hashpw(password, bcrypt.gensalt()), "basic", str(datetime.now())))
    async with aiosqlite.connect(GAMES_PER_USER_DB_PATH) as DB:
        await DB.execute(f"""
            CREATE TABLE {id} (
                Index INTEGER primary key,
                ID INTEGER NOT NULL UNIQUE
            )
        """)

async def archive(game_data: "GameData"):
    async with aiosqlite.connect(EACH_GAME_METADATA_DB_PATH) as DB:
        cursor = await DB.execute(f"""
            SELECT seq FROM sqlite_sequence where name="{EACH_GAME_METADATA_TABLE_NAME}"
        """)
        row = await cursor.fetchone()
        id_for_this_game = row[0]+1 if row else 1
    logger.info(f"ARCHIVING: {id_for_this_game}")
    async with aiosqlite.connect(INGAME_RECORDS_DB_PATH) as DB:
        await DB.execute(f"""
            CREATE TABLE "{id_for_this_game}" (
                index integer primary key autoincrement,
                text not null
            )
        """)
        async def _insert_one_record(line: dict):
            await DB.execute(f"""
                INSERT INTO {id_for_this_game} (text)
                VALUES (?)
            """, (str(line)))
        await asyncio.gather(*[_insert_one_record(line) for line in game_data.record])
    async with aiosqlite.connect(EACH_GAME_METADATA_DB_PATH) as DB:
        setup = game_data.setup
        query =  f"INSERT INTO {EACH_GAME_METADATA_TABLE_NAME} (Title, Inventor, Formation, Constraints, Exclusion, Total"
        values = f"VALUES (?, ?, ?, ?"
        for i, in range(game_data.lineup):
            query += f", Player{i+1}"
            values += f", ?"
        query += ")"
        values += ")"
        await DB.execute(query + values, [
            setup.title,
            setup.inventor,
            setup.formation,
            setup.constraints,
            setup.exclusion,
            len(game_data.lineup)
        ]+[user.id for user in game_data.lineup])
    logger.info(f"ARCHIVED: {id_for_this_game}")

async def add_sample_nickname(nickname: str):
    pass # TODO