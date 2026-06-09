
import os
import json
import mcp_retrieve
import logging
import sys
import chat
import re
import langgraph_agent

from langchain_core.prompts.chat import ChatPromptTemplate
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_QUERIES_PATH = os.path.normpath(
    os.path.join(WORKING_DIR, "..", "labs", "example_queries_temp.jsonl")
)

engine = create_engine(f"sqlite:///{langgraph_agent.CHINOOK_DB_PATH}")
db = SQLDatabase(engine)
DIALECT = "sqlite"

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("text2sql")


def load_schema_description():
    file_path = os.path.join(WORKING_DIR, '..', 'labs', 'chinook_schema.json')

    with open(file_path, 'r') as file:
        schema_description = json.load(file)

    return schema_description


def get_sample_queries(question: str) -> list:
    samples_json = mcp_retrieve.retrieve(question)
    logger.info(f"samples: {samples_json}")

    samples = json.loads(samples_json)
    contents = [doc["contents"] for doc in samples if doc.get("contents")]
    logger.info(f"contents: {contents}")

    return contents


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


def generate_query(question: str) -> str:
    sample_queries = get_sample_queries(question)

    table_details = load_schema_description()
    dialect = "sqlite"
    
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
    )

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat.get_chat()

    response = chain.invoke({
        "dialect": dialect,
        "question": question,
        "sample_queries": sample_queries,
        "table_details": table_details
    })
    logger.info(f"response of generate_query: {response.content}")

    generated_query = extract_sql_query(response.content)
    logger.info(f"generated_query: {generated_query}")

    return generated_query


def is_execution_error(result: str) -> bool:
    return isinstance(result, str) and result.startswith("An error occurred")


def save_example_query(input_text: str, query: str) -> bool:
    """성공한 질문-SQL 쌍을 labs/example_queries_temp.jsonl에 추가합니다."""
    input_text = input_text.strip()
    query = query.strip().rstrip(";").strip()
    if not input_text or not query:
        return False

    entry = {"input": input_text, "query": query}
    serialized = json.dumps(entry, ensure_ascii=False, indent=2)

    if os.path.exists(EXAMPLE_QUERIES_PATH):
        with open(EXAMPLE_QUERIES_PATH, "r", encoding="utf-8") as f:
            if serialized in f.read():
                logger.info("example query already exists, skipping append")
                return False

    os.makedirs(os.path.dirname(EXAMPLE_QUERIES_PATH), exist_ok=True)
    with open(EXAMPLE_QUERIES_PATH, "a", encoding="utf-8") as f:
        f.write(serialized + "\n")

    logger.info(f"saved example query to {EXAMPLE_QUERIES_PATH}")
    return True


def execute_query(query: str) -> str:
    try:
        query_result = db.run(query)
        logger.info(f"query result: {query_result}")

    except Exception as e:
        return f"An error occurred while executing the query: {str(e)}"

    return query_result