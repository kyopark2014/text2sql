#!/usr/bin/env python3
"""
Text2QL CLI — 자연어 질문을 SQL로 변환하고 Chinook DB를 조회합니다.

mcp_text2sql.py / mcp_server_text2sql.py 와 동일한 로직을 스크립트로 직접 호출합니다.

Usage:
    python text2ql.py generate "여름에 듣기 좋은 음악 리스트는?"
    python text2ql.py execute "SELECT Title FROM Track LIMIT 5"
    python text2ql.py query "가장 많이 팔린 앨범 10개는?"
    python text2ql.py query "..." --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _application_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _ensure_import_path() -> None:
    app_dir = _application_dir()
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)


def cmd_generate(question: str) -> dict:
    import mcp_text2sql

    sql = mcp_text2sql.generate_query(question)
    return {"question": question, "sql": sql}


def cmd_execute(sql: str, question: str | None = None) -> dict:
    import mcp_text2sql

    result = mcp_text2sql.execute_query(sql)
    payload = {"sql": sql, "result": result}
    if question and not mcp_text2sql.is_execution_error(result):
        payload["question"] = question
        payload["example_saved"] = mcp_text2sql.save_example_query(question, sql)
    return payload


def cmd_query(question: str) -> dict:
    import mcp_text2sql

    sql = mcp_text2sql.generate_query(question)
    result = mcp_text2sql.execute_query(sql)
    payload = {"question": question, "sql": sql, "result": result}
    if not mcp_text2sql.is_execution_error(result):
        payload["example_saved"] = mcp_text2sql.save_example_query(question, sql)
    return payload


def _print_human(payload: dict) -> None:
    if "question" in payload:
        print(f"질문: {payload['question']}")
    if "sql" in payload:
        print(f"\nSQL:\n{payload['sql']}")
    if "result" in payload:
        print(f"\n결과:\n{payload['result']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="자연어 질문을 SQL로 변환하고 Chinook SQLite DB를 조회합니다."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="자연어 질문에서 SQL만 생성")
    generate_parser.add_argument("question", help="데이터베이스에 묻고 싶은 질문")

    execute_parser = subparsers.add_parser("execute", help="SQL을 실행하고 결과 반환")
    execute_parser.add_argument("sql", help="실행할 SQL 문")
    execute_parser.add_argument(
        "--save-question",
        metavar="QUESTION",
        help="실행 성공 시 labs/example_queries_temp.jsonl에 저장할 질문(input)",
    )

    query_parser = subparsers.add_parser(
        "query", help="SQL 생성 후 즉시 실행 (generate + execute)"
    )
    query_parser.add_argument("question", help="데이터베이스에 묻고 싶은 질문")

    parser.add_argument(
        "--json",
        action="store_true",
        help="사람이 읽기 쉬운 형식 대신 JSON으로 출력",
    )

    args = parser.parse_args()
    _ensure_import_path()

    try:
        if args.command == "generate":
            payload = cmd_generate(args.question)
        elif args.command == "execute":
            payload = cmd_execute(args.sql, question=getattr(args, "save_question", None))
        else:
            payload = cmd_query(args.question)
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload)

    if "result" in payload:
        import mcp_text2sql

        if mcp_text2sql.is_execution_error(payload["result"]):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
