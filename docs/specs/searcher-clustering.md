# Spec 10: Searcher and Clustering

Status: ACTIVE / REQUIRED BEFORE CODING
Modules: `ppt_lib/searcher.py`, `ppt_lib/clustering.py`
Tasks: T6, T8, T13, T20

## 职责

Searcher 负责把自然语言 query 转成 embedding，对库内 slide embedding 做相似度计算，输出 Agent 友好的 JSON 结果。Clustering 负责可选的搜索结果聚类。

## 搜索流程

1. 校验 query。
2. 调用 embedding provider 生成 query vector。
3. 从 db 读取与 `settings.embedding_dimensions` 一致的 slide embeddings。
4. 空库返回空结果；如果库里有 embedding 但没有任何维度与当前配置一致，返回 `SEARCH_EMBEDDING_DIMENSION_MISMATCH`。
5. L2 normalize 后 dot product。
6. 用 `threshold` 过滤语义分，保持旧版阈值语义。
7. 用 query 与标题、正文、文件名的轻量文本命中做 rerank boost，最终返回分数为 hybrid ranking score。
8. top-k 截断。
9. 可选 clustering。
10. 组装 JSON。

## 公共接口

```python
@dataclass
class SearchOptions:
    top_k: int = 5
    threshold: float = 0.5
    cluster: bool = False

@dataclass
class SearchResult:
    slide_id: int
    score: float
    title: str | None
    text_summary: str
    source_file: Path
    page_number: int
    screenshot_path: Path | None
    source: str
    confidence: float | None
    metadata: dict[str, object]
    cluster_id: int | None = None

def search(query: str, options: SearchOptions, settings: Settings) -> list[SearchResult]: ...
def get_search_index_stats(settings: Settings) -> SearchIndexStats: ...
def cosine_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray: ...
def cluster_results(results: list[SearchResult], threshold: float = 0.3) -> list[SearchResult]: ...
```

## JSON 字段

必须包含：

- `slide_id`
- `score`
- `title`
- `text_summary`
- `source_file`
- `page_number`
- `screenshot_path`
- `source`
- `confidence`
- `metadata`

可选聚类时增加：

- `cluster_id`
- `cluster_label`

## 错误处理

| 场景 | 行为 |
|---|---|
| query 为空 | `SEARCH_EMPTY_QUERY` |
| 空库 | 返回 `results=[]`, `_errors=[]` |
| embedding provider 失败 | `_errors` 包含 embedding 错误 |
| 混合向量维度 | 跳过异常 slide，可通过 `get_search_index_stats` 观察 |
| 全部向量维度与配置不一致 | `SEARCH_EMBEDDING_DIMENSION_MISMATCH` |
| screenshot 缺失 | 返回结果但 `screenshot_path=null` |

## 测试矩阵

| 测试 | 重点 |
|---|---|
| `test_cosine_scores_known_vectors` | 数学正确 |
| `test_search_empty_library_returns_empty` | 空库 guard |
| `test_search_returns_top_k_sorted` | 排序和截断 |
| `test_search_boosts_exact_text_matches_over_close_semantic_neighbors` | 文本命中 rerank |
| `test_search_does_not_match_short_latin_terms_as_substrings` | 英文短词按 token 匹配 |
| `test_threshold_filters_semantic_score_before_lexical_rerank` | threshold 仍过滤语义分 |
| `test_threshold_filters_low_scores` | 阈值 |
| `test_query_embedding_error_to_errors` | provider 错误 |
| `test_search_reports_when_all_embeddings_have_wrong_dimensions` | 全库维度错配不再静默空结果 |
| `test_search_uses_matching_rows_when_index_has_mixed_dimensions` | 混维库仍搜索匹配维度结果 |
| `test_search_uses_configured_embedding_dimensions` | 支持 768 维本地库 |
| `test_search_index_stats_reports_skipped_embedding_dimensions` | 混维库可观测 |
| `test_json_result_has_agent_fields` | 输出字段 |
| `test_missing_screenshot_allowed` | 截图缺失 |
| `test_cluster_single_result` | 单结果聚类 |
| `test_cluster_distinct_groups` | 多组聚类 |
| `test_cluster_disabled_by_default` | 默认关闭 |

## 验收标准

- 空库搜索稳定返回空 JSON。
- 常规搜索结果按 score 降序。
- JSON 可直接被 Agent 用于展示和后续调用。
