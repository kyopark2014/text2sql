pm = 'us-west-2'
opensearch_domain_endpoint = f"https://search-rag-multimodal-zeaonjcszpc7fpbivijtojze4m.us-west-2.es.amazonaws.com"
opensearch_user_id = 'admin'
opensearch_user_password = "Wifi1234!"
print(opensearch_domain_endpoint)

import json

# file_path = './chinook_schema.json'

# with open(file_path, 'r') as file:
#     schema_description = json.load(file)

# print(json.dumps(schema_description, indent=4))



sql_file = './chinook_sample_queries.sql'

with open(sql_file, 'r') as file:
    data = file.read()

queries = [query.strip() for query in data.split(';') if query.strip()]

for i, query in enumerate(queries, start=1):
    print(f"Query {i}:\n{query}\n{'-'*80}\n")


SYS_PROMPT_TEMPLATE1 = """ 
You are an expert in extracting table names and column names from SQL queries. 
From the provided SQL query, extract all table names and column names used for SELECT, WHERE, and JOIN clauses, excluding asterisks ("*"). 
Ensure that the response is in a valid JSON format that can be used directly with json.load(). 
Skip the preamble and only provide the answer in a JSON document:

{
  "table": ["table1", "table2", ...],
  "column": ["col1", "col2", ...]
}

<example>
SQL:
SELECT * from LOGIS_ADMIN.IAWD_TB_DCBSCD_BASISLC_M 
where basis_lclsf_cd_nm like '%예약구분%'
LIMIT 200;

{
  "table": ["IAWD_TB_DCBSCD_BASISLC_M"],
  "column": ["basis_lclsf_cd_nm"]
}
</example>
"""

USR_PROMPT_TEMPLATE1="""
SQL: {sql}
"""

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

parameters = {
    "max_tokens": get_max_output_tokens(modelId),
    "temperature": 0.1,
    "top_k": 250,
    "stop_sequences": [STOP_SEQUENCE],
    "system": SYS_PROMPT_TEMPLATE1,
}

def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())

model1 = ChatBedrock(model_id=modelId, region_name='us-west-2', model_kwargs=parameters)
prompt1 = ChatPromptTemplate.from_template(USR_PROMPT_TEMPLATE1)

chain1 = prompt1 | model1 | StrOutputParser()

sql = queries[8].strip()
response = chain1.invoke({"sql": sql})
used_schema = parse_json_response(response)
print(used_schema)