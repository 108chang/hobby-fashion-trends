# hobby-fashion-trends

운동 검색 관심도가 패션 쇼핑 클릭 시계열의 예측에 도움이 되는지 탐색하는 포트폴리오 프로젝트.

## 방법
주간 상대지수의 계절성·52주 차분·시차 상관을 비교한다. H4는 필라테스 상품에 헬스 관심도를 추가한 효과, H5는 상품의 과거 클릭과 관심도 추가 모델의 예측 오차를 비교한다. 지속성·계절 단순 예측 및 Ridge를 동일 평가 표본으로 비교하며, 확장 학습 창에서 시점별 재학습한다. 클릭은 구매나 매출이 아니며 상관은 인과를 의미하지 않는다.

## 실행
Python 3.11 이상에서 `python -m pip install -r requirements.txt`로 설치한다.
허용된 로컬 데이터만 `data/processed/activity_trends.csv`, `data/processed/shopping_trends.csv`에 배치한다.
`python analyze.py`와 `python forecast_h4_h5.py`를 실행한다. `collect.py`는 외부 API 요청과 이용량을 발생시키므로 해당 서비스의 이용 자격·약관을 확인한 뒤 실행한다.
인증값은 `.env.example`을 참고해 로컬 `.env`에 설정한다.

## 공개 범위
실제 CSV·예측값·보고서 PDF·원본 대시보드는 공개되지 않는다. `docs/index.html`은 데이터가 없는 프로젝트 소개 페이지이다. 자세한 기준은 PUBLICATION_POLICY.md에 있다.

## Pages 배포 상태
공개 저장소: https://github.com/108chang/hobby-fashion-trends
예정 사이트: https://108chang.github.io/hobby-fashion-trends/ (현재 404, 배포 미완료)

GitHub에 코드·설정·소개 페이지를 게시했다. Pages는 GitHub Actions 배포로 설정했으며 `.github/workflows/static.yml`은 `docs` 폴더만 배포한다.
저장소 Actions 정책은 허용 상태지만 활성화 요청에 `Unable to enable Actions for this repository.` 오류가 발생한다. 이는 코드 빌드 오류 이전의 실행 차단으로, GitHub 측 제한 사유 확인이 필요하다. 로그인하지 않은 외부 조회에서도 저장소가 404로 나타나 공개 접근은 아직 검증되지 않았다.
GitHub App 설치 0개인 연결 문제와 Actions 실행 제한은 구분해서 확인해야 한다.
