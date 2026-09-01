# Employee Search MCP

직원 검색 및 상세정보 조회, 이메일 전송을 위한 MCP 서버입니다.

Dify와 연동하여 사용자의 자연어 요청을 기반으로
직원 검색, 직원 상세정보 조회, 이력서 확인, 이메일 전송을 처리합니다.

## 주요 기능

- 직원 조건 검색
  - 부서
  - 국적
  - 개발 스킬
  - 사용 가능 언어
  - 자격증
  - 실무경력
  - 근무 가능 지역
  - 투입 가능 시기

- 직원 상세정보 조회

- 직원 이력서 PDF 링크 제공

- Gmail SMTP를 이용한 이메일 전송

- MCP Streamable HTTP 지원

## 프로젝트 구조

```text
employee-search-mcp/
├── server.py
├── mail_server.py
├── employees.csv
├── pdf/
├── start_mcp.sh
├── pyproject.toml
└── README.md
