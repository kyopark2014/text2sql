# Athena Query

여기에서는 Amazon Glue의 catalog를 이용해 SQL query하는것에 대해 설명합니다.

## 데이터 준비

[Amazon Serverless를 이용한 실시간 버스 정보 수집 및 저장](https://github.com/kyopark2014/analytics-for-bus-schedule)을 실행하면 아래와 같은 데이터를 수집할 수 있습니다.


<img width="818" alt="image" src="https://user-images.githubusercontent.com/52392004/163711367-be6c51a4-5300-4bc7-919a-481373dceeac.png">



Glue database의 Table에 접속해서 businfo를 선택하면 아래와 같은 table 정보를 확인할 수 있습니다.

<img width="684" height="280" alt="image" src="https://github.com/user-attachments/assets/8d809ab7-813c-46cb-bf83-128519d0bb6c" />

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
@athena/schema.json 을 @athena/chinook_schema.json 와 같은 형태로 변환하여 @athena/athean_schema.json 에 저장하세요.
```

이때 얻어진 [athean_schema.json](./athena/athean_schema.json)은 아래와 같습니다.

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


