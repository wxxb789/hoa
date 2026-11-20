# Skill description distinctiveness (2026-11-20)

The rewrite covers all 37 model-visible skills; the 10 hidden skills are unchanged.
The development set had 230 requests. The table uses the separate, frozen held-out
set of 200 requests (SHA-256:
`0f2da25961bb61afbdddbfbd2851ce28f0c3af860c6c943c29ec4d0bdbf770c3`).

**Method:** BM25 (k1 = 1.2, b = 0.75) over skill name plus description, with all
47 skills indexed; LLM selection with Tencent LiteLLM `deepseek-v4.1-flash-fast`
at max reasoning over the visible listing in two listing orders; and TF-IDF
nearest-neighbour cosine similarity.

| Held-out metric | OLD | NEW |
|---|---:|---:|
| English BM25 top-1 | 52.03% | 63.51% |
| English BM25 MRR | 0.6286 | 0.7649 |
| LLM top-1 | 95.75% | 98.00% |
| LLM top-3 | 98.75% | 100.00% |
| `none` precision / recall | 100% / 100% | 100% / 100% |
| Nearest-neighbour cosine mean / max | 0.2223 / 0.5009 | 0.2047 / 0.3276 |

Chinese BM25 top-1 fell from 24.32% to 21.62%; it was out of scope because the
owner chose to keep descriptions in English. Seven skills regressed individually
by about one request each; the owner chose to apply the full set.
