import React, { useState } from 'react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Send, Bot, User } from 'lucide-react';
import { api } from '../api/client';

export const Chat: React.FC = () => {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hello! I am your Invoice Intelligence assistant. You can ask me questions like "How many invoices from Acme Corp exceeded $10,000 this month?" or "What is our total spend on software subscriptions?"' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    
    const newMsg = { role: 'user', content: input };
    setMessages(prev => [...prev, newMsg]);
    setInput('');
    setLoading(true);
    
    try {
      const res = await api.askQuestion({ question: input });
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: res.answer + (res.sql_used ? `\n\n\`\`\`sql\n${res.sql_used}\n\`\`\`` : '')
      }]);
    } catch (err: any) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `Error: ${err.message}`
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-col h-full" style={{maxHeight: 'calc(100vh - 160px)'}}>
      <div className="mb-6">
        <h2 className="text-2xl">Intelligence Chat</h2>
        <p className="text-muted mt-4">Ask natural language questions about your invoice data.</p>
      </div>

      <Card className="flex-1 flex flex-col no-padding h-full" style={{overflow: 'hidden'}}>
        <div className="flex-1 p-6" style={{overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px'}}>
          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-4 ${msg.role === 'user' ? 'justify-end' : ''}`}>
              {msg.role === 'assistant' && (
                <div style={{width: 36, height: 36, borderRadius: '50%', background: 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                  <Bot size={20} color="white" />
                </div>
              )}
              <div style={{
                background: msg.role === 'user' ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                padding: '12px 16px',
                borderRadius: '12px',
                borderTopRightRadius: msg.role === 'user' ? '4px' : '12px',
                borderTopLeftRadius: msg.role === 'assistant' ? '4px' : '12px',
                maxWidth: '70%'
              }}>
                <div style={{whiteSpace: 'pre-wrap', fontSize: '0.95rem'}} dangerouslySetInnerHTML={{__html: msg.content.replace(/```sql([^`]*)```/g, '<div style="background:var(--bg-secondary);padding:12px;border-radius:6px;margin-top:8px;font-family:monospace;font-size:0.85rem;color:var(--text-secondary)">$1</div>')}} />
              </div>
              {msg.role === 'user' && (
                <div style={{width: 36, height: 36, borderRadius: '50%', background: 'var(--bg-tertiary)', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                  <User size={20} color="var(--text-secondary)" />
                </div>
              )}
            </div>
          ))}
          {loading && (
             <div className="flex gap-4">
                <div style={{width: 36, height: 36, borderRadius: '50%', background: 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                  <Bot size={20} color="white" />
                </div>
                <div style={{background: 'var(--bg-tertiary)', padding: '12px 16px', borderRadius: '12px', borderTopLeftRadius: '4px'}}>
                   <span className="text-muted">Thinking...</span>
                </div>
             </div>
          )}
        </div>
        
        <div className="p-4" style={{borderTop: '1px solid var(--border-color)', background: 'var(--bg-secondary)'}}>
          <form onSubmit={handleSend} className="flex gap-4 items-center">
            <input 
              type="text" 
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your data..." 
              disabled={loading}
              style={{
                flex: 1,
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-full)',
                padding: '12px 20px',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
            <Button type="submit" variant="primary" disabled={loading} style={{borderRadius: '50%', width: '46px', height: '46px', padding: 0}} icon={<Send size={20} />} />
          </form>
        </div>
      </Card>
    </div>
  );
};
