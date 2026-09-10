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
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="flex justify-between items-center mb-2">
        <h2 className="text-3xl font-bold text-white">All Invoices</h2>
        <div className="flex gap-4">
          <div className="relative flex items-center">
            <Search size={18} className="absolute left-3 text-ios-gray" />
            <input 
              type="text" 
              placeholder="Search invoices..." 
              className="bg-white/5 border border-white/10 rounded-full pl-10 pr-4 py-2 text-white outline-none focus:ring-2 focus:ring-ios-blue/50 w-64 transition-all placeholder:text-ios-gray"
            />
          </div>
          <Button variant="secondary" icon={<Filter size={18} />}>Filter</Button>
        </div>
      </div>

      <Card noPadding>
        {error && <div className="p-4 text-ios-red font-medium">API Error: {error}</div>}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead className="border-b border-white/5 bg-white/5">
              <tr>
                <th className="px-6 py-4 font-semibold text-xs tracking-wide uppercase text-ios-gray">Invoice ID</th>
                <th className="px-6 py-4 font-semibold text-xs tracking-wide uppercase text-ios-gray">Vendor</th>
                <th className="px-6 py-4 font-semibold text-xs tracking-wide uppercase text-ios-gray">Amount</th>
                <th className="px-6 py-4 font-semibold text-xs tracking-wide uppercase text-ios-gray">Date</th>
                <th className="px-6 py-4 font-semibold text-xs tracking-wide uppercase text-ios-gray">Status</th>
                <th className="px-6 py-4 font-semibold text-xs tracking-wide uppercase text-ios-gray">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                <tr><td colSpan={6} className="p-8 text-center text-ios-gray">Loading...</td></tr>
              ) : invoices.length === 0 ? (
                <tr><td colSpan={6} className="p-8 text-center text-ios-gray">No invoices found.</td></tr>
              ) : invoices.map((inv, i) => (
                <tr key={i} className="hover:bg-white/5 transition-colors cursor-pointer group">
                  <td className="px-6 py-4 font-semibold text-white">{inv.id}</td>
                  <td className="px-6 py-4 text-ios-gray font-medium">{inv.vendor_name || inv.vendor_id || '-'}</td>
                  <td className="px-6 py-4 font-bold text-white">{inv.amount ? `$${inv.amount.toLocaleString()}` : '-'}</td>
                  <td className="px-6 py-4 text-ios-gray font-medium">{inv.date || '-'}</td>
                  <td className="px-6 py-4">
                    <span className={`px-3 py-1 rounded-full text-xs font-bold tracking-wide ${
                      inv.status === 'Approved' 
                        ? 'bg-ios-green/10 text-ios-green' 
                        : 'bg-ios-orange/10 text-ios-orange'
                    }`}>
                      {inv.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <Button variant="ghost" size="sm" icon={<Eye size={16} />}>View</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
