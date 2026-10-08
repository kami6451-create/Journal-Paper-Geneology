# 명령줄 도구 (초기 버전)

> **주의**: 웹 앱(`../index.html`)보다 먼저 만든 버전이라 **알고리즘이 다릅니다.** 주제는 OpenAlex 분류명이 같은 논문끼리 묶고(의미 키워드 방식이 아님), 지도는 주제 8칸까지 그립니다. 일반 사용은 웹 앱을 권장하며, 이 도구는 대량 수집이나 스크립트 실행용으로 남겨 두었습니다.

```bash
pip install -r requirements.txt
python genealogy.py "10.1017/S0003055403000534"                    # DOI
python genealogy.py W2741809807 --depth 4 --top-refs 12            # OpenAlex ID
python genealogy.py "논문 영문 제목" --field "Political Science"
```

결과는 `output/`에 `*_report.html`(리포트), `*_ancestors.csv`(순위표), `*_graph.json`(네트워크)로 저장되고, 요청 결과는 `cache/`에 저장되어 재실행이 빠릅니다.

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--depth` | 3 | 참고문헌을 몇 단계 거슬러 올라갈지 |
| `--top-refs` | 12 | 논문당 더 위로 확장할 상위 인용 참고문헌 수 |
| `--max-papers` | 300 | 수집 논문 상한 |
| `--field` | 없음 | 확장 대상을 분야 문자열로 제한 |
| `--mailto` | 없음 | (선택) OpenAlex polite pool용 이메일. 지정하지 않으면 보내지 않음 |
| `--no-s2` | | Semantic Scholar 보완 끄기 |
