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
    return <div className="p-8 text-center text-ios-gray font-medium">Loading pending approvals...</div>;
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="mb-2">
        <h2 className="text-3xl font-bold text-white">Pending Approvals</h2>
        <p className="text-ios-gray mt-1 font-medium tracking-wide">These invoices have been flagged by the anomaly detection model.</p>
        {error && <p className="text-sm mt-2 text-ios-red font-medium">API Error: {error}</p>}
      </div>

      {approvals.length === 0 && !error && (
        <Card>
          <div className="p-12 text-center text-ios-gray font-medium flex flex-col items-center justify-center">
            <Check size={48} className="opacity-20 mb-4 text-ios-green" />
            No pending approvals at this time. You're all caught up!
          </div>
        </Card>
      )}

      {approvals.map(inv => (
        <Card key={inv.id} className="mb-6 hover:bg-white/5 transition-colors">
          <div className="flex justify-between items-start mb-6">
            <div className="flex items-start gap-4">
              <div className="p-3 bg-ios-orange/10 text-ios-orange rounded-full">
                <AlertTriangle size={24} />
              </div>
              <div>
                <h3 className="text-xl font-bold text-white">{inv.id}</h3>
                <p className="text-ios-gray mt-1 font-medium tracking-wide">{inv.vendor_name || inv.vendor_id || 'Unknown'} • {inv.amount ? `$${inv.amount.toLocaleString()}` : 'N/A'} • {inv.date || 'No Date'}</p>
              </div>
            </div>
            <div className="text-right">
              <div className="text-3xl font-bold text-ios-orange">{inv.anomaly_score?.toFixed(2) || 'N/A'}</div>
              <div className="text-xs text-ios-gray font-semibold tracking-wide uppercase mt-1">Anomaly Score</div>
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-6 mb-6 mt-6">
            <div className="flex-1 p-6 bg-white/5 rounded-2xl border border-white/5">
              <h4 className="font-semibold mb-4 text-xs text-ios-gray uppercase tracking-wider">Anomaly Reason</h4>
              <p className="text-sm text-white font-medium">{inv.anomaly_reason || 'Model flagged anomalous data patterns.'}</p>
            </div>
            <div className="flex-1 p-6 bg-white/5 rounded-2xl border border-white/5">
              <h4 className="font-semibold mb-4 text-xs text-ios-gray uppercase tracking-wider">Extracted Data</h4>
              <div className="flex justify-between mb-3"><span className="text-sm text-ios-gray font-medium">PO Number:</span><span className="text-sm font-semibold text-white">{inv.po_number || '-'}</span></div>
              <div className="flex justify-between mb-3"><span className="text-sm text-ios-gray font-medium">Tax Amount:</span><span className="text-sm font-semibold text-white">{inv.tax_amount ? `$${inv.tax_amount}` : '-'}</span></div>
              <div className="flex justify-between"><span className="text-sm text-ios-gray font-medium">SAP Match:</span><span className={`text-sm font-bold ${inv.sap_match === 'Valid' ? 'text-ios-green' : 'text-ios-orange'}`}>{inv.sap_match || 'Unknown'}</span></div>
            </div>
          </div>

          <div className="flex justify-end gap-4 mt-6 pt-6 border-t border-white/5">
            <Button variant="ghost" icon={<X size={18} />} onClick={() => handleDecision(inv.id, false)} className="hover:bg-ios-red/10 text-ios-red">Reject</Button>
            <Button variant="primary" icon={<Check size={18} />} onClick={() => handleDecision(inv.id, true)}>Approve to SAP</Button>
          </div>
        </Card>
      ))}
    </div>
  );
};
