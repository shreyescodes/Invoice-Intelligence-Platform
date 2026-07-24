import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { LayoutDashboard, FileText, CheckSquare, MessageSquare, Hexagon, Bell } from 'lucide-react';
import { Button } from './Button';

export const Layout: React.FC = () => {
  const location = useLocation();

  const getPageTitle = () => {
    switch (location.pathname) {
      case '/': return 'Dashboard';
      case '/invoices': return 'Invoices';
      case '/approvals': return 'Pending Approvals';
      case '/chat': return 'Intelligence';
      default: return 'Overview';
    }
  };

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <Hexagon className="text-gradient" size={28} />
          <span>InvoiceAI</span>
        </div>

        <nav className="nav-menu">
          <NavLink to="/" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <LayoutDashboard size={20} />
            Dashboard
          </NavLink>
          <NavLink to="/invoices" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <FileText size={20} />
            Invoices
          </NavLink>
          <NavLink to="/approvals" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <CheckSquare size={20} />
            Approvals
          </NavLink>
          <NavLink to="/chat" className={({isActive}) => `nav-item ${isActive ? 'active' : ''}`}>
            <MessageSquare size={20} />
            Intelligence
          </NavLink>
        </nav>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        <header className="header">
          <h1 className="text-xl">{getPageTitle()}</h1>
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" icon={<Bell size={20} />} />
            <div className="flex items-center gap-2" style={{marginLeft: '16px'}}>
              <div style={{width: 36, height: 36, borderRadius: '50%', background: 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))'}} />
              <div className="flex-col" style={{display: 'flex', flexDirection: 'column'}}>
                <span className="text-sm font-medium">Admin User</span>
                <span className="text-xs text-muted">admin@invoiceai.com</span>
              </div>
            </div>
          </div>
        </header>
        
        <div className="content-scroll">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
