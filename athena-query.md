# Athena Query

여기에서는 Amazon Glue의 catalog를 이용해 SQL query하는것에 대해 설명합니다.

## 데이터 준비

[Amazon Serverless를 이용한 실시간 버스 정보 수집 및 저장](https://github.com/kyopark2014/analytics-for-bus-schedule)을 실행하면 아래와 같은 데이터를 수집할 수 있습니다.


<img width="818" alt="image" src="https://user-images.githubusercontent.com/52392004/163711367-be6c51a4-5300-4bc7-919a-481373dceeac.png">



Glue database의 Table에 접속해서 businfo를 선택하면 아래와 같은 schema 정보를 확인할 수 있습니다.

<img width="684" height="280" alt="image" src="https://github.com/user-attachments/assets/8d809ab7-813c-46cb-bf83-128519d0bb6c" />

이 schema 정보를 json으로 추출하면 아래와 같습니다.

```java
[
   {
      "Name":"timestamp",
      "Type":"string"
   },
   {
      "Name":"routeid",
      "Type":"string"
   },
   {
      "Name":"remainseatcnt",
      "Type":"string"
   },
   {
      "Name":"plateno",
      "Type":"string"
   },
   {
      "Name":"predicttime",
      "Type":"string"
   }
]
```

이후 아래와 같이 변환합니다.

```bash
@athena/schema.json 을 @athena/chinook_schema.json 와 같은 형태로 변환하여 @athena/athena_schema.json 에 저장하세요.
```

이때 얻어진 [athean_schema.json](./athena/athena_schema.json)은 아래와 같습니다.

```java
[
    {
        "bus_arrival": {
            "table_desc": "Stores real-time bus arrival information including route, vehicle, remaining seats, and predicted arrival time.",
            "cols": [
                {
                    "col": "timestamp",
                    "col_desc": "Timestamp when the bus arrival data was recorded."
                },
                {
                    "col": "routeid",
                    "col_desc": "Identifier of the bus route."
                },
                {
                    "col": "remainseatcnt",
                    "col_desc": "Number of remaining seats on the bus."
                },
                {
                    "col": "plateno",
                    "col_desc": "License plate number of the bus vehicle."
                },
                {
                    "col": "predicttime",
                    "col_desc": "Predicted arrival time of the bus at the stop."
                }
            ]
        }
    }
]
```

아래와 같이 [sample_queries.sql](./athena/sample_queries.sql)을 생성합니다.

```bash
@athena/sample_queries.sql 는 @athena/athean_schema.json 을 참조하여 @athena/chinook_sample_queries.sql 과 형태로 작성하여 주세요. 예제는 5개정도 만들어주세요.
```

이때 생성된 [athena_queries.jsonl](./athena/athena_queries.jsonl)은 아래와 같습니다.

```java
{
  "input": "버스 도착 정보 전체 조회",
  "query": "SELECT * FROM bus_arrival"
}
{
  "input": "버스 도착 정보 테이블에서 첫 번째 행의 노선 ID와 동일한 모든 도착 정보 조회",
  "query": "SELECT * FROM bus_arrival WHERE routeid = (SELECT routeid FROM bus_arrival LIMIT 1)"
}
{
  "input": "bus_arrival 테이블의 전체 잔여 좌석 수 합계 조회",
  "query": "SELECT SUM(remainseatcnt) FROM bus_arrival"
}
{
  "input": "잔여 좌석이 0인 버스 도착 정보 건수 조회",
  "query": "SELECT COUNT(*) FROM bus_arrival WHERE remainseatcnt = 0"
}
{
  "input": "평균 잔여 좌석 수가 많은 상위 5개 버스 노선 조회",
  "query": "SELECT routeid, AVG(remainseatcnt) AS AvgRemainSeats FROM bus_arrival GROUP BY routeid ORDER BY AvgRemainSeats DESC LIMIT 5"
}
```

[athena_queries.jsonl](./athena/athena_queries.jsonl)을 Amazon S3에 복사하고 Knowledge Base에서 sync를 하면 준비가 완료됩니다.
