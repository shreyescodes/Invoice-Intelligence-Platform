import React, { useState, useEffect } from 'react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Upload, TrendingUp, AlertTriangle, CheckCircle, FileText } from 'lucide-react';
import { api, type InvoiceRecord } from '../api/client';

export const Dashboard: React.FC = () => {
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const fetchInvoices = () => {
    setLoading(true);
    api.getInvoices()
      .then(data => setInvoices(data))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchInvoices();
  }, []);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploading(true);
      try {
        await api.uploadInvoice(file);
        fetchInvoices();
      } catch (err: any) {
        alert('Upload failed: ' + err.message);
      } finally {
        setUploading(false);
      }
    }
  };

  const pendingCount = invoices.filter(i => i.status === 'Pending').length;
  const autoRate = invoices.length ? Math.round((invoices.filter(i => i.status === 'Approved').length / invoices.length) * 100) : 0;

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="flex justify-between items-end mb-4">
        <div>
          <h2 className="text-3xl font-bold text-white">Overview</h2>
          <p className="text-ios-gray mt-1 font-medium tracking-wide">Here is what's happening with your invoices today.</p>
          {error && <p className="text-sm mt-2 text-ios-red font-medium">Backend API Error: {error}</p>}
        </div>
        <div>
          <input type="file" ref={fileInputRef} className="hidden" onChange={handleFileChange} />
          <Button icon={<Upload size={18} />} onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            {uploading ? 'Processing...' : 'Upload Invoice'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="hover:bg-white/5 transition-colors cursor-pointer">
          <div className="flex justify-between items-center mb-4">
            <span className="text-ios-gray font-semibold tracking-wide uppercase text-xs">Total Processed</span>
            <div className="p-2 bg-ios-blue/10 rounded-full">
              <FileText className="text-ios-blue" size={20} />
            </div>
          </div>
          <div className="text-4xl font-bold text-white">{loading ? '...' : invoices.length}</div>
          <div className="flex items-center gap-2 mt-4 text-ios-green bg-ios-green/10 w-fit px-2 py-1 rounded-full">
            <TrendingUp size={14} />
            <span className="text-xs font-semibold tracking-wide">+12% from last month</span>
          </div>
        </Card>

        <Card className="hover:bg-white/5 transition-colors cursor-pointer">
          <div className="flex justify-between items-center mb-4">
            <span className="text-ios-gray font-semibold tracking-wide uppercase text-xs">Pending Approvals</span>
            <div className="p-2 bg-ios-orange/10 rounded-full">
              <AlertTriangle className="text-ios-orange" size={20} />
            </div>
          </div>
          <div className="text-4xl font-bold text-white">{loading ? '...' : pendingCount}</div>
          <div className="text-sm text-ios-gray mt-4 font-medium tracking-wide">Requires human review</div>
        </Card>

        <Card className="hover:bg-white/5 transition-colors cursor-pointer">
          <div className="flex justify-between items-center mb-4">
            <span className="text-ios-gray font-semibold tracking-wide uppercase text-xs">Auto-Approved</span>
            <div className="p-2 bg-ios-green/10 rounded-full">
              <CheckCircle className="text-ios-green" size={20} />
            </div>
          </div>
          <div className="text-4xl font-bold text-white">{loading ? '...' : `${autoRate}%`}</div>
          <div className="text-sm text-ios-gray mt-4 font-medium tracking-wide">Straight-through processing rate</div>
        </Card>
      </div>

      <Card className="mt-2" noPadding>
        <div className="p-6 border-b border-white/5">
          <h3 className="text-xl font-bold text-white">Recent Activity</h3>
        </div>
        <div className="flex flex-col">
          {invoices.slice(0, 5).map((inv, idx) => (
            <div key={inv.id} className={`flex justify-between items-center p-4 hover:bg-white/5 transition-colors cursor-pointer ${idx !== 0 ? 'border-t border-white/5' : ''}`}>
              <div className="flex items-center gap-4">
                <div className={`p-2 rounded-full ${inv.status === 'Approved' ? 'bg-ios-green/10 text-ios-green' : 'bg-ios-orange/10 text-ios-orange'}`}>
                   {inv.status === 'Approved' ? <FileText size={18} /> : <AlertTriangle size={18} />}
                </div>
                <div>
                  <div className="font-semibold text-white tracking-wide">{inv.vendor_name || inv.vendor_id || 'Unknown Vendor'}</div>
                  <div className="text-xs text-ios-gray font-medium mt-0.5">{inv.id} • {inv.date || 'Just now'}</div>
                </div>
              </div>
              <div className="text-right">
                <div className="font-bold text-white tracking-wide">{inv.amount ? `$${inv.amount.toLocaleString()}` : '-'}</div>
                <div className={`text-xs font-semibold mt-0.5 ${inv.status === 'Approved' ? 'text-ios-green' : 'text-ios-orange'}`}>{inv.status}</div>
              </div>
            </div>
          ))}
          {invoices.length === 0 && !loading && (
             <div className="p-8 text-center text-ios-gray">No activity found.</div>
          )}
        </div>
      </Card>
    </div>
  );
};
