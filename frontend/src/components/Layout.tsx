import React from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, FileText, CheckSquare, MessageSquare } from 'lucide-react';

export const Layout: React.FC = () => {
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: <LayoutDashboard size={22} /> },
    { path: '/invoices', label: 'Invoices', icon: <FileText size={22} /> },
    { path: '/approvals', label: 'Approvals', icon: <CheckSquare size={22} /> },
    { path: '/chat', label: 'Intelligence', icon: <MessageSquare size={22} /> }
  ];

  return (
    <div className="flex h-screen bg-[#050505] text-white overflow-hidden relative">
      
      {/* Background ambient lighting for liquid glass to refract */}
      <div className="absolute top-0 left-0 w-[500px] h-[500px] bg-ios-blue/20 rounded-full blur-[120px] pointer-events-none -translate-x-1/2 -translate-y-1/2" />
      <div className="absolute bottom-0 right-0 w-[500px] h-[500px] bg-purple-500/10 rounded-full blur-[120px] pointer-events-none translate-x-1/4 translate-y-1/4" />

      {/* iOS Translucent Sidebar */}
      <aside className="w-64 ios-glass flex flex-col z-20 m-6 rounded-3xl overflow-hidden shadow-2xl relative">
        <div className="p-8 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-ios-blue/20 border border-ios-blue/30 flex items-center justify-center shadow-[0_0_15px_rgba(10,132,255,0.3)]">
              <span className="text-xl font-bold text-ios-blue">II</span>
            </div>
            <h1 className="text-sm font-semibold tracking-widest uppercase text-white/70">Invoice Intel</h1>
          </div>
        </div>

        <nav className="flex-1 px-4 mt-2 space-y-3">
          {navItems.map((item) => {
            const active = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-300 font-medium ${
                  active 
                    ? 'glass-active scale-[1.02]' 
                    : 'text-ios-gray hover:text-white hover:bg-white/5 border border-transparent'
                }`}
              >
                <div className={`${active ? 'text-ios-blue' : 'text-ios-gray'}`}>
                  {item.icon}
                </div>
                {item.label}
              </Link>
            );
          })}
        </nav>
        
        <div className="p-6">
          <div className="flex items-center gap-3 px-4 py-3 rounded-2xl bg-white/5 border border-white/5 backdrop-blur-xl shadow-lg hover:bg-white/10 transition-colors cursor-pointer">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-ios-blue/50 to-purple-500/50 p-[1px]">
              <div className="w-full h-full bg-[#111] rounded-full border border-white/10" />
            </div>
            <div className="flex-col">
              <div className="text-sm font-semibold text-white/90">Demo User</div>
              <div className="text-xs text-ios-gray tracking-wide">Finance Team</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden relative z-10">
        <header className="h-24 flex items-center justify-between px-10 z-10">
          <div className="flex items-center gap-2">
            <h2 className="text-3xl font-bold tracking-tight">Overview</h2>
          </div>
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-full ios-glass flex items-center justify-center cursor-pointer hover:bg-white/10 transition-colors">
              <span className="text-ios-blue font-bold text-sm tracking-widest">Q3</span>
            </div>
          </div>
        </header>
        <div className="flex-1 overflow-auto p-10 pt-0 pb-20">
          <div className="max-w-6xl mx-auto w-full">
            <Outlet />
          </div>
        </div>
      </main>
      
    </div>
  );
};
