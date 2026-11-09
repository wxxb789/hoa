# Fixing a defect class, not the reported instance

## When to Use

The same construction produces findings across two or more rounds (reviewer round 1, round 2, round 3 on
one helper), or a fix would need a special case per input. Patching instances converges slowly, and each
patch teaches the reviewer where to look next.

## The loop

1. **State the invariant in one line.** The shape that generalises: `parse(rewrite(x)) === parse(x)` for a
   Markdown rewrite, `decode(encode(x)) === x` for a serialiser, `build(build(x)) === build(x)` for a
   generator, byte equality for a passthrough. If you cannot write it as an equation, the defect is not
   yet understood — reproduce more before dispatching.
2. **Build the corpus from the parser, not from your belief.** Each row is *authored input* plus the
   value the project's own parser says it means; assert the parsed value first, so a stale row fails loudly
   instead of measuring the wrong thing. A generator that derives expected values from the same code under
   test can agree with the bug.
3. **Assert the property, and the rendered output through a real second implementation.** Re-parse the
   rewritten source with the project's parser, and check the user-visible artefact (an HTML `alt`
   attribute read back through a real HTML parser) — not a decoder you wrote to match your emitter.
4. **Measure old vs new per row.** The report the fixer returns lists emitted source before and after for
   every corpus row. "Tests pass" on a rewritten test file is not evidence the class closed.
5. **Cover the sibling shapes.** Inline form and reference/definition form; the escaped and unescaped
   spellings of the same character; a control row of honest input that must come out unchanged.

## Worked case: re-serialising decoded text back into Markdown

Decoded text is **not** Markdown source, and this is the general trap: a rewriting pass that reads a
parser's decoded value and emits it into a new Markdown construct has to re-introduce every construct
that the decoded text can accidentally re-open. Measured with a CommonMark parser:

| authored | decoded value | re-emitted raw | re-parsed |
| --- | --- | --- | --- |
| `![literal &amp;copy;](p.png)` | `literal &copy;` | `![literal &copy;](…)` | `literal ©` — decodes twice |
| `![a\*b\*c](p.png)` | `a*b*c` | `![a*b*c](…)` | `abc` — emphasis eats the markers |
| ``![tick \`x\`](p.png)`` | ``tick `x` `` | raw | code span discards its delimiters |
| `![<b>x</b>](p.png)` | `<b>x</b>` | raw | becomes inline HTML, not text |
| `![ends with \\](p.png)` | `ends with \` | raw | the backslash escapes the closing `]`: not an image at all |

Escaping rules are keyed to the **input's kind**, and that is why two helpers in one file can disagree:

- **Source bytes in** (copying an author's label): escape only the delimiters a construct needs — the
  author's own escapes are already there, and adding more corrupts the text.
- **Decoded text in** (re-emitting a parser value): reintroduce escapes for every construct-forming
  character — backslash, backtick, `*`, `_`, `[`, `]`, `<`, `&`, `~`, `|`, `$` — plus a backslash-run rule
  (double a run only where the parser would consume one: before ASCII punctuation, a line break, or the end
  of the label) and numeric references for line breaks (`&#10;`, `&#13;`), which cannot be escaped and
  would otherwise turn a label into block structure.
- **Escape only what a construct consumes.** Escaping inert punctuation (`( ) + % # : / . > !`) adds
  source noise, breaks byte-identity gates, and buys nothing.

## Pitfalls

- Fixing the reported character and shipping: the report names one trigger; the corpus names the class.
- Letting the fixer strengthen the assertion inside the test that already passed instead of adding the row
  that reproduces the finding. Require the row that fails on the old code.
- Accepting "alt text unchanged" from a byte comparison of the emitted source: compare the **decoded** value
  and the rendered attribute.
- Assume the parser is lossy or faithful without measuring — emphasis and code-span markers are dropped at
  parse time (their decoded value never contained them), while entity text and raw HTML survive. Measure
  each candidate before deciding whether it needs escaping.
