-- 작성일: 2026-10-20 03:01 (KST)
-- 팀 편성 웹 앱 — 테이블 생성 SQL
-- 학번 2601975 · 이름 정수현
--
-- Supabase 대시보드의 SQL Editor에 이 파일 전체를 붙여 넣고 Run 하면 된다.
-- 6장 실습 테이블과 같은 DB를 쓰므로 이 과제의 테이블은 모두 tf_ 로 시작한다.
-- 여러 번 실행해도 안전하도록 drop 후 create 한다.

drop table if exists tf_votes cascade;
drop table if exists tf_applications cascade;
drop table if exists tf_members cascade;
drop table if exists tf_student_sub_roles cascade;
drop table if exists tf_teams cascade;
drop table if exists tf_students cascade;
drop table if exists tf_settings cascade;
drop table if exists tf_ai_logs cascade;

-- 역할 6개 밖의 값을 막기 위한 공통 목록
--   기획자, 웹 프로그래머, 프론트엔드 디자이너, 테스터, 보고서 작성자, 발표자

-- ---------------------------------------------------------------
-- 학생과 관리자
-- ---------------------------------------------------------------
create table tf_students (
    id            bigserial primary key,
    student_no    text    not null unique,            -- 학번. 관리자는 'admin'
    name          text    not null,
    main_role     text    not null
        check (main_role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너',
                             '테스터', '보고서 작성자', '발표자')),
    password_hash text    not null,                   -- bcrypt 해시. 평문 저장 금지
    is_admin      boolean not null default false,
    created_at    timestamptz not null default now()
);

-- 관리자도 main_role 열이 필요하므로 '기획자'를 넣어 두고 is_admin 으로 구분한다.

-- ---------------------------------------------------------------
-- 보조 역할 (학생 1명에 0~2행)
-- ---------------------------------------------------------------
create table tf_student_sub_roles (
    student_id bigint not null references tf_students(id) on delete cascade,
    role       text   not null
        check (role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너',
                        '테스터', '보고서 작성자', '발표자')),
    primary key (student_id, role)
);

-- ---------------------------------------------------------------
-- 팀
-- ---------------------------------------------------------------
create table tf_teams (
    id   bigserial primary key,
    no   int  not null unique,        -- 1, 2, 3 ... 화면 key(team_1)와 같은 번호
    name text not null unique         -- '팀1', '팀2' ...
);

-- ---------------------------------------------------------------
-- 팀원
--   (team_id, slot_no) 기본 키  -> 마지막 자리에 두 명이 동시에 들어가지 못함
--   student_id 유일            -> 한 학생은 한 팀에만 소속
--   slot_no 1~4                -> 다섯 번째 자리를 막음
-- ---------------------------------------------------------------
create table tf_members (
    team_id    bigint not null references tf_teams(id) on delete cascade,
    slot_no    int    not null check (slot_no between 1 and 4),
    student_id bigint not null unique references tf_students(id) on delete cascade,
    joined_at  timestamptz not null default now(),
    primary key (team_id, slot_no)
);

-- ---------------------------------------------------------------
-- 지원
-- ---------------------------------------------------------------
create table tf_applications (
    id         bigserial primary key,
    team_id    bigint not null references tf_teams(id) on delete cascade,
    student_id bigint not null references tf_students(id) on delete cascade,
    status     text   not null default '대기'
        check (status in ('대기', '승인', '거절')),
    reason     text,                                   -- 거절 사유
    created_at timestamptz not null default now(),
    decided_at timestamptz                             -- 승인/거절이 정해진 시각
);

-- 한 학생은 결과를 기다리는 지원을 동시에 하나만 가질 수 있다.
create unique index tf_applications_one_pending
    on tf_applications (student_id)
    where status = '대기';

create index tf_applications_team_status on tf_applications (team_id, status);

-- ---------------------------------------------------------------
-- 투표
--   (application_id, voter_id) 기본 키 -> 같은 지원에 두 번 투표 불가
-- ---------------------------------------------------------------
create table tf_votes (
    application_id bigint not null references tf_applications(id) on delete cascade,
    voter_id       bigint not null references tf_students(id) on delete cascade,
    vote           text   not null check (vote in ('찬성', '거부')),
    created_at     timestamptz not null default now(),
    primary key (application_id, voter_id)
);

-- ---------------------------------------------------------------
-- 설정 (마감 여부 등)
-- ---------------------------------------------------------------
create table tf_settings (
    key   text primary key,
    value text
);

-- ---------------------------------------------------------------
-- AI 호출 기록 (README의 실패 사례 근거로 쓴다)
-- ---------------------------------------------------------------
create table tf_ai_logs (
    id          bigserial primary key,
    attempt_no  int  not null,          -- 1차, 2차, 3차
    model       text not null,
    ok          boolean not null,
    elapsed_ms  int,
    error       text,                   -- 실패 사유 (시간 초과, 빈 응답, 검사 실패 등)
    raw_excerpt text,                   -- 응답 앞부분 일부
    created_at  timestamptz not null default now()
);
