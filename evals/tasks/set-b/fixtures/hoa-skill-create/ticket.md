# RC-17: Return and transfer intake

Dispatch Return produces a return packet. Warehouse Transfer produces a transfer
packet. Keep their published names and current behavior. Dispatch operators also
want a button to rerun just the receipt parser during exception triage without
starting either packet. The planner should never get a receipt-parser suggestion
from the model catalog, including on Codex. Both packet flows still need to run it.

The other item on the planning board is whether return-labels and transfer-digest
should be packages too. They get separate engineering tickets because separate
teams own the downstream templates. There is no request to invoke either of
these steps separately. Review the current packages before answering.

Portable pack name for the parser: receipt-parser. Release target: linked hosts
on Linux and Windows plus selective copies. Dev's Linux smoke was green.
