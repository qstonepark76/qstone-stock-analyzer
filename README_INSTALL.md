# Q Stone Park Stock Analyzer v3.1 Beta

## 목적
기존 v2.1 운영본과 v3.0 베타를 보존하고, `v3-1-beta` 별도 브랜치에서 점수·데이터 커버리지 오류를 수정 검증합니다.

## v3.1 변경점
1. **공식 점수와 잠정 점수 분리**: 7개 평가영역의 유효 커버리지 100%일 때만 `score`와 `grade`를 부여합니다. 부분 데이터 종목은 `provisional_score`, `provisional_grade`로만 표시합니다.
2. **모멘텀 점수 게이트**: 20거래일 종가 이력이 없으면 모멘텀 점수를 산출하지 않습니다. 거래대금 순위만으로 모멘텀 점수가 높게 나오는 오류를 방지합니다.
3. **재무 수집 순환 배치**: 매번 거래대금 상위 120개만 반복 조회하던 방식 대신 전체 KRX 종목을 순환하며 120개씩 조회합니다. 캐시가 유효하면 API 재호출을 줄입니다.
4. **전략별 커버리지 표시**: 재무·성장·모멘텀 리스트의 점수와 해당 영역 커버리지를 별도로 전달합니다.
5. 기존 100점 배점은 그대로 유지합니다.

## 적용 순서 (운영 main은 건드리지 않음)
1. GitHub 저장소에서 기존 `v3-beta`를 기준으로 새 브랜치 `v3-1-beta`를 만듭니다. 그래야 기존 `data/history`와 `financial_cache.json`을 이어받습니다.
2. `v3-1-beta` 브랜치에 아래 코드 파일만 같은 경로로 추가/교체합니다. 기존 `data/` 폴더는 삭제하거나 교체하지 말고 그대로 보존합니다.
   - `index.html`
   - `scripts/collect.py`
   - `requirements.txt`
   - `.github/workflows/v3-1-beta.yml`
   - `README_INSTALL.md`
3. Actions의 수동 실행 인식을 위해 `.github/workflows/v3-1-beta.yml` 파일만 `main`에도 동일하게 추가합니다. 기존 `daily.yml`은 수정하지 않습니다.
4. Actions에서 `Q Stone Park v3.1 Beta Validation`을 선택하고 Branch를 `v3-1-beta`로 지정해 실행합니다.
5. `qstone-v3-1-beta-data` Artifact를 다운로드해 검증합니다.

## 필요한 GitHub Secrets
기존 저장소의 다음 Secrets를 그대로 사용합니다.
- `KRX_AUTH_KEY`
- `DART_AUTH_KEY`

## 유의사항
- 워크플로는 GitHub Pages 배포를 하지 않습니다.
- 외국인·기관 수급, PER/PBR, 증권사 전망 API는 아직 연결되지 않았습니다. 해당 항목을 추정하거나 임의 점수화하지 않습니다.
- 공식 종합 TOP 10은 모든 7개 영역이 확보되기 전까지 비어 있을 수 있습니다. 이는 오류가 아니라 의도된 안전장치입니다.
- 연간 재무자료는 우선 순환 수집합니다. 5개년 연간 및 3개년 분기 재무자료는 후속 단계에서 확장해야 합니다.
- 가격 이력이 21개 거래일 이상 쌓이기 전까지 모멘텀 TOP 10은 비어 있거나 일부 종목만 표시될 수 있습니다.
