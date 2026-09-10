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
    <div className="flex flex-col h-full max-h-[calc(100vh-160px)] animate-fade-in">
      <div className="mb-6">
        <h2 className="text-3xl font-bold text-white">Intelligence Chat</h2>
        <p className="text-ios-gray mt-1 font-medium tracking-wide">Ask natural language questions about your invoice data.</p>
      </div>

      <Card className="flex-1 flex flex-col p-0 overflow-hidden border border-white/5" noPadding>
        <div className="flex-1 p-6 overflow-y-auto flex flex-col gap-6 bg-black">
          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
                  <Bot size={16} className="text-white" />
                </div>
              )}
              <div className={`p-3.5 rounded-2xl max-w-[80%] md:max-w-[70%] text-[15px] leading-relaxed ${
                msg.role === 'user' 
                  ? 'bg-ios-blue text-white rounded-br-sm' 
                  : 'bg-ios-gray6 text-white rounded-bl-sm border border-white/5'
              }`}>
                <div className="whitespace-pre-wrap" 
                     dangerouslySetInnerHTML={{__html: msg.content.replace(/```sql([^`]*)```/g, '<div class="bg-black/50 p-4 rounded-xl mt-3 font-mono text-xs text-ios-gray overflow-x-auto border border-white/5">$1</div>')}} />
              </div>
              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
                  <User size={16} className="text-white" />
                </div>
              )}
            </div>
          ))}
          {loading && (
             <div className="flex gap-3 animate-pulse">
                <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
                  <Bot size={16} className="text-white" />
                </div>
                <div className="p-3.5 rounded-2xl rounded-bl-sm bg-ios-gray6 border border-white/5">
                   <span className="flex items-center gap-1.5 px-2">
                     <span className="w-2 h-2 bg-ios-gray rounded-full animate-bounce" style={{animationDelay: '0ms'}} />
                     <span className="w-2 h-2 bg-ios-gray rounded-full animate-bounce" style={{animationDelay: '150ms'}} />
                     <span className="w-2 h-2 bg-ios-gray rounded-full animate-bounce" style={{animationDelay: '300ms'}} />
                   </span>
                </div>
             </div>
          )}
        </div>
        
        <div className="p-4 border-t border-white/5 bg-ios-gray6/50 backdrop-blur-xl">
          <form onSubmit={handleSend} className="flex gap-3 items-center max-w-4xl mx-auto relative">
            <input 
              type="text" 
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your data..." 
              disabled={loading}
              className="flex-1 bg-black border border-white/10 rounded-full pl-6 pr-14 py-3.5 text-white outline-none focus:border-ios-blue/50 transition-colors disabled:opacity-50 placeholder:text-ios-gray"
            />
            <Button type="submit" variant="primary" disabled={loading} className="absolute right-1 top-1 bottom-1 rounded-full w-10 h-10 p-0 flex items-center justify-center" icon={<Send size={16} className={input.trim() ? "translate-x-0.5" : ""} />} />
          </form>
        </div>
      </Card>
    </div>
  );
};
