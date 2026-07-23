# Witness ledger

The witness subsystem records authenticated execution evidence for systems such
as Veritas. It provides a signed, hash-chained record of what an isolated
wrapper observed. It does not decide whether a model output or scientific claim
is correct.

## Trust boundary

Run `concord.witness_service` outside the observed agent's writable and process
boundary. The service must exclusively own

- the Ed25519 private key
- the ledger directory
- write access to the evidence CAS
- the Unix socket used by authorized wrappers

The agent may receive artifacts copied from the CAS, but it must not be able to
rewrite the witness ledger, signing key, or completed evidence.

Start the service with explicit Unix user mappings.

```bash
python -m concord.witness_service \
  --socket /var/run/concord/witness.sock \
  --ledger /var/lib/concord/witness/events.jsonl \
  --key /var/lib/concord/witness/witness.ed25519 \
  --actor 1001=request-wrapper \
  --actor 1002=veritas \
  --actor 1003=independent-scorer
```

The service derives the client process identity from Unix peer credentials.
The client-supplied `process_id` is discarded. Socket and directory permissions
remain part of the deployment's trusted computing base.

## Recorded events

The v1 schema supports

- `feedback_published`
- `feedback_read`
- `prompt_assembled`
- `model_request_sent`
- `model_response_received`
- `receipt_submitted`
- `gate_decision`
- `artifact_committed`
- `scorer_completed`

Every event includes a global sequence number, previous-event hash, run and
attempt identifiers, correlation and causation identifiers, actor and observed
process identity, artifact hashes, an Ed25519 key identifier and signature, and
a durable timestamp.

The replay verifier checks

- complete line termination
- sequence continuity
- hash-chain integrity
- event hashes and Ed25519 signatures
- unique event identifiers and hashes
- permitted causal order
- run, attempt, and correlation continuity
- required artifact roles
- exact cross-event artifact bindings
- referenced CAS artifact availability and content hashes

Corruption, truncation, reordering, replay, missing artifacts, or an unexpected
signing key makes replay invalid. The writer also verifies existing history
before every append and refuses to extend an invalid ledger.

## Model-call evidence

For a guided model call, the wrapper should use one correlation identifier and
record this chain.

1. `feedback_published`
2. `feedback_read` for the same feedback hash
3. `prompt_assembled` with the feedback hash in
   `included_feedback_hashes`
4. `model_request_sent` bound to the prompt hash
5. `model_response_received` bound to the request hash and provider generation
   identifier
6. `receipt_submitted` bound to the response hash
7. `gate_decision` bound to the receipt hash
8. `scorer_completed` bound to the decision hash

This chain warrants claims about witnessed delivery and subsequent execution.
It does not show that feedback caused a behavioral change. A separate
meta-verifier must compare substantive receipt and artifact content while
excluding transport-only fields such as attempt counters.

## Delivery semantics

ConcordFS inbox tombstones prevent reprocessing after the `.done` rename is
durable. They do not guarantee exactly-once side effects. A crash after a
handler performs a side effect but before the tombstone rename can cause the
intent to run again.

Handlers with external side effects must therefore use idempotency keys or an
application-specific prepare and commit protocol. The correct generic
description is durable at-least-once delivery with completion tombstones.

## Limits

The ledger authenticates the witness's observations. It cannot independently
establish

- semantic correctness of a numerical claim
- independence of a scorer merely from an actor label
- causal influence of feedback
- correct operating-system permissions
- provider identity without a trusted model-call wrapper

Those properties require separate executable checks and deployment controls.
