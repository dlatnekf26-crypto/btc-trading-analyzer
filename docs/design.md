# V1 설계와 검증 계약

## 시간과 데이터

OHLCV의 DatetimeIndex `timestamp`는 봉의 UTC **시작 시각**입니다. 종료/가용 시각은 timestamp + timeframe duration입니다. Provider는 현재 종료되지 않은 봉을 제거합니다. 모든 타임프레임은 거래소 네이티브 데이터입니다. 데모만 하나의 합성 경로에서 리샘플링합니다.

중복은 마지막 관측값을 유지하고 개수를 보고합니다. 비정상 가격·거래량·timestamp·시간 그리드를 검사합니다. 누락은 attrs에 기록하고 채우지 않습니다. 분석의 연속 봉 계산은 갭마다 초기화합니다. 상위 데이터는 가용 시각으로 backward as-of join을 하며 최대 1개 상위 기간까지의 오래된 값만 인정합니다.

EMA는 첫 관측값 시드의 재귀 EMA, RSI/ATR은 최초 SMA 시드의 Wilder 방법, Bollinger는 모집단 표준편차입니다. 각 방법은 주석과 독립 수치 테스트를 갖습니다. 미래 표본의 수정이 과거 feature/score/structure를 바꾸지 않는 테스트가 포함됩니다.

## 구조와 설명

확정 pivot은 양쪽 left/right 봉에서 엄격히 높거나 낮은 점입니다. 동률은 제외하고 N의 pivot을 N+right의 행에 기록합니다. 과거 행에 나중에 발견한 pivot을 덧씌우지 않습니다. 확인된 두 고점과 두 저점을 비교해 HH/HL/LH/LL을 판단합니다. 확인 상태에는 만료 기간을 두고 데이터 갭에서 리셋합니다.

지지·저항은 확인 pivot과 평균선의 ATR 크기 가격 클러스터입니다. 각 방향 최대 3개 영역만 표시합니다. Regime는 EMA 배열·기울기·EMA200 관계와 구조를 조합하고, 변동성 상태는 과거 ATR%/BB width 중간값 대비 비율로 결정합니다. 규칙 기반 상승 우위와 setup quality는 서로 다른 값입니다. 숫자는 확률이 아닙니다.

## 체결과 위험

가상 포지션은 고정 구조적 손절, 1/3씩 3개 목표, 1x 자본 상한, 비용 후 RR 검사, next-open-only 진입을 사용합니다. Entry Zone 밖으로 열린 다음 봉은 만료합니다. 따라서 pending limit order를 미래 저가/고가로 유리하게 체결하지 않습니다.

단일 OHLC 봉에서 손절과 TP가 모두 닿으면 손절이 우선합니다. 갭 손절은 더 불리한 시가, 익절은 목표 가격을 기준으로 하고 양쪽에 불리한 슬리피지를 적용합니다. 모든 fee는 실제 수량×실제 체결가격으로 기록합니다. 체결 시각을 정확히 알 수 없는 intrabar 청산은 그 봉의 종료 시각으로 저장합니다. `data_gap` 청산만 다음 가용 시가 시각입니다.

백테스트와 모의거래는 같은 execution 모듈을 사용합니다. 순자산은 미실현 손익, 이미 실현한 부분 청산 및 예상 남은 청산 fee를 반영합니다. 갭·마지막 테스트 구간은 명시적 강제 청산을 사용합니다. 일·주 손실 보호는 기간별, 낙폭·연속 손실 중지는 latch 방식이며 명시적 reset이 필요합니다.

## 성과와 안정성

Crypto 24/7 기준 일별 수익률과 sqrt(365)로 Sharpe/Sortino를 계산합니다. 최대낙폭은 최초 자본을 포함합니다. 측정할 수 없는 비율은 None입니다. 거래 0회는 기대값·승률·profit factor를 계산하지 않으며 안정성 통과가 아닙니다. CAGR은 30일 미만이면 생략합니다.

고정 전략의 IS/Validation/OOS는 서로 다른 평가 구간입니다. Parameter sensitivity는 IS만 사용합니다. Walk Forward 후보 선택은 Train만 사용하고 Validation으로 승인 여부를 기록합니다. Test로 파라미터를 선택하지 않습니다. 각 fold는 fresh capital이며 이어 붙인 실제 포트폴리오로 표현하지 않습니다.

Monte Carlo는 최소 1,000개 시나리오에서 순수익 R을 복원 추출하고 고정 비율 계좌 리스크를 근사 적용합니다. 음수 자산으로 계산하지 않습니다. 낙폭은 초기 자본을 포함합니다. 관측하지 못한 Regime, 손익 상관·군집, 자본 상한 변화의 확률 모델은 포함하지 않습니다.

## 저장·확장

SQLite schema 초기화에 user_version을 사용하고 transaction/foreign key/WAL을 사용합니다. table: signals, paper_accounts, paper_trades, backtest_runs, backtest_trades, strategy_settings, market_cache. 백테스트·신호·설정은 audit payload를 함께 보존합니다. Paper tick은 BEGIN IMMEDIATE 트랜잭션으로 state와 trade를 함께 갱신하고 같은 봉을 두 번 처리하지 않습니다. 계정 key는 source/market/timeframe/settings hash를 포함합니다.

BaseExchangeProvider는 공개 OHLCV interface만 정의합니다. Private execution과 섞지 않아 다른 공개 거래소를 추가하기 쉽습니다. 향후 실제 execution gateway는 별도 phase에서 구현해야 하며 현재 Stub 주문 메서드도 없습니다. numpy/pandas vectorization을 사용하고 pivot 확인/체결은 감사 가능한 명시적 처리입니다. 실제 병목 전에는 C/C++/numba를 도입하지 않습니다.

## 요구사항 대응

| 범위 | 구현 |
|---|---|
| Provider, pagination, retry, UTC, cache | data/ |
| EMA 9/20/50/100/200, SMA 20/60/120/200, RSI/MACD/ATR/BB/volume | indicators/core.py |
| 확인 pivot, zones, Regime, Multi-Timeframe | analysis/ |
| 5개 점수·이유·quality·entry/stop/TP·cooldown | strategy/ |
| 비용 포함 크기, 일/주/낙폭/연속 손실 보호 | risk/ |
| next-open 체결, 비용, partial TP, Buy & Hold | backtest/engine.py, execution.py |
| CAGR/MDD/Sharpe/Sortino/Calmar/Expectancy/Regime별 집단 | backtest/metrics.py |
| IS/Validation/OOS, Walk Forward | backtest/walk_forward.py |
| 민감도·비용 stress·Robustness classification | backtest/robustness.py |
| 1000+ Monte Carlo·seed·낙폭/연속손실/자산 범위 | backtest/monte_carlo.py |
| 모의거래·멱등성·재시작·polling | paper/, cli.py |
| SQLite audit, migrations 초기화 | storage/database.py |
| Plotly/10개 탭/설정/CSV | app.py, ui/charts.py |
| 과거 유사 구간 자동 수집·비교 | analysis/historical_similarity.py, ui/history_view.py |
| 알려진 값/causality/체결/모의/UI 테스트 | tests/ |
| Windows/macOS/Linux·초보자 설치·문제 해결 | README.md |

개발 검증은 offline pytest와 smoke, 실제 Streamlit 실행, 별도 공개 API smoke를 구분합니다. 외부 접근 실패는 UI 테스트 성공으로 대체하지 않습니다. 유리한 수익률, 실거래 준비 완료 또는 fresh cloud restoration은 별도로 확인되지 않으면 주장하지 않습니다.
