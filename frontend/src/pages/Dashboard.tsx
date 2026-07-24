import React, { useState, useEffect, useRef } from 'react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { FileText, CheckCircle, AlertTriangle, TrendingUp, Upload } from 'lucide-react';
import { api, type InvoiceRecord } from '../api/client';

export const Dashboard: React.FC = () => {
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getInvoices()
      .then(data => {
        setInvoices(data);
        setError(null);
      })
      .catch(err => {
        setError(err.message);
        setInvoices([]); // empty state on 501
      })
      .finally(() => setLoading(false));
  }, []);

  const handleUploadClick = () => fileInputRef.current?.click();

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await api.uploadInvoice(file);
      alert('Invoice uploaded successfully!');
      // Refresh
      const data = await api.getInvoices();
      setInvoices(data);
    } catch (err: any) {
      alert('Upload failed: ' + err.message);
    }
  };

  const pendingCount = invoices.filter(i => i.status === 'Pending Review' || i.status === 'pending_approval').length;
  const approvedCount = invoices.filter(i => i.status === 'Approved').length;
  const autoRate = invoices.length > 0 ? Math.round((approvedCount / invoices.length) * 100) : 0;

  return (
    <div className="flex-col gap-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl">Overview</h2>
          <p className="text-muted mt-4">Here is what's happening with your invoices today.</p>
          {error && <p className="text-sm mt-2" style={{color: 'var(--danger)'}}>Backend API Error: {error}</p>}
        </div>
        <div>
          <input type="file" ref={fileInputRef} style={{display: 'none'}} onChange={handleFileChange} />
          <Button icon={<Upload size={18} />} onClick={handleUploadClick}>Upload Invoice</Button>
        </div>
      </div>

      <div className="flex gap-6 mb-6">
        <Card className="flex-1">
          <div className="flex justify-between items-center mb-4">
            <span className="text-muted font-medium">Total Processed</span>
            <div className="p-4" style={{background: 'rgba(99, 102, 241, 0.1)', borderRadius: '8px', padding: '8px'}}>
              <FileText className="text-gradient" size={24} />
            </div>
          </div>
          <div className="text-2xl" style={{fontSize: '2rem'}}>{loading ? '...' : invoices.length}</div>
          <div className="flex items-center gap-2 mt-4" style={{color: 'var(--success)'}}>
            <TrendingUp size={16} />
            <span className="text-sm">+0% from last month</span>
          </div>
        </Card>

        <Card className="flex-1">
          <div className="flex justify-between items-center mb-4">
            <span className="text-muted font-medium">Pending Approvals</span>
            <div className="p-4" style={{background: 'rgba(245, 158, 11, 0.1)', borderRadius: '8px', padding: '8px'}}>
              <AlertTriangle style={{color: 'var(--warning)'}} size={24} />
            </div>
          </div>
          <div className="text-2xl" style={{fontSize: '2rem'}}>{loading ? '...' : pendingCount}</div>
          <div className="text-sm text-muted mt-4">Requires human review</div>
        </Card>

        <Card className="flex-1">
          <div className="flex justify-between items-center mb-4">
            <span className="text-muted font-medium">Auto-Approved</span>
            <div className="p-4" style={{background: 'rgba(16, 185, 129, 0.1)', borderRadius: '8px', padding: '8px'}}>
              <CheckCircle style={{color: 'var(--success)'}} size={24} />
            </div>
          </div>
          <div className="text-2xl" style={{fontSize: '2rem'}}>{loading ? '...' : `${autoRate}%`}</div>
          <div className="text-sm text-muted mt-4">Straight-through processing rate</div>
        </Card>
      </div>

      <Card>
        <h3 className="text-xl mb-4">Recent Activity</h3>
        <div className="flex-col gap-4">
          {invoices.slice(0, 5).map(inv => (
            <div key={inv.id} className="flex justify-between items-center p-4" style={{background: 'var(--bg-tertiary)', borderRadius: '8px', marginBottom: '8px'}}>
              <div className="flex items-center gap-4">
                {inv.status === 'Approved' ? <FileText size={20} className="text-muted" /> : <AlertTriangle size={20} style={{color: 'var(--warning)'}} />}
                <div>
                  <div className="font-medium">{inv.id} - {inv.vendor_name || inv.vendor_id || 'Unknown Vendor'}</div>
                  <div className="text-xs text-muted">{inv.date || 'Recent'}</div>
                </div>
              </div>
              <span style={{
                color: inv.status === 'Approved' ? 'var(--success)' : 'var(--warning)', 
                fontSize: '0.875rem', 
                fontWeight: 500
              }}>
                {inv.status}
              </span>
            </div>
          ))}
          {!loading && invoices.length === 0 && <p className="text-sm text-muted text-center py-4">No recent activity.</p>}
        </div>
      </Card>
    </div>
  );
};
