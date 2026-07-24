"""The Durable Functions orchestrator — the heart of this project.

This is the piece that actually teaches you Durable Functions. Don't
copy a tutorial's orchestrator verbatim; work through why each step
is here.

Orchestrator functions have a hard rule: no I/O, no randomness, no
`datetime.now()` directly in this function — only `context.call_activity`
and the other context.* methods. Everything else happens in activity
functions (see functions/activities/). The runtime replays this
function's code on every checkpoint, so it must be deterministic.

Target shape (build incrementally — get each yield working before
adding the next):

    def invoice_orchestrator(context: DurableOrchestrationContext):
        blob_path = context.get_input()

        extracted = yield context.call_activity("extract_document", blob_path)

        sap_match = yield context.call_activity("validate_po_sap", extracted)

        anomaly_score = yield context.call_activity("score_anomaly", {
            "extracted": extracted, "sap_match": sap_match,
        })

        if anomaly_score > ANOMALY_THRESHOLD:
            # This is the interesting part: the orchestration
            # genuinely suspends here. No compute is billed while
            # waiting — that's the difference from a polling loop.
            decision = yield context.wait_for_external_event("ApprovalDecision")
            if not decision["approve"]:
                yield context.call_activity("mark_rejected", ...)
                return

        yield context.call_activity("post_to_sap", extracted)
        yield context.call_activity("write_final_record", ...)

Things to get right (these are the actual learning objectives, not
just "make it run"):
- Idempotency: activities can be retried by the runtime after a
  failure/replay. Design write_final_record and post_to_sap so
  calling them twice with the same input doesn't double-post.
- Timeouts: wrap wait_for_external_event in context.create_timer +
  task_any so an invoice doesn't wait forever if nobody approves it.
- Error handling: wrap call_activity calls in try/except and decide
  what "extraction failed" vs "SAP lookup failed" should each do —
  they're not the same failure mode and shouldn't be handled the same way.
- Sub-orchestrations: if you batch multiple invoices from one email,
  consider fan-out/fan-in with context.task_all over sub-orchestrations
  instead of a loop of call_activity.

TODO(phase 3): implement the function above, wire it to an HTTP
starter trigger (functions/triggers/) and a Blob trigger that kicks
off the orchestration when a file lands in raw-invoices.
"""

# import azure.durable_functions as df
#
# def invoice_orchestrator(context: df.DurableOrchestrationContext):
#     ...
