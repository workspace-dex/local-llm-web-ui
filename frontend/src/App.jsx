import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [history, setHistory] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [chatId, setChatId] = useState(null);

  const [memoryOn, setMemoryOn] = useState(true);
  const [webSearch, setWebSearch] = useState(false);
  const [status, setStatus] = useState('');

  const [historyOpen, setHistoryOpen] = useState(true);
  const [ragOpen, setRagOpen] = useState(true);

  const endRef = useRef(null);

  // ---------- INIT ----------
  useEffect(() => {
    init();
  }, []);

  async function init() {
    await fetchModels();
    await fetchHistory();
    createNewChat();
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, status]);

  // ---------- DATA ----------
  async function fetchModels() {
    try {
      const res = await fetch(`${API_BASE}/models`);
      const data = await res.json();
      setModels(data.models || []);
      if (data.models?.length) setSelectedModel(data.models[0].name);
    } catch {}
  }

  async function fetchHistory() {
    try {
      const res = await fetch(`${API_BASE}/history`);
      const data = await res.json();
      setHistory(data.history || []);
    } catch {}
  }

  async function loadChat(id) {
    const res = await fetch(`${API_BASE}/history/${id}`);
    const data = await res.json();
    setChatId(data.conversation.id);
    setMessages(data.conversation.messages);
  }

  function createNewChat() {
    setChatId(`conv_${Date.now()}`);
    setMessages([
      {
        role: 'system',
        content:
          '**DEMO MODE (Local-Only)**\n\n' +
          'This UI is designed for **locally hosted LLMs** using Ollama.\n\n' +
          '- No cloud inference\n' +
          '- No telemetry\n' +
          '- All data stays on your machine\n\n' +
          'Run Ollama locally to use this project.'
      }
    ]);
    setStatus('');
  }

  // ---------- CHAT ----------
  async function sendMessage() {
    if (!input.trim()) return;

    const userMsg = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setStatus('Thinking…');

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: selectedModel,
          message: userMsg.content,
          conversationId: chatId,
          webSearch,
          memoryOn
        })
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let assistant = { role: 'assistant', content: '' };

      setMessages(prev => [...prev, assistant]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n').filter(Boolean);

        for (const line of lines) {
          const event = JSON.parse(line);
          if (event.type === 'status') {
            setStatus(event.content);
          } else if (event.type === 'chunk') {
            assistant.content += event.content;
            setMessages(prev => {
              const copy = [...prev];
              copy[copy.length - 1] = { ...assistant };
              return copy;
            });
            setStatus('');
          }
        }
      }

      fetchHistory();
    } catch {
      setStatus('Error');
    }
  }

  // ---------- UI ----------
  return (
    <div className="app-container">

      {/* LEFT SIDEBAR */}
      <aside className={`history-sidebar ${!historyOpen ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <span className="panel-header">ARCHIVES</span>
          <button className="collapse-btn" onClick={() => setHistoryOpen(false)}>◀</button>
        </div>
        <div className="sidebar-controls">
          <button className="upload-btn" onClick={createNewChat}>+ NEW OPERATION</button>
        </div>
        <div className="rag-files-list">
          {history.map(h => (
            <div key={h.id} className="rag-file-item" onClick={() => loadChat(h.id)}>
              <div className="file-name">{h.title}</div>
            </div>
          ))}
        </div>
      </aside>

      {!historyOpen && (
        <button className="sidebar-toggle-btn visible" onClick={() => setHistoryOpen(true)}>
          ☰ ARCHIVES
        </button>
      )}

      {/* CENTER */}
      <main className="chat-container">
        <header className="chat-header">
          <span className="panel-header">LOCAL LLM UI</span>

          <div className="controls">
            <select
              className="model-select"
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
            >
              {models.map(m => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </select>

            <label className="toggle-label">
              <input type="checkbox" checked={memoryOn} onChange={e => setMemoryOn(e.target.checked)} />
              <div className="toggle-switch"></div>
              <span className="toggle-text">MEM</span>
            </label>

            <label className="toggle-label">
              <input type="checkbox" checked={webSearch} onChange={e => setWebSearch(e.target.checked)} />
              <div className="toggle-switch accent-blue"></div>
              <span className="toggle-text">WEB</span>
            </label>
          </div>
        </header>

        <div className="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`message message-${m.role}`}>
              <div className="message-header">
                <span className="panel-header">{m.role}</span>
              </div>
              <div className="message-body">
                <ReactMarkdown skipHtml>{m.content}</ReactMarkdown>
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="chat-input-container">
          <div className="status-bar">{status}</div>
          <textarea
            className="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), sendMessage())}
            placeholder="Execute prompt…"
          />
          <button className="send-btn" onClick={sendMessage}>EXECUTE</button>

          <div style={{ marginTop: 6, fontSize: 10, color: '#505050', textAlign: 'right' }}>
            Made by Shakib S.
          </div>
        </div>
      </main>

      {/* RIGHT SIDEBAR */}
      <aside className={`rag-sidebar ${!ragOpen ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <span className="panel-header">KNOWLEDGE BASE</span>
          <button className="collapse-btn" onClick={() => setRagOpen(false)}>▶</button>
        </div>
        <div className="empty-state">
          RAG ingestion is disabled in demo mode.
        </div>
      </aside>

      {!ragOpen && (
        <button
          className="sidebar-toggle-btn visible"
          style={{ right: 10 }}
          onClick={() => setRagOpen(true)}
        >
          📄 INTEL
        </button>
      )}

    </div>
  );
}

export default App;
