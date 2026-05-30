# Schema Linking

Text-to-SQL 분야에서 핵심적인 단계 중 하나로, 자연어 질문(Natural Language Question)에 등장하는 단어나 표현을 데이터베이스의 스키마 요소(테이블명, 컬럼명, 값 등)와 연결(매핑)하는 과정입니다. 자연어에는 모호한 표현이 많기 때문에, 어떤 테이블/컬럼을 가리키는지 정확히 파악해야 올바른 SQL을 생성할 수 있습니다. Schema Linking이 잘못되면 엉뚱한 테이블이나 컬럼을 참조하는 SQL이 만들어져 결과가 틀리게 됩니다.

### 주요 방법

- 문자열 매칭 - 질문의 단어와 스키마 이름을 직접 비교
- 임베딩 유사도 - 단어의 의미적 유사도를 벡터로 비교
- LLM 활용 - GPT 등 대형 언어 모델이 문맥을 파악하여 자동으로 연결

## 구현

복잡한 데이터베이스에서 Text2SQL의 가장 어려운 작업은 쿼리 생성에 필요한 스키마를 선별하는 과정, 즉 Schema Linking 입니다.

현실의 기업 환경에서는 테이블/컬럼 이름이 의미를 축약하고 있어서 LLM이 이를 파악하기 힘들거나, 테이블/컬럼이 너무 많아서 모든 목록을 프롬프트에 담아 전달하는 것이 불가능한 경우가 많습니다.

이를 해결하기 위해, 우리 DB에 맞춰 스키마 설명 문서를 정제하고, LLM에 필요한 컨텍스트를 선별하여 제공하는 작업이 필요합니다. 이 노트북에서는 스키마 준비 과정을 시뮬레이션 하기 위해, Chinook DB 설명 문서를 활용하겠습니다. 전체 작업 흐름은 아래와 같이 이어갈 예정입니다.

### Schema Description 문서 활용

[chinook_schema.json](./labs/chinook_schema.json)와 같은 Schema를 설명한 문서를 활용할 수 있습니다. 아래는 정의된 schema의 일부분입니다.

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

Schema description 문서에는 테이블의 이름과 테이블에 대한 기본 설명, 컬럼 이름과 컬럼에 대한 설명이 포함되어야 합니다. 

정리된 스키마 설명 문서가 없다면, 아주 기본적인 정보만 제공하고 LLM이 이를 증강하여 초기 설명문서 자체를 생성하도록 할 수도 있습니다. 



## Query Translator

좋은 샘플 쿼리를 LLM에게 제공하는 것은 쿼리 작성 뿐만 아니라 Schema Linking에도 도움이 됩니다. 그러나, 대부분의 기업 환경에서 자주 사용되는 쿼리를 로그로 관리하고 있는 반면, (기존에 Text2SQL을 사용하지 않았기 때문에) 쿼리에 매칭되는 자연어 질문은 없습니다. 

자주 사용하는 쿼리들을 자연어 질문으로 변환하는 SQL2Text 과정을 진행합니다.

[chinook_sample_queries.sql](./labs/chinook_sample_queries.sql)에 아래와 같이 sample이 있습니다.

쿼리를 해석하기 위해, 각 쿼리에 사용된 테이블/컬럼의 의미를 파악해야 합니다. 따라서, 각 쿼리에 사용된 테이블/컬럼 정보를 아래와 같이 추출합니다.
```
{
  "table": ["table1", "table2", ...],
  "column": ["col1", "col2", ...]
}
```
다음은 SQL 쿼리에 활용된 스키마 목록을 추출하는 LLM 요청 구문입니다.



