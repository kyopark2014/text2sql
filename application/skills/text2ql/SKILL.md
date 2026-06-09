---
name: text2ql
description: >-
  자연어 질문을 SQL로 변환해 Chinook SQLite 데이터베이스를 조회합니다.
  Bedrock LLM과 Knowledge Base example query, schema 정보를 활용합니다.
  Use when the user asks database questions in natural language, wants text-to-SQL,
  text2sql, text2ql, SQL generation from Korean/English questions, or Chinook DB queries.
---

# Text2QL

자연어 질문을 SQL로 변환하고 실행합니다. 핵심 로직은 `application/mcp_text2sql.py`와 동일하며, MCP 서버(`mcp_server_text2sql.py`)의 `generate_query` / `execute_query` 도구를 스크립트로 직접 호출합니다.

## 사전 요구사항

- `application/config.json` — Bedrock 리전, Knowledge Base ID, AWS 자격 증명
- Knowledge Base에 example query가 sync되어 있어야 RAG 검색이 동작합니다
- 대상 DB: Chinook SQLite (`labs/Chinook.db`)

## 빠른 시작

스크립트는 **반드시 `application` 디렉터리를 cwd로** 실행하세요.

```bash
cd application

# SQL만 생성
python skills/text2ql/scripts/text2ql.py generate "가장 많이 팔린 앨범 10개는?"

# SQL 실행
python skills/text2ql/scripts/text2ql.py execute "SELECT Title FROM Album LIMIT 5"

# 생성 + 실행 (일반적인 조회 흐름)
python skills/text2ql/scripts/text2ql.py query "여름에 듣기 좋은 음악 리스트는?"

# JSON 출력 (후속 자동화·파싱용)
python skills/text2ql/scripts/text2ql.py query "..." --json
```

## 워크플로

사용자가 데이터베이스 조회를 요청하면 아래 순서를 따릅니다.

```
Task Progress:
- [ ] 1. 질문을 명확히 정리
- [ ] 2. text2ql.py query 로 SQL 생성·실행
- [ ] 3. SQL과 결과를 사용자에게 설명
- [ ] 4. 오류 시 SQL만 수정해 execute 재시도
- [ ] 5. 실행 성공 시 example query 자동 저장 (아래 참고)
```

### 1. 질문 정리

모호한 질문은 테이블·기간·정렬 기준을 확인한 뒤 진행합니다.

### 2. 조회 실행

기본은 `query` 서브커맨드 한 번으로 처리합니다.

```bash
python skills/text2ql/scripts/text2ql.py query "사용자 질문" --json
```

SQL만 먼저 확인해야 하면 `generate`를 사용합니다.

### 3. 결과 전달

응답에 다음을 포함합니다.

- 생성된 SQL (사용자가 검증할 수 있도록)
- 조회 결과 요약 (핵심 수치·목록)
- 필요 시 가정·한계 (스키마에 없는 정보 등)

### 4. 오류 처리

`execute` 결과가 `An error occurred while executing the query:` 로 시작하면:

1. 오류 메시지를 확인
2. SQL을 수정하거나 `generate`로 재생성
3. `execute`로 재실행

```bash
python skills/text2ql/scripts/text2ql.py execute "수정된 SQL" --save-question "정리된 질문"
```

### 5. 성공한 example query 저장

`query` 서브커맨드로 SQL 생성·실행이 **성공**하면, 질문(1단계에서 정리한 내용)과 SQL이 자동으로 `labs/example_queries_temp.jsonl`에 추가됩니다.

```json
{
  "input": "질문의 주요 내용",
  "query": "SELECT ..."
}
```

- 1단계에서 질문을 명확히 정리할수록 `input` 품질이 좋아집니다 (예: "Artist 테이블의 모든 데이터 조회").
- 동일한 `input`+`query` 쌍이 이미 있으면 중복 추가하지 않습니다.
- Knowledge Base에 sync하면 이후 RAG 샘플로 활용됩니다.
- `--json` 출력의 `example_saved: true`로 저장 여부를 확인할 수 있습니다.

## MCP와의 관계

| 방식 | 용도 |
|------|------|
| `scripts/text2ql.py` | Cursor skill·터미널에서 직접 실행 |
| `mcp_server_text2sql.py` | Streamlit Agent·MCP 클라이언트 연동 |

두 방식 모두 `mcp_text2sql.generate_query` / `mcp_text2sql.execute_query`를 호출합니다.

## 데이터베이스 개요

Chinook 음악 스토어 스키마입니다. 주요 테이블:

| 테이블 | 설명 |
|--------|------|
| Artist, Album, Track | 아티스트·앨범·트랙 |
| Customer, Employee, Invoice, InvoiceLine | 고객·직원·매출 |
| Genre, MediaType, Playlist | 장르·미디어·플레이리스트 |

상세 스키마: `labs/chinook_schema.json`

## 예시

**질문:** "가장 많이 팔린 앨범 10개는?"

```bash
cd application
python skills/text2ql/scripts/text2ql.py query "가장 많이 팔린 앨범 10개는?"
```

**질문:** "미국 고객이 구매한 트랙 수는?"

```bash
python skills/text2ql/scripts/text2ql.py query "미국 고객이 구매한 트랙 수는?" --json
```

## 주의사항

- SELECT/WITH 조회 위주로 사용하세요. INSERT/UPDATE/DELETE는 피합니다.
- `generate_query`는 Bedrock API와 Knowledge Base RAG를 호출하므로 AWS 설정이 필요합니다.
- SQL 생성 품질은 example query(KB)와 `chinook_schema.json` 품질에 의존합니다.
