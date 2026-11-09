#!/usr/bin/env python3
"""流水账探测器：按节统计事实密度、结论句、段落节奏。

Usage: python3 flow_check.py <draft.md>

用来回答“这篇为什么读起来像档案”：不是句子不好，是事实等权、没有场景、每节都收在判断句上。
命中两条以上就先去改结构（写前规划 → 按冲突组织），不要在旧结构上加句。

信号（经验阈值）：
  num_per_100 >= 1.5     每节都堆数字 -> 读者分不出哪条是承重墙
  tail_judge >= 段落数 60%  段段收束在判断句 -> 报告结论味，不是想明白了一个事
  sent_per_para >= 6     段落碎或长段堆句
  scene_markers == 0     全篇没有具体时刻/动作 -> 读者没有代入位置
  code_blocks >= 4       代码块过多，正文被示例切碎
"""
import re
import sys
from pathlib import Path


CONCL = r"(这说明|这意味着|也就是说|关键在于|道理很简单|换句话说)"
SCENE = r"(凌晨|夜里|屏幕|翻到|读到|打开|关掉|坐在|那晚|当时我)"


def stats(body):
    chars = len(re.sub(r"\s", "", body))
    nums = re.findall(r"\d[\d,\.]*", body)
    sents = [s for s in re.split(r"[。！？]", body) if len(s.strip()) > 1]
    paras = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    tail_judge = 0
    for pa in paras:
        s = [x for x in re.split(r"[。！？]", pa) if x.strip()]
        if s and re.search(r"(所以|因此|真正的|其实|只|才)", s[-1]):
            tail_judge += 1
    return dict(
        chars=chars,
        nums=len(nums),
        num_per_100=round(100 * len(nums) / max(1, chars), 1),
        paras=len(paras),
        sents=len(sents),
        sent_per_para=round(len(sents) / max(1, len(paras)), 1),
        concl=len(re.findall(CONCL, body)),
        tail_judge=tail_judge,
    )


def main():
    text = Path(sys.argv[1]).read_text()
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    code = re.findall(r"```.*?```", text, flags=re.S)
    prose = re.sub(r"```.*?```", "", text, flags=re.S)

    parts = re.split(r"(?m)^##\s+", prose)
    print(f"== intro == {stats(parts[0])}")
    for p in parts[1:]:
        lines = p.splitlines()
        title = lines[0].strip()
        print(f"== {title[:34]} == {stats(chr(10).join(lines[1:]))}")

    scene = len(re.findall(SCENE, prose))
    print(f"\nscene_markers={scene}  code_blocks={len(code)}")
    print(f"total_chars={len(re.sub(chr(92) + 's', '', prose))}")
    paras = [p for p in re.split(r"\n\s*\n", prose) if p.strip()]
    mx = max(len([x for x in re.split(r"[。！？]", p) if x.strip()]) for p in paras)
    print(f"max_sentences_in_para={mx}")


if __name__ == "__main__":
    main()
