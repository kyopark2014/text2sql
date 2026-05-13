# Chinook Database

Chinook은 SQL Server, Oracle, MySQL 등 다양한 DBMS에서 사용할 수 있는 샘플 데이터베이스입니다. SQL 스크립트 하나만 실행하면 바로 생성할 수 있으며, 기존의 Northwind 데이터베이스의 대안으로 만들어졌습니다. 단일 및 다중 데이터베이스 서버를 대상으로 하는 ORM 도구의 데모 및 테스트에 적합합니다.

---

## 지원 데이터베이스

- DB2
- MySQL
- Oracle
- PostgreSQL
- SQL Server
- SQLite

---

## 다운로드

[최신 릴리즈](https://github.com/lerocha/chinook-database/releases) 페이지에서 SQL 스크립트 파일을 다운로드할 수 있습니다. 각 DB 벤더별로 하나 이상의 SQL 스크립트가 제공되며, 원하는 DB 도구로 실행하면 됩니다.

> 같은 제작자가 만든 [Netflix Sample Database](https://github.com/lerocha/netflixdb)도 있습니다. Netflix 참여 보고서 및 Netflix 글로벌 TOP 10 주간 목록 데이터를 기반으로 한 영화 및 TV 쇼 샘플 데이터베이스입니다.

---

## 데이터 모델

Chinook의 데이터 모델은 아티스트, 앨범, 미디어 트랙, 송장, 고객 테이블을 포함한 디지털 미디어 스토어를 표현합니다.

![Chinook 데이터 모델](https://github.com/lerocha/chinook-database/assets/135025/cea7a05a-5c36-40cd-84c7-488307a123f4)

---

## 샘플 데이터

| 데이터 종류 | 출처 |
|---|---|
| 미디어 관련 데이터 | 실제 iTunes Library 데이터 기반 |
| 고객 및 직원 정보 | 가상의 이름, 주소, 전화번호 등으로 수동 생성 |
| 판매 정보 | 4년치 랜덤 자동 생성 |

미디어 관련 데이터는 실제 iTunes Library 데이터를 사용하여 생성되었습니다. 본인의 iTunes Library를 사용하여 SQL 스크립트를 직접 생성하는 것도 가능합니다. 고객 및 직원 정보는 가상의 이름, Google 지도에서 확인 가능한 주소, 전화번호, 팩스, 이메일 등의 형식에 맞게 수동으로 생성되었습니다. 판매 정보는 4년간의 랜덤 데이터로 자동 생성됩니다.

---

## 이름의 유래

이 샘플 데이터베이스의 이름은 Northwind 데이터베이스를 기반으로 지어졌습니다. Chinook은 북미 내륙 서부, 캐나다 대초원과 산악 지대가 만나는 곳에 부는 바람의 이름으로, 캐나다 앨버타 남부에서 가장 자주 붑니다. Northwind(북풍)를 대체하는 데이터베이스인 만큼, 또 다른 바람 이름인 Chinook을 선택한 것입니다.

---

## 개발 환경

### 시스템 요구사항

- [.NET 8](https://dotnet.microsoft.com/en-us/download/dotnet/8.0)
- [dotnet-t4](https://www.nuget.org/packages/dotnet-t4/) (T4 템플릿 처리 CLI 도구): `dotnet tool install --global dotnet-t4`

### 참고 사항

- `dotnet` 및 `dotnet-t4` 도구만 있으면 macOS, Linux, Windows 모든 OS에서 스크립트 빌드 및 생성이 가능합니다.
- IDE가 필요한 경우 [Visual Studio Code](https://code.visualstudio.com)에서 권장 플러그인을 설치하거나, JetBrains Rider 또는 Visual Studio Community Edition(Windows 전용)을 사용할 수 있습니다.
- SQL 스크립트는 [Text Template Transformation](https://learn.microsoft.com/en-us/visualstudio/modeling/code-generation-and-t4-text-templates?view=vs-2022)을 사용하여 자동 생성됩니다.
- `ChinookDataSet.xsd` 파일에는 스키마 정의가, `ChinookData.json`에는 데이터가, `*.tt` 파일에는 SQL 스크립트를 생성하는 텍스트 템플릿이 포함되어 있습니다.

### 빌드, 스크립트 자동 생성 및 테스트

```bash
# SQL 스크립트 빌드 및 자동 생성
dotnet build

# 로컬 데이터베이스 실행 (Docker 필요)
docker compose up -d

# 전체 테스트 실행
dotnet test
```
