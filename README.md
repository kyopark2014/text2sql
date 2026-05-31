# LLM으로 SQL 생성하기

RDB를 조회하여 사용할때 필요한 기능을 정의하고자 합니다.

추후 Reference를 바탕으로 SQL Query를 수행할 계획입니다.

## Chinook Sample

여기에서는 [Chinook](https://github.com/lerocha/chinook-database/blob/master/README.md)을 활용합니다. 상세한 내용은 [chinook-database.md](./chinook-database.md)을 참조합니다.

<img width="700" alt="chinook_table" src="./contents/chinook_table.png" />

## Schema Linking

Text-to-SQL 분야에서 핵심적인 단계 중 하나로, 자연어 질문(Natural Language Question)에 등장하는 단어나 표현을 데이터베이스의 스키마 요소(테이블명, 컬럼명, 값 등)와 연결(매핑)하는 과정입니다. 자연어에는 모호한 표현이 많기 때문에, 어떤 테이블/컬럼을 가리키는지 정확히 파악해야 올바른 SQL을 생성할 수 있습니다. Schema Linking이 잘못되면 엉뚱한 테이블이나 컬럼을 참조하는 SQL이 만들어져 결과가 틀리게 됩니다. 상세 내용은 [Lab. 1-1 Schema Preparation-1](https://github.com/aws-samples/aws-ai-ml-workshop-kr/blob/master/genai/aws-gen-ai-kr/20_applications/12_advanced_agentic_text2sql/lab1_text2sql_schema_preparation/1.sample_queries.ipynb)을 참조하였습니다.

Schema linking은 아래와 같은 방법을 통해 구현합니다.

- 문자열 매칭 - 질문의 단어와 스키마 이름을 직접 비교
- 임베딩 유사도 - 단어의 의미적 유사도를 벡터로 비교
- LLM 활용 - GPT 등 대형 언어 모델이 문맥을 파악하여 자동으로 연결

복잡한 데이터베이스에서 Text2SQL의 가장 어려운 작업은 쿼리 생성에 필요한 스키마를 선별하는 과정, 즉 Schema Linking 입니다. 현실의 기업 환경에서는 테이블/컬럼 이름이 의미를 축약하고 있어서 LLM이 이를 파악하기 힘들거나, 테이블/컬럼이 너무 많아서 모든 목록을 프롬프트에 담아 전달하는 것이 불가능한 경우가 많습니다. 이를 해결하기 위해, 우리 DB에 맞춰 스키마 설명 문서를 정제하고, LLM에 필요한 컨텍스트를 선별하여 제공하는 작업이 필요합니다. 이 노트북에서는 스키마 준비 과정을 시뮬레이션 하기 위해, Chinook DB 설명 문서를 활용하겠습니다. 전체 작업 흐름은 아래와 같이 이어갈 예정입니다.

### Step 1: Schema Description 문서 로드

[chinook_schema.json](./labs/chinook_schema.json)와 같은 Schema를 설명한 문서를 활용할 수 있습니다. 아래는 정의된 schema의 일부분입니다. Schema description 문서에는 테이블의 이름과 테이블에 대한 기본 설명, 컬럼 이름과 컬럼에 대한 설명이 포함되어야 합니다. 

```java
{
    "table_name": {
        "table_desc": "Description of the table",
        "cols": [
            {
                "col": "Column Name 1",
                "col_desc": "Description of the column including PK info"
            },
            {
                "col": "Column Name 2",
                "col_desc": "Description of the column"
            }
        ]
    }
}
```

정리된 스키마 설명 문서가 없다면, 먼저 기본적인 정보만 제공하고 LLM이 이를 증강하여 초기 설명문서 자체를 생성하도록 할 수도 있습니다. 


### Step 2: SQL2Text 샘플 쿼리 변환 

좋은 샘플 쿼리를 LLM에게 제공하는 것은 쿼리 작성 뿐만 아니라 schema linking에도 도움이 됩니다. 그러나, 대부분의 기업 환경에서 자주 사용되는 쿼리를 로그로 관리하므로, Text2SQL에서 사용하는 쿼리에 매칭되는 자연어 질문은 없습니다. 자주 사용하는 쿼리들을 자연어 질문으로 변환하는 SQL2Text 과정을 진행합니다.

쿼리를 해석하기 위해서는 각 쿼리에 사용된 테이블/컬럼의 의미를 파악해야 합니다. 따라서, 각 쿼리에 사용된 테이블/컬럼 정보를 아래와 같이 추출합니다.
```
{
  "table": ["table1", "table2", ...],
  "column": ["col1", "col2", ...]
}
```

[chinook_sample_queries.sql](./labs/chinook_sample_queries.sql)와 같은 sample이 있다고 가정합니다. 여기서는 설명을 위해 "SELECT CustomerId, SUM(Total) AS TotalPurchase FROM Invoice GROUP BY CustomerId ORDER BY TotalPurchase DESC LIMIT 5"에 대한 변환을 해보겠습니다. 아래의 extract_schema와 같이 query 문을 주고 table, column에 대한 정보를 추출합니다. 

```python
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
```

이때 추출된 table, column에 대한 결과는 아래와 같습니다.

```java
{
  "table": ["Invoice"],
  "column": ["CustomerId", "Total", "TotalPurchase"]
}
```

[chinook_schema.json](./labs/chinook_schema.json)에서 table과 column에 대한 description을 추출합니다.

```python
schema_description = load_schema_description()
extracted_description = extract_descriptions(
    schema_description, used_schema['table'], used_schema['column']
)
```

이때의 결과는 아래와 같습니다.

```python
{
  "table": {
    "Invoice": "Records details of transactions, linked to customers."
  },
  "column": {
    "CustomerId": "Foreign key that references the customer associated with this invoice.",
    "Total": "Total amount of the invoice."
  }
}
```

아래와 같이 query문의 의미를 하나의 문장으로 표현합니다.

```python
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
```

이와같이 "SELECT CustomerId, SUM(Total) AS TotalPurchase FROM Invoice GROUP BY CustomerId ORDER BY TotalPurchase DESC LIMIT 5"로 주어진 query문의 의미가 "구매 총액 기준 상위 5명의 고객별 총 구매 금액 내림차순 조회"로 변환됩니다.

나머지 항목에 대해서도 아래와 같이 수행합니다.

```
{
  "input": "Artist 테이블의 모든 데이터 조회",
  "query": "SELECT * FROM Artist"
}
{
  "input": "'AC/DC' 아티스트의 모든 앨범 조회",
  "query": "SELECT * FROM Album WHERE ArtistId = (SELECT ArtistId FROM Artist WHERE Name = 'AC/DC')"
}
{
  "input": "Rock 장르에 해당하는 모든 트랙 조회",
  "query": "SELECT * FROM Track WHERE GenreId = (SELECT GenreId FROM Genre WHERE Name = 'Rock')"
}
{
  "input": "Track 테이블의 전체 재생 시간 합계 조회",
  "query": "SELECT SUM(Milliseconds) FROM Track"
}
{
  "input": "캐나다 고객 전체 정보 조회",
  "query": "SELECT * FROM Customer WHERE Country = 'Canada'"
}
{
  "input": "앨범 ID가 5인 트랙의 총 개수 조회",
  "query": "SELECT COUNT(*) FROM Track WHERE AlbumId = 5"
}
{
  "input": "Invoice 테이블의 전체 레코드 수 조회",
  "query": "SELECT COUNT(*) FROM Invoice"
}
{
  "input": "재생 시간이 300,000밀리초 초과인 트랙 전체 정보 조회",
  "query": "SELECT * FROM Track WHERE Milliseconds > 300000"
}
{
  "input": "구매 총액 기준 상위 5명의 고객별 총 구매 금액 내림차순 조회",
  "query": "SELECT CustomerId, SUM(Total) AS TotalPurchase FROM Invoice GROUP BY CustomerId ORDER BY TotalPurchase DESC LIMIT 5"
}
{
  "input": "전체 직원 수 조회",
  "query": "SELECT COUNT(*) FROM Employee"
}
```



## Agentic Workflow

[Workflow Composition using LangGraph](https://github.com/aws-samples/aws-ai-ml-workshop-kr/tree/master/genai/aws-gen-ai-kr/20_applications/12_advanced_agentic_text2sql#lab-2-workflow-composition-using-langgraph)와 같이 Graph를 이용해 agent를 이용해 좀더 복잡한 경우에도 효과적으로 query문을 생성할 수 있습니다.


### 


## 실행 결과

아래와 같이 "Text2SQL Agent"을 선택합니다.

<img width="192" height="263" alt="image" src="https://github.com/user-attachments/assets/7b6faf50-2cbe-4bc4-a7db-2ac9fd2b0520" />

"Track 테이블의 전체 재생 시간"을 입력하면 기존 검색이므로 아래와 같은 답변을 얻을 수 있습니다.

<img width="725" alt="image" src="https://github.com/user-attachments/assets/a36569cb-a70e-4028-a22b-d20ac5129ea1" />


이후 "테이블의 전체 레코드 수 조회"하면, 유사한 schema를 활용하여 아래와 같은 검색을 수행합니다.

<img width="729" alt="image" src="https://github.com/user-attachments/assets/798567d7-4841-44e3-a013-8818a692460b" />

최종 결과는 아래와 같습니다.

<img width="675" alt="image" src="https://github.com/user-attachments/assets/27879ea2-83fe-425e-8693-706e0ca748c3" />



"크리스마스에 듣기 좋은 음악 리스트는?"와 같은 질문을 하면 기존 query에 없으므로 아래와 같이 schema 정보를 이용해 query문을 생성합니다.



<img width="719" alt="image" src="https://github.com/user-attachments/assets/ea2d21e9-911c-477c-94f6-6e7d1b80f7e5" />



## Reference

[Amazon Bedrock과 LangChain을 이용한 "비즈니스 데이터 분석을 위한 자연어 기반 BI"](https://github.com/jesamkim/aws-genai-for-retail/blob/main/2_lab/2-text-to-sql_redshift.ipynb)

[Invoke Bedrock model for SQL Query Generation](https://github.com/aws-samples/amazon-bedrock-workshop/blob/main/06_CodeGeneration/01_sql_query_generate_w_bedrock.ipynb)

[Text-to-Trouble: Real World Vulnerabilities in LLM Based Text-to-SQL Solutions](https://medium.com/shape-ai/text-to-trouble-real-world-vulnerabilities-in-llm-based-text-to-sql-implementations-c7f2112a7470)
