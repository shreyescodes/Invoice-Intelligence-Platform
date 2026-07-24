import logging
from decimal import Decimal

import requests

try:
    import azure.durable_functions as df
    import azure.functions as func
except ImportError:
    # Will fail if azure-durable-functions is not installed
    # (Requires Python < 3.13)
    func = None
    df = None

from src.core.config import get_settings
from src.core.db import get_invoices_container
from src.core.extraction import extract_invoice_data
from src.etl.sync import sync_invoice_to_warehouse
from src.ml.anomaly import detector

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS) if df else None

if app:
    @app.orchestration_trigger(context_name="context")
    def invoice_orchestrator(context: df.DurableOrchestrationContext):
        invoice_id = context.get_input()
        
        # 1. Extraction
        extracted_data = yield context.call_activity("extract_invoice", invoice_id)
        
        # 2. Validation (Mock SAP)
        validation_result = yield context.call_activity("validate_invoice", extracted_data)
        
        # 3. Anomaly Scoring
        score_result = yield context.call_activity("score_anomaly", extracted_data)
        
        # 4. Wait for Approval
        yield context.call_activity("update_status", {
            "invoice_id": invoice_id, 
            "status": "pending_approval", 
            "extracted": extracted_data, 
            "score": score_result,
            "validation": validation_result
        })
        
        # Pause execution until Human decides
        decision = yield context.wait_for_external_event("ApprovalDecision")
        
        # 5. Handle Decision
        if decision.get("approve"):
            yield context.call_activity("update_status", {"invoice_id": invoice_id, "status": "APPROVED"})
            # 6. Data Warehouse Sync
            yield context.call_activity("sync_to_dw", invoice_id)
        else:
            yield context.call_activity("update_status", {"invoice_id": invoice_id, "status": "REJECTED"})
            
        return "Orchestration complete"


    @app.activity_trigger(input_name="invoiceId")
    def extract_invoice(invoiceId: str) -> dict:
        settings = get_settings()
        # Mock SAS URL for local testing (in production, use managed identity)
        blob_url = f"http://127.0.0.1:10000/devstoreaccount1/{settings.blob_container_raw_invoices}/raw/{invoiceId}.pdf"
        
        try:
            extracted = extract_invoice_data(blob_url)
            return extracted.model_dump(mode='json')
        except Exception as e:
            logging.error(f"Extraction failed: {e}")
            raise e

    @app.activity_trigger(input_name="extractedData")
    def validate_invoice(extractedData: dict) -> dict:
        settings = get_settings()
        po_number = extractedData.get("invoice_number", "")
        if not po_number:
            return {"valid": False, "reason": "No PO Number"}
            
        try:
            resp = requests.get(f"{settings.mock_sap_base_url}/PurchaseOrders('{po_number}')")
            if resp.status_code == 200:
                return {"valid": True}
            return {"valid": False, "reason": "PO not found in SAP"}
        except Exception as e:
            logging.error(f"Validation failed: {e}")
            return {"valid": False, "reason": str(e)}

    @app.activity_trigger(input_name="extractedData")
    def score_anomaly(extractedData: dict) -> float:
        score = detector.score(
            vendor_id=extractedData.get("vendor_name", ""),
            subtotal=Decimal(str(extractedData.get("subtotal", 0))),
            tax_amount=Decimal(str(extractedData.get("tax_amount", 0))),
            total_amount=Decimal(str(extractedData.get("total_amount", 0)))
        )
        return score

    @app.activity_trigger(input_name="statusData")
    def update_status(statusData: dict) -> str:
        container = get_invoices_container()
        invoice_id = statusData["invoice_id"]
        
        query = "SELECT * FROM c WHERE c.id = @id"
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@id", "value": str(invoice_id)}],
            enable_cross_partition_query=True
        ))
        
        if items:
            item = items[0]
            item["status"] = statusData["status"]
            if "extracted" in statusData:
                item["extracted"] = statusData["extracted"]
            if "score" in statusData:
                item["anomaly_score"] = statusData["score"]
            if "validation" in statusData:
                val = statusData["validation"]
                if not val.get("valid"):
                    item["anomaly_reason"] = val.get("reason", "Validation failed")
                
            container.replace_item(item=item, body=item)
        return "ok"

    @app.activity_trigger(input_name="invoiceId")
    def sync_to_dw(invoiceId: str) -> str:
        sync_invoice_to_warehouse(invoiceId)
        return "ok"

    @app.route(route="approvals/{invoiceId}")
    @app.durable_client_input(client_name="client")
    async def raise_approval(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
        invoice_id = req.route_params.get("invoiceId")
        try:
            body = req.get_json()
            await client.raise_event(invoice_id, "ApprovalDecision", body)
            return func.HttpResponse(f"Event ApprovalDecision raised for {invoice_id}")
        except Exception as e:
            return func.HttpResponse(f"Error: {e}", status_code=500)
