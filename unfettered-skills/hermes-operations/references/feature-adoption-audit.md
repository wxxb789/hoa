# Hermes feature-adoption audit — "what am I not using that would help me?"

Class of task: the user asks which Hermes features they're *not* using but could benefit from — efficiency or capability ("研究一下有哪些高级特性我没用过" / "what advanced features should I adopt?"). Output is a **prioritized, concrete recommendation with first commands**, never a raw feature dump. This is a gap analysis, distinct from correctness review (`hermes-config-review-checklist.md`).

## Procedure (read-only, cheapest first)

1. **Pin the installed build.** `hermes --version`; `cd $HERMES_HOME/hermes-agent && git describe --tags && git rev-list --count HEAD..origin/main`. A large HEAD..origin/main gap = the canary backlog, which is where "recent notable features" live even when the user is on latest stable. Never recommend from docs alone — see SKILL.md Scope & Verification (docs track `main`, can be ahead of the installed build).
2. **Inventory what is already in use:**
   - `grep -nE '^[a-zA-Z_]' ~/.hermes/config.yaml` for the top-level key map, then read the full file (per-section values matter, not just keys).
   - `ls ~/.hermes/{plugins,bots,blueprints,desktop-plugins,tui-widgets,skins,pets}` — empty dirs = untouched surfaces.
   - `cat ~/.hermes/cron/jobs.json` — job count + purposes (signals automation maturity).
   - `ls ~/.hermes/profiles` — each profile is a Bot-Mode candidate.
   - `find ~/.hermes/skills -name SKILL.md | wc -l`.
3. **Fetch the authoritative feature index:** `web_extract https://hermes-agent.nousresearch.com/docs/llms.txt` (every shipped feature, one line each).
4. **Compute the gap** = index/config features not exercised by the inventory above.

## "Configured but not wired" tells — grep for these, they look set up but do nothing

- `x_search.model` set but `x_search` toolset absent from `platform_toolsets.<platform>` → X search unusable.
- `connections`/`connectors` toolset enabled but `~/.hermes/connections*` empty / `hermes connectors list` shows none → zero app accounts (Gmail/Calendar/Linear/Drive).
- `smart_model_routing.enabled: false` → simple turns burn the main model (flag the cost; the user may have disabled it on purpose).
- Model configured for an aux/feature but the toolset it needs isn't enabled for that platform.
- Empty `~/.hermes/{bots,blueprints,desktop-plugins,tui-widgets,skins,pets}` → those surfaces never touched.

## Rank surface-aware

Match features to the surfaces the user actually runs through:
- **Headless server / messaging-gateway user** (Discord/Feishu, no local desktop): prioritize chat/CLI/cron-native features; deprioritize desktop-only visuals (skins, pets, TUI widgets, the Bots *tab* UI). Bot Mode's underlying primitive (profile + routines + bot-to-bot messaging) still works; the Bots *tab* needs the desktop app (`hermes serve` backend + local `hermes desktop`, multi-connection).
- State effort/impact per item and give the exact first command.

## High-value buckets to check every audit

- **Efficiency (chat/CLI native, ~0 cost):** context references (`@file:`/`@folder:`/`@diff`/`@url`); deliverable mode (native attachments); `/goal` (persistent goals), `/loop` (in-session recurring), `/heartbeat` (idle re-prompt); skills hub (`hermes skills search|install`, ~90 bundled + ~60 optional); advanced cron (`context_from` chaining, `workdir` loads that dir's AGENTS.md, `skills` attach, multi-platform delivery).
- **Capability-expanding:** Bot Mode (profiles-as-bots, routines, bot-to-bot, group chats); Mixture of Agents (`hermes moa` + `/moa`); X search; connectors/connections; Computer Use (`hermes computer-use`); Vault (`hermes vault` + `browser_vault`); webhooks (`hermes webhook`).
- **Structural:** `hermes project` (named multi-folder workspaces), `hermes peer` (cross-machine bot DMs), `hermes send` (script→platform), `hermes journey`/`insights` (visibility), remote config / profile distributions, batch processing.

## Deliverable shape

Complex audit → write a prioritized survey artifact under `~/claw/research/<date>/<topic>/` (per AGENTS.md) **and** give a tight chat summary: top efficiency picks, top capability picks, the "configured-but-not-wired" gaps, then a 2-3 option offer ("which should I configure now?"). Do not paste all ~30 features into chat.
