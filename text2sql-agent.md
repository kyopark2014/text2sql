## Agentic Workflow

[Workflow Composition using LangGraph](https://github.com/aws-samples/aws-ai-ml-workshop-kr/tree/master/genai/aws-gen-ai-kr/20_applications/12_advanced_agentic_text2sql#lab-2-workflow-composition-using-langgraph)와 같이 Graph를 이용해 agent를 이용해 좀더 복잡한 경우에도 효과적으로 query문을 생성할 수 있습니다.

이때의 세부동작은 아래와 같습니다.

<img width="903" height="870" alt="image" src="https://github.com/user-attachments/assets/f472f8c2-c2de-4e4b-8552-30dc5d110b7d" />

## 상세 구현

get_sample_queries와 같이 Knowledge Base를 이용해 질문과 유사한 SQL sample을 가져옯니다.

```python
def get_sample_queries(state: GraphState) -> GraphState:
    question = state["question"]
    samples_json = mcp_retrieve.retrieve(question)
    logger.info(f"samples: {samples_json}")

    samples = json.loads(samples_json)
    contents = [doc["contents"] for doc in samples if doc.get("contents")]
    logger.info(f"contents: {contents}")

    return GraphState(sample_queries=contents)
```

check_readiness는 가져온 sample queries들이 query를 생성할만큼 충분히 적절한지 확인합니다. 

```python
def check_readiness(state: GraphState) -> GraphState:
    question = state["question"]
    sample_queries = state["sample_queries"]
    
    table_details = state.get("table_details") or load_schema_description()

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
    readiness = parse_readiness(response.content)

    return GraphState(readiness=readiness)
```

generate_query에서는 질문, sample query와 table 정보를 활용하여 query문을 생성합니다.

```python
def generate_query(state: GraphState) -> GraphState:
    new_query_state = copy.deepcopy(initial_query_state)
    question = state["question"]

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
```

execute_query은 생성된 query를 이용하여 조회합니다.

```python
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
```



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


