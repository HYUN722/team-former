# 작성일: 2026-10-20 03:12 (KST)
"""팀 편성 규칙 판정.

화면(Streamlit)이나 DB와 전혀 상관없는 순수 함수만 둔다.
지원 시점 검사, 승인 직전 재검사, AI 배정안 검사가 모두 이 파일의
같은 함수를 쓰게 해서 세 군데의 판정이 어긋나지 않도록 한다.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# 공고 2.2절: 역할은 6개
ROLES: Tuple[str, ...] = (
    "기획자",
    "웹 프로그래머",
    "프론트엔드 디자이너",
    "테스터",
    "보고서 작성자",
    "발표자",
)

# 공고 2.3절: 모든 팀에 서로 다른 사람으로 1명씩 있어야 하는 역할
REQUIRED_ROLES: Tuple[str, ...] = ("기획자", "웹 프로그래머")

TEAM_MIN_SIZE = 2
TEAM_MAX_SIZE = 4


@dataclass(frozen=True)
class Student:
    student_no: str
    name: str
    main_role: str
    sub_roles: Tuple[str, ...] = ()

    def can_take(self, role: str) -> bool:
        """그 역할을 맡을 수 있는가. 주 역할이든 보조 역할이든 상관없다."""
        return role == self.main_role or role in self.sub_roles

    @property
    def role_label(self) -> str:
        if self.sub_roles:
            return f"{self.main_role} (보조: {', '.join(self.sub_roles)})"
        return self.main_role


Team = List[Student]


# ---------------------------------------------------------------
# 필수 포함 역할 계산
# ---------------------------------------------------------------
def covered_required_roles(members: Sequence[Student]) -> int:
    """팀원들이 서로 다른 사람으로 채울 수 있는 필수 포함 역할의 최대 개수.

    기획자와 웹 프로그래머는 서로 다른 학생이 맡아야 하므로, 한 학생이
    둘 다 할 수 있어도 하나로만 센다. (사람-역할 이분 매칭의 최대 매칭)
    """
    matched: Dict[str, int] = {}  # 역할 -> 그 역할을 맡기로 한 팀원의 인덱스

    def augment(member_idx: int, visited: set) -> bool:
        for role in REQUIRED_ROLES:
            if role in visited:
                continue
            if not members[member_idx].can_take(role):
                continue
            visited.add(role)
            if role not in matched or augment(matched[role], visited):
                matched[role] = member_idx
                return True
        return False

    count = 0
    for i in range(len(members)):
        if augment(i, set()):
            count += 1
    return count


def missing_required_roles(members: Sequence[Student]) -> int:
    """아직 채우지 못한 필수 포함 역할의 개수 (0, 1, 2)."""
    return len(REQUIRED_ROLES) - covered_required_roles(members)


def unfilled_required_role_names(members: Sequence[Student]) -> List[str]:
    """어느 필수 역할이 비었는지 사람이 읽을 수 있게 돌려준다 (안내 문구용)."""
    missing = []
    for role in REQUIRED_ROLES:
        if not any(m.can_take(role) for m in members):
            missing.append(role)
    if not missing and missing_required_roles(members) > 0:
        # 맡을 사람은 있지만 같은 한 사람이라 서로 다른 사람으로 못 채우는 경우
        missing.append("기획자와 웹 프로그래머를 서로 다른 사람으로")
    return missing


# ---------------------------------------------------------------
# 지원 검사
# ---------------------------------------------------------------
def check_join(applicant: Student, team_members: Sequence[Student]) -> Tuple[bool, str]:
    """이 학생이 지금 이 팀에 들어가도 되는가.

    지원 접수 시점과 승인 직전 재검사에 똑같이 쓴다.
    (공고 2.4절 "승인 직전 검사", 3장 "같은 팀에 대기 중인 지원이 여럿"의 어려운 해결)
    """
    if len(team_members) >= TEAM_MAX_SIZE:
        return False, "팀이 꽉 참"

    if any(m.main_role == applicant.main_role for m in team_members):
        return False, "같은 주 역할의 팀원이 있음"

    # 필수 포함 역할 자리 지키기 (3장의 어려운 해결, 7점)
    after = list(team_members) + [applicant]
    free_slots = TEAM_MAX_SIZE - len(after)
    if free_slots < missing_required_roles(after):
        return False, "필수 포함 역할을 맡을 학생의 자리가 모자람"

    return True, ""


def check_apply(
    applicant: Student,
    team_members: Sequence[Student],
    *,
    closed: bool,
    has_team: bool,
    has_pending: bool,
) -> Tuple[bool, str]:
    """지원 단추를 눌렀을 때의 전체 검사. 실패하면 '막힘'의 사유를 돌려준다."""
    if closed:
        return False, "모집이 마감됨"
    if has_team:
        return False, "이미 팀이 있음"
    if has_pending:
        return False, "결과를 기다리는 지원이 있음"
    return check_join(applicant, team_members)


# ---------------------------------------------------------------
# 확정 구성 검사 (공고 2.5절 4항)
# ---------------------------------------------------------------
def validate_teams(teams: Dict[int, Sequence[Student]]) -> List[str]:
    """확정하려는 팀 구성이 규칙을 지키는지. 어긴 내용을 문장으로 모아 돌려준다."""
    errors: List[str] = []
    for team_no in sorted(teams):
        members = list(teams[team_no])
        label = f"팀{team_no}"

        if len(members) < TEAM_MIN_SIZE:
            errors.append(f"{label}이 {len(members)}명임 (최소 {TEAM_MIN_SIZE}명)")
        if len(members) > TEAM_MAX_SIZE:
            errors.append(f"{label}이 {len(members)}명임 (최대 {TEAM_MAX_SIZE}명)")

        seen: Dict[str, str] = {}
        for m in members:
            if m.main_role in seen:
                errors.append(
                    f"{label}에 주 역할 '{m.main_role}'이 중복됨 "
                    f"({seen[m.main_role]}, {m.name})"
                )
            else:
                seen[m.main_role] = m.name

        for role in unfilled_required_role_names(members):
            errors.append(f"{label}에 {role}를 맡을 학생이 없음")

    return errors


def validate_assignment(
    current_teams: Dict[int, Sequence[Student]],
    unassigned: Sequence[Student],
    plan: Dict[str, int],
) -> List[str]:
    """AI가 낸 배정안을 공고 2.5절 4항의 다섯 가지로 검사한다.

    plan: {학번: 팀번호}
    """
    errors: List[str] = []
    unassigned_nos = {s.student_no for s in unassigned}
    by_no = {s.student_no: s for s in unassigned}

    # ① 팀이 없는 학생이 빠짐없이 배정됨
    for no in sorted(unassigned_nos - set(plan)):
        errors.append(f"학번 {no} 학생이 배정되지 않음")

    # ② 배정안에 엉뚱한 학생이 들어 있지 않음 / 한 학생은 한 팀에만
    #    (plan 이 dict 이므로 중복 배정은 구조상 생기지 않지만, 범위는 검사한다)
    for no in sorted(set(plan) - unassigned_nos):
        errors.append(f"학번 {no} 은 배정 대상이 아님 (이미 팀이 있거나 명단에 없음)")

    for no, team_no in plan.items():
        if team_no not in current_teams:
            errors.append(f"팀{team_no} 은 없는 팀임")

    if errors:
        return errors

    # ③④⑤ 배정 뒤의 구성으로 인원, 주 역할 중복, 필수 포함 역할 검사
    after: Dict[int, List[Student]] = {
        no: list(members) for no, members in current_teams.items()
    }
    for student_no, team_no in plan.items():
        after[team_no].append(by_no[student_no])

    return validate_teams(after)


# ---------------------------------------------------------------
# 앱이 스스로 하는 배정 (3차 모델까지 실패했을 때, 어려운 해결)
# ---------------------------------------------------------------
def solve_assignment(
    current_teams: Dict[int, Sequence[Student]],
    unassigned: Sequence[Student],
) -> Optional[Dict[str, int]]:
    """규칙을 모두 지키는 배정을 완전 탐색으로 찾는다. 없으면 None.

    이미 팀에 있는 학생은 옮기지 않는다 (공고 2.5절 3항).
    팀이 없는 학생은 최대 8명, 팀은 3~4개이므로 경우의 수가 작다.
    """
    team_nos = sorted(current_teams)
    teams: Dict[int, List[Student]] = {
        no: list(current_teams[no]) for no in team_nos
    }

    # 들어갈 수 있는 팀이 적은 학생부터 넣어야 가지치기가 빨리 된다
    def freedom(s: Student) -> int:
        return sum(
            1
            for no in team_nos
            if len(teams[no]) < TEAM_MAX_SIZE
            and not any(m.main_role == s.main_role for m in teams[no])
        )

    todo = sorted(unassigned, key=freedom)
    plan: Dict[str, int] = {}

    def need_more() -> int:
        return sum(max(0, TEAM_MIN_SIZE - len(teams[no])) for no in team_nos)

    def free_total() -> int:
        return sum(TEAM_MAX_SIZE - len(teams[no]) for no in team_nos)

    def search(i: int) -> bool:
        left = len(todo) - i
        if left < need_more() or left > free_total():
            return False

        # 남은 자리로는 필수 역할을 채울 수 없는 팀이 생기면 실패
        for no in team_nos:
            members = teams[no]
            if TEAM_MAX_SIZE - len(members) < missing_required_roles(members):
                return False

        if i == len(todo):
            return not validate_teams(teams)

        s = todo[i]
        for no in team_nos:
            members = teams[no]
            if len(members) >= TEAM_MAX_SIZE:
                continue
            if any(m.main_role == s.main_role for m in members):
                continue
            members.append(s)
            plan[s.student_no] = no
            if search(i + 1):
                return True
            members.pop()
            del plan[s.student_no]
        return False

    return dict(plan) if search(0) else None


def explain_infeasible(
    current_teams: Dict[int, Sequence[Student]],
    unassigned: Sequence[Student],
) -> str:
    """규칙을 지키는 배정이 없을 때 관리자에게 보여 줄 이유 (공고 2.5절 8항)."""
    team_nos = sorted(current_teams)
    reasons: List[str] = []

    # 이미 꽉 찼는데 필수 역할을 못 채운 팀
    for no in team_nos:
        members = list(current_teams[no])
        free = TEAM_MAX_SIZE - len(members)
        missing = unfilled_required_role_names(members)
        if missing and free < missing_required_roles(members):
            reasons.append(f"팀{no}에 {', '.join(missing)}를 맡을 학생을 넣을 자리가 없음")

    # 자리와 인원이 맞지 않는 경우
    need = sum(
        max(0, TEAM_MIN_SIZE - len(current_teams[no])) for no in team_nos
    )
    capacity = sum(TEAM_MAX_SIZE - len(current_teams[no]) for no in team_nos)
    if len(unassigned) < need:
        reasons.append(
            f"팀이 없는 학생이 {len(unassigned)}명인데 "
            f"모든 팀을 {TEAM_MIN_SIZE}명 이상으로 만들려면 {need}명이 필요함"
        )
    if len(unassigned) > capacity:
        reasons.append(
            f"팀이 없는 학생이 {len(unassigned)}명인데 남은 자리는 {capacity}개뿐임"
        )

    # 필수 역할을 맡을 사람 자체가 모자란 경우
    for role in REQUIRED_ROLES:
        teams_needing = [
            no for no in team_nos if not any(m.can_take(role) for m in current_teams[no])
        ]
        available = sum(1 for s in unassigned if s.can_take(role))
        if len(teams_needing) > available:
            reasons.append(
                f"{role}를 맡을 학생이 {available}명인데 "
                f"{len(teams_needing)}개 팀에 필요함"
            )

    if not reasons:
        reasons.append("주 역할 중복과 인원 조건을 함께 만족시키는 조합이 없음")

    return " / ".join(dict.fromkeys(reasons))
