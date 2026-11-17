# Q Stone Park Stock Analyzer — 자동 업데이트 배포 패키지

## 무엇이 들어 있나요?
- `index.html`: 모바일 대응 주식 분석 대시보드
- `scripts/collect.py`: KRX 유가증권 일별매매정보 수집 및 기술지표 기반 TOP 10 산출
- `.github/workflows/daily.yml`: 평일 19:00(KST) 자동 수집 및 GitHub Pages 배포
- `data/latest.json`: 웹 화면이 읽는 최신 데이터
- `data/history/`: 매일 수집한 원본 종목 스냅샷(실행 후 생성)

## 중요 — 자동 업데이트를 켜기 위한 준비
이 ZIP은 실행 가능한 배포 뼈대이며, 사용자 GitHub 계정과 KRX 인증키에 접근할 수 없으므로 공개 웹사이트에 직접 배포되지는 않았습니다. 아래 설정을 한 번 해야 자동화가 작동합니다.

### 1. KRX 인증키 발급
1. KRX Data Marketplace OPEN API에 회원가입/로그인합니다.
2. API 인증키를 신청합니다.
3. 서비스 목록에서 **유가증권 일별매매정보**를 찾아 이용 신청합니다.
4. 승인 후 인증키와 API 서비스 사용 권한을 확인합니다.
공식 안내: https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp

KRX 서비스 설명/최신 수정일: https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=JvJFzlAENzZlPBDNGAWC

> KRX 문서상 인증키는 요청 헤더 `AUTH_KEY`에 전달합니다. API 서비스 승인 전에는 호출이 실패할 수 있습니다. API ID 및 응답 스키마가 계정의 승인 서비스 명세와 다르면 `KRX_API_BASE` 또는 `normalize()`의 필드명을 해당 명세에 맞춰 조정해야 합니다.

### 2. GitHub 저장소 만들기
1. GitHub에서 새 **Public repository**를 만듭니다. 예: `qstone-stock-analyzer`
2. ZIP 압축을 풀고 모든 파일을 저장소의 루트에 업로드합니다.
3. `Settings → Secrets and variables → Actions → New repository secret`에서:
   - Name: `KRX_AUTH_KEY`
   - Secret: 발급받은 KRX 인증키
4. `Settings → Pages → Build and deployment → Source`를 **GitHub Actions**로 선택합니다.
5. `Actions` 탭에서 `Update KOSPI data and deploy site`를 수동 실행합니다.

공식 GitHub Pages 배포 안내: https://docs.github.com/en/get-started/start-your-journey/deploying-your-website-automatically

### 3. 접속 주소
배포 성공 후:
`https://YOUR-GITHUB-USERNAME.github.io/qstone-stock-analyzer/`

## 현재 산출 로직과 제한
현재 1차 자동화 점수는 KRX 일별 시세에서 계산할 수 있는 기술·거래 지표만 사용합니다.
- 20일 가격 모멘텀: 30점
- 5일 가격 모멘텀: 20점
- 거래대금 백분위: 20점
- 20일 변동성 역순위: 15점
- 당일 등락률 백분위: 15점

사용 가능한 지표만 가중치를 재정규화하며, 실제 데이터가 없는 값은 만들지 않습니다.
**실적 성장성, PER/PBR/ROE, 외국인·기관 순매수, 증권사 목표주가, KOSPI 지수 레벨은 아직 연결하지 않았습니다.** 해당 데이터는 별도 승인된 API/공식 소스와 스키마 검증을 거쳐야 하므로 현재 점수에 가짜로 반영하지 않습니다.

## 자동 수집 시간
GitHub Actions 예약은 월~금 10:00 UTC(한국시간 19:00)입니다. 공휴일에는 데이터가 없어 최근 7일을 역순 조회하도록 되어 있습니다. GitHub Actions 예약 실행은 시스템 부하에 따라 지연될 수 있습니다.

## 보안
- 인증키는 GitHub Secrets에만 저장합니다.
- 인증키를 `index.html`, JSON 파일, 공개 저장소 코드에 직접 넣지 마세요.
- KRX 시세정보를 공개 웹사이트에서 재배포·상업적으로 이용하려는 경우 별도 이용계약/승인이 필요할 수 있습니다. KRX의 데이터 수신방법 안내를 확인하세요: https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA003.jsp

## 주의
이 도구는 종목 스크리닝 및 리서치 보조용입니다. 자동 점수는 매수 추천이나 수익 보장을 의미하지 않습니다.
