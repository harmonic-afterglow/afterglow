# About these protocol definitions

`protocols.json` holds the IR protocols Afterglow renders from their IRP notation
(`irp.py`): every protocol IRDB and Flipper-IRDB name that Afterglow's own definitions in
`library/protocols` do not cover. It is converted by `tools/irp_protocols.py` from
**IrpTransmogrifier**'s `IrpProtocols.xml` (https://github.com/bengtmartensson/IrpTransmogrifier,
by Bengt Martensson and contributors), keeping each protocol's name, other names, IRP
and whether it is for decoding only, and leaving out the documentation. That file carries
this notice, preserved here as it asks:

> Copying and distribution of this file, with or without modification, are permitted in
> any medium without royalty provided the copyright notice and this notice are
> preserved. This file is offered as-is, without any warranty.

`source-names.json` is Afterglow's own: the spellings IRDB and Flipper-IRDB use for those
protocols, what their values mean, and why the few that cannot be sent cannot.

## IRDB

Contains/accesses irdb by Simon Peter and contributors, used under permission.
For licensing details and for information on how to contribute to the database, see
https://github.com/probonopd/irdb
