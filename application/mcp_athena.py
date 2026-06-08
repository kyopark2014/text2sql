
import os
import json
import time
import mcp_retrieve
import logging
import sys
import chat
import re
import boto3
import utils

from langchain_core.prompts.chat import ChatPromptTemplate

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))

config = utils.load_config()
REGION = config.get("region", "us-west-2")
S3_BUCKET = config.get("s3_bucket")
ATHENA_CATALOG = "AwsDataCatalog"
ATHENA_DATABASE = "businfo"
ATHENA_WORKGROUP = "primary"
ATHENA_OUTPUT_LOCATION = f"s3://{S3_BUCKET}/athena-results/"
DIALECT = "Amazon Athena (Presto SQL)"

QUERY_POLL_INTERVAL_SEC = 0.5
QUERY_TIMEOUT_SEC = 120

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("text2sql")

_athena_client = None
_glue_client = None


def get_athena_client():
    global _athena_client
    if _athena_client is None:
        _athena_client = boto3.client("athena", region_name=REGION)
    return _athena_client


def get_glue_client():
    global _glue_client
    if _glue_client is None:
        _glue_client = boto3.client("glue", region_name=REGION)
    return _glue_client


def _load_local_schema_descriptions():
    file_path = os.path.join(WORKING_DIR, "..", "athena", "athena_schema.json")

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_schema_description():
    """Glue Data Catalog에서 businfo DB 스키마를 조회하고 로컬 설명과 병합."""
    glue = get_glue_client()
    local_descriptions = _load_local_schema_descriptions()

    local_table_desc = {}
    local_col_desc = {}
    for entry in local_descriptions:
        for table_name, info in entry.items():
            local_table_desc[table_name.lower()] = info.get("table_desc", "")
            for col in info.get("cols", []):
                local_col_desc[col["col"].lower()] = col.get("col_desc", "")

    schema = []
    paginator = glue.get_paginator("get_tables")
    for page in paginator.paginate(DatabaseName=ATHENA_DATABASE):
        for table in page["TableList"]:
            table_name = table["Name"]
            table_desc = local_table_desc.get(table_name.lower())
            if not table_desc:
                table_desc = next(iter(local_table_desc.values()), "")

            cols = []
            for col in table["StorageDescriptor"]["Columns"]:
                col_name = col["Name"]
                cols.append({
                    "col": col_name,
                    "type": col["Type"],
                    "col_desc": local_col_desc.get(col_name.lower(), ""),
                })

            for partition in table.get("PartitionKeys", []):
                col_name = partition["Name"]
                cols.append({
                    "col": col_name,
                    "type": partition["Type"],
                    "col_desc": local_col_desc.get(col_name.lower(), "Partition column"),
                    "partition": True,
                })

            schema.append({
                table_name: {
                    "database": ATHENA_DATABASE,
                    "catalog": ATHENA_CATALOG,
                    "table_desc": table_desc,
                    "cols": cols,
                }
            })

    logger.info(f"loaded schema from Glue: {schema}")
    return schema


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

    system = (
        "당신은 사용자 질문에 대한 {dialect} SQL 쿼리를 작성하는 유능한 데이터베이스 엔지니어입니다. "
        "당신의 임무는 주어진 DB 정보를 바탕으로, 사용자 질문에 부합하는 정확한 SQL 쿼리를 작성하는 것입니다.\n"
        "대상 데이터베이스는 AWS Glue Data Catalog의 {catalog} 카탈로그, {database} 데이터베이스입니다. "
        "테이블 이름은 스키마에 명시된 이름을 그대로 사용하세요.\n"
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
        "dialect": DIALECT,
        "catalog": ATHENA_CATALOG,
        "database": ATHENA_DATABASE,
        "question": question,
        "sample_queries": sample_queries,
        "table_details": table_details
    })
    logger.info(f"response of generate_query: {response.content}")

    generated_query = extract_sql_query(response.content)
    logger.info(f"generated_query: {generated_query}")

    return generated_query


def _wait_for_query(query_execution_id: str) -> dict:
    athena = get_athena_client()
    deadline = time.time() + QUERY_TIMEOUT_SEC

    while time.time() < deadline:
        response = athena.get_query_execution(QueryExecutionId=query_execution_id)
        execution = response["QueryExecution"]
        state = execution["Status"]["State"]

        if state == "SUCCEEDED":
            return execution
        if state in ("FAILED", "CANCELLED"):
            reason = execution["Status"].get("StateChangeReason", state)
            raise RuntimeError(reason)

        time.sleep(QUERY_POLL_INTERVAL_SEC)

    raise TimeoutError(
        f"Athena query timed out after {QUERY_TIMEOUT_SEC} seconds "
        f"(QueryExecutionId={query_execution_id})"
    )


def _fetch_query_results(query_execution_id: str) -> str:
    athena = get_athena_client()
    paginator = athena.get_paginator("get_query_results")
    pages = paginator.paginate(QueryExecutionId=query_execution_id)

    all_rows = []
    headers = None
    for page in pages:
        rows = page["ResultSet"]["Rows"]
        if not rows:
            continue

        if headers is None:
            headers = [col.get("VarCharValue", "") for col in rows[0]["Data"]]
            rows = rows[1:]

        for row in rows:
            values = [col.get("VarCharValue", "") for col in row["Data"]]
            all_rows.append(dict(zip(headers, values)))

    if headers is None:
        return "[]"

    if not all_rows:
        return f"Columns: {headers}\nRows: []"

    return json.dumps(all_rows, ensure_ascii=False, indent=2)


def execute_athena_query(query: str) -> str:
    """boto3로 Amazon Athena 쿼리를 실행하고 결과를 반환."""
    if not query or not query.strip():
        return "An error occurred while executing the query: empty SQL"

    try:
        athena = get_athena_client()
        response = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={
                "Database": ATHENA_DATABASE,
                "Catalog": ATHENA_CATALOG,
            },
            ResultConfiguration={"OutputLocation": ATHENA_OUTPUT_LOCATION},
            WorkGroup=ATHENA_WORKGROUP,
        )
        query_execution_id = response["QueryExecutionId"]
        logger.info(f"started Athena query: {query_execution_id}")

        _wait_for_query(query_execution_id)
        query_result = _fetch_query_results(query_execution_id)
        logger.info(f"query result: {query_result}")

    except Exception as e:
        return f"An error occurred while executing the query: {str(e)}"

    return query_result
