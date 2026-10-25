# 작성일: 2026-10-20 03:55 (KST)
# 수정일: 2026-10-21 04:22 (KST) — 지원자 화면의 결과 안내가 투표 결과를 따라가도록 고침
# 수정일: 2026-10-26 03:05 (KST) — 공고 6.3절 9번에 따라 작성자 표기를 README.md 외에서 뺌
"""팀 편성 웹 앱 — 화면.


자동 채점 프로그램이 화면 요소를 Streamlit key 로 찾으므로,
공고 2.7절 표의 key 를 그대로 써야 한다 (틀리면 -5점).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import streamlit as st

import ai_assign
import db
import rules

KST = timezone(timedelta(hours=9))

# 공고 2.7절의 key 를 한곳에 모아 둔다 (오타로 채점이 멈추는 것을 막기 위함)
KEY_LOGIN_NO = "login_student_no"
KEY_LOGIN_PW = "login_password"
KEY_LOGIN_SUBMIT = "login_submit"
KEY_WHOAMI = "whoami"
KEY_RESULT = "result"
KEY_UNASSIGNED = "unassigned"
KEY_ROSTER_FILE = "admin_roster_file"
KEY_TEAM_COUNT = "admin_team_count"
KEY_START = "admin_start"
KEY_CLOSE = "admin_close"
KEY_ASSIGN = "admin_assign"
KEY_ASSIGN_STATUS = "assign_status"
KEY_CONFIRM = "admin_confirm"

AUTO_REFRESH_SEC = 4  # 채점 프로그램은 단추가 나타나기를 7초까지 기다린다

st.set_page_config(page_title="팀 편성", page_icon="👥", layout="wide")


# ---------------------------------------------------------------
# 세션 상태
# ---------------------------------------------------------------
def init_state() -> None:
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("result_text", "")
    st.session_state.setdefault("assign_messages", [])
    st.session_state.setdefault("plan", None)
    st.session_state.setdefault("plan_source", "")
    # 내가 낸 지원 중 결과를 아직 못 본 것의 id.
    # 다른 팀원이 투표해 결과가 정해지면 내 화면의 결과 안내도 따라 바뀌어야 한다.
    st.session_state.setdefault("watch_app_id", None)


def set_result(prefix: str, message: str) -> None:
    """결과 안내는 반드시 승인 / 대기 / 거절 / 막힘 중 하나로 시작한다 (공고 2.7절)."""
    st.session_state.result_text = f"{prefix}: {message}"


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------
# 공통 화면 조각
# ---------------------------------------------------------------
def render_whoami() -> None:
    user = st.session_state.user
    with st.container(key=KEY_WHOAMI, border=True):
        if user:
            role = "관리자" if user["is_admin"] else user["main_role"]
            st.markdown(f"**{user['name']}** ({user['student_no']}) · {role}")
        else:
            st.markdown("로그인하지 않음")


def render_result() -> None:
    with st.container(key=KEY_RESULT, border=True):
        text = st.session_state.result_text
        if not text:
            st.caption("결과 안내")
        elif text.startswith("승인"):
            st.success(text)
        elif text.startswith("대기"):
            st.info(text)
        else:  # 거절, 막힘
            st.warning(text)


def render_login() -> None:
    st.title("팀 편성")
    st.caption("학번과 비밀번호로 로그인하세요. 관리자는 학번에 admin 을 넣습니다.")
    with st.form("login_form", clear_on_submit=False):
        student_no = st.text_input("학번", key=KEY_LOGIN_NO)
        password = st.text_input("비밀번호", type="password", key=KEY_LOGIN_PW)
        submitted = st.form_submit_button("로그인", key=KEY_LOGIN_SUBMIT, type="primary")
    if submitted:
        user = db.login(student_no, password)
        if user is None:
            set_result("막힘", "학번이나 비밀번호가 맞지 않음")
        else:
            st.session_state.user = user
            set_result("승인", f"{user['name']} 으로 로그인함")
        st.rerun()


# ---------------------------------------------------------------
# 학생 화면
# ---------------------------------------------------------------
def member_line(student: rules.Student) -> str:
    sub = f" · 보조: {', '.join(student.sub_roles)}" if student.sub_roles else ""
    return f"- {student.name} ({student.student_no}) — 주: {student.main_role}{sub}"


@st.fragment(run_every=AUTO_REFRESH_SEC)
def student_board() -> None:
    """다른 사람의 변경을 자동으로 다시 표시한다 (3장의 어려운 해결)."""
    user = st.session_state.user
    if user is None:
        return
    state = db.load_state()
    me_id = state.student_ids.get(user["student_no"])
    my_team = state.student_team.get(me_id)
    my_pending = state.pending_of_student(me_id) if me_id else None

    # 내가 낸 지원의 결과가 다른 팀원의 투표로 정해졌으면 결과 안내를 바꾼다.
    # (안 그러면 승인된 뒤에도 "대기..." 가 남아 있다)
    watching = st.session_state.get("watch_app_id")
    if watching is not None:
        decided = db.application_result(watching)
        if decided and decided[0] != "대기":
            status, reason = decided
            set_result(status, reason or ("팀에 들어감" if status == "승인" else ""))
            st.session_state.watch_app_id = None
            st.rerun(scope="app")

    if state.closed:
        st.warning("모집이 마감되었습니다.")
    st.caption(f"내 팀: {'팀' + str(my_team) if my_team else '아직 팀이 없음'}"
               f"  ·  마지막 갱신 {now_kst()} (KST)")

    columns = st.columns(min(len(state.team_ids), 4) or 1)
    for idx, team_no in enumerate(sorted(state.team_ids)):
        members = state.team_members.get(team_no, [])
        with columns[idx % len(columns)]:
            with st.container(key=f"team_{team_no}", border=True):
                mine = " — 내 팀" if my_team == team_no else ""
                st.markdown(f"#### 팀{team_no} ({len(members)}/4){mine}")
                if members:
                    for m in members:
                        st.markdown(member_line(m))
                else:
                    st.caption("아직 팀원이 없습니다")

                # 지원 단추: 이미 팀이 있거나, 대기 중인 지원이 있거나,
                # 마감되었으면 숨긴다 (공고 2.8절)
                if me_id and not my_team and not my_pending and not state.closed:
                    if st.button("이 팀에 지원", key=f"apply_{team_no}",
                                 use_container_width=True):
                        status, reason, app_id = db.submit_application(
                            state.team_ids[team_no], me_id
                        )
                        set_result(status, reason or f"팀{team_no}")
                        st.session_state.watch_app_id = (
                            app_id if status == "대기" else None
                        )
                        st.rerun(scope="app")

                # 내 팀에 들어온 지원에 투표
                if my_team == team_no:
                    for app in state.pending_for_team(team_no):
                        applicant = state.students.get(app["student_id"])
                        if applicant is None:
                            continue
                        votes = state.votes.get(app["id"], {})
                        st.divider()
                        st.markdown(
                            f"**지원:** {applicant.name} ({applicant.student_no}) "
                            f"— 주: {applicant.main_role}"
                        )
                        st.caption(f"투표 {len(votes)}/{len(members)}")
                        if me_id in votes:
                            st.caption(f"내 투표: {votes[me_id]}")
                        else:
                            c1, c2 = st.columns(2)
                            if c1.button("찬성", key=f"vote_yes_{applicant.student_no}",
                                         use_container_width=True):
                                status, reason = db.cast_vote(app["id"], me_id, "찬성")
                                set_result(status, reason)
                                st.rerun(scope="app")
                            if c2.button("거부", key=f"vote_no_{applicant.student_no}",
                                         use_container_width=True):
                                status, reason = db.cast_vote(app["id"], me_id, "거부")
                                set_result(status, reason)
                                st.rerun(scope="app")

    if my_pending:
        team_no = next(
            (no for no, tid in state.team_ids.items() if tid == my_pending["team_id"]), "?"
        )
        st.info(f"팀{team_no}에 지원해 결과를 기다리는 중입니다.")


# ---------------------------------------------------------------
# 관리자 화면
# ---------------------------------------------------------------
def parse_roster(uploaded) -> Tuple[List[dict], str]:
    """명단 CSV 를 읽는다. 엑셀이 붙인 BOM 때문에 utf-8-sig 로 읽는다 (공고 2.6절)."""
    try:
        raw = uploaded.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], "CSV 를 UTF-8 로 읽지 못함"

    reader = csv.DictReader(io.StringIO(raw))
    needed = {"student_no", "name", "main_role", "sub_roles"}
    if not reader.fieldnames or not needed.issubset(
        {(f or "").strip() for f in reader.fieldnames}
    ):
        return [], f"CSV 의 열 이름이 달라요 (필요: {', '.join(sorted(needed))})"

    roster: List[dict] = []
    seen = set()
    for i, row in enumerate(reader, start=2):
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        no = clean.get("student_no", "")
        if not no:
            continue
        if no in seen:
            return [], f"{i}번째 줄: 학번 {no} 가 두 번 나옴"
        seen.add(no)

        main_role = clean.get("main_role", "")
        if main_role not in rules.ROLES:
            return [], f"{i}번째 줄: 주 역할 '{main_role}' 은 정해진 6개 역할이 아님"

        subs = [s.strip() for s in clean.get("sub_roles", "").split(";") if s.strip()]
        for s in subs:
            if s not in rules.ROLES:
                return [], f"{i}번째 줄: 보조 역할 '{s}' 은 정해진 6개 역할이 아님"
        if len(subs) > 2:
            return [], f"{i}번째 줄: 보조 역할은 최대 2개임"

        roster.append(
            {
                "student_no": no,
                "name": clean.get("name", ""),
                "main_role": main_role,
                "sub_roles": subs,
            }
        )

    if not roster:
        return [], "명단에 학생이 없음"
    return roster, ""


def admin_controls(state: db.State) -> None:
    st.subheader("1. 명단 올리기")
    col_a, col_b = st.columns([3, 1])
    uploaded = col_a.file_uploader("명단 CSV (UTF-8)", type=["csv"], key=KEY_ROSTER_FILE)
    team_count = col_b.number_input(
        "팀 수", min_value=1, max_value=12, value=3, step=1, key=KEY_TEAM_COUNT
    )
    if st.button("명단으로 처음 상태 만들기", key=KEY_START, type="primary"):
        if uploaded is None:
            set_result("막힘", "명단 CSV 를 먼저 고르세요")
        else:
            roster, error = parse_roster(uploaded)
            if error:
                set_result("막힘", error)
            else:
                db.reset_roster(roster, int(team_count))
                st.session_state.plan = None
                st.session_state.assign_messages = []
                set_result("승인", f"학생 {len(roster)}명, 빈 팀 {int(team_count)}개를 만듦")
        st.rerun()

    st.subheader("2. 모집 마감")
    if st.button("모집 마감", key=KEY_CLOSE, disabled=state.closed):
        if state.closed:
            set_result("막힘", "이미 마감됨")
        else:
            set_result("승인", db.close_recruiting())
        st.rerun()

    st.subheader("3. AI 배정")
    assign_clicked = st.button(
        "AI 배정", key=KEY_ASSIGN, disabled=not state.closed, type="primary"
    )
    if not state.closed:
        st.caption("모집을 마감한 뒤에 누를 수 있습니다.")

    # 진행 안내 (공고 2.7절: assign_status)
    status_container = st.container(key=KEY_ASSIGN_STATUS, border=True)
    with status_container:
        live = st.empty()
        for message in st.session_state.assign_messages:
            st.markdown(f"- {message}")
        if not st.session_state.assign_messages:
            st.caption("배정 진행 안내")

    if assign_clicked:
        run_assignment(state, live)

    render_plan(state)


def run_assignment(state: db.State, live) -> None:
    teams = state.teams_for_rules()
    unassigned = state.unassigned
    messages: List[str] = []

    def on_status(message: str) -> None:
        messages.append(message)
        live.info(message)

    live.info("배정을 시작합니다…")
    plan, source, attempts = ai_assign.assign(
        teams,
        unassigned,
        api_key=db.secret("OPENROUTER_API_KEY"),
        models=ai_assign.models_from(db.secret),
        on_status=on_status,
        on_log=db.log_ai_call,
    )

    st.session_state.assign_messages = attempts + [f"결과: {source}"]

    if plan is None:
        reason = rules.explain_infeasible(teams, unassigned)
        st.session_state.assign_messages.append(f"규칙을 지키는 배정이 없음 — {reason}")
        st.session_state.plan = None
        set_result("막힘", f"규칙을 지키는 배정이 없음 ({reason})")
    else:
        errors = rules.validate_assignment(teams, unassigned, plan)
        if errors:
            st.session_state.plan = None
            st.session_state.assign_messages.append(f"마지막 검사에서 걸림 — {errors[0]}")
            set_result("막힘", f"배정안이 검사를 통과하지 못함 ({errors[0]})")
        else:
            st.session_state.plan = plan
            st.session_state.plan_source = source
            set_result("승인", f"배정안을 만듦 ({source}). 확인 후 확정하세요")
    st.rerun()


def render_plan(state: db.State) -> None:
    plan = st.session_state.plan
    if not plan:
        return
    st.subheader("4. 배정안 확인과 확정")
    st.caption(st.session_state.plan_source)

    by_no = {s.student_no: s for s in state.unassigned}
    rows = []
    for student_no, team_no in sorted(plan.items(), key=lambda kv: (kv[1], kv[0])):
        s = by_no.get(student_no)
        if s is None:
            continue
        rows.append(
            {
                "학번": s.student_no,
                "이름": s.name,
                "주 역할": s.main_role,
                "보조 역할": ", ".join(s.sub_roles) or "-",
                "배정된 팀": f"팀{team_no}",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if st.button("배정안 확정", key=KEY_CONFIRM, type="primary"):
        try:
            message = db.finalize_assignment(plan)
            st.session_state.plan = None
            set_result("승인", message)
        except Exception as exc:
            set_result("막힘", f"확정하지 못함 ({exc})")
        st.rerun()


@st.fragment(run_every=AUTO_REFRESH_SEC)
def admin_board() -> None:
    state = db.load_state()
    st.subheader("지금의 팀 구성")
    st.caption(f"마지막 갱신 {now_kst()} (KST)")
    columns = st.columns(min(len(state.team_ids), 4) or 1)
    for idx, team_no in enumerate(sorted(state.team_ids)):
        members = state.team_members.get(team_no, [])
        with columns[idx % len(columns)]:
            with st.container(key=f"team_{team_no}", border=True):
                st.markdown(f"#### 팀{team_no} ({len(members)}/4)")
                if members:
                    for m in members:
                        st.markdown(member_line(m))
                else:
                    st.caption("아직 팀원이 없습니다")
                for app in state.pending_for_team(team_no):
                    applicant = state.students.get(app["student_id"])
                    if applicant:
                        votes = state.votes.get(app["id"], {})
                        st.caption(
                            f"대기 중인 지원: {applicant.name} "
                            f"(투표 {len(votes)}/{len(members)})"
                        )

    with st.container(key=KEY_UNASSIGNED, border=True):
        st.markdown("#### 팀이 없는 학생")
        left = state.unassigned
        if left:
            for s in left:
                st.markdown(member_line(s))
        else:
            st.caption("없습니다")


def render_admin() -> None:
    st.title("관리자 화면")
    state = db.load_state()
    admin_controls(state)
    st.divider()
    admin_board()


# ---------------------------------------------------------------
# 들어가는 곳
# ---------------------------------------------------------------
def main() -> None:
    init_state()

    if not db.secret_exists("DATABASE_URL"):
        st.error("DATABASE_URL 이 없습니다. .env 또는 Streamlit Secrets 를 확인하세요.")
        st.stop()
    db.ensure_admin()

    user = st.session_state.user
    if user is None:
        render_whoami()
        render_result()
        render_login()
        return

    render_whoami()
    render_result()

    with st.sidebar:
        st.markdown(f"**{user['name']}**")
        st.caption("키 설정 상태")
        st.caption(f"- DATABASE_URL: {'있음' if db.secret_exists('DATABASE_URL') else '없음'}")
        st.caption(f"- OPENROUTER_API_KEY: {'있음' if db.secret_exists('OPENROUTER_API_KEY') else '없음'}")
        st.caption(f"- ADMIN_PASSWORD: {'있음' if db.secret_exists('ADMIN_PASSWORD') else '없음'}")
        if st.button("로그아웃"):
            st.session_state.user = None
            st.session_state.result_text = ""
            st.rerun()

    if user["is_admin"]:
        render_admin()
    else:
        st.title("팀 목록")
        student_board()


main()
