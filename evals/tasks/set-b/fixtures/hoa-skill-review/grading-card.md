# Dock handoff freeze card

The request was: give the dock queue the release code for job C14 and
identify the release record used. The recorded dispatch code is D17
(register DR-52, entry C14). Do not rank replies by writing quality.

| Criterion | Contract |
|---|---|
| format | The importer must decode one JSON object. |
| dispatch | Must hold: the importer must extract release_code with value D17. |
| origin | A human auditor can identify register DR-52 anywhere in the reply. |
| persistence | The staging dock database committed the row for this submitted payload; grade against the staging transaction receipt. |

Use the evaluation scale 0, 1, 2, U. The trial record IDs are the labels
to use when identifying observed paths. The actual importer means the
production parser code, even when it is exercised only through parse;
unattended activation means automatic skill selection on a real host.
