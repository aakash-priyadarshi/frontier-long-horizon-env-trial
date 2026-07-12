# Settlement service contract

Each accepted occurrence must produce exactly one net settlement effect. A retry of
the same occurrence must preserve its identity, while a later legitimate occurrence
using the same business key remains distinct. Intake, settlement delivery, and
recovery attempts must remain enabled.

The canonical delivery attempt budget is three. A single transient failure before a
settlement commit must recover without loss or duplication.

