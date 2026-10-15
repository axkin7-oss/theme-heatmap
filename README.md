# 나의 테마 히트맵

직접 만든 테마별로 종목을 묶어, 1일·3일·1주·2주·3주 누적 등락률을 타일 크기와 색으로 보여주는 정적 웹앱.

- `app.html`: 앱 본문 (Claude 아티팩트로 게시하는 원본)
- `index.html`: 호스팅용 완성 문서 (`app.html`을 감싼 것. app.html 수정 후 다시 생성)
- `scripts/update_prices.py`: 코스피·코스닥 전 종목 + S&P 500 + `config/extra_tickers.txt` 종목의 최근 30거래일 종가를 Yahoo Finance(yfinance)에서 받아 `data/prices.json` 생성. API 키 불필요.
- `.github/workflows/update-prices.yml`: 평일 16:40 KST(한국 마감 후), 06:30 KST(미국 마감 후) 자동 실행.

`data/prices.json`이 페이지 옆에 있으면 실제 시세, 없으면 데모용 가상 시세로 동작한다.
테마는 브라우저 localStorage에 저장된다 (백업·복원 탭으로 옮길 수 있음).

## 지표
- 누적 등락률: 마지막 종가 / n거래일 전 종가 − 1 (1주=5, 2주=10, 3주=15거래일)
- 꾸준 상승: 기간 ≥3일, 상승, 상승일 비율 ≥ 60%, 로그가격 직선 적합도 R² ≥ 0.75
- 박스 크기(시가총액 미사용): 상승 종목은 0.4 + 2.6·z (z = 누적 등락률 / (2.5%·√n), 최대 4), 보합·하락 종목은 0.15~0.4로 작게
