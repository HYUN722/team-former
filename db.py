# 작성일: 2026-10-20 03:42 (KST)
# 수정일: 2026-10-20 04:58 (KST) — _members_of 의 order by 를 min(m.slot_no) 로 고침 (GroupingError)
# 수정일: 2026-10-21 04:22 (KST) — submit_application 이 지원 id 를 돌려주고, application_result 추가
"""Supabase(PostgreSQL) 연결과 질의.

연결은 앱 전체에서 한 번만 만들어(st.cache_resource) 연결 풀로 재사용한다.
키 값(DATABASE_URL, ADMIN_PASSWORD 등)은 절대 화면에 출력하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import bcrypt
import streamlit as st
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import rules
from rules import Student

try:  # 로컬에서는 .env, 배포에서는 Streamlit Secrets
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


# ---------------------------------------------------------------
# 비밀 값
# ---------------------------------------------------------------
def secret(name: str) -> Optional[str]:
    """Streamlit Secrets -> 환경 변수 순으로 찾는다. 값은 돌려주기만 하고 출력하지 않는다."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name)


def secret_exists(name: str) -> bool:
    """키가 있는지 '있음/없음'만 알려 준다 (공고 4.1절)."""
    return bool(secret(name))


# ---------------------------------------------------------------
# 연결 풀 (공고 4.2절: 연결은 한 번만 만들고 다시 쓴다)
# ---------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_pool() -> ConnectionPool:
    url = secret("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL 이 설정되지 않았습니다. .env 또는 Streamlit Secrets를 확인하세요."
        )
    return ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=5,
        timeout=20,
        max_idle=300,
        kwargs={
            "row_factory": dict_row,
            # Supabase 트랜잭션 풀러(6543 포트)에서는 prepared statement를 쓰면 안 된다
            "prepare_threshold": None,
            "autocommit": True,
        },
        open=True,
    )


def fetch(sql: str, params: Sequence = ()) -> List[dict]:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql: str, params: Sequence = ()) -> Optional[dict]:
    rows = fetch(sql, params)
    return rows[0] if rows else None


def run(sql: str, params: Sequence = ()) -> None:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)


# ---------------------------------------------------------------
# 비밀번호 (공고 6.3절 10번: 해시하지 않으면 -2점)
# ---------------------------------------------------------------
def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def ensure_admin() -> bool:
    """앱이 시작할 때 관리자 계정을 만들거나 비밀번호를 갱신한다 (공고 2.1절)."""
    pw = secret("ADMIN_PASSWORD")
    if not pw:
        return False
    run(
        """
        insert into tf_students (student_no, name, main_role, password_hash, is_admin)
        values ('admin', '관리자', '기획자', %s, true)
        on conflict (student_no) do update
            set password_hash = excluded.password_hash,
                is_admin = true
        """,
        (hash_password(pw),),
    )
    return True


def login(student_no: str, password: str) -> Optional[dict]:
    """학번과 비밀번호가 모두 맞을 때만 사용자 정보를 돌려준다."""
    if not student_no or not password:
        return None
    row = fetch_one(
        "select id, student_no, name, main_role, password_hash, is_admin "
        "from tf_students where student_no = %s",
        (student_no.strip(),),
    )
    if not row:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "student_no": row["student_no"],
        "name": row["name"],
        "main_role": row["main_role"],
        "is_admin": row["is_admin"],
    }


# ---------------------------------------------------------------
# 설정
# ---------------------------------------------------------------
def get_setting(key: str) -> Optional[str]:
    row = fetch_one("select value from tf_settings where key = %s", (key,))
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    run(
        "insert into tf_settings (key, value) values (%s, %s) "
        "on conflict (key) do update set value = excluded.value",
        (key, value),
    )


# ---------------------------------------------------------------
# 화면 한 번을 그리는 데 필요한 상태를 모아서 읽는다
# ---------------------------------------------------------------
@dataclass
class State:
    students: Dict[int, Student] = field(default_factory=dict)      # id -> Student
    student_ids: Dict[str, int] = field(default_factory=dict)       # 학번 -> id
    team_ids: Dict[int, int] = field(default_factory=dict)          # 팀번호 -> team_id
    team_members: Dict[int, List[Student]] = field(default_factory=dict)  # 팀번호 -> 팀원
    member_slots: Dict[int, List[int]] = field(default_factory=dict)      # 팀번호 -> 쓰인 slot
    student_team: Dict[int, int] = field(default_factory=dict)      # 학생 id -> 팀번호
    pending: List[dict] = field(default_factory=list)               # 대기 중인 지원
    votes: Dict[int, Dict[int, str]] = field(default_factory=dict)  # 지원 id -> {투표자 id: 찬성/거부}
    closed: bool = False
    confirmed: bool = False

    @property
    def unassigned(self) -> List[Student]:
        return [
            s for sid, s in sorted(self.students.items(), key=lambda kv: kv[1].student_no)
            if sid not in self.student_team
        ]

    def teams_for_rules(self) -> Dict[int, List[Student]]:
        return {no: list(self.team_members.get(no, [])) for no in sorted(self.team_ids)}

    def pending_for_team(self, team_no: int) -> List[dict]:
        tid = self.team_ids.get(team_no)
        return [a for a in self.pending if a["team_id"] == tid]

    def pending_of_student(self, student_id: int) -> Optional[dict]:
        for a in self.pending:
            if a["student_id"] == student_id:
                return a
        return None


def _to_student(row: dict) -> Student:
    subs = tuple(r for r in (row.get("sub_roles") or []) if r)
    return Student(row["student_no"], row["name"], row["main_role"], subs)


def load_state() -> State:
    """화면 한 번을 그리는 데 필요한 모든 것을 6번의 질의로 읽는다."""
    st_ = State()

    for row in fetch(
        """
        select s.id, s.student_no, s.name, s.main_role,
               coalesce(array_agg(r.role) filter (where r.role is not null), '{}') as sub_roles
        from tf_students s
        left join tf_student_sub_roles r on r.student_id = s.id
        where s.is_admin = false
        group by s.id
        order by s.student_no
        """
    ):
        st_.students[row["id"]] = _to_student(row)
        st_.student_ids[row["student_no"]] = row["id"]

    for row in fetch("select id, no from tf_teams order by no"):
        st_.team_ids[row["no"]] = row["id"]
        st_.team_members[row["no"]] = []
        st_.member_slots[row["no"]] = []

    id_to_no = {tid: no for no, tid in st_.team_ids.items()}
    for row in fetch("select team_id, slot_no, student_id from tf_members order by team_id, slot_no"):
        no = id_to_no.get(row["team_id"])
        student = st_.students.get(row["student_id"])
        if no is None or student is None:
            continue
        st_.team_members[no].append(student)
        st_.member_slots[no].append(row["slot_no"])
        st_.student_team[row["student_id"]] = no

    st_.pending = fetch(
        "select id, team_id, student_id, created_at from tf_applications "
        "where status = '대기' order by created_at, id"
    )
    if st_.pending:
        ids = [a["id"] for a in st_.pending]
        for row in fetch(
            "select application_id, voter_id, vote from tf_votes where application_id = any(%s)",
            (ids,),
        ):
            st_.votes.setdefault(row["application_id"], {})[row["voter_id"]] = row["vote"]

    settings = {r["key"]: r["value"] for r in fetch("select key, value from tf_settings")}
    st_.closed = settings.get("closed") == "1"
    st_.confirmed = settings.get("assignment_confirmed") == "1"
    return st_


# ---------------------------------------------------------------
# 명단 올리기 (공고 2.6절)
# ---------------------------------------------------------------
def reset_roster(roster: List[dict], team_count: int) -> None:
    """지원, 투표, 팀원, 마감 표시를 모두 지우고 학생과 빈 팀을 새로 만든다.

    관리자 계정은 남긴다.
    """
    shared_hash = hash_password("1234")  # 학생 비밀번호는 모두 1234 (공고 2.2절)
    with get_pool().connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("delete from tf_votes")
            cur.execute("delete from tf_applications")
            cur.execute("delete from tf_members")
            cur.execute("delete from tf_student_sub_roles")
            cur.execute("delete from tf_students where is_admin = false")
            cur.execute("delete from tf_teams")
            cur.execute("delete from tf_settings")
            cur.execute("delete from tf_ai_logs")

            for r in roster:
                cur.execute(
                    "insert into tf_students (student_no, name, main_role, password_hash) "
                    "values (%s, %s, %s, %s) returning id",
                    (r["student_no"], r["name"], r["main_role"], shared_hash),
                )
                sid = cur.fetchone()["id"]
                for role in r["sub_roles"]:
                    cur.execute(
                        "insert into tf_student_sub_roles (student_id, role) values (%s, %s) "
                        "on conflict do nothing",
                        (sid, role),
                    )

            for n in range(1, team_count + 1):
                cur.execute(
                    "insert into tf_teams (no, name) values (%s, %s)", (n, f"팀{n}")
                )


# ---------------------------------------------------------------
# 지원과 투표
# ---------------------------------------------------------------
def _free_slot(cur, team_id: int) -> Optional[int]:
    cur.execute("select slot_no from tf_members where team_id = %s", (team_id,))
    used = {r["slot_no"] for r in cur.fetchall()}
    for n in range(1, rules.TEAM_MAX_SIZE + 1):
        if n not in used:
            return n
    return None


def _members_of(cur, team_id: int) -> List[Student]:
    cur.execute(
        """
        select s.id, s.student_no, s.name, s.main_role,
               coalesce(array_agg(r.role) filter (where r.role is not null), '{}') as sub_roles
        from tf_members m
        join tf_students s on s.id = m.student_id
        left join tf_student_sub_roles r on r.student_id = s.id
        where m.team_id = %s
        group by s.id
        order by min(m.slot_no)
        """,
        (team_id,),
    )
    return [_to_student(r) for r in cur.fetchall()]


def _member_ids_of(cur, team_id: int) -> List[int]:
    cur.execute("select student_id from tf_members where team_id = %s", (team_id,))
    return [r["student_id"] for r in cur.fetchall()]


def submit_application(team_id: int, student_id: int) -> Tuple[str, str, Optional[int]]:
    """지원 단추를 눌렀을 때. 반환: (결과, 사유, 지원 id)  결과는 승인 / 대기 / 막힘.

    지원 id 는 화면이 그 지원의 결과를 뒤에 확인하는 데 쓴다.
    """
    with get_pool().connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            # 같은 팀에 대한 동시 처리를 줄 세운다
            cur.execute("select id from tf_teams where id = %s for update", (team_id,))
            if cur.fetchone() is None:
                return "막힘", "없는 팀임", None

            cur.execute("select value from tf_settings where key = 'closed'")
            row = cur.fetchone()
            closed = bool(row and row["value"] == "1")

            cur.execute(
                """
                select s.id, s.student_no, s.name, s.main_role,
                       coalesce(array_agg(r.role) filter (where r.role is not null), '{}') as sub_roles
                from tf_students s
                left join tf_student_sub_roles r on r.student_id = s.id
                where s.id = %s
                group by s.id
                """,
                (student_id,),
            )
            srow = cur.fetchone()
            if srow is None:
                return "막힘", "학생을 찾을 수 없음", None
            applicant = _to_student(srow)

            cur.execute("select 1 from tf_members where student_id = %s", (student_id,))
            has_team = cur.fetchone() is not None
            cur.execute(
                "select 1 from tf_applications where student_id = %s and status = '대기'",
                (student_id,),
            )
            has_pending = cur.fetchone() is not None

            members = _members_of(cur, team_id)
            ok, reason = rules.check_apply(
                applicant, members, closed=closed, has_team=has_team, has_pending=has_pending
            )
            if not ok:
                # 막힌 지원은 DB에 기록하지 않는다 (공고 2.4절)
                return "막힘", reason, None

            cur.execute(
                "insert into tf_applications (team_id, student_id, status) "
                "values (%s, %s, '대기') returning id",
                (team_id, student_id),
            )
            app_id = cur.fetchone()["id"]

            if not members:
                # 빈 팀: 투표할 팀원이 없으므로 바로 승인 (공고 2.4절)
                slot = _free_slot(cur, team_id)
                cur.execute(
                    "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
                    (team_id, slot, student_id),
                )
                cur.execute(
                    "update tf_applications set status = '승인', decided_at = now() where id = %s",
                    (app_id,),
                )
                return "승인", "빈 팀이라 바로 승인함", app_id

            return "대기", "팀원의 투표를 기다리는 중", app_id


def cast_vote(application_id: int, voter_id: int, vote: str) -> Tuple[str, str]:
    """찬성/거부 단추를 눌렀을 때. 반환: (그 지원의 지금 상태, 사유)."""
    with get_pool().connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "select a.id, a.team_id, a.student_id, a.status "
                "from tf_applications a where a.id = %s for update",
                (application_id,),
            )
            app = cur.fetchone()
            if app is None:
                return "막힘", "없는 지원임"
            cur.execute("select id from tf_teams where id = %s for update", (app["team_id"],))

            cur.execute("select value from tf_settings where key = 'closed'")
            row = cur.fetchone()
            if row and row["value"] == "1":
                return "막힘", "모집이 마감됨"

            if app["status"] != "대기":
                return app["status"], "이미 결과가 나온 지원임"

            member_ids = _member_ids_of(cur, app["team_id"])
            if voter_id not in member_ids:
                return "막힘", "그 팀의 팀원이 아님"

            cur.execute(
                "insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s) "
                "on conflict (application_id, voter_id) do nothing",
                (application_id, voter_id, vote),
            )

            if vote == "거부":
                # 다른 팀원의 투표를 기다리지 않고 바로 거절 (공고 2.4절)
                cur.execute(
                    "update tf_applications set status = '거절', reason = %s, decided_at = now() "
                    "where id = %s",
                    ("팀원이 거부함", application_id),
                )
                return "거절", "팀원이 거부함"

            cur.execute(
                "select voter_id from tf_votes where application_id = %s", (application_id,)
            )
            voted = {r["voter_id"] for r in cur.fetchall()}
            if not set(member_ids).issubset(voted):
                return "대기", "아직 투표하지 않은 팀원이 있음"

            # 전원 찬성 -> 승인 직전 재검사 (공고 2.4절, 3장의 어려운 해결)
            members = _members_of(cur, app["team_id"])
            cur.execute(
                """
                select s.id, s.student_no, s.name, s.main_role,
                       coalesce(array_agg(r.role) filter (where r.role is not null), '{}') as sub_roles
                from tf_students s
                left join tf_student_sub_roles r on r.student_id = s.id
                where s.id = %s
                group by s.id
                """,
                (app["student_id"],),
            )
            applicant = _to_student(cur.fetchone())

            ok, reason = rules.check_join(applicant, members)
            if not ok:
                cur.execute(
                    "update tf_applications set status = '거절', reason = %s, decided_at = now() "
                    "where id = %s",
                    (f"승인 직전 검사: {reason}", application_id),
                )
                return "거절", f"승인 직전 검사에서 걸림 ({reason})"

            slot = _free_slot(cur, app["team_id"])
            if slot is None:
                cur.execute(
                    "update tf_applications set status = '거절', reason = %s, decided_at = now() "
                    "where id = %s",
                    ("승인 직전 검사: 팀이 꽉 참", application_id),
                )
                return "거절", "승인 직전 검사에서 걸림 (팀이 꽉 참)"

            cur.execute(
                "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
                (app["team_id"], slot, app["student_id"]),
            )
            cur.execute(
                "update tf_applications set status = '승인', decided_at = now() where id = %s",
                (application_id,),
            )
            return "승인", "모든 팀원이 찬성함"


def application_result(application_id: int) -> Optional[Tuple[str, str]]:
    """지원 하나의 지금 상태를 돌려준다. (상태, 사유)

    지원한 학생의 화면이 다른 사람의 투표 결과를 따라잡는 데 쓴다.
    """
    row = fetch_one(
        "select status, reason from tf_applications where id = %s", (application_id,)
    )
    if row is None:
        return None
    return row["status"], (row["reason"] or "")


# ---------------------------------------------------------------
# 마감 (공고 2.5절 1~2항)
# ---------------------------------------------------------------
def close_recruiting() -> str:
    with get_pool().connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "insert into tf_settings (key, value) values ('closed', '1') "
                "on conflict (key) do update set value = '1'"
            )
            cur.execute(
                "update tf_applications set status = '거절', reason = '모집 마감', "
                "decided_at = now() where status = '대기'"
            )
            rejected = cur.rowcount
            cur.execute(
                """
                delete from tf_members
                where team_id in (
                    select team_id from tf_members group by team_id having count(*) = 1
                )
                """
            )
            dropped = cur.rowcount
    return f"모집을 마감함 (대기 지원 {rejected}건 거절, 1명뿐인 팀의 학생 {dropped}명 해제)"


# ---------------------------------------------------------------
# 배정 확정 (공고 2.5절 7항)
# ---------------------------------------------------------------
def finalize_assignment(plan: Dict[str, int]) -> str:
    """plan: {학번: 팀번호}"""
    with get_pool().connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("select id, no from tf_teams")
            team_id_of = {r["no"]: r["id"] for r in cur.fetchall()}
            cur.execute("select id, student_no from tf_students where is_admin = false")
            sid_of = {r["student_no"]: r["id"] for r in cur.fetchall()}

            for student_no, team_no in plan.items():
                team_id = team_id_of.get(team_no)
                student_id = sid_of.get(student_no)
                if team_id is None or student_id is None:
                    raise RuntimeError(f"배정안에 잘못된 값이 있음 ({student_no} -> 팀{team_no})")
                slot = _free_slot(cur, team_id)
                if slot is None:
                    raise RuntimeError(f"팀{team_no}에 빈 자리가 없음")
                cur.execute(
                    "insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)",
                    (team_id, slot, student_id),
                )
            cur.execute(
                "insert into tf_settings (key, value) values ('assignment_confirmed', '1') "
                "on conflict (key) do update set value = '1'"
            )
    return f"배정을 확정함 ({len(plan)}명)"


# ---------------------------------------------------------------
# AI 호출 기록
# ---------------------------------------------------------------
def log_ai_call(attempt_no: int, model: str, ok: bool, elapsed_ms: int,
                error: str = "", raw_excerpt: str = "") -> None:
    try:
        run(
            "insert into tf_ai_logs (attempt_no, model, ok, elapsed_ms, error, raw_excerpt) "
            "values (%s, %s, %s, %s, %s, %s)",
            (attempt_no, model, ok, elapsed_ms, error[:500], raw_excerpt[:1000]),
        )
    except Exception:
        pass  # 기록 실패가 배정을 막으면 안 된다
