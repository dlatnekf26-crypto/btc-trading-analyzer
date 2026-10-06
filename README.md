# BTC Trading Analyzer

BTC 현재가, 확정 봉 차트, 다섯 시간대의 중장기 신호와 과거 유사 사례 기반 예측을 보는 가벼운 Streamlit 대시보드입니다. 실제 주문 기능은 없습니다.

## 인터넷에서 이용하기

공개 배포 진입점은 **`web_app.py`**입니다. [Streamlit 배포 안내](docs/deployment.md)에 따라 배포하면 휴대폰과 PC에서 같은 주소로 접속할 수 있습니다. 이용자의 Python 설치나 거래소 API 키는 필요하지 않습니다.

로컬과 공개 웹 모두 **Binance · BTC/USDT · Live · 일봉 차트**로 고정합니다. 상단에서 BTC·ETH·원/달러 환율·김치프리미엄·나스닥100 선물(NQ)·미국 10년물 금리를 봅니다. 거래소와 Demo 모드 선택을 제거했으며 분석에는 Binance 원래 USDT 가격을 사용합니다.

화면은 **시장 개요 / 기술 지표 / 다중 시간대 / 미래 예측** 네 탭입니다. 백테스트·전략 검증·몬테카를로·모의거래·신호 기록·설정 탭과 계좌/전략 설정, 일목 읽는 법 카드, 관찰용 가격 영역과 목표·손절선 표시를 제거했습니다. 앱은 별도 연구 전략이나 모의계좌·신호 기록 DB를 실행하지 않습니다. 기존 로컬 DB 파일은 보존합니다.

**기술 지표**는 추세·RSI·MACD·평균 변동 폭·거래량·일목의 현재 상태를 한국어 카드로 보여줍니다. 시간대를 고르고 RSI/추세 탄력/변동 폭/밴드 폭/거래량을 하나씩 크게 확인하세요. 그래프의 기준선·단위와 손가락/마우스 툴팁으로 값을 읽으며, 다른 이동평균 등의 현재값은 접힌 한국어 표에서 봅니다. 지표 조작은 부분 갱신으로 처리하고 이미 계산한 확정 봉을 재사용합니다.

## 처음 실행하기

Python 3.11 이상을 설치합니다. 개발·검증 환경은 Python 3.12입니다. 터미널에서 프로젝트 폴더로 이동하세요.

### Windows PowerShell

```powershell
cd btc-trading-analyzer
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
Copy-Item .env.example .env
.\.venv\Scripts\python -m streamlit run app.py
```

Python 3.12 대신 3.11을 설치했다면 첫 명령을 `py -3.11 -m venv .venv`로 바꿉니다. 가상환경을 활성화하지 않고도 위 명령으로 실행할 수 있습니다. 설치 오류가 있으면 64비트 Python을 사용하세요.

### macOS / Linux

```bash
cd btc-trading-analyzer
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
.venv/bin/python -m streamlit run app.py
```

`.venv`는 프로젝트 전용 라이브러리 공간입니다. `requirements.lock`은 전체 의존성의 정확한 버전을 고정하며, 설치 시 TLS 인증을 끄지 않습니다. SQLite는 Python 표준 라이브러리를 사용합니다. `.env`에서 선택적으로 공개 캐시 위치 `BTC_WEB_DATA_DIR`와 로그 수준을 설정합니다. `BTC_DB_PATH`는 기존 CLI용입니다.

`uv`를 이미 사용한다면 다음 명령으로 동일하게 설치합니다.

```bash
uv pip sync requirements.lock --python .venv/bin/python
```

패키지 사양은 `pyproject.toml`에서 변경하고, 의존성을 의도적으로 갱신할 때만 다음을 실행합니다.

```bash
uv pip compile requirements-dev.in -o requirements.lock --python .venv/bin/python --python-version 3.11 --universal --no-emit-index-url
uv pip compile pyproject.toml -o requirements.txt --python .venv/bin/python --python-version 3.11 --universal --no-emit-index-url
```

## 대시보드 사용

1. 분석 시장은 Binance BTC/USDT Live입니다. 필요할 때 상단의 데이터 새로고침을 사용합니다. 예전 `BTC_DEFAULT_SOURCE`·`BTC_DEFAULT_EXCHANGE` 환경변수로 Demo나 Upbit 선택을 복구하지 않습니다.
2. 상단은 **BTC·ETH·원/달러 환율·BTC 김치프리미엄·NQ 선물·미국 10년물 금리** 여섯 카드입니다. Binance BTC/ETH는 최근 1시간 그래프와 24시간 변화율, 환율·김프는 자료의 시각과 상태를 표시합니다. Yahoo `KRW=X` 시장 환율·`NQ=F` 선물·`^TNX` 수익률 지표(%)는 공개 스트림을 우선하고 10초 공유 조회를 대체로 사용합니다. NQ/금리는 작은 그래프와 원자료 시각·제공 지연을 표시합니다. 공개 스트림 수신이 무지연 거래소 시세 이용 권한을 뜻하지는 않습니다. 아래 **코인에 영향을 주는 주요 뉴스**에서 코인 수급·규제와 코인에 연결된 유가·전쟁·금리·물가·경제지표 소식의 출처와 영향을 봅니다.
3. **시장 개요**에서 중장기 매수·매도·관망 판단을 봅니다. 차트 시간대는 1시간·4시간·일봉·주봉·월봉이며 간편/상세 보기와 일목균형표·이동평균선·볼린저밴드를 선택합니다. 손가락을 대거나 마우스를 올리면 날짜·가격을 읽고, 손가락을 가로로 움직이면 표시가 따라옵니다. 차트 확대는 끄고 세로 스와이프는 페이지 스크롤로 사용합니다. 확정 봉 차트와 실시간 현재가는 구분합니다.
4. **기술 지표**는 시간대별 RSI·MACD·변동성, **다중 시간대**는 방향·비중·자료 충족 상태를 보여줍니다. 일목은 기본 9/26/52/26봉으로 계산하며 차트와 종합 판단에 계속 반영합니다.
5. **미래 예측**에서 1주·1개월·3개월·6개월 후의 예상 경로와 범위를 봅니다. 파란 점선은 기본 기술 모델, 주황색은 가장 닮은 과거 사례를 현재 기준 종가에 맞춘 재현, 보라색은 최근 뉴스의 조건부 가격 시나리오입니다. 뉴스 반영을 끄거나 근거를 펼쳐 기본 전망과 비교합니다. 뉴스 조정의 정확도는 아직 검증되지 않았으며 과거 검증 성적은 기술 모델만 평가한 결과입니다. 별도 과거 비교·직접 설정·전체 사례 겹치기도 지원합니다. [예측과 과거 유사성 설명](docs/historical-similarity.md)을 참고하세요.

종합 신호는 일봉·주봉·월봉 85%, 단기 봉 15%를 반영합니다. 가격 매력과 하락 진정을 별도로 평가해 단기 상승 전의 눌림목도 검토합니다. 데이터 부족·급락·지지 이탈은 매수를 보류합니다. 점수는 성공 확률이 아니며 예측은 미래 가격을 보장하지 않습니다. [종합 신호 설명](docs/composite-signals.md)에 계산 조건이 있습니다.

가벼운 모바일 화면을 위해 하단 과거 예측 성적·세부 유사도·모든 다운로드를 제거했습니다. 기본 예측과 과거 사례, 검증 부족/가격 유지 가정 대비 열세 안내는 유지합니다. RSI·ADX·CMF 연구 후보는 실제 자료 검증에서 일관된 개선이 없어 기본 예상 가격에 반영하지 않습니다.

## 실시간 연결과 갱신

- 브라우저는 Binance 연결 하나로 BTC/ETH `aggTrade`(100ms 주기)와 `ticker`를 함께 구독합니다. 가격은 빠른 체결 메시지에서, 24시간 변화율은 ticker에서 받습니다. 김프용 Upbit BTC는 별도 연결 하나입니다. 숫자와 Canvas 갱신을 최대 50ms씩 합치며 상한은 20회/초입니다. 틱으로 Python 분석을 다시 실행하지 않습니다.
- 시작할 때 Binance BTC/ETH의 최근 60개 분봉을 공개 REST로 받습니다. 이후 현재 틱을 마지막 분의 점에 반영하며 최대 61개 점을 유지합니다. 최근 이력 조회가 실패해도 수신한 가격부터 선을 그립니다.
- BTC/ETH 분봉 요청이 실패하거나 제한되면 자동 재시도합니다. 최근 이력은 같은 브라우저 탭에 잠시 저장해 새로고침에서도 복원합니다. 캐시와 분봉 가격을 실시간 수신으로 표시하지 않습니다.
- WebSocket이 연결되지 않으면 Binance 두 심볼을 한 REST 요청으로 5초마다 조회하고 Upbit는 11초 간격을 유지합니다. 429/418·Retry-After는 대기 시간을 늘립니다. 정상 WS 값은 늦은 REST가 덮어쓰지 않습니다. 15초 이상 갱신되지 않은 값은 **수신 지연 · 마지막 가격**으로 표시합니다. 잘못된 가격·다른 시장·이전 시각 메시지는 반영하지 않습니다.
- 재연결 간격은 1초부터 최대 30초까지 늘어납니다. 숨긴 페이지는 연결을 해제하고 돌아오면 다시 구독합니다. 화면의 분석 탭 전환은 가격 연결을 유지합니다.
- 분석용 확정 봉은 60초마다 확인하며 이미 받은 봉과 계산을 재사용합니다. 수동 새로고침은 해당 시장 자료를 갱신합니다. 현재가 연결과 봉 수집이 독립적이므로 봉 API 오류가 현재가 위젯을 멈추지 않습니다.

원/달러 환율은 Yahoo `KRW=X` 시장 시세를 우선합니다. 3분 넘게 오래된 시장 값은 새 김프 계산에 쓰지 않습니다. 시장 자료를 못 받으면 두나무 은행 고시, Frankfurter ECB 일별 자료 순으로 대체하며 **시장/고시/일별** 출처·시각을 구분합니다. 은행/일별 조회는 60초 간격이고 최근 시장 스트림이 있으면 은행 요청을 미룹니다. 공개 시장 호가도 외환 실행 가격을 보장하지 않습니다. 김프는 `(Upbit BTC/KRW ÷ (Binance BTC/USDT × Coinbase USDT/USD × USD/KRW) − 1) × 100`입니다. USDT를 1달러로 고정하지 않으며 수수료는 제외합니다. 코인·환율·환산 자료가 없거나 지연되면 새 계산을 보류하고 마지막 값은 회색으로 구분합니다.

Yahoo 공개 WebSocket 하나에서 `NQ=F`·`^TNX`·`KRW=X`를 구독합니다. 메시지 크기·가격·종목·통화·시각·역순을 검사하고 기존 iframe에서 숫자/작은 그래프만 갱신합니다. 느린 서버 응답이 최신 스트림을 덮지 않으며 숨긴 페이지와 종료 시 연결·리스너를 해제합니다. source 지연/휴장 값은 실시간으로 표시하지 않습니다. NQ의 무지연 CME 시세에는 별도 권한이 필요하고 ^TNX는 국채 가격 자체가 아닌 수익률 지표입니다.

시세 REST 대체·뉴스는 서버 작업 최대 4개를 공유합니다. 자료원별 진행 중 요청은 하나이며 시세는 10초, 뉴스는 1분 캐시를 사용합니다. 시세 확인은 2초 fragment, 뉴스 목록/조건부 시나리오는 15초 fragment로 분리해 코인 연결이나 확정 봉 분석을 재실행하지 않습니다. 오류 시 대기·Retry-After와 마지막 값을 보존합니다. 뉴스 검색과 목록/전망 양쪽에서 **명시적인 코인 연결과 시장 이벤트**가 있는 제목만 선택하며 일반 유가·전쟁·주식 ETF 기사는 제외합니다. 최근 24시간의 한국어·영어 공개 RSS 제목 분류로, 실제 가격 영향이나 기사 원문 검증을 보장하지 않습니다.

Binance REST는 공식 시장 데이터 전용 `data-api.binance.vision`, Upbit REST는 `api.upbit.com`을 사용합니다. 네트워크·지역 제한이 있으면 해당 연결의 실제 오류/지연 상태를 표시합니다. Live 실패를 합성 데이터로 대체하지 않습니다. 서버의 분석 자료 연결과 방문자 브라우저의 현재가 연결은 각각 접근 가능해야 합니다.

## 테스트와 성능

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke.py
.venv/bin/ruff check src tests app.py web_app.py checkout_bootstrap.py scripts
.venv/bin/python scripts/check_deployment.py
.venv/bin/python scripts/benchmark_ui.py --repeats 9
```

pytest와 배포 검사는 외부 인터넷 없이 계산·캐시 무효화·UI와 공개 진입점을 확인합니다. `scripts/offline_ui_fixture.py`가 검사 프로세스의 공개 자료원 경계에서 응답을 주입하며 제품에 숨은 Demo 모드를 만들지 않습니다. Playwright/Chromium의 `check_live_widget.py`는 거래소 메시지를, `check_live_latency.py`는 수신→DOM 반영 지연·체결 파싱을, `check_macro_stream.py`는 실제 PricingData 형태의 세 자산 메시지·원자료 지연·대체/재연결을 확인합니다. `--app-url`은 실제 앱의 임베딩도 확인합니다. 응답 주입 검사가 외부 시세의 실제 수신 성공을 뜻하지 않습니다.

`scripts/check_touch_charts.py --app-url <검증 서버> --event-log <이번 실행 계측 로그>`는 390/820/1440px Chromium의 실제 터치 입력으로 가격 조회·가로 이동·세로 스크롤·확대 방지·버튼 터치와 상위 분석 추가 실행 여부를 확인합니다. 물리 기기나 모든 Safari 버전의 검증은 아닙니다. 반복 실행·초기 실행·차트 크기의 비교 조건과 결과는 [성능 기록](docs/performance.md)에 있습니다. 로컬 계산 시간이 실제 호스팅의 전체 접속 시간을 뜻하지는 않습니다.

## 기존 명령행 연구 도구

이전 연구·검증 모듈은 `btc_analyzer.cli`에 남아 있으며 웹 화면에서 호출하지 않습니다. CLI를 직접 실행한 경우에만 해당 연구 작업과 기록을 사용합니다. 기존 `data/` DB와 보고서는 삭제하지 않습니다.

## 문제 해결

- `ModuleNotFoundError` / `ImportError`: 공개 배포의 `main` / `web_app.py`와 설치 로그를 확인합니다. 새 체크아웃은 editable 설치 없이 실행되도록 검사합니다. 수정 반영 후에도 이전 오류가 남으면 Manage app → Reboot app을 사용하세요.
- `403 / 451 / ProxyError`: 해당 호스트의 네트워크·서비스 지역 제한을 확인합니다. 인증서 검증을 끄지 않습니다.
- 시세가 회색으로 표시됨: 마지막 수신 시각을 확인하세요. 연결이 회복되면 자동 갱신합니다. REST만 가능하면 Binance 5초 또는 Upbit 11초 조회로 표시됩니다.
- 데이터 부족: 월봉 EMA200 등 실제 이력이 없는 지표를 채워 넣지 않습니다. 부족한 자료 때문에 신호나 예측을 보류할 수 있습니다.
- SQLite 오류: 기존 파일을 삭제하지 말고 쓰기 권한과 캐시 경로를 확인합니다. 공개 가격 캐시에는 OHLCV만 저장합니다.

`.env`, 키, DB와 로그를 공개 저장소에 올리지 마세요. 이 앱은 공개 데이터만 사용합니다. 작업 단계와 다음 실행의 시작 지점은 [PROGRESS.md](PROGRESS.md)에 기록합니다.
