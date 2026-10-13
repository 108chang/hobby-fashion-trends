# 공개 범위 점검 (2026-10-13)

공개 대상: 수집·분석·모델링 코드, 설정의 상품 정의, 방법론, 실제 데이터가 없는 소개 페이지.
비공개 로컬 보관: API 시계열 CSV, 분석 결과 CSV, 내장 데이터 HTML, 보고서 PDF, 전체 입력 ZIP.

NAVER Developers 일반약관 7.3과 8.1~8.2는 허용 범위를 넘는 저장·가공·배포와 결과 데이터의 권리를 제한한다. 검색 API 특약을 데이터랩에 그대로 적용해 금지라고 단정하지 않는다. 현재 수집 코드는 NAVER API HUB 호스트를 사용한다. API HUB 약관 개정 공지(2026-09-20 시행)를 확인했지만 이 자료에 적용되는 계약 및 데이터랩 재배포 허용 조항은 확인되지 않았다. 비공개 저장소도 약관상 재배포 허가를 대신하지 않는다. 별도 허가가 확보될 때까지 데이터를 외부 업로드하지 않는다.

- https://developers.naver.com/products/terms/
- https://www.ncloud.com/support/notice/all/2243
- https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md

Client ID/Secret은 브라우저 JavaScript, HTML, URL, PDF, 커밋에 넣지 않는다. API 호출은 로컬 환경변수에서만 수행한다. 원본 .env·가상환경·백업·개인 경로는 패키지에서 제외했다.
GitHub Pages의 사이트 접근 제한은 별도 기능 및 플랜 조건을 확인해야 한다. private 저장소만으로 사이트가 비공개라는 보장은 없다.
