import React, { useState, useEffect } from 'react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Search, Filter, Eye } from 'lucide-react';
import { api, type InvoiceRecord } from '../api/client';

export const Invoices: React.FC = () => {
  const [invoices, setInvoices] = useState<InvoiceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getInvoices()
      .then(data => setInvoices(data))
      .catch(err => {
        setError(err.message);
        setInvoices([]);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex-col gap-6">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl">All Invoices</h2>
        <div className="flex gap-4">
          <div style={{position: 'relative', display: 'flex', alignItems: 'center'}}>
            <Search size={18} style={{position: 'absolute', left: '12px', color: 'var(--text-secondary)'}} />
            <input 
              type="text" 
              placeholder="Search invoices..." 
              style={{
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                padding: '8px 12px 8px 36px',
                color: 'var(--text-primary)',
                outline: 'none',
                width: '250px'
              }}
            />
          </div>
          <Button variant="secondary" icon={<Filter size={18} />}>Filter</Button>
        </div>
      </div>

      <Card noPadding>
        {error && <div className="p-4" style={{color: 'var(--danger)'}}>API Error: {error}</div>}
        <table style={{width: '100%', borderCollapse: 'collapse'}}>
          <thead style={{borderBottom: '1px solid var(--border-color)', textAlign: 'left'}}>
            <tr>
              <th style={{padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)'}}>Invoice ID</th>
              <th style={{padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)'}}>Vendor</th>
              <th style={{padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)'}}>Amount</th>
              <th style={{padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)'}}>Date</th>
              <th style={{padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)'}}>Status</th>
              <th style={{padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)'}}>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} style={{padding: '24px', textAlign: 'center', color: 'var(--text-muted)'}}>Loading...</td></tr>
            ) : invoices.length === 0 ? (
              <tr><td colSpan={6} style={{padding: '24px', textAlign: 'center', color: 'var(--text-muted)'}}>No invoices found.</td></tr>
            ) : invoices.map((inv, i) => (
              <tr key={i} style={{borderBottom: '1px solid var(--glass-border)'}}>
                <td style={{padding: '16px 24px', fontWeight: 500}}>{inv.id}</td>
                <td style={{padding: '16px 24px'}}>{inv.vendor_name || inv.vendor_id || '-'}</td>
                <td style={{padding: '16px 24px'}}>{inv.amount ? `$${inv.amount.toFixed(2)}` : '-'}</td>
                <td style={{padding: '16px 24px', color: 'var(--text-secondary)'}}>{inv.date || '-'}</td>
                <td style={{padding: '16px 24px'}}>
                  <span style={{
                    background: inv.status === 'Approved' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                    color: inv.status === 'Approved' ? 'var(--success)' : 'var(--warning)',
                    padding: '4px 8px',
                    borderRadius: '12px',
                    fontSize: '0.75rem',
                    fontWeight: 600
                  }}>
                    {inv.status}
                  </span>
                </td>
                <td style={{padding: '16px 24px'}}>
                  <Button variant="ghost" size="sm" icon={<Eye size={16} />}>View</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};
