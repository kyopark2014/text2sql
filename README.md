# LLM으로 SQL 생성하기

RDB를 조회하여 사용할때 필요한 기능을 정의하고자 합니다.

추후 Reference를 바탕으로 SQL Query를 수행할 계획입니다.

## Chinook Sample

여기에서는 [Chinook](https://github.com/lerocha/chinook-database/blob/master/README.md)을 활용합니다. 상세한 내용은 [chinook-database.md](./chinook-database.md)을 참조합니다.

<img width="700" alt="chinook_table" src="./contents/chinook_table.png" />

## Schema Linking

Text-to-SQL 분야에서 핵심적인 단계 중 하나로, 자연어 질문(Natural Language Question)에 등장하는 단어나 표현을 데이터베이스의 스키마 요소(테이블명, 컬럼명, 값 등)와 연결(매핑)하는 과정입니다. 자연어에는 모호한 표현이 많기 때문에, 어떤 테이블/컬럼을 가리키는지 정확히 파악해야 올바른 SQL을 생성할 수 있습니다. Schema Linking이 잘못되면 엉뚱한 테이블이나 컬럼을 참조하는 SQL이 만들어져 결과가 틀리게 됩니다.

### 주요 방법

- 문자열 매칭 - 질문의 단어와 스키마 이름을 직접 비교
- 임베딩 유사도 - 단어의 의미적 유사도를 벡터로 비교
- LLM 활용 - GPT 등 대형 언어 모델이 문맥을 파악하여 자동으로 연결


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
