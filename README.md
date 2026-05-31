# LLM으로 SQL 생성하기

RDB를 조회하여 사용할때 필요한 기능을 정의하고자 합니다.

추후 Reference를 바탕으로 SQL Query를 수행할 계획입니다.

## Chinook Sample

여기에서는 [Chinook](https://github.com/lerocha/chinook-database/blob/master/README.md)을 활용합니다. 상세한 내용은 [chinook-database.md](./chinook-database.md)을 참조합니다.

<img width="700" alt="chinook_table" src="./contents/chinook_table.png" />

## Schema Linking


## Agentic Workflow

[Workflow Composition using LangGraph](https://github.com/aws-samples/aws-ai-ml-workshop-kr/tree/master/genai/aws-gen-ai-kr/20_applications/12_advanced_agentic_text2sql#lab-2-workflow-composition-using-langgraph)와 같이 Graph를 이용해 agent를 이용해 좀더 복잡한 경우에도 효과적으로 query문을 생성할 수 있습니다.



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
