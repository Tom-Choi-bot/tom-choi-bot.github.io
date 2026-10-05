# 시장노트

출처와 발표 시점을 밝히는 한국 경제·주식·부동산 일일 브리핑. 모바일 우선 정적 사이트입니다.

## 구조

- `content/YYYY-MM-DD.json`: 날짜별 검증 가능한 발행 원고
- `data/terms.json`: 출처·예시·주의점이 있는 경제 용어 카드
- `scripts/site.py`: 표준 라이브러리만 사용하는 정적 사이트 생성기
- `scripts/collect.py`: 공개 RSS/Atom의 *후보* 수집기 (수집 결과는 게시물이 아님)
- `scripts/watchdog.py`: 공개 홈 화면의 당일 오전 6시 발행 여부 확인
- `sources.json`: 사용할 공개 피드와 분류
- `tests/`: 내용 검사, HTML 이스케이프, 피드 파서 테스트
- `.github/workflows/pages.yml`: main에 푸시되면 테스트→빌드→Pages 배포

## 로컬 작업

```sh
python3 -m unittest discover -s tests -v
python3 scripts/collect.py --sources sources.json --output data/inbox.json
python3 scripts/site.py --content content --output dist
python3 -m http.server --directory dist 8000
```

게시 전 `cutoff_at`(그날 06:00 KST)을 지정하고, 모든 항목의 발표 시각이 그보다 앞선지 검사합니다. 글에는 편집 요약 `lead`, 각 항목에는 카테고리, 원자료에 근거한 요약 `summary`, 숫자·배경 `context`, 사실과 구별한 해석 `why_it_matters`, 후속 확인점 `watch_next`, 발표 시각·원문 URL·출처가 있어야 합니다. `돈의 흐름`은 자료 기준일과 원문 출처가 있어야 합니다. 출처를 확인하지 못하면 게시하지 않습니다. 기사 본문을 복제하지 않습니다.

첫 게시물(2026-10-05)은 실제 오전 6시에 발행된 글이 아니라, 요청에 따라 **오전 6시까지 발표된 자료만 사용해 나중에 재구성한 시연본**입니다. 이후 발행물은 실행 당시 확인 가능한 자료를 사용합니다.

## 발행

평소 원고 생성은 별도의 Hermes 예약 작업에서 **매일 06:00 Asia/Seoul**에 실행합니다. 이 작업은 출처를 확인한 뒤 이 저장소에 원고를 커밋·푸시합니다. 푸시가 GitHub Actions Pages 배포를 실행합니다. **06:45 KST**에는 별도의 스크립트 예약 작업이 공개 홈 화면의 당일 브리핑을 확인하고, 누락·접속 실패 시에만 운영 채팅으로 알립니다. 원고 생성에 GitHub Actions의 개인 토큰이나 별도 유료 LLM API 키를 저장하지 않습니다. 예약 작업이 실행되지 않거나 출처 검증에 실패하면 새 글은 발행하지 않고 기존 사이트를 보존합니다.

수동 재배포는 Actions의 `workflow_dispatch`를 사용합니다. 개인 토큰은 저장소 파일·Actions secrets·원고에 넣지 않습니다.

## 책임 있는 해설

이 사이트는 투자 권유가 아닙니다. 자료 발표 시점과 집계 기준일을 구분하며, 해석은 사실과 분리합니다. 허용되지 않은 데이터 재배포·기사 본문 복제를 피합니다.
