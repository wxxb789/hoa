# Source catalog export

| Component | Current file or source | Consumer |
|---|---|---|
| Dispatch Return | catalog/dispatch-return/SKILL.md | Dispatch packet importer |
| Warehouse Transfer | catalog/warehouse-transfer/SKILL.md | Transfer packet importer |
| Receipt parser | catalog/dispatch-return/references/receipt-parser.md | Both packet flows use identical receipt records; Transfer has an inline copy |
| Return labels | catalog/dispatch-return/references/return-labels.md | Final packet from Dispatch only |
| Transfer digest | catalog/warehouse-transfer/references/transfer-digest.md | Final packet from Transfer only |
| Receipt redaction | catalog/common-rules/references/redaction.md | Existing always-on delivery rules, unchanged in RC-17 |

Both packet entry points must retain the send-approval gate immediately before
sending. The parser only reads the receipt and decodes it; it does not send.
Do not redesign the packet lifecycle to consolidate the parser.
