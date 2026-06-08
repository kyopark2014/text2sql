import json
import os

from langchain_aws import ChatBedrock
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

modelId = "us.anthropic.claude-sonnet-4-6"
STOP_SEQUENCE = "\n\nHuman:"

def get_max_output_tokens(model_id: str = "") -> int:
    """Return the max output tokens based on the model ID."""
    if "claude-opus-4-6" in model_id:
        return 128000
    if "claude-opus-4-5" in model_id:
        return 64000
    if "claude-opus-4" in model_id or "claude-4-opus" in model_id:
        return 32000
    if "claude-sonnet-4" in model_id or "claude-4-sonnet" in model_id or "claude-haiku-4" in model_id:
        return 64000
    return 8192

model_kwargs = {
    "max_tokens": get_max_output_tokens(modelId),
    "temperature": 0.1,
    "top_k": 250,
    "stop_sequences": [STOP_SEQUENCE]
}

def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())

def load_schema_description():
    file_path = './athena_schema.json'

    with open(file_path, 'r') as file:
        schema_description = json.load(file)

    return schema_description

def load_queries():
    sql_file = './sample_queries.sql'

    with open(sql_file, 'r') as file:
        data = file.read()

    queries = [query.strip() for query in data.split(';') if query.strip()]

    for i, query in enumerate(queries, start=1):
        print(f"Query {i}:\n{query}\n{'-'*80}\n")

    return queries


def extract_schema(query):
    chat = ChatBedrock(model_id=modelId, region_name='us-west-2', model_kwargs=model_kwargs)

    system = """ 
You are an expert in extracting table names and column names from SQL queries. 
From the provided SQL query, extract all table names and column names used for SELECT, WHERE, and JOIN clauses, excluding asterisks ("*"). 
Ensure that the response is in a valid JSON format that can be used directly with json.load(). 
Skip the preamble and only provide the answer in a JSON document:

{{
  "table": ["table1", "table2", ...],
  "column": ["col1", "col2", ...]
}}

<example>
SQL:
SELECT * from LOGIS_ADMIN.IAWD_TB_DCBSCD_BASISLC_M 
where basis_lclsf_cd_nm like '%예약구분%'
LIMIT 200;

{{
  "table": ["IAWD_TB_DCBSCD_BASISLC_M"],
  "column": ["basis_lclsf_cd_nm"]
}}
</example>
"""
    human = "SQL: {sql}"

    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat | StrOutputParser()

    response = chain.invoke({"sql": query})

    used_schema = parse_json_response(response)
    print(used_schema)

    return used_schema

def extract_descriptions(table_info, tables, columns):
    tables_lower = {table.lower() for table in tables}
    columns_lower = {column.lower() for column in columns}
    
    description = {
        "table": {},
        "column": {}
    }
    
    for table_schema in table_info:
        for table_name, table_info in table_schema.items():
            if table_name.lower() in tables_lower:
                description["table"][table_name] = table_info["table_desc"]
                for col in table_info["cols"]:
                    col_name = col["col"]
                    if col_name.lower() in columns_lower:
                        description["column"][col_name] = col["col_desc"]
    return description



def translate_query(query, description):
    chat = ChatBedrock(model_id=modelId, region_name='us-west-2', model_kwargs=model_kwargs)

    system = """
You are an SQL expert who understands the intent behind a given SQL query.
Translate the SQL query into one short Korean sentence that a real user might say.

- Output exactly one sentence (under 80 Korean characters when possible).
- Include all filters, joins, aggregations, ordering, and limits from the SQL.
- Do not reference the <description> section; do not use a question form.
- Use a concise, straightforward tone without a verb ending (e.g. "~조회", "~확인").
- Do not add headings, bullet lists, markdown, or business-purpose explanations.
- Return only the sentence, with no preamble or labels.
"""
    human = """
<description>
{description}
</description>

SQL: {sql}
"""
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    chain = prompt | chat | StrOutputParser()

    response = chain.invoke({
        "sql": query,
        "description": json.dumps(description, ensure_ascii=False, indent=2),
    })

    return response


def main():
    schema_description = load_schema_description()
    queries = load_queries()

    inputs = []
    for query in queries:
        sql = query.strip()
        used_schema = extract_schema(sql)
        extracted_description = extract_descriptions(
            schema_description, used_schema['table'], used_schema['column']
        )
        natural_language = translate_query(sql, extracted_description)
        print(f"input: {natural_language}, sql: {sql}")

        inputs.append({"input": natural_language, "query": sql})

    print(f"inputs: {json.dumps(inputs, ensure_ascii=False, indent=2)}")

    FILE_PATH_1 = './athena_queries.jsonl'
    if not os.path.exists(FILE_PATH_1):
        with open(FILE_PATH_1, 'a') as output_file:
            for input in inputs:
                data = {"input": input["input"], "query": input["query"]}
                output_file.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")                

if __name__ == "__main__":
    main()