import json
import logging
import re
import sys
import langgraph_agent 
import chat
import copy

from langgraph.graph import StateGraph, START, END
from notification_queue import NotificationQueue
from typing import TypedDict
from langchain_core.prompts.chat import ChatPromptTemplate
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessageChunk

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("text2sql")

engine = create_engine(f"sqlite:///{langgraph_agent.CHINOOK_DB_PATH}")
db = SQLDatabase(engine)
DIALECT = "sqlite"

class GraphState(TypedDict):
    question: str  
    intent: str
    sample_queries: list
    readiness: str
    tables_summaries: list
    table_names: list
    table_details: list
    query_state: dict
    next_action: str
    answer: str
    dialect: str

initial_query_state = {
    "status": "success",
    "query": "",
    "result": "",
    "error": {
        "code": "",
        "message": "",
        "failed_step": "",
        "hint": ""
    }
}

import mcp_retrieve

def get_sample_queries(state: GraphState) -> GraphState:
    question = state["question"]
    samples_json = mcp_retrieve.retrieve(question)
    logger.info(f"samples: {samples_json}")

    samples = json.loads(samples_json)
    contents = [doc["contents"] for doc in samples if doc.get("contents")]
    logger.info(f"contents: {contents}")

    return GraphState(sample_queries=contents)

import os
WORKING_DIR = os.path.dirname(os.path.abspath(__file__))

def load_schema_description():
    file_path = os.path.join(WORKING_DIR, '..', 'labs', 'chinook_schema.json')

    with open(file_path, 'r') as file:
        schema_description = json.load(file)

    return schema_description

def get_schema_table_catalog() -> list[dict]:
    """chinook_schema.json을 인덱스 가능한 테이블 목록으로 평탄화."""
    catalog = []
    for block in load_schema_description():
        if not isinstance(block, dict):
            continue
        for table_name, info in block.items():
            entry = {"table_name": table_name}
            if isinstance(info, dict):
                entry.update(info)
            catalog.append(entry)
    return catalog

def format_schema_catalog_for_prompt(catalog: list[dict]) -> str:
    return "\n".join(
        f"{i}: {entry['table_name']} - {entry.get('table_desc', '')}"
        for i, entry in enumerate(catalog)
    )

def extract_result(content: str) -> str:
    start_tag = "<result>"
    end_tag = "</result>"
    if start_tag in content and end_tag in content:
        start = content.find(start_tag) + len(start_tag)
        end = content.find(end_tag, start)
        return content[start:end].replace("\n", "").strip()
    return content.replace("\n", "").strip()

def extract_sql_query(content: str) -> str:
    """<result> 또는 응답 본문에서 실행 가능한 SQL만 추출."""
    text = content or ""
    if "<result>" in text and "</result>" in text:
        start = text.find("<result>") + len("<result>")
        end = text.find("</result>", start)
        text = text[start:end].strip()
    else:
        text = text.strip()

    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    text = "\n".join(lines).strip()

    if not text or text.lstrip().startswith("--"):
        flat = re.sub(r"\s+", " ", content)
        match = re.search(r"\b(SELECT|WITH|INSERT|UPDATE|DELETE)\b", flat, re.IGNORECASE)
        if match:
            text = flat[match.start():].strip()
            sql_kw = (
                r"FROM|(?:LEFT|RIGHT|INNER)\s+JOIN|JOIN|WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT"
            )
            text = re.sub(rf"([^\s;])({sql_kw})\b", r"\1 \2", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+", " ", text).strip()

    return text.rstrip(";").strip()

def parse_readiness(content: str) -> str:
    """LLM 응답에서 라우팅용 Ready / Not Ready만 추출."""
    text = extract_result(content).strip()
    if not text:
        return "Not Ready"
    if re.search(r"\bnot\s*ready\b", text, re.IGNORECASE):
        return "Not Ready"
    if re.search(r"\bready\b", text, re.IGNORECASE):
        return "Ready"
    logger.warning(f"Unrecognized readiness, defaulting to Not Ready: {text[:200]}")
    return "Not Ready"

def extract_chunk_text(message: AIMessageChunk) -> str:
    """AIMessageChunk에서 텍스트 추출 (Bedrock: str, Anthropic API: list[dict])."""
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "".join(parts)

def parse_json_response(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {"failure_type": "syntax_check", "hint": ""}

    if "<result>" in text and "</result>" in text:
        text = extract_result(text)

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse JSON response: {text[:200]}")
        return {"failure_type": "syntax_check", "hint": text[:500]}

def check_readiness(state: GraphState) -> GraphState:
    question = state["question"]
    sample_queries = state["sample_queries"]
    
    table_details = state.get("table_details") or load_schema_description()
    # logger.info(f"table_details: {table_details}")

    system = (
        "당신은 사용자 질문에 대한 SQL 쿼리를 작성하는 유능한 데이터베이스 엔지니어입니다.\n"
        "당신의 임무는 주어진 DB 정보를 바탕으로, 사용자 질문에 대한 SQL 쿼리 작성이 가능한지 판단하는 것입니다."
        "<result> tag를 붙이세요."
    )

    human = (
        "질문에 대한 SQL 쿼리를 생성하기에 충분한 정보가 제공되었는지 판단합니다.\n"
        "<result> 태그 안에는 `Ready` 또는 `Not Ready` 중 하나만 넣으세요. "
        "부족한 이유·설명은 <result> 태그 밖에 작성하세요.\n"
        "질문: {question}\n"
        "샘플 쿼리: {sample_queries}\n"
        "사용 가능한 테이블: {table_details}"        
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "question": question,
        "sample_queries": sample_queries,
        "table_details": table_details
    })
    # logger.info(f"response of check_readiness: {response.content}")
    readiness = parse_readiness(response.content)
    logger.info(f"readiness: {readiness}")

    return GraphState(readiness=readiness)
        
def generate_query(state: GraphState) -> GraphState:
    new_query_state = copy.deepcopy(initial_query_state)
    question = state["question"]
    logger.info(f"question: {question}")

    sample_queries = state["sample_queries"]

    table_details = state.get("table_details") or load_schema_description()
    dialect = state.get("dialect") or DIALECT

    query_state = state.get("query_state", {}) or {}
    error_info = query_state.get("error", {}) or {}
    hint = error_info.get("hint", "None")
    
    system = (
        "당신은 사용자 질문에 대한 {dialect} SQL 쿼리를 작성하는 유능한 데이터베이스 엔지니어입니다. "
        "당신의 임무는 주어진 DB 정보를 바탕으로, 사용자 질문에 부합하는 정확한 SQL 쿼리를 작성하는 것입니다.\n"
        "<result> 태그 안에는 실행 가능한 SQL 문장만 넣으세요. "
        "주석(--, /* */), 설명, 서두, 마크다운 코드블록 표시는 <result> 안에 포함하지 마세요."
    )

    human = (
        "샘플 쿼리·스키마·과거 실패 이력을 바탕으로 {dialect} SQL을 작성하세요.\n"
        "응답 형식:\n"
        "- <result> 태그 안: SELECT/WITH 등으로 시작하는 SQL 한 문장만 (세미콜론 생략 가능)\n"
        "- <result> 태그 밖: 스키마 한계·가정 등 설명이 필요할 때만 작성\n\n"
        "질문: {question}\n"
        "샘플 쿼리: {sample_queries}\n"
        "사용 가능한 테이블: {table_details}\n"
        "추가 정보 (과거 실패 이력 등): {hint}\n"
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "dialect": dialect,
        "question": question,
        "sample_queries": sample_queries,
        "table_details": table_details,
        "hint": hint
    })

    generated_query = extract_sql_query(response.content)
    logger.info(f"generated_query: {generated_query}")

    new_query_state["query"] = generated_query

    return GraphState(query_state=new_query_state)

def validate_query(state: GraphState) -> GraphState:
    dialect = DIALECT
    question = state["question"]
    query_state = copy.deepcopy(state["query_state"])
    query = query_state["query"]
    
    explain_statements = {
        'mysql': "EXPLAIN {query}",
        'mariadb': "EXPLAIN {query}",
        'sqlite': "EXPLAIN QUERY PLAN {query}",
        'oracle': "EXPLAIN PLAN FOR\n{query}\n\nSELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);",
        'postgresql': "EXPLAIN ANALYZE {query}",
        'postgres': "EXPLAIN ANALYZE {query}",
        'presto': "EXPLAIN ANALYZE {query}",
        'sqlserver': "SET STATISTICS PROFILE ON; {query}; SET STATISTICS PROFILE OFF;"
    }
    
    if dialect.lower() not in explain_statements:
        query_plan = " "
    else:
        try:
            explain_query = explain_statements[dialect.lower()].format(query=query)
            query_plan = db.run(explain_query)
        except Exception as e:
            query_state["status"] = "error"
            query_state["error"]["code"] = "E01"
            query_state["error"]["message"] = f"An error occurred while executing the EXPLAIN query: {str(e)}"
            query_state["error"]["failed_step"] = "validation"
            query_state["query"] = query
            return GraphState(query_state=query_state)

    system = (
        "당신은 사용자 질문에 대한 기존 {dialect} SQL 쿼리를 검토하고, 필요 시 최적화하는 데이터베이스 전문가입니다. "
        "당신의 임무는 주어진 SQL 쿼리 및 추가 정보를 바탕으로 쿼리의 정합성, 최적화 가능성을 검토하고, 이에 입각한 최종 쿼리를 제공하는 것입니다."
    )

    human = (
        "사용자 질문에 맞춰 쿼리에 alias를 추가하세요. 기존 쿼리에 없던 테이블·컬럼은 추가하지 마세요.\n"
        "<result> 태그 안에는 실행 가능한 SQL만 넣고, 주석·설명은 태그 밖에 작성하세요.\n"
        "질문: {question}\n"
        "기존 쿼리:\n{query}\n"
        "쿼리 플랜:\n{query_plan}\n"
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "dialect": dialect,
        "question": question,
        "query": query,
        "query_plan": query_plan
    })
    # logger.info(f"response: {response.content}")

    validated_query = extract_sql_query(response.content)
    logger.info(f"validated_query: {validated_query}")

    query_state["query"] = validated_query

    return GraphState(query_state=query_state)

def execute_query(state: GraphState) -> GraphState:
    query_state = copy.deepcopy(state["query_state"])
    query = query_state["query"]
    logger.info(f"query to execute: {query}")

    try:
        query_result = db.run(query)
        logger.info(f"query result: {query_result}")

    except Exception as e:
        query_state["status"] = "error"
        query_state["error"]["code"] = "E02"
        query_state["error"]["message"] = f"An error occurred while executing the validated query: {str(e)}"
        query_state["error"]["failed_step"] = "execution"
        return GraphState(query_state=query_state)

    query_state["result"] = query_result
    return GraphState(query_state=query_state)

def handle_failure(state: GraphState) -> GraphState:
    query_state = copy.deepcopy(state["query_state"])
    query = query_state['query']
    message = query_state['error']['message']
    system = (
        "당신은 SQL 쿼리의 실패를 처리하는 유능한 데이터베이스 엔지니어입니다. "
        "당신의 임무는 주어진 SQL 쿼리의 실패 원인을 파악하여, 문제 해결을 위한 다음 작업을 결정하는 것입니다."
    )

    human = (
        "주어진 SQL 쿼리의 실패 메시지를 바탕으로 다음 중 하나의 원인(`failure_type`)과 해결을 위한 실마리(`hint`)를 함께 제공합니다.\n"
        "다음은 failure_type의 선택 예시입니다.\n"
        "부정확한 쿼리 구문 작성: `syntax_check`\n"
        "스키마 불일치: `schema_check`\n"
        "DB 외부요인(권한, 연결 문제 등): `stop`\n"
        "DB의 일시적 오동작(쿼리 재실행 필요): `retry`\n\n"
        "실패 쿼리: {query}\n"
        "실패 메시지: {message}\n"
        "JSON 형식으로만 응답하세요: {{\"failure_type\": \"...\", \"hint\": \"...\"}}"
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "query": query,
        "message": message
    })
    result = response.content
    json_result = parse_json_response(result)

    query_state["hint"] = json_result["hint"]
    return GraphState(next_action=json_result["failure_type"], query_state=query_state)

def get_relevant_columns(state: GraphState) -> GraphState:
    query_state = copy.deepcopy(state["query_state"])
    question = state["question"]
    query = query_state["query"]
    message = query_state['error']['message']
    system = (
        "당신은 SQL 쿼리의 실패를 처리하는 유능한 데이터베이스 엔지니어입니다. "
        "당신의 임무는 앞서 발생한 쿼리 실패를 해결하기 위해 스키마를 재탐색 하는 것입니다."
    )

    human = (
        "사용자 질문과 주어진 실패 메시지를 바탕으로 쿼리 재탐색에 적절한 키워드를 제공하세요. "
        "서두는 생략하고 키워드만 형식에 맞춰 응답하세요.\n\n"
        "사용자 질문: {question}\n"
        "이전 실패 쿼리: {query}\n"
        "메시지: {message}\n"
        "쉼표로 구분된 키워드 목록만 응답하세요. 예: keyword1, keyword2, keyword3"
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "question": question,
        "query": query,
        "message": message
    })
    keywords = response.content
    return keywords

def get_relevant_tables(state: GraphState) -> GraphState:
    question = state["question"]
    catalog = get_schema_table_catalog()
    table_inputs = format_schema_catalog_for_prompt(catalog)

    system = (
        "당신은 사용자 요청에 맞는 SQL 쿼리를 작성하는 유능한 데이터베이스 엔지니어입니다. "
        "당신의 임무는 SQL 쿼리 작성에 필요한 테이블을 선택하는 것입니다."
    )

    human = (
        "사용자 요청에 맞는 SQL 쿼리를 생성하기 위해 필요한 테이블을 선택하여, "
        "이를 중요도 순서로 정렬한 후 인덱스 번호(0부터 시작)로 응답하세요. "
        "사용자 요청에 관련된 테이블이 없으면 빈 문자열로 응답하세요.\n\n"
        "질문: {question}\n"
        "테이블 정보:\n{table_inputs}\n"
        "쉼표로 구분된 인덱스 번호만 응답하세요. 예: 0, 2, 5"
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "question": question,
        "table_inputs": table_inputs
    })
    table_ids = response.content.strip()
    logger.info(f"get_relevant_tables raw response: {table_ids}")
    try:
        if not table_ids or table_ids == '""':
            logger.info("get_relevant_tables: no tables selected")
            return GraphState(table_names=[])
        table_ids_list = [int(i) for i in re.findall(r"\d+", table_ids)]
        table_names = [
            catalog[i]["table_name"]
            for i in table_ids_list
            if 0 <= i < len(catalog)
        ]
        logger.info(f"get_relevant_tables selected: {table_names}")
        return GraphState(table_names=table_names)
    except Exception as e:
        logger.warning(f"get_relevant_tables failed: {e}")
        return GraphState(table_names=[])

def get_table_schema_info(table_name: str) -> dict:
    """chinook_schema.json에서 테이블·컬럼 설명을 추출 (sample_queries.extract_descriptions 참고)."""
    table_name_lower = table_name.lower()
    for block in load_schema_description():
        if not isinstance(block, dict):
            continue
        for name, info in block.items():
            if name.lower() != table_name_lower or not isinstance(info, dict):
                continue
            return {
                "table_desc": info.get("table_desc", ""),
                "cols": {
                    col["col"]: col["col_desc"]
                    for col in info.get("cols", [])
                    if isinstance(col, dict) and col.get("col")
                },
            }
    return {"table_desc": "", "cols": {}}

def get_database_answer(state: GraphState) -> GraphState:
    question = state["question"]
    query_state = state.get("query_state") or copy.deepcopy(initial_query_state)
    query = query_state["query"]
    data = query_state["result"]
    failed_step = query_state["error"]["failed_step"]
    message = query_state["error"]["message"]
    system = (
        "당신은 데이터베이스의 정보를 바탕으로 사용자의 질문에 답변하는 유능한 비서입니다. "
        "당신의 임무는 주어진 참고정보를 참고하여, 사용자의 질문에 성실히 답변하는 것입니다."
    )

    if query_state["status"] == "success":
        human = (
            "답변에는 사용된 쿼리, 데이터프레임(Markdown Table), 질문에 대한 간단한 답변을 포함해야 합니다.\n\n"
            "질문: {question}\n"
            "사용된 쿼리: {query}\n"
            "데이터: {data}\n"
        )
        invoke_params = {
            "question": question,
            "query": query,
            "data": data
        }
    else:
        human = (
            "다음에는 사용자 질문에 대한 쿼리 수행에 실패한 기록이 주어집니다. "
            "이를 바탕으로 요청 처리에 실패한 이유를 설명하세요.\n\n"
            "질문: {question}\n"
            "사용된 쿼리: {query}\n"
            "실패 단계: {failed_step}\n"
            "에러메시지: {message}\n"
        )
        invoke_params = {
            "question": question,
            "query": query,
            "failed_step": failed_step,
            "message": message
        }

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke(invoke_params)
    answer = response.content
    return GraphState(answer=answer)

def describe_schema(state: GraphState) -> GraphState:
    table_names = state.get("table_names") or []
    logger.info(f"describe_schema tables: {table_names}")
    table_details = []
    data = db.get_table_info_no_throw(table_names)
    
    if not isinstance(data, list):
        data = [data]
    
    for item in data:
        if isinstance(item, str):
            items = item.split('CREATE TABLE')
        else:
            items = [item]
        
        for i in range(1, len(items)):
            sub_item = 'CREATE TABLE' + items[i]
            for table_name in table_names:
                if f'CREATE TABLE "{table_name}"' in sub_item:
                    
                    parts = sub_item.split('/*', 1)
                    sql_statement = parts[0].strip()
                    
                    sample_data = "No sample data available"
                    if len(parts) > 1:
                        sample_part = parts[1].split('*/', 1)[0] 
                        sample_lines = sample_part.strip().split('\n')
                        if len(sample_lines) > 1:
                            sample_data = '\n'.join(sample_lines)
                    
                    schema_info = get_table_schema_info(table_name)
                    table_detail = {
                        "table": table_name,
                        "table_desc": schema_info["table_desc"],
                        "cols": schema_info["cols"],
                        "create_table_sql": sql_statement,
                        "sample_data": sample_data
                    }
                    
                    if not table_detail["cols"]:
                        print(f"No columns found for table {table_name}")
                    table_details.append(table_detail)

    logger.info(f"describe_schema: {len(table_details)} table(s) described")
    return GraphState(table_details=table_details)


def next_step_by_readiness(state: GraphState) -> GraphState:
    return state["readiness"]

def next_step_by_query_state(state:GraphState) -> GraphState:
    return state["query_state"]["status"]

def next_step_by_next_action(state:GraphState) -> GraphState:
    return state["next_action"]

def buildText2SQLAgent():
    workflow = StateGraph(GraphState)

    workflow.add_node("get_sample_queries", get_sample_queries)
    workflow.add_node("check_readiness", check_readiness)
    workflow.add_node("get_relevant_tables", get_relevant_tables)
    workflow.add_node("describe_schema", describe_schema)

    workflow.add_node("generate_query", generate_query)
    workflow.add_node("validate_query", validate_query)
    workflow.add_node("get_relevant_columns", get_relevant_columns)
    workflow.add_node("get_database_answer", get_database_answer)
    workflow.add_node("execute_query", execute_query)
    workflow.add_node("handle_failure", handle_failure)
    
    workflow.add_edge(START, "get_sample_queries")
    workflow.add_edge("get_sample_queries", "check_readiness")

    workflow.add_conditional_edges(
        "check_readiness",
        next_step_by_readiness,
        {
            "Ready": "generate_query",
            "Not Ready": "get_relevant_tables"
        }
    )

    workflow.add_edge("generate_query", "validate_query")
    workflow.add_edge("get_relevant_tables", "describe_schema")
    workflow.add_edge("describe_schema", "generate_query")

    workflow.add_conditional_edges(
        "validate_query"    ,
        next_step_by_query_state,
        {
            "success": "execute_query",
            "error": "handle_failure"
        }
    )
    workflow.add_conditional_edges(
        "execute_query"    ,
        next_step_by_query_state,
        {
            "success": "get_database_answer",
            "error": "handle_failure"
        }
    )
    workflow.add_conditional_edges(
        "handle_failure"    ,
        next_step_by_next_action,
        {
            "schema_check": "get_relevant_columns",
            "syntax_check": "generate_query",
            "retry": "validate_query",
            "stop": "get_database_answer"
        }
    )
    workflow.add_edge("get_relevant_columns", "generate_query")
    workflow.add_edge("get_database_answer", END)

    return workflow.compile()

async def create_text2sql_agent() -> tuple[str, list]:    
    app = buildText2SQLAgent()
    config = {
        "recursion_limit": 500,
        "configurable": {"thread_id": chat.user_id}
    }        
    
    return app, config

async def text2sql_agent(query: str, notification_queue: NotificationQueue):
    queue = notification_queue if notification_queue else None
    if queue:
        queue.reset()

    logger.info(f"text2sql_agent: {query}")

    app, config = await create_text2sql_agent()

    inputs = {
        "question": query
    }

    result = ""
    tool_used = False  # Track if tool was used
    tool_name = toolUseId = ""
    async for stream in app.astream(inputs, config, stream_mode="messages"):
        if not isinstance(stream[0], AIMessageChunk):
            continue

        message = stream[0]
        metadata = stream[1] if len(stream) > 1 else {}
        node = metadata.get("langgraph_node")
        if node and node != "get_database_answer":
            continue

        text_content = extract_chunk_text(message)
        if text_content:
            if tool_used:
                result = text_content
                tool_used = False
            else:
                result += text_content
            if queue:
                chat.update_streaming_result(notification_queue, result, "markdown")

        if isinstance(message.content, list):
            for content_item in message.content:
                if not isinstance(content_item, dict):
                    continue
                if content_item.get("type") == "tool_use":
                    if "id" in content_item and "name" in content_item:
                        toolUseId = content_item.get("id", "")
                        tool_name = content_item.get("name", "")
                        logger.info(f"tool_name: {tool_name}, toolUseId: {toolUseId}")
                        if queue:
                            queue.register_tool(toolUseId, tool_name)
                    if "partial_json" in content_item:
                        partial_json = content_item.get("partial_json", "")
                        if toolUseId not in chat.tool_input_list:
                            chat.tool_input_list[toolUseId] = ""
                        chat.tool_input_list[toolUseId] += partial_json
                        input = chat.tool_input_list[toolUseId]
                        if queue:
                            queue.tool_update(toolUseId, f"Tool: {tool_name}, Input: {input}")

    if not result:
        result = "답변을 찾지 못하였습니다."

    if queue:
        chat.update_final_result(notification_queue, result)

    return result