# BTC Trading Analyzer

Python으로 BTC 시장을 분석하고, 비용·리스크를 포함한 백테스트와 전략 안정성 검증 및 모의거래를 실행하는 Streamlit 대시보드입니다. **V1에는 실제 주문 API가 없습니다.** 상승 우위 점수와 설정 품질은 규칙 기반 평가이며 성공 확률 또는 확정적 가격 예측이 아닙니다.

## 인터넷에서 이용하기

공개 배포 진입점은 **`web_app.py`**입니다. [무료 Streamlit 배포 안내](docs/deployment.md)에 따라 한 번 배포하면 휴대폰과 PC 브라우저에서 같은 웹 주소로 접속할 수 있습니다. 이용자에게 Python 설치는 필요하지 않습니다.

공개 웹의 기본값은 **Binance · BTC/USDT · Live · 1h**입니다. USDT 원본 시세로 지표·가격 영역·백테스트를 계산합니다. 상단에는 현재가와 24시간 변동을 표시하며, 신호 분석은 확정된 봉만 사용합니다. 방문자마다 모의거래·신호 기록·설정·백테스트를 별도의 임시 저장 공간에 보관합니다. 이 버전은 로그인 계정이 없어 기기 간 개인 기록 동기화를 제공하지 않습니다. 새로고침·접속 종료·배포 재시작 후 기록이 사라질 수 있으니 CSV/JSON으로 내려받으세요. 공개 거래소 가격 캐시만 공유하며 기존 로컬 DB는 공개하지 않습니다.

무료 서버의 계산량을 고려해 공개 모드는 Live 3,000개 평가 봉, Demo 1,200개 봉, 안정성 검증 1,200개 평가 봉, Monte Carlo 5,000회로 제한합니다. 동시에 한 개의 연구 작업을 실행하며 전체 27개 파라미터 검증도 선택할 수 있습니다. 아래 로컬 실행은 기존 한도를 사용합니다.

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

`.venv`는 프로젝트 전용 라이브러리 공간입니다. `requirements.lock`은 전체 의존성의 정확한 버전을 고정하며, 설치 시 TLS 인증을 끄지 않습니다. SQLite는 Python 표준 라이브러리를 사용합니다. `.env`에는 DB 경로와 로그 수준만 설정하면 됩니다.

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

기본값은 **Demo · 합성 데이터**입니다. 날짜가 고정된 하나의 재현 가능한 가격 경로를 여러 타임프레임으로 리샘플링합니다. 화면에 합성 데이터임을 표시하며 Live 실패를 Demo 가격으로 몰래 대체하지 않습니다.

1. 사이드바에서 Exchange, Symbol, Timeframe, 계좌 규모, 리스크 비율, 비용을 선택합니다.
2. 실제 가격은 `Live · 공개 거래소 데이터`로 전환합니다. `Date Range · Live`에서 평가 기간을 지정합니다. 지표 계산을 위해 각 타임프레임별 워밍업 데이터를 추가로 수집합니다.
3. 시장 개요에서 상승 우위·진입 품질·시장 흐름·현재 판단을 먼저 확인합니다. 세부 점수와 전체 설명은 접힌 패널에 있습니다.
4. 기술 지표에서 EMA/SMA, RSI, MACD, ATR, Bollinger, 거래량과 데이터 품질을 확인합니다.
5. 다중 시간대에서 하위·현재·상위·일봉을 비교합니다. 상위 봉은 닫힌 시각부터만 사용합니다.

### Binance

Exchange에서 Binance, Symbol에서 `BTC/USDT`를 사용합니다. 공개 Spot OHLCV는 키 없이 CCXT로 조회하며, 1회 최대 1,000개 봉을 앞 방향으로 페이지네이션합니다. Binance가 공식 제공하는 [시장 데이터 전용 API](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)의 `data-api.binance.vision`을 사용합니다. 개인/주문 API 주소는 변경하지 않습니다. 분석 금액은 USDT이며 원화 환산은 수행하지 않습니다. 이 버전은 Binance Futures나 주문 기능을 제공하지 않습니다.

현재가 카드는 최대 30초 캐시를 사용하며 최근 조회 시각과 24시간 변동을 표시합니다. 별도 현재가 조회가 지연되면 확정 봉 종가로 표시를 바꾸고 안내합니다. 신호와 체결 엔진은 이 현재가를 입력으로 사용하지 않습니다. 관망 중의 목표선은 관찰용 가격 영역이며 거래 진입 신호를 뜻하지 않습니다.

### Upbit

Exchange에서 Upbit, Symbol에서 `KRW-BTC`를 사용합니다. 5분·15분·60분·240분 및 일봉의 공개 REST API를 이용하고, 1회 최대 200개 봉을 뒤 방향으로 수집합니다. UTC 필드를 사용하므로 KST를 UTC로 잘못 해석하지 않습니다. 분석 금액은 KRW입니다. Binance와 Upbit 자본의 숫자를 직접 비교하지 마세요.

## 백테스트

Backtest 탭에서 **백테스트 실행**을 누릅니다. 순자산, 비용을 반영한 Buy & Hold, 낙폭, 진입·청산 마커, 거래 목록, 월별 수익률(충분한 기간일 때), Regime별 집단 성과를 표시합니다. 모든 실행의 설정·성과·순자산·체결 내역이 SQLite에 저장됩니다.

- 닫힌 N봉의 신호는 N+1봉 시가에서만 진입을 평가합니다.
- 다음 시가가 진입 Zone 밖이면 주문 후보는 만료됩니다. OHLC로 지나간 지정가 체결을 가정하지 않습니다.
- 수수료 0.1%, 불리한 슬리피지 0.05%가 기본입니다. 사이드바에서 바꿀 수 있습니다.
- 진입 시 비용을 포함한 평균 목표 RR을 재검사합니다. 세 목표는 각각 원래 수량의 1/3을 청산합니다.
- 손절과 목표가 같은 봉에서 동시에 닿으면 남은 수량은 손절 우선입니다. 손절을 넘어선 시가 갭은 더 불리한 시가로 체결합니다.
- 마지막 평가 봉에서 남은 포지션을 비용 포함 강제 청산합니다.
- 포지션은 한 번에 하나, 레버리지는 1x입니다. Short 옵션은 대칭 계산을 위한 가상 연구 기능입니다.
- 봉이 누락되면 지표 워밍업을 다시 시작합니다. 기존 포지션은 다음 가용 시가로 청산하고 결과에 경고를 남깁니다. 누락 구간에서 손절 체결을 보장하지 않습니다.
- 높은 수익률만으로 전략을 우수하다고 평가하지 않습니다. 거래가 0회인 결과도 그대로 보이며 30회 미만은 표본 부족입니다.

## 안정성 검증

Robustness 탭에서 **전략 안정성 검증 실행**을 누릅니다. 계산량이 큰 경우 빠른 검증은 ATR 3개 조합만 평가하며, 기본 전체 검증은 RSI 12/14/16 × EMA 18/20/22 × ATR buffer 0.3/0.5/0.7의 27개 조합입니다.

- IS 60% / Validation 20% / OOS 20%를 시간 순서로 나눕니다. 각 구간은 새 자본으로 시작하고 평가 시점 전의 지표 워밍업만 사용할 수 있습니다.
- 파라미터 민감도는 **IS에서만** 계산하며 최종 OOS로 최적화하지 않습니다.
- Walk Forward는 Train에서 후보를 선택하고 Validation으로 거래 허용 여부를 검토합니다. Test는 선택에 사용하지 않습니다. 승인되지 않은 fold도 숨기지 않습니다.
- 비용 1x / 1.5x / 2x에서 신호·수량·체결을 다시 실행합니다.
- Monte Carlo는 최소 1,000회, seed 지정 가능, 순수익 R을 복원 추출합니다. 예상/최악/95% 낙폭, 연속 손실, 자산 범위와 심각한 낙폭 확률을 제공합니다.
- OOS 거래 30회, 주변 파라미터 표본, 비용 스트레스, 관측된 Regime 수, Walk Forward 표본이 부족하면 Production Candidate로 승격하지 않습니다.

기본 Demo에서 거래가 없을 수 있습니다. 이는 체결 또는 RR 필터를 만족하지 못한 결과이며, Monte Carlo에 가짜 거래를 넣거나 유리한 결과를 만들기 위해 필터를 우회하지 않습니다. 체결 엔진은 독립적인 수치 시나리오 테스트에서 실제 거래를 실행해 검증합니다.

## 모의거래와 신호 기록

Paper Trading 탭에서 **모의거래 활성화**를 누릅니다. 처음에는 가장 최근 확정 봉을 기준으로 후보를 만들고, 과거 가상 수익을 만들어 넣지 않습니다. 다음 업데이트부터 새로 닫힌 봉을 순서대로 처리합니다.

- **데이터 새로고침** 또는 **Live 자동 업데이트 · 60초**로 진행합니다.
- 시장·타임프레임·설정·Demo/Live별로 별도 계정을 사용합니다. Demo와 실제 데이터를 섞지 않습니다.
- 상태·손실 연속 횟수·진입 대기·부분 청산·쿨다운을 SQLite에 저장하며 재시작 후에도 유지합니다.
- **신규 모의거래 중지**는 신규 진입과 대기 후보만 중지합니다. 이미 열린 포지션의 보호 청산은 데이터 업데이트가 있는 동안 계속 평가합니다.
- 일 손실 3%, 주 손실 6%, 최대 낙폭 15%, 4연속 손실 위험 절반, 6연속 손실 신규 진입 중지가 기본입니다.
- 낙폭/연속 손실 보호는 명시적으로 리셋하기 전까지 유지합니다. **리스크 보호 명시적 리셋**은 현재 자산 기준으로 보호 상태를 재설정하며 거래 내역이나 실제 손익을 지우지 않습니다.
- Signal History에서 분석 스냅샷과 후보 이력을 확인하고 CSV로 받습니다. 동일 봉·시장·설정의 기록은 중복 저장하지 않습니다.

**모의거래는 데이터를 읽는 프로세스가 살아 있는 동안만 업데이트됩니다.** 브라우저를 닫거나 프로세스를 종료하면 체결 검사가 멈춥니다. 별도 스케줄러는 V1에 포함하지 않으며, 연속 모의 폴링은 다음 CLI를 이용할 수 있습니다.

```bash
.venv/bin/python -m btc_analyzer.cli --source live --exchange Upbit --timeframe 1h --paper-watch --interval 60
```

폴링은 공개 데이터와 가상 주문만 사용합니다. Ctrl+C로 종료하면 상태는 유지됩니다. 다시 시작하면 누락된 확정 봉을 순서대로 처리하며 실제 거래소와 연결된 보호 주문은 없습니다.

## 설정과 명령행

Settings 탭에서 현재 설정 JSON을 다운로드하거나 SQLite에 저장합니다. 업로드한 JSON은 검증 후 `imported` 설정으로 저장하며 사이드바 값을 자동 변경하지 않습니다. CLI에서는 내려받은 JSON을 직접 로드할 수 있습니다.

```bash
.venv/bin/python -m btc_analyzer.cli --source demo --bars 800 --paper-tick
.venv/bin/python -m btc_analyzer.cli --source demo --bars 800 --robustness --compact
.venv/bin/python -m btc_analyzer.cli --source live --exchange Upbit --timeframe 1h --start 2025-01-01 --end 2025-03-01 --config strategy.json
```

결과는 `data/reports/run-*-summary.json`, 순자산/체결/민감도/비용/Walk Forward CSV로 저장됩니다. 기본 DB는 `data/analyzer.sqlite3`이며 `.env`의 `BTC_DB_PATH`로 변경할 수 있습니다.

## 테스트

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke.py
.venv/bin/ruff check src tests app.py web_app.py scripts
.venv/bin/python scripts/check_live.py --exchange both
```

Windows는 `.venv/bin/python`을 `.\.venv\Scripts\python`으로 바꿉니다. 전체 pytest는 외부 인터넷 없이 실행하며, 알려진 RSI 값, 독립 EMA/ATR/Bollinger 계산, 비용·슬리피지 현금흐름, 피벗 확인 지연, 미래 값 변경 불변성, 상위 봉 종료 시각, 데이터 갭, 모의거래 멱등성·DB 롤백, 실제 Streamlit 상호작용을 검사합니다. `check_live.py`만 실제 공개 거래소를 조회하고 실패 시 종료 코드 1을 반환합니다.

## 자주 발생하는 오류

- `ModuleNotFoundError`: 가상환경 Python으로 설치·실행했는지 확인하세요. 저장소 루트에서 `pip install -r requirements.lock`을 다시 실행하세요.
- Streamlit Cloud의 `ModuleNotFoundError`: `main` / `web_app.py`로 배포했는지 확인하고 Manage app의 로그에서 빠진 모듈 이름을 확인합니다. 최신 버전은 `requirements.txt`에 런타임 라이브러리를 직접 고정하며 앱이 `src/`를 직접 읽으므로 로컬 프로젝트의 별도 설치가 필요하지 않습니다. 업데이트가 반영되지 않으면 Reboot app을 사용하세요.
- `streamlit` 명령이 없음: `.venv/bin/python -m streamlit run app.py`를 사용하세요.
- `403 / ProxyError`: 클라우드 네트워크 설정에서 `data-api.binance.vision`, `api.upbit.com` 접근을 허용해야 합니다. 초안 저장은 실행 중 네트워크 정책을 즉시 바꾸지 않습니다. Binance가 HTTP 451을 반환하면 해당 서버의 서비스 지역에서 실데이터를 제공할 수 없습니다.
- `429 / timeout`: 제공자가 제한·네트워크 오류를 지수 지연으로 최대 4회 재시도합니다. 짧은 기간으로 확인하고, 자동 폴링 간격을 늘리세요.
- 데이터 부족 / No Trade: EMA200 워밍업, 상위 봉 이력, 최근 데이터 갭, RR·변동성 필터를 확인하세요. 차트에 표시된 후보가 반드시 거래로 이어지지는 않습니다.
- 설정 JSON 오류: 최상위 및 `indicators`, `strategy`, `risk`는 JSON 객체여야 합니다. 알 수 없는 섹션이나 잘못된 값은 오류로 표시합니다.
- DB 파일 손상: 파일을 자동 삭제하지 않고 안내 후 중지합니다. 기존 파일을 보존해 백업에서 복구하거나 `BTC_DB_PATH`에 별도 새 DB 경로를 지정하세요.
- SQLite 쓰기 오류: `data/`에 쓰기 권한이 있는지 확인하고 `BTC_DB_PATH`를 쓰기 가능한 경로로 지정하세요. DB 복사 전 앱을 종료해 WAL을 정상 반영하세요.
- 너무 큰 연환산 수치: CAGR은 30일 이상에서만 표시하지만 짧은 관측 기간의 연환산은 여전히 불안정합니다. 일별 Sharpe·Sortino에는 최소 2개 일 수익률이 필요합니다.

## 보안과 한계

`.env`, 데이터베이스, 로그와 생성 보고서는 Git에서 제외합니다. `.env.example`에 실제 키를 넣지 마세요. V1은 비밀키를 필요로 하지 않으며 주문·송금 API를 구현하지 않습니다. 미래 Private API는 별도의 인터페이스/검토 단계에서 추가해야 합니다.

OHLCV만으로 봉 내부 경로·호가창·거래량별 체결·실제 시장 충격을 재구성할 수 없습니다. 데이터 누락/거래소 이력 범위/현물 단일 BTC 선택에 따른 표본 편향은 남습니다. Regime 표는 거래 진입 시점 기준 집단이며 완전한 시장별 별도 포트폴리오가 아닙니다. Monte Carlo는 경험적 거래 결과에 조건부인 근사 모델입니다. 구현 검증과 전략 수익성 입증은 구분합니다.

클라우드 검증에서는 Upbit의 5m/15m/1h/4h/1d 실제 닫힌 봉 수집에 성공했습니다. 기존 Binance 일반 API는 HTTP 451을 반환했습니다. 현재 선택한 공식 시장 데이터 전용 호스트는 이 작업 환경의 프록시가 HTTP 403으로 차단해 실데이터 검증을 아직 완료하지 못했습니다. 관련 도메인 허용 초안을 저장했으며 배포 서버의 실제 접근 가능 여부는 별도 확인이 필요합니다. Binance 실패를 합성 결과로 대체해 성공이라고 표시하지 않습니다.

## 구조와 다음 개선

`src/btc_analyzer/` 아래에 `data`, `indicators`, `analysis`, `strategy`, `risk`, `backtest`, `storage`, `paper`, `ui`를 분리했습니다. `config.py`는 전체 설정, `cli.py`는 화면 없는 연구 실행, `app.py`는 로컬 대시보드, `web_app.py`는 공개 웹 진입점입니다. 설계 원칙과 요구사항 대응은 [docs/design.md](docs/design.md)를 참고하세요.

다음 우선순위는 실데이터 연결 후 장기 OOS 검증, 누락·호가·체결 모델 고도화, 장기 모의거래 스케줄러입니다. Funding/OI/청산 데이터, 알림, Futures와 Private 주문은 별도 후속 Phase로 남겨두었습니다.
