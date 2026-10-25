# 작성일: 2026-10-20 03:48 (KST)
# 수정일: 2026-10-21 04:35 (KST) — 모델 3개가 모두 HTTP 404 를 내서 살아 있는 무료 모델로 교체
# 수정일: 2026-10-26 00:50 (KST) — 1차 모델이 계속 404 를 내서 교체, 응답이 확인된 모델을 뒤로 둠
"""오픈라우터 모델 3개를 차례로 불러 배정안을 받고, 앱이 그 답을 규칙으로 검사한다.

공고 2.5절, 4.3절, 3장의 어려운 해결에 해당하는 부분:
  - 모델마다 '전체 대기 시간' 120초를 재서 끊고 다음 모델로 넘어감
  - 빈 응답, 오류, 검사 실패도 모두 실패로 보고 다음 모델로 넘어감
  - 3차 모델까지 실패하면 앱이 스스로 완전 탐색으로 배정함
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import requests

import rules
from rules import Student

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# 모델 하나에 허용하는 전체 대기 시간 (공고 2.5절 5항)
MODEL_TIMEOUT_SEC = 120

# 무료 모델 3개. 오픈라우터에서 모델이 사라질 수 있으므로 .env 로 바꿀 수 있게 해 둔다.
# 무료 모델 자동 라우터(openrouter/free)는 쓰지 않는다 (공고 4.3절, 감점 14번).
DEFAULT_MODELS = (
    # 1차: 공고 7.1절의 예시에 나온 모델
    "nvidia/nemotron-3-super-120b-a12b:free",
    # 2차, 3차: 실제로 응답을 돌려준 것이 확인된 모델
    "xingchen-agi/xing4.0-29b-a4b:free",
    "nvidia/nemotron-3.5-super-vl:free",
)


def models_from(secret_getter: Callable[[str], Optional[str]]) -> Tuple[str, str, str]:
    picked = []
    for i, default in enumerate(DEFAULT_MODELS, start=1):
        picked.append(secret_getter(f"OPENROUTER_MODEL_{i}") or default)
    return tuple(picked)  # type: ignore[return-value]


# ---------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------
def build_prompt(
    teams: Dict[int, Sequence[Student]], unassigned: Sequence[Student]
) -> str:
    lines: List[str] = []
    lines.append("너는 대학 팀 프로젝트의 팀 배정을 돕는다.")
    lines.append("아직 팀이 없는 학생들을 기존 팀에 넣어라. 이미 팀에 있는 학생은 절대 옮기지 마라.")
    lines.append("")
    lines.append("[규칙]")
    lines.append("1. 배정이 끝나면 모든 팀의 인원이 2명 이상 4명 이하여야 한다. 빈 팀이 있으면 안 된다.")
    lines.append("2. 한 팀 안에 '주 역할'이 같은 학생이 2명 이상 있으면 안 된다.")
    lines.append("3. 모든 팀에는 기획자를 맡을 학생 1명과 웹 프로그래머를 맡을 학생 1명이 "
                 "서로 다른 사람으로 있어야 한다. 주 역할이든 보조 역할이든 상관없다.")
    lines.append("4. 팀이 없는 학생은 한 명도 빠짐없이, 각자 한 팀에만 배정해야 한다.")
    lines.append("")
    lines.append("[지금의 팀 구성]")
    for no in sorted(teams):
        members = list(teams[no])
        if not members:
            lines.append(f"- 팀{no}: (비어 있음)")
            continue
        desc = "; ".join(
            f"{m.name}(주:{m.main_role}"
            + (f", 보조:{'/'.join(m.sub_roles)}" if m.sub_roles else "")
            + ")"
            for m in members
        )
        lines.append(f"- 팀{no}: {desc}")
    lines.append("")
    lines.append("[팀이 없는 학생]")
    for s in unassigned:
        sub = f", 보조:{'/'.join(s.sub_roles)}" if s.sub_roles else ""
        lines.append(f"- 학번 {s.student_no} {s.name} (주:{s.main_role}{sub})")
    lines.append("")
    lines.append("[답하는 방법]")
    lines.append('설명이나 코드 블록 없이 JSON 객체 하나만 출력해라. 형식은 정확히 다음과 같다:')
    lines.append('{"assignments": [{"student_no": "2026001", "team_no": 1}]}')
    lines.append("student_no 는 위에 적힌 학번 문자열 그대로, team_no 는 팀 번호 정수다.")
    return "\n".join(lines)


def parse_plan(text: str) -> Dict[str, int]:
    """모델의 응답에서 {학번: 팀번호} 를 뽑아낸다. 실패하면 예외를 던진다."""
    if not text or not text.strip():
        raise ValueError("빈 응답")

    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("JSON 을 찾지 못함")

    data = json.loads(cleaned[start : end + 1])
    items = data.get("assignments")
    if not isinstance(items, list):
        raise ValueError("assignments 목록이 없음")

    plan: Dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("assignments 의 항목이 객체가 아님")
        no = str(item.get("student_no", "")).strip()
        team = item.get("team_no")
        if not no:
            raise ValueError("student_no 가 비어 있음")
        try:
            team_no = int(team)
        except (TypeError, ValueError):
            raise ValueError(f"team_no 가 정수가 아님 ({team!r})")
        if no in plan:
            raise ValueError(f"학번 {no} 가 여러 번 배정됨")
        plan[no] = team_no
    if not plan:
        raise ValueError("배정이 하나도 없음")
    return plan


# ---------------------------------------------------------------
# 오픈라우터 호출
# ---------------------------------------------------------------
def _post(api_key: str, model: str, prompt: str) -> str:
    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,          # 추론 모델이 생각하느라 빈 응답을 내지 않도록 넉넉히
            "temperature": 0.2,
            "reasoning": {"effort": "low"},
        },
        timeout=(10, MODEL_TIMEOUT_SEC),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    data = resp.json()
    if "error" in data and data.get("error"):
        raise RuntimeError(str(data["error"])[:200])
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("빈 응답 (choices 없음)")
    return (choices[0].get("message") or {}).get("content") or ""


def call_model(api_key: str, model: str, prompt: str) -> str:
    """모델 하나를 부른다. 전체 대기 시간이 120초를 넘으면 끊는다.

    requests 의 timeout 은 '응답이 시작될 때까지'만 재는 경우가 많으므로,
    별도 스레드에 올려 전체 시간을 직접 잰다 (3장의 어려운 해결).
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_post, api_key, model, prompt)
    try:
        return future.result(timeout=MODEL_TIMEOUT_SEC)
    except FutureTimeout:
        future.cancel()
        raise TimeoutError(f"{MODEL_TIMEOUT_SEC}초 안에 응답하지 않음")
    finally:
        executor.shutdown(wait=False)


# ---------------------------------------------------------------
# 배정 전체 흐름
# ---------------------------------------------------------------
def assign(
    teams: Dict[int, Sequence[Student]],
    unassigned: Sequence[Student],
    api_key: Optional[str],
    models: Sequence[str],
    on_status: Callable[[str], None] = lambda _m: None,
    on_log: Callable[..., None] = lambda **_k: None,
) -> Tuple[Optional[Dict[str, int]], str, List[str]]:
    """반환: (배정안 또는 None, 어떻게 얻었는지, 시도 기록)"""
    attempts: List[str] = []

    if not unassigned:
        return {}, "배정할 학생이 없음", attempts

    # 규칙을 지키는 배정이 아예 없으면 AI 를 부르지 않는다 (공고 2.5절 8항)
    if rules.solve_assignment(teams, unassigned) is None:
        return None, "규칙을 지키는 배정이 없음", attempts

    if not api_key:
        attempts.append("오픈라우터 키가 설정되지 않아 AI 를 건너뜀")
    else:
        prompt = build_prompt(teams, unassigned)
        for i, model in enumerate(models, start=1):
            on_status(f"{i}차 모델의 응답을 기다리는 중입니다… ({model}, 최대 {MODEL_TIMEOUT_SEC}초)")
            started = time.monotonic()
            try:
                text = call_model(api_key, model, prompt)
                plan = parse_plan(text)
                errors = rules.validate_assignment(teams, unassigned, plan)
                elapsed = int((time.monotonic() - started) * 1000)
                if errors:
                    msg = f"{i}차 모델({model}): 배정안이 규칙 검사에 걸림 — {errors[0]}"
                    attempts.append(msg)
                    on_status(msg + " → 다음 모델로 넘어갑니다")
                    on_log(attempt_no=i, model=model, ok=False, elapsed_ms=elapsed,
                           error=" / ".join(errors)[:500], raw_excerpt=text[:1000])
                    continue
                attempts.append(f"{i}차 모델({model}): 성공 ({elapsed/1000:.1f}초)")
                on_log(attempt_no=i, model=model, ok=True, elapsed_ms=elapsed,
                       error="", raw_excerpt=text[:1000])
                return plan, f"{i}차 모델({model})의 배정안", attempts
            except Exception as exc:  # 시간 초과, HTTP 오류, 빈 응답, JSON 파싱 실패
                elapsed = int((time.monotonic() - started) * 1000)
                msg = f"{i}차 모델({model}): 실패 — {type(exc).__name__}: {exc}"
                attempts.append(msg)
                on_status(msg + " → 다음 모델로 넘어갑니다")
                on_log(attempt_no=i, model=model, ok=False, elapsed_ms=elapsed,
                       error=f"{type(exc).__name__}: {exc}"[:500], raw_excerpt="")

    # 3차 모델까지 실패 -> 앱이 스스로 배정 (3장의 어려운 해결)
    on_status("AI 모델이 모두 실패했습니다. 앱이 직접 규칙을 지키는 배정을 찾는 중입니다…")
    plan = rules.solve_assignment(teams, unassigned)
    if plan is None:
        return None, "규칙을 지키는 배정이 없음", attempts
    attempts.append("앱이 직접 배정을 계산함 (완전 탐색)")
    return plan, "앱이 직접 계산한 배정 (AI 3차까지 실패)", attempts
