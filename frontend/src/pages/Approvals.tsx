import React, { useState, useEffect } from 'react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { AlertTriangle, Check, X } from 'lucide-react';
import { api, type InvoiceRecord } from '../api/client';

export const Approvals: React.FC = () => {
  const [approvals, setApprovals] = useState<InvoiceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchApprovals();
  }, []);

  const fetchApprovals = () => {
    setLoading(true);
    api.getPendingApprovals()
      .then(data => setApprovals(data))
      .catch(err => {
        setError(err.message);
        setApprovals([]);
      })
      .finally(() => setLoading(false));
  };

  const handleDecision = async (id: string, approve: boolean) => {
    try {
      await api.submitDecision(id, { approve, reason: approve ? '' : 'Manually rejected via UI' });
      alert(`Invoice ${approve ? 'approved' : 'rejected'} successfully!`);
      fetchApprovals();
    } catch (err: any) {
      alert('Decision failed: ' + err.message);
    }
  };

  if (loading) {
    return <div className="p-6 text-muted">Loading pending approvals...</div>;
  }

  return (
    <div className="flex-col gap-6">
      <div className="mb-6">
        <h2 className="text-2xl">Pending Approvals</h2>
        <p className="text-muted mt-4">These invoices have been flagged by the anomaly detection model.</p>
        {error && <p className="text-sm mt-2" style={{color: 'var(--danger)'}}>API Error: {error}</p>}
      </div>

      {approvals.length === 0 && !error && (
        <Card>
          <div className="p-6 text-center text-muted">No pending approvals at this time.</div>
        </Card>
      )}

      {approvals.map(inv => (
        <Card key={inv.id} className="mb-6">
          <div className="flex justify-between items-start mb-6">
            <div className="flex items-start gap-4">
              <div className="p-3" style={{background: 'rgba(245, 158, 11, 0.1)', borderRadius: '8px', color: 'var(--warning)'}}>
                <AlertTriangle size={24} />
              </div>
              <div>
                <h3 className="text-xl">{inv.id}</h3>
                <p className="text-muted mt-4">{inv.vendor_name || inv.vendor_id || 'Unknown'} • {inv.amount ? `$${inv.amount.toFixed(2)}` : 'N/A'} • {inv.date || 'No Date'}</p>
              </div>
            </div>
            <div style={{textAlign: 'right'}}>
              <div className="text-2xl" style={{color: 'var(--warning)', fontWeight: 700}}>{inv.anomaly_score?.toFixed(2) || 'N/A'}</div>
              <div className="text-xs text-muted">Anomaly Score</div>
            </div>
          </div>

          <div className="flex gap-6 mb-6 mt-6">
            <div className="flex-1 p-6" style={{background: 'var(--bg-tertiary)', borderRadius: '8px'}}>
              <h4 className="font-medium mb-4 text-sm text-muted">Anomaly Reason</h4>
              <p className="text-sm">{inv.anomaly_reason || 'Model flagged anomalous data patterns.'}</p>
            </div>
            <div className="flex-1 p-6" style={{background: 'var(--bg-tertiary)', borderRadius: '8px'}}>
              <h4 className="font-medium mb-4 text-sm text-muted">Extracted Data</h4>
              <div className="flex justify-between mb-4"><span className="text-sm text-muted">PO Number:</span><span className="text-sm font-medium">{inv.po_number || '-'}</span></div>
              <div className="flex justify-between mb-4"><span className="text-sm text-muted">Tax Amount:</span><span className="text-sm font-medium">{inv.tax_amount ? `$${inv.tax_amount}` : '-'}</span></div>
              <div className="flex justify-between"><span className="text-sm text-muted">SAP Match:</span><span className="text-sm font-medium" style={{color: inv.sap_match === 'Valid' ? 'var(--success)' : 'var(--warning)'}}>{inv.sap_match || 'Unknown'}</span></div>
            </div>
          </div>

          <div className="flex justify-end gap-4 mt-6 pt-6" style={{borderTop: '1px solid var(--border-color)'}}>
            <Button variant="ghost" icon={<X size={18} />} onClick={() => handleDecision(inv.id, false)}>Reject</Button>
            <Button variant="primary" icon={<Check size={18} />} onClick={() => handleDecision(inv.id, true)}>Approve to SAP</Button>
          </div>
        </Card>
      ))}
    </div>
  );
};
