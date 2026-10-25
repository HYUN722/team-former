# 작성일: 2026-10-20 03:16 (KST)
"""공고 부록의 연습용 시나리오 3개로 rules.py 를 검증한다.

앱을 띄우지 않고 규칙 판정만 확인하는 시험이다.
실행: python tests/test_rules.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules import (  # noqa: E402
    Student,
    check_join,
    solve_assignment,
    validate_teams,
)

PL = "기획자"
WP = "웹 프로그래머"
FD = "프론트엔드 디자이너"
TT = "테스터"
RW = "보고서 작성자"
PT = "발표자"


def S(no, name, main, *subs):
    return Student(no, name, main, tuple(subs))


ok_count = 0
fail_count = 0


def expect(label, got, want):
    global ok_count, fail_count
    if got == want:
        ok_count += 1
        print(f"  통과  {label}: {got}")
    else:
        fail_count += 1
        print(f"  실패  {label}: 받은 값 {got!r} / 기대 {want!r}")


def first_word(result):
    ok, reason = result
    return "승인/대기" if ok else f"막힘({reason})"


# ===============================================================
# 부록 1. 쉬움 — 팀 3개
# ===============================================================
print("\n[부록 1] 쉬움")

e1 = S("2026101", "학생1(PL;RW)", PL, RW)
e2 = S("2026102", "학생2(PL;PT)", PL, PT)
e3 = S("2026103", "학생3(PL;TT)", PL, TT)
e4 = S("2026104", "학생4(WP;FD)", WP, FD)
e5 = S("2026105", "학생5(WP)", WP)
e6 = S("2026106", "학생6(WP;TT)", WP, TT)
e7 = S("2026107", "학생7(FD;PT)", FD, PT)
e8 = S("2026108", "학생8(TT;RW;PT)", TT, RW, PT)

# 2단계: 학생4가 팀1(학생1뿐)에 지원 -> 접수되어 투표로 감
expect("2단계 학생4 -> 팀1", check_join(e4, [e1])[0], True)

# 4단계: 학생7이 팀1(학생1, 학생4)에 지원 -> 접수됨. 거부로 떨어지는 것은 투표 단계의 일
expect("4단계 학생7 -> 팀1 접수 가능", check_join(e7, [e1, e4])[0], True)

# 6단계: 마감 뒤 배정. 팀1~3 각 2명, 팀 없는 학생은 7, 8
easy_teams = {1: [e1, e4], 2: [e2, e5], 3: [e3, e6]}
easy_plan = solve_assignment(easy_teams, [e7, e8])
expect("6단계 배정 성공", easy_plan is not None, True)
if easy_plan:
    after = {no: list(ms) for no, ms in easy_teams.items()}
    for sn, tno in easy_plan.items():
        after[tno].append({s.student_no: s for s in [e7, e8]}[sn])
    expect("6단계 배정 결과가 규칙을 지킴", validate_teams(after), [])


# ===============================================================
# 부록 2. 중간 — 팀 4개
# ===============================================================
print("\n[부록 2] 중간")

m1 = S("2026201", "학생1(PL;PT;TT)", PL, PT, TT)
m2 = S("2026202", "학생2(PL;TT)", PL, TT)
m3 = S("2026203", "학생3(PL;RW)", PL, RW)
m5 = S("2026205", "학생5(WP;TT)", WP, TT)
m6 = S("2026206", "학생6(WP;FD)", WP, FD)
m9 = S("2026209", "학생9(FD;WP)", FD, WP)
m10 = S("2026210", "학생10(TT;PL)", TT, PL)
m11 = S("2026211", "학생11(RW)", RW)
m12 = S("2026212", "학생12(PT;RW;FD)", PT, RW, FD)

# 3단계: 학생2가 팀1(학생1, 학생5)에 지원 -> 막힘(주 역할 중복)
expect("3단계 학생2 -> 팀1", first_word(check_join(m2, [m1, m5])), "막힘(같은 주 역할의 팀원이 있음)")

# 5단계: 학생9가 팀2(학생6)에 지원 -> 접수됨
expect("5단계 학생9 -> 팀2", check_join(m9, [m6])[0], True)

# 6단계: 학생10이 팀2(학생6, 학생9)에 지원 -> 접수됨 (거부로 떨어짐)
expect("6단계 학생10 -> 팀2 접수 가능", check_join(m10, [m6, m9])[0], True)

# 8단계: 학생12가 팀4(학생11)에 지원 -> 접수됨
expect("8단계 학생12 -> 팀4", check_join(m12, [m11])[0], True)

# 11단계: 마감 뒤 상태 — 팀1은 학생1, 학생5 / 팀2는 학생6, 학생9 / 팀3, 팀4는 빈 팀
mid_teams = {1: [m1, m5], 2: [m6, m9], 3: [], 4: []}
m4 = S("2026204", "학생4(PL)", PL)
m7 = S("2026207", "학생7(WP)", WP)
m8 = S("2026208", "학생8(WP;PT)", WP, PT)
mid_unassigned = [m2, m3, m4, m7, m8, m10, m11, m12]
mid_plan = solve_assignment(mid_teams, mid_unassigned)
expect("11단계 배정 성공", mid_plan is not None, True)
if mid_plan:
    after = {no: list(ms) for no, ms in mid_teams.items()}
    by_no = {s.student_no: s for s in mid_unassigned}
    for sn, tno in mid_plan.items():
        after[tno].append(by_no[sn])
    expect("11단계 배정 결과가 규칙을 지킴", validate_teams(after), [])


# ===============================================================
# 부록 3. 어려움 — 팀 4개
# ===============================================================
print("\n[부록 3] 어려움")

h1 = S("2026301", "학생1(PL;RW)", PL, RW)
h2 = S("2026302", "학생2(PL;PT)", PL, PT)
h3 = S("2026303", "학생3(PL;TT)", PL, TT)
h4 = S("2026304", "학생4(WP;PL)", WP, PL)
h5 = S("2026305", "학생5(WP;FD)", WP, FD)
h6 = S("2026306", "학생6(WP;RW)", WP, RW)
h7 = S("2026307", "학생7(FD;PT;TT)", FD, PT, TT)
h8 = S("2026308", "학생8(FD;TT)", FD, TT)
h9 = S("2026309", "학생9(FD;WP)", FD, WP)
h10 = S("2026310", "학생10(TT;RW)", TT, RW)
h11 = S("2026311", "학생11(TT;PT)", TT, PT)
h12 = S("2026312", "학생12(TT;PL)", TT, PL)
h13 = S("2026313", "학생13(RW;PT;FD)", RW, PT, FD)
h14 = S("2026314", "학생14(RW;TT)", RW, TT)
h15 = S("2026315", "학생15(PT;FD)", PT, FD)
h16 = S("2026316", "학생16(PT)", PT)

# 3단계: 학생7이 팀1(학생1, 학생4)에 지원 -> 승인
#   팀1은 학생1이 기획자, 학생4가 웹 프로그래머를 맡아 필수 역할이 이미 충족됨
expect("3단계 학생7 -> 팀1", check_join(h7, [h1, h4])[0], True)

# 6단계: 학생5, 학생6이 차례로 팀2(학생2, 학생8)에 지원 -> 둘 다 접수(대기)
expect("6단계 학생5 -> 팀2 접수", check_join(h5, [h2, h8])[0], True)
expect("6단계 학생6 -> 팀2 접수", check_join(h6, [h2, h8])[0], True)

# 7단계: 학생5 승인 직전 재검사 -> 통과
expect("7단계 학생5 승인 직전 재검사", check_join(h5, [h2, h8])[0], True)

# 8단계: 학생5가 먼저 승인되어 팀2가 바뀐 뒤, 학생6의 승인 직전 재검사 -> 거절
expect(
    "8단계 학생6 승인 직전 재검사",
    first_word(check_join(h6, [h2, h8, h5])),
    "막힘(같은 주 역할의 팀원이 있음)",
)

# 10단계: 학생15가 팀3(학생11)에 지원 -> 접수
#   넣으면 2명, 남는 자리 2개, 필요한 필수 역할 2개 -> 아슬아슬하게 통과
expect("10단계 학생15 -> 팀3", check_join(h15, [h11])[0], True)

# 11단계: 학생14가 팀3(학생11, 학생15)에 지원 -> 막힘(필수 포함 역할 자리)
expect(
    "11단계 학생14 -> 팀3",
    first_word(check_join(h14, [h11, h15])),
    "막힘(필수 포함 역할을 맡을 학생의 자리가 모자람)",
)

# 15단계: 마감 뒤 배정
#   팀1 = 1,4,7 / 팀2 = 2,8,5 / 팀3 = 11,15 / 팀4 = 빈 팀(학생10이 빠짐)
hard_teams = {1: [h1, h4, h7], 2: [h2, h8, h5], 3: [h11, h15], 4: []}
hard_unassigned = [h3, h6, h9, h10, h12, h13, h14, h16]
hard_plan = solve_assignment(hard_teams, hard_unassigned)
expect("15단계 배정 성공", hard_plan is not None, True)
if hard_plan:
    after = {no: list(ms) for no, ms in hard_teams.items()}
    by_no = {s.student_no: s for s in hard_unassigned}
    for sn, tno in hard_plan.items():
        after[tno].append(by_no[sn])
    expect("15단계 배정 결과가 규칙을 지킴", validate_teams(after), [])
    print("\n  찾은 배정:")
    for no in sorted(after):
        names = ", ".join(f"{m.name}" for m in after[no])
        print(f"    팀{no}: {names}")


print(f"\n통과 {ok_count}개, 실패 {fail_count}개")
sys.exit(1 if fail_count else 0)
